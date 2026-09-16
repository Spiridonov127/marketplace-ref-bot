/**
 * Cloudflare Worker — облачный релей между Telegram и GitHub Actions.
 *
 * Зачем это нужно: Telegram-бот на компьютере пользователя слушает
 * обновления через long polling, а для этого процесс main.py должен
 * постоянно работать. Если компьютер выключен — бот не отвечает.
 * GitHub Actions, в свою очередь, не может постоянно "слушать" Telegram —
 * это разовые запуски по событию (workflow_dispatch/schedule/
 * repository_dispatch).
 *
 * Решение: между Telegram и GitHub встаёт этот Worker. Он всегда "включён"
 * (это и есть смысл serverless), принимает от Telegram webhook-обновления
 * (вместо long polling) и:
 *   - на /start запоминает в KV, что этот chat_id ждёт запрос, и отвечает
 *     тем же текстом, что и раньше отвечал Python-бот;
 *   - на свободный текст, если чат "ждёт запрос", очищает флаг ожидания и
 *     дёргает GitHub REST API (repository_dispatch), передавая текст
 *     запроса и chat_id — дальше всё делает GitHub Actions
 *     (.github/workflows/telegram_query.yml -> scripts/run_dispatch_query.py),
 *     который сам публикует статью в Дзен и сам же присылает результат в
 *     Telegram. Компьютер пользователя во всей этой цепочке не участвует.
 *
 * Пользовательский сценарий в Telegram не меняется ни на шаг: /start ->
 * "о чём хотите написать?" -> пользователь пишет категорию -> статья
 * публикуется в Дзен -> бот "отключается" -> для следующего раза снова
 * нужен /start.
 */

const OFF_NOTICE = "Бот отключился — когда понадобится снова, нажмите /start.";

const START_TEXT =
  "👋 <b>Яндекс Маркет → Дзен Бот</b>\n\n" +
  "О чём хотите написать? Пришлите запрос — например: <i>шапка</i>, " +
  "<i>кофемашина</i>, <i>детские коляски</i>. Найду товар на Яндекс " +
  "Маркете, напишу статью и опубликую в Дзен с маркировкой рекламы " +
  "(erid).\n\n" +
  "Нужна подборка с ценами, рейтингами и плюсами-минусами из отзывов — " +
  "попросите явно: <i>топ-5 наушников</i>, <i>лучшие кофемашины</i>, " +
  "<i>подборка колясок</i>.\n\n" +
  "После публикации бот отключается — когда понадобится снова, просто " +
  "нажмите /start ещё раз.\n\n" +
  "Остальные команды — /help.";

const HELP_TEXT =
  "<b>📖 Как пользоваться:</b>\n\n" +
  "1. Нажмите /start.\n" +
  "2. Напишите, о чём статья — что угодно, не только электроника:\n" +
  "   • <i>шапка</i>, <i>кофемашина</i> — статья про сам предмет с фото " +
  "и ссылкой;\n" +
  "   • <i>топ-5 наушников</i>, <i>лучшие пылесосы</i>, <i>подборка " +
  "колясок</i> — подборка товаров с ценами, рейтингами и " +
  "плюсами-минусами из реальных отзывов покупателей.\n" +
  "3. Бот опубликует статью в Дзен с маркировкой рекламы (erid), после " +
  "чего отключится — для следующего раза снова нужен /start.\n\n" +
  "Работает даже если ваш компьютер выключен — всё делает облако.";

// Те же слова-триггеры, что и в scheduler.wants_top_selection на стороне
// Python. Воркер сам ничего не публикует — ему это нужно ровно для одной
// вещи: написать в ответ "готовлю статью" или "готовлю подборку", чтобы
// обещание совпадало с тем, что в итоге выйдет в Дзене.
// Границы слова заданы через \p{L}/\p{N} с флагом u, а НЕ через \b и \W:
// в JavaScript \w — это только латиница, поэтому кириллица считается
// "не-буквой", и наивная версия ловила "топор", "стоп сигнал", "автостоп"
// как просьбу собрать подборку (проверено тестом).
const TOP_WORDS_RE =
  /(?<![\p{L}\p{N}])(топ\d*|подборк\p{L}*|лучш\p{L}+|рейтинг\p{L}*|сравн\p{L}+|собер\p{L}+|подбер\p{L}+)(?![\p{L}\p{N}])/iu;

// Сколько времени чат остаётся "включённым" после /start, если пользователь
// так и не прислал запрос. Один час с запасом — не годами, чтобы состояние
// не накапливалось вечно в KV, но и не так коротко, чтобы отвлёкся на пару
// минут и /start пришлось нажимать заново.
const AWAITING_TTL_SECONDS = 60 * 60;

