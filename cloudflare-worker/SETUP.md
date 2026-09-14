# Настройка облачного релея (бот работает даже при выключенном компьютере)

Что это даёт: вы нажимаете /start в Telegram с телефона, компьютер выключен —
бот всё равно спрашивает «о чём написать», ищет на Яндекс Маркете, публикует
статью в Дзен и присылает результат. Всю работу делает GitHub Actions в
облаке; Cloudflare Worker — это "дежурный", который всегда включён и
передаёт сообщения из Telegram в GitHub.

Сделать это нужно один раз. Дальше всё работает само.

## 0. Добавить один файл вручную (единственный ручной шаг)

Мост к вашему компьютеру не даёт мне удалённо писать файлы в
`.github/workflows/` — это защита от того, чтобы кто-то удалённо подменял
CI/CD-процессы. Поэтому этот один файл нужно добавить самому — проще всего
через сайт GitHub, без терминала:

1. Откройте свой репозиторий на github.com.
2. Add file → Create new file.
3. В поле имени файла введите: `.github/workflows/telegram_query.yml`
4. Вставьте содержимое (файл `telegram_query.yml` я уже прислал вам в чат —
   можно открыть его и скопировать содержимое).
5. Commit directly to the main branch → Commit new file.

Остальные три файла (`scripts/run_dispatch_query.py`,
`cloudflare-worker/src/worker.js`, `cloudflare-worker/wrangler.toml`) уже
лежат в папке проекта на вашем компьютере — их тоже нужно закоммитить и
запушить в GitHub вместе с workflow-файлом (иначе `run_dispatch_query.py`
просто не будет существовать в репозитории, и workflow не сможет его
запустить):

```bash
cd ~/marketplace-ref-bot
git add scripts/run_dispatch_query.py cloudflare-worker/
git commit -m "Add cloud relay for Telegram bot (works with PC off)"
git push
```

(Файл `.github/workflows/telegram_query.yml`, который вы добавили через
сайт GitHub на шаге выше, при этом уже будет в репозитории — `git pull`
подтянет его к вам локально, если нужно.)

## 1. Проверить недостающие секреты GitHub

Workflow использует секреты `DZEN_DRAFT_URL` и `GROQ_API_KEY`, которых нет
в старом `post.yml` — похоже, их вообще нет в репозитории. Без
`DZEN_DRAFT_URL` публикация в Дзен не сработает вообще (упадёт с ошибкой),
без `GROQ_API_KEY` статьи будут генерироваться по шаблону вместо ИИ-текста
(не критично, но хуже).

Проверьте на github.com: Settings → Secrets and variables → Actions.
Если `DZEN_DRAFT_URL` и `GROQ_API_KEY` там нет — добавьте (New repository
secret) со значениями из вашего локального `.env`. Либо через терминал:

```bash
cd ~/marketplace-ref-bot
gh secret set DZEN_DRAFT_URL --body "https://dzen.ru/profile/editor/id/.../.../edit"
gh secret set GROQ_API_KEY --body "ваш_ключ_groq"
```

## 2. Установить wrangler (CLI Cloudflare)

```bash
npm install -g wrangler
wrangler login
```

Откроется браузер — войдите (или зарегистрируйтесь, это бесплатно) в
Cloudflare.

## 3. Создать KV-хранилище

Из папки `cloudflare-worker/`:

```bash
cd ~/marketplace-ref-bot/cloudflare-worker
wrangler kv namespace create AWAITING_KV
```

Команда выведет что-то вроде:

```
{ binding = "AWAITING_KV", id = "abcd1234..." }
```

Откройте `wrangler.toml` и замените `ЗАМЕНИТЕ_НА_ID` на этот id.

## 4. Задать секреты воркера

Все — из папки `cloudflare-worker/`:

```bash
wrangler secret put TELEGRAM_BOT_TOKEN
wrangler secret put GITHUB_TOKEN
wrangler secret put GITHUB_REPO
wrangler secret put ADMIN_USER_IDS
```

Для каждой команды wrangler спросит значение — вводите и жмите Enter.

- `TELEGRAM_BOT_TOKEN` — тот же токен, что уже в `.env` локального бота.
- `GITHUB_TOKEN` — **новый** Personal Access Token с правом `repo`:
  github.com → Settings → Developer settings → Personal access tokens →
  Tokens (classic) → Generate new token → отметьте галочку `repo` →
  Generate. Скопируйте токен сразу (второй раз показать не дадут).
- `GITHUB_REPO` — строка вида `ваш_логин/marketplace-ref-bot`.
- `ADMIN_USER_IDS` — тот же список ID, что и в `.env` (через запятую, без
  пробелов, например `123456789`).

## 5. Опубликовать воркер

```bash
wrangler deploy
```

В выводе будет URL вида `https://marketplace-ref-bot-relay.<ваш-логин>.workers.dev`.
Скопируйте его.

## 6. Подключить Telegram к воркеру (webhook)

```bash
curl "https://api.telegram.org/bot<ТОКЕН_БОТА>/setWebhook?url=<URL_ВОРКЕРА>"
```

Должно вернуть `{"ok":true,"result":true,...}`. Проверить, что всё
подключилось:

```bash
curl "https://api.telegram.org/bot<ТОКЕН_БОТА>/getWebhookInfo"
```

## 7. Важно: больше не запускать локального бота одновременно с webhook

Telegram разрешает только один способ получать сообщения — либо long
polling (то, как сейчас работает `main.py` на вашем компьютере), либо
webhook (то, что вы только что настроили). Оба одновременно работать не
могут — будут ошибки `409 Conflict`.

Как только webhook подключён (шаг 6) — весь функционал `/start → вопрос →
ответ → публикация → отключение` работает через облако, компьютер для этого
не нужен вообще. `main.py` на компьютере запускать для этого больше не
обязательно.

Если вы всё же захотите на время вернуться к локальному боту (например,
для отладки) — сначала отключите webhook:

```bash
curl "https://api.telegram.org/bot<ТОКЕН_БОТА>/deleteWebhook"
```

и только потом запускайте `main.py`. Не забудьте затем повторить шаг 6,
чтобы облачный вариант заработал снова.

## 8. Проверка

Выключите компьютер (или просто не запускайте `main.py`), возьмите
телефон, откройте бота в Telegram, нажмите /start, напишите любую
категорию (например «наушники»). Через пару минут должно прийти сообщение
об успешной публикации в Дзен — GitHub Actions выполнит всё в облаке.
Прогресс можно посмотреть на github.com в репозитории: вкладка Actions →
workflow "Telegram Query (Dzen)".
