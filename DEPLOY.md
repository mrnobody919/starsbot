# Как задеплоить бота

## Вариант 1: Railway (рекомендуется)

### 1. Подготовка репозитория

- Закоммитьте проект в **Git** и залейте на **GitHub** (или GitLab).
- Убедитесь, что в корне есть папка `bot/`, файлы `Procfile` и `requirements.txt` в `bot/requirements.txt`.

### 2. Создание проекта на Railway

1. Зайдите на [railway.app](https://railway.app) и войдите через GitHub.
2. **New Project** → **Deploy from GitHub repo** → выберите ваш репозиторий.
3. Railway создаст один сервис из репозитория. Пока что это только бот, без БД.

### 3. Добавление PostgreSQL

1. В проекте нажмите **+ New** → **Database** → **PostgreSQL**.
2. Дождитесь создания БД. Railway выдаст переменную **DATABASE_URL** (она подставится в сервис бота автоматически, если включена общая конфигурация, или её можно скопировать вручную).

### 4. Настройка сервиса бота

1. Откройте сервис с вашим кодом (не БД).
2. Вкладка **Variables** — добавьте переменные окружения:

| Переменная | Значение |
|------------|----------|
| `BOT_TOKEN` | Токен от @BotFather |
| `BOT_USERNAME` | Имя бота без @ (например `thexstarsbot`) |
| `ADMIN_IDS` | Ваш Telegram ID (число), можно несколько через запятую |
| `DATABASE_PRIVATE_URL` или `DATABASE_URL` | Из сервиса PostgreSQL взять **приватный** URL (Private), чтобы не платить за egress. Бот сначала использует `DATABASE_PRIVATE_URL`, если он задан. |
| `FREEKASSA_MERCHANT_ID` | ID магазина из FreeKassa |
| `FREEKASSA_SECRET_WORD_1` | Секретное слово 1 |
| `FREEKASSA_SECRET_WORD_2` | Секретное слово 2 |
| `WEBHOOK_BASE_URL` | **Заполнить после деплоя** — публичный URL сервиса (см. ниже) |

Остальные переменные (TON, поддержка и т.д.) — по желанию, как в `.env.example`.

### 5. Сборка и запуск

1. **Settings** → **Build**:
   - **Build Command:** `pip install -r bot/requirements.txt`
   - **Root Directory:** оставьте пустым (корень репозитория).
2. **Start Command:** оставьте пустым — Railway возьмёт команду из **Procfile** (`web: python -m bot.main`).
3. **Deploy** — Railway соберёт образ и запустит бота. Порт берётся из переменной **PORT** (Railway задаёт её сам).

### 6. Публичный URL и FreeKassa

1. В **Settings** сервиса бота откройте **Networking** → **Generate Domain**. Railway выдаст домен, например: `web-production-59ae8.up.railway.app`.
2. **Variables создаются вручную.** Откройте вкладку **Variables** у сервиса бота и нажмите **+ New Variable** (или **Add Variable**). Добавьте переменную:
   - **Имя:** `WEBHOOK_BASE_URL`
   - **Значение:** `https://web-production-59ae8.up.railway.app` (подставьте свой домен из шага 1, обязательно с `https://`).
   Сохранённых переменных из шага 4 (BOT_TOKEN, FREEKASSA_* и т.д.) это не заменяет — добавляется ещё одна строка.
3. В личном кабинете **FreeKassa** в поле **URL оповещения** укажите:
   - `https://web-production-59ae8.up.railway.app/webhook/freekassa` (свой домен из шага 1).
   - Метод: **GET** (или POST — оба поддерживаются).

После каждого пуша в GitHub Railway будет пересобирать и перезапускать бота. 

---

## Вариант 2: Свой VPS (Ubuntu/Debian)

### 1. Установка зависимостей на сервере

```bash
sudo apt update
sudo apt install python3.11 python3-pip python3-venv postgresql -y
```

### 2. Клонирование и настройка

```bash
cd /opt
sudo git clone https://github.com/ВАШ_ЛОГИН/ВАШ_РЕПО.git stars-bot
cd stars-bot
sudo chown -R $USER:$USER .
python3 -m venv venv
source venv/bin/activate
pip install -r bot/requirements.txt
```

### 3. База данных

```bash
sudo -u postgres psql -c "CREATE USER starsbot WITH PASSWORD 'надёжный_пароль';"
sudo -u postgres psql -c "CREATE DATABASE stars_bot OWNER starsbot;"
```

В `.env` (или в systemd) задайте:
`DATABASE_URL=postgresql://starsbot:надёжный_пароль@localhost:5432/stars_bot`

### 4. Запуск через systemd (постоянная работа)

Создайте файл `/etc/systemd/system/stars-bot.service`:

```ini
[Unit]
Description=Stars Telegram Bot
After=network.target postgresql.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/stars-bot
EnvironmentFile=/opt/stars-bot/bot/.env
ExecStart=/opt/stars-bot/venv/bin/python -m bot.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Подставьте свой путь и пользователя. Затем:

```bash
sudo systemctl daemon-reload
sudo systemctl enable stars-bot
sudo systemctl start stars-bot
sudo systemctl status stars-bot
```

### 5. Nginx для webhook (HTTPS)

Чтобы FreeKassa мог слать запросы на ваш сервер, поднимите Nginx с SSL (например, Let's Encrypt) и проксируйте запросы на порт, который слушает бот (например 8080):

```nginx
location /webhook/freekassa {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

В `.env` укажите `WEBHOOK_BASE_URL=https://ваш-домен.ru`. В FreeKassa — URL оповещения: `https://ваш-домен.ru/webhook/freekassa`.

---

## Частые проблемы

- **Conflict: terminated by other getUpdates** — одновременно работает больше одного экземпляра бота (например локально и на Railway). Остановите все, кроме одного: только один процесс должен вызывать long polling.
- **429 Too Many Requests (CoinGecko)** — курс TON обновляется реже (интервал 10 мин по умолчанию). При 429 используется последний известный курс.
- **Кнопки «Профиль» / «Реферальная программа» не реагируют** — убедитесь, что задеплоена последняя версия с безопасным ответом на callback; при долгом ответе Telegram может считать запрос устаревшим.

---

## Проверка после деплоя

1. Откройте в браузере: `https://ваш-домен/health` — должно вернуться `ok`.
2. Напишите боту в Telegram команду `/start` — должно открыться меню.
3. В FreeKassa сделайте тестовый платёж и убедитесь, что в бота приходит уведомление об оплате (и при необходимости проверьте логи на Railway или через `journalctl -u stars-bot -f` на VPS).