export default {
  async fetch(request, env) {
    // Прозрачный прокси к Bot API: с российских IP (например, наш VPS
    // в Яндекс.Облаке — captcha на Маркете требует именно такой IP)
    // api.telegram.org не отвечает — Telegram заблокирован на уровне
    // провайдера. Cloudflare не блокируется, поэтому бот на VPS ходит
    // не напрямую в Telegram, а сюда: /bot<token>/<method> пересылается
    // как есть на https://api.telegram.org/bot<token>/<method>, включая
    // long polling (getUpdates) и отправку сообщений.
    const url = new URL(request.url);
    if (url.pathname.startsWith("/bot")) {
      const target = "https://api.telegram.org" + url.pathname + url.search;
      const proxied = await fetch(target, {
        method: request.method,
        headers: request.headers,
        body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      });
      return new Response(proxied.body, {
        status: proxied.status,
        headers: proxied.headers,
      });
    }

    if (request.method !== "POST") {
      return new Response("ok", { status: 200 });
    }

    let update;
    try {
      update = await request.json();
    } catch (e) {
      return new Response("bad request", { status: 400 });
    }

    try {
      await handleUpdate(update, env);
    } catch (e) {
      // Telegram ретраит webhook, если получит не-2xx, а также если
      // обработка займёт слишком долго. repository_dispatch — быстрый
      // fire-and-forget вызов, так что залипаний быть не должно, но на
      // всякий случай не даём ошибке обработки апдейта превратиться в
      // бесконечные повторные попытки от Telegram.
      console.error("handleUpdate failed", e);
    }

    return new Response("ok", { status: 200 });
  },
};

async function handleUpdate(update, env) {
  const message = update.message;
  if (!message || !message.chat || !message.from) return;

  const chatId = message.chat.id;
  const userId = message.from.id;
  const text = (message.text || "").trim();

  const adminIds = (env.ADMIN_USER_IDS || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const isAdmin = adminIds.includes(String(userId));
  if (!isAdmin) return;

  if (text === "/start") {
    await env.AWAITING_KV.put(`awaiting:${chatId}`, "1", {
      expirationTtl: AWAITING_TTL_SECONDS,
    });
    await sendTelegram(env, chatId, START_TEXT);
    return;
  }

  if (text === "/help") {
    await sendTelegram(env, chatId, HELP_TEXT);
    return;
  }

  // Прочие команды (/stats, /top, /cookies и т.д.) по-прежнему обслуживает
  // локальный Python-бот, если/когда компьютер включён и main.py запущен —
  // здесь мы их просто не трогаем, чтобы не отвечать на них дважды либо
  // ошибочно, если Worker когда-нибудь получит апдейт раньше локального
  // бота. Обрабатываем в Worker только то, что нужно именно "без компьютера":
  // /start и сам запрос категории.
  if (text.startsWith("/")) return;

  if (!text) return;

  const awaitingKey = `awaiting:${chatId}`;
  const awaiting = await env.AWAITING_KV.get(awaitingKey);
  if (!awaiting) return; // бот "отключён" — молча игнорируем, как и раньше

  await env.AWAITING_KV.delete(awaitingKey);

  const what = TOP_WORDS_RE.test(text)
    ? "готовлю подборку"
    : "готовлю статью";
  await sendTelegram(
    env,
    chatId,
    `🔍 Ищу «${text}» на Яндекс Маркете, ${what} для Дзена ` +
      `(с получением erid) — это займёт пару минут...`
  );

  try {
    await triggerGithubDispatch(env, text, chatId);
  } catch (e) {
    console.error("github dispatch failed", e);
    await sendTelegram(
      env,
      chatId,
      `❌ Не удалось запустить обработку запроса «${text}»: ${e.message}\n\n${OFF_NOTICE}`
    );
  }
}

async function triggerGithubDispatch(env, query, chatId) {
  const resp = await fetch(
    `https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "marketplace-ref-bot-worker",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        event_type: "telegram_query",
        client_payload: {
          query: query,
          chat_id: String(chatId),
        },
      }),
    }
  );

  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`GitHub API вернул ${resp.status}: ${body}`);
  }
}

async function sendTelegram(env, chatId, text) {
  const resp = await fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        text: text,
        parse_mode: "HTML",
      }),
    }
  );
  if (!resp.ok) {
    const body = await resp.text();
    console.error(`Telegram sendMessage вернул ${resp.status}: ${body}`);
  }
}
