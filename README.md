# Marketplace Ref Bot

Автоматизированная система заработка на реферальных ссылках для маркетплейсов.

## Архитектура

```
┌─────────────────────────────────────────────────────────┐
│                    GitHub Actions                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Parse (q6h)  │  │ Post (q4h)   │  │ Dashboard    │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┘  │
│         │                 │                              │
│         ▼                 ▼                              │
│  ┌──────────────────────────────────┐                    │
│  │      SQLite (marketplace.db)     │                    │
│  └──────────────────────────────────┘                    │
│         │                 │                              │
│         ▼                 ▼                              │
│  ┌──────────────┐  ┌──────────────┐                     │
│  │   Parsers    │  │  TG Bot API  │                     │
│  │  WB│OZ│AL│YM │  │  Autopost    │                     │
│  └──────────────┘  └──────────────┘                     │
└─────────────────────────────────────────────────────────┘
```

## Фичи

- **4 парсера**: Wildberries, Ozon, AliExpress, Яндекс Маркет
- **Автопостинг**: 4 поста/день с товарами со скидками
- **Контент-генерация**: эмодзи, бейджи, CTA-кнопки
- **Трекинг кликов**: через inline-кнопки бота
- **Аналитика**: статистика по кликам, постам, маркетплейсам
- **Дашборд**: HTML-отчёт с Chart.js графиками
- **Дайджест**: ежедневный обзор лучших скидок
- **GitHub Actions**: бесплатная автоматизация 24/7

## Установка

### 1. Секреты GitHub

Добавьте в **Settings → Secrets and variables → Actions**:

| Секрет | Описание |
|--------|----------|
| `TELEGRAM_BOT_TOKEN` | Токен от BotFather |
| `TELEGRAM_CHANNEL_ID` | ID канала (`@name` или `-100xxx`) |
| `ADMIN_USER_IDS` | ID админов через запятую |
| `WB_AFFILIATE_ID` | Реферальный ID WB |
| `OZON_AFFILIATE_ID` | Реферальный ID Ozon |
| `ALIEXPRESS_AFFILIATE_ID` | Реферальный ID AliExpress |
| `YANDEX_MARKET_AFFILIATE_ID` | Реферальный ID Яндекс Маркет |

### 2. Локальный запуск

```bash
cd marketplace-ref-bot
pip install -r requirements.txt
cp .env.example .env  # заполните переменные
python main.py
```

### 3. Запуск через GitHub Actions

Пуш в `main` активирует воркфлоу:
- **Parse**: каждые 6 часов
- **Post**: 4 раза в день (09:00, 13:00, 17:00, 21:00 МСК)

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие |
| `/stats` | Общая статистика |
| `/stats_clicks` | Клики за 7 дней |
| `/top` | Топ товаров |
| `/post` | Опубликовать пост |
| `/digest` | Дайджест дня |
| `/parse` | Запустить парсинг |
| `/search <запрос>` | Поиск товаров |
| `/setposts N` | Постов в день |
| `/setdiscount N` | Мин. скидка (%) |

## Получение реферальных ID

| Партнёрка | Ссылка |
|-----------|--------|
| Wildberries | [adv.wildberries.ru](https://adv.wildberries.ru) |
| Ozon | [ozon.best](https://ozon.best) / admitad |
| AliExpress | [portals.aliexpress.com](https://portals.aliexpress.com) |
| Яндекс Маркет | [market.yandex.ru/partner](https://market.yandex.ru/partner) |

## Дашборд

```bash
python scripts/generate_dashboard.py
# → dashboard/index.html
```

## Структура проекта

```
marketplace-ref-bot/
├── main.py                  # Точка входа
├── config.py                # Конфигурация
├── models.py                # Модели данных
├── database.py              # SQLite база
├── content_generator.py     # Генерация постов
├── scheduler.py             # Планировщик
├── parsers/
│   ├── __init__.py          # Базовый парсер
│   ├── wb_parser.py         # Wildberries
│   ├── ozon_parser.py       # Ozon
│   ├── aliexpress_parser.py # AliExpress
│   └── ym_parser.py         # Яндекс Маркет
├── bot/
│   └── __init__.py          # Telegram бот
├── scripts/
│   ├── parse_only.py        # Только парсинг (CI)
│   ├── post_only.py         # Только постинг (CI)
│   └── generate_dashboard.py
├── dashboard/
│   └── index.html           # Аналитика
├── .github/workflows/
│   ├── parse.yml            # Парсинг по расписанию
│   └── post.yml             # Постинг по расписанию
├── .env.example
├── .gitignore
└── requirements.txt
```

## Автоматизация (GitHub Actions — бесплатно)

- **3000 минут/мес** бесплатно на приватных репах
- Один запуск: ~30 секунд парсинг + ~10 секунд постинг
- ~10 запусков/день = ~300 мин/мес — в рамках бесплатного тира

## Как это зарабатывает

1. Парсеры собирают товары со скидками с маркетплейсов
2. Генератор создаёт привлекательные посты с реферальными ссылками
3. Бот автоматически публикует посты в канал
4. Подписчики переходят по ссылкам и покупают
5. Вы получаете комиссию от партнёрской программы
6. Аналитика показывает, какие товары и маркетплейсы приносят больше всего
