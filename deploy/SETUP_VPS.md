# Перенос бота на VPS в России

Зачем: IP-адреса GitHub Actions общие для тысяч людей, с них постоянно
кто-то парсит, поэтому Яндекс встречает их капчей SmartCaptcha — это
подтверждено логом боевого запуска (редирект на `market.yandex.ru/showcaptcha`,
заголовок «Вы не робот?»). Обойти это из кода нельзя: блокировка по адресу,
а не по поведению браузера. Нужен российский IP с низким объёмом запросов.

После переезда бот работает ровно так же, как у вас на компьютере, только
круглосуточно и без участия компьютера.

## 1. Какой сервер брать

Провайдер любой российский (Timeweb, Beget, aeza, Selectel, reg.ru).
Важны только характеристики:

- **ОЗУ: 2 ГБ** — это главное. Бот запускает headless-Chromium, а он
  прожорлив. На 1 ГБ Chromium будет падать по нехватке памяти на середине
  публикации; если всё же берёте 1 ГБ — обязательно добавьте swap (см. п. 3).
- ЦП: 1 ядра достаточно, бот работает редко и недолго.
- Диск: 20 ГБ (один Chromium занимает около 400 МБ).
- ОС: **Ubuntu 24.04** (команды ниже написаны под неё).
- Локация: **Россия**. Это весь смысл переезда.

## 2. Первый вход

Провайдер пришлёт IP и пароль root. Заходим с вашего компьютера:

```bash
ssh root@ВАШ_IP
```

## 3. Подготовка системы

```bash
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-pip git

# Только если взяли сервер с 1 ГБ ОЗУ — иначе пропустите:
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

## 4. Код и зависимости

```bash
cd /root
git clone https://github.com/Spiridonov127/marketplace-ref-bot.git
cd marketplace-ref-bot

python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt playwright
./venv/bin/playwright install --with-deps chromium
```

Последняя команда качает Chromium и системные библиотеки к нему — занимает
несколько минут.

## 5. Настройки и куки

Файлы `.env` и куки в git не лежат (и правильно) — копируем их со своего
компьютера. **В отдельном терминале у себя**, не на сервере:

```bash
cd ~/marketplace-ref-bot
scp .env root@ВАШ_IP:/root/marketplace-ref-bot/.env
scp data/dzen_cookies.json data/distribution_cookies.json \
    root@ВАШ_IP:/root/marketplace-ref-bot/data/
```

Если `scp` ругается, что каталога `data` нет — создайте его на сервере
(`mkdir -p /root/marketplace-ref-bot/data`) и повторите.

## 6. Отключить вебхук Telegram

Обязательный шаг. Сейчас Telegram шлёт сообщения в Cloudflare Worker.
Бот на сервере работает опросом (long polling), а одновременно с вебхуком
это невозможно — будут ошибки 409. **На сервере**:

```bash
cd /root/marketplace-ref-bot
TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' .env | cut -d= -f2- | tr -d '\n')
curl -s "https://api.telegram.org/bot$TOKEN/deleteWebhook"
```

Должно вернуть `{"ok":true,...}`.

Cloudflare Worker и workflow в GitHub после этого просто перестают
использоваться. Удалять их не нужно — денег они не стоят и останутся как
запасной вариант.

## 7. Проверка вручную

Перед тем как ставить в автозапуск, убедимся, что всё работает:

```bash
cd /root/marketplace-ref-bot
./venv/bin/python main.py
```

Возьмите телефон, нажмите в боте /start, напишите «часы». Следите за
выводом в консоли сервера. Если статья опубликовалась — останавливайте
(Ctrl+C) и переходите к автозапуску.

## 8. Автозапуск

```bash
cp /root/marketplace-ref-bot/deploy/marketplace-bot.service \
   /etc/systemd/system/marketplace-bot.service
systemctl daemon-reload
systemctl enable --now marketplace-bot
systemctl status marketplace-bot
```

Бот теперь стартует сам при перезагрузке сервера и поднимается обратно,
если процесс упадёт.

Смотреть логи в реальном времени:

```bash
journalctl -u marketplace-bot -f
```

Перезапустить после обновления кода:

```bash
cd /root/marketplace-ref-bot && git pull
systemctl restart marketplace-bot
```

## Если что-то пойдёт не так

**Снова капча.** Маловероятно, но некоторые диапазоны хостингов у Яндекса
тоже на подозрении. Диагностика уже встроена: в логе будет «Яндекс Маркет
показал капчу», а скриншот ляжет в `data/ym_debug_captcha.png`. Лечится
сменой провайдера или добавлением прокси.

**Просит войти в Яндекс.** Куки снимались в браузере на вашем домашнем
IP, и Яндекс может не принять их с нового адреса. Тогда куки надо
переснять — и Дзена, и Дистрибуции — и заново скопировать на сервер
(`save_dzen_cookies()` и `save_distribution_cookies.py` запускаются на
вашем компьютере, им нужен видимый браузер).

**Chromium падает.** Почти всегда нехватка памяти: проверьте `free -h`,
добавьте swap из пункта 3.
