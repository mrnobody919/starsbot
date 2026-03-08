# Telegram-бот для продажи Stars

Бот для продажи Telegram Stars с оплатой через **CryptoBot**, **Toncoin** и **FreeKassa**. После оплаты создаётся заказ, администратор уведомляется и вручную отправляет Stars пользователю.

## Возможности

- **Главное меню** — инлайн-кнопки: Купить Stars, Мои заказы, Профиль, Реферальная программа, Поддержка
- **Профиль** — ID, реферальная ссылка, количество рефералов, бонусы (10%), успешные заказы и купленные Stars
- **Реферальная система** — 10% от покупок приглашённых пользователей
- **Оплата** — CryptoBot (Stars), TON, FreeKassa (ссылка на оплату + webhook)
- **Админ-панель** (`/admin`) — заказы, фильтры, «Отправил Stars», статистика, блокировка пользователей, рассылка
- **Динамический курс** — обновление TON/USD каждые 5 минут (CoinGecko)
- **Антифрод** — лимит заказов в минуту, проверка подписи FreeKassa, блокировка пользователей
- **Логирование** — операции и логи в файл/консоль

## Структура проекта

```
bot/
├── main.py              # Точка входа
├── config.py            # Конфигурация из env
├── webhook_server.py    # HTTP для webhook FreeKassa
├── handlers/            # Обработчики команд и callback
├── services/           # Платёжные сервисы, цена, антифрод
├── database/           # Модели и работа с БД
├── keyboards/           # Инлайн-клавиатуры
├── middlewares/        # Сессия БД, антифлуд
└── utils/              # Логгер, хелперы
```

## Установка и запуск локально

1. Клонировать репозиторий и перейти в каталог `bot`:

```bash
cd bot
```

2. Создать виртуальное окружение и установить зависимости:

```bash
python -m venv venv
source venv/bin/activate   # Linux/macOS
# или venv\Scripts\activate на Windows
pip install -r requirements.txt
```

3. Скопировать `.env.example` в `.env` и заполнить переменные (см. ниже).

4. Запуск (из корня проекта, где лежит папка `bot`):

```bash
# Из корня репозитория (родитель bot/)
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
python -m bot.main
```

Либо из папки `bot`:

```bash
cd bot
python -m bot.main
```
(при этом родительская папка должна быть в `PYTHONPATH`).

## Переменные окружения

| Переменная | Описание |
|------------|----------|
| `BOT_TOKEN` | Токен бота от @BotFather |
| `BOT_USERNAME` | Username бота (для реферальных ссылок) |
| `DATABASE_URL` | PostgreSQL, например `postgresql://user:pass@host:5432/dbname` |
| `ADMIN_IDS` | ID админов через запятую |
| `FREEKASSA_MERCHANT_ID`, `FREEKASSA_SECRET_WORD_1`, `FREEKASSA_SECRET_WORD_2` | Настройки FreeKassa |
| `WEBHOOK_BASE_URL` | Публичный URL приложения (для FreeKassa notification_url), например `https://your-app.railway.app` |
| `STARS_PER_USD` | Сколько Stars за 1 USD (по умолчанию 100) |
| `MIN_STARS_PER_ORDER`, `MAX_STARS_PER_ORDER` | Лимиты заказа (50 и 50000) |
| `REFERRAL_PERCENT` | Процент реферального бонуса (10) |
| `ANTIFRAUD_MAX_ORDERS_PER_MINUTE` | Лимит заказов в минуту (3) |
| `WEBHOOK_PORT` | Порт для HTTP webhook (по умолчанию 8080) |

Остальные переменные (CryptoBot, TON, поддержка) — см. `.env.example`.

## Развёртывание на Railway

1. Создайте проект на [Railway](https://railway.app), подключите репозиторий.
2. Добавьте сервис **PostgreSQL** (Railway создаст `DATABASE_URL`).
3. В настройках сервиса бота задайте переменные окружения (см. выше). Обязательно укажите `WEBHOOK_BASE_URL`: в Railway это будет вид `https://<your-service>.up.railway.app`.
4. В настройках сборки:
   - **Build Command**: `pip install -r bot/requirements.txt` (или если корень — `pip install -r requirements.txt`)
   - **Start Command**: `python -m bot.main` (запуск из корня: `cd bot && python -m bot.main` или задать **Root Directory** = `bot` и **Start** = `python -m bot.main`)
5. Откройте порт **8080** (или заданный `WEBHOOK_PORT`) для входящих запросов (в Railway это обычно настраивается автоматически при прослушивании порта).
6. В личном кабинете FreeKassa укажите URL уведомлений: `https://<your-app>.up.railway.app/webhook/freekassa`.

Бот будет работать 24/7, при деплое из GitHub сборка и перезапуск выполняются автоматически.

## FreeKassa webhook

Сервер слушает порт из `WEBHOOK_PORT` (по умолчанию 8080). Endpoint: `POST /webhook/freekassa`. После проверки подписи заказ помечается оплаченным, пользователь и админы получают уведомления.

## Логи

Логи пишутся в консоль и при необходимости в файлы в каталоге `logs/` (см. `utils/logger.py`).

## Лицензия

MIT.
