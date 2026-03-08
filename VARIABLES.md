# Переменные для Railway (Variables)

Добавляйте их во вкладке **Variables** сервиса бота. Имя — слева, значение — справа (без кавычек).

---

## Обязательные (без них бот не запустится)

| Переменная   | Пример значения        | Откуда взять |
|-------------|-------------------------|--------------|
| `BOT_TOKEN` | `8714948872:AAGyPC6_...` | @BotFather → токен бота |
| `DATABASE_URL` или `DATABASE_PRIVATE_URL` | `postgresql://...` | **Лучше приватный URL** (без egress): в сервисе PostgreSQL скопировать **Private** URL. Если используете публичный (`DATABASE_PUBLIC_URL`) — будет платный исходящий трафик. |
| `ADMIN_IDS` | `1200042735` | Ваш Telegram ID (несколько через запятую: `123,456`) |

**BOT_USERNAME** (рекомендуется): имя бота без @, например `thexstarsbot` — для реферальных ссылок.

**Важно:** Бот подключается по **приватному** URL, если задан `DATABASE_PRIVATE_URL` (так не начисляется egress в Railway). Иначе используется `DATABASE_URL`. Укажите URL из сервиса PostgreSQL (Private — в панели БД, вкладка Variables или Connect → Private). Если бот падает с «Temporary failure in name resolution» — проверьте, что хост не localhost. До 5 попыток подключения с паузой 5 сек (`DB_CONNECT_ATTEMPTS`, `DB_CONNECT_DELAY` — по желанию).

---

## FreeKassa (если нужна оплата через FreeKassa)

| Переменная   | Пример |
|-------------|--------|
| `FREEKASSA_MERCHANT_ID` | ID магазина из кабинета FreeKassa |
| `FREEKASSA_SECRET_WORD_1` | Секретное слово 1 |
| `FREEKASSA_SECRET_WORD_2` | Секретное слово 2 |
| `FREEKASSA_ENABLED` | Поставьте **0** или **false**, пока FreeKassa ещё не активирован — кнопка и СБП не показываются. После активации уберите переменную или поставьте **1**. |
| `WEBHOOK_BASE_URL` | `https://web-production-59ae8.up.railway.app` (ваш домен Railway) |

Без этих переменных бот запустится, но кнопка «FreeKassa» не будет показана.

---

## TON (Toncoin)

Чтобы в боте работала оплата **Toncoin** (кнопка «Toncoin» и ссылка на перевод):

| Переменная | Пример / откуда взять |
|------------|------------------------|
| `TON_WALLET_ADDRESS` | Адрес вашего TON-кошелька, например `UQD7kv9rKnNeTUVpk9o8JXUXkvULVkdwgBtBpvIiM5nqHpV_`. Можно взять из Tonkeeper, TON Space или другого кошелька (раздел «Получить» → скопировать адрес). |

Опционально (для автоматической проверки платежей в будущем):

| Переменная | Зачем |
|------------|--------|
| `TON_API_KEY` | Ключ от TON API (toncenter.com или tonapi.io) для проверки входящих транзакций. Сейчас бот без него выдаёт ссылку на оплату; подтверждение заказа — вручную через админку. |

Без `TON_WALLET_ADDRESS` кнопка «Toncoin» не показывается или при выборе будет «временно недоступна».

---

## CryptoBot (Stars через @CryptoBot)

Оплата **Telegram Stars** через CryptoBot. Сейчас бот при выборе «CryptoBot» показывает подсказку оплатить через @CryptoBot; для автоматических инвойсов в боте можно добавить:

| Переменная | Откуда взять |
|------------|--------------|
| `CRYPTOBOT_API_TOKEN` | @CryptoBot → Crypto Pay → Create App → скопировать API-токен. |
| `CRYPTOBOT_MERCHANT_ID` | Там же в Crypto Pay (если нужен для API). |

Если переменные не заданы, кнопка «CryptoBot» всё равно есть; пользователю показывается текст «Оплатите через @CryptoBot».

---

## По желанию

| Переменная | По умолчанию | Зачем |
|------------|--------------|--------|
| `SUPPORT_LINK` | — | Ссылка «Поддержка», например `https://t.me/username` |
| `USD_PER_STAR` | `0.0175` | Курс: 1 Star = 0.0175 USD (цена в долларах за одну звезду) |
| **Курс TON** | **автоматический** | По умолчанию курс TON/USD берётся с CoinGecko и обновляется каждые 10 мин. Сумма в TON = сумма в USD ÷ курс TON/USD. Переменные ниже — только если нужен ручной курс. |
| `TON_USD_RATE` | — | Ручной курс: 1 TON = N USD (напр. `1.33`). Не задавайте для автоматического курса. |
| `TON_PER_STAR` | — | Ручной курс: 1 Star = N TON. Не задавайте для автоматического курса. |
| `PRICE_UPDATE_INTERVAL` | `600` | Интервал автообновления курса TON/USD в секундах (10 мин) |
| `MIN_STARS_PER_ORDER` | `50` | Минимум Stars в одном заказе |
| `MAX_STARS_PER_ORDER` | `50000` | Максимум Stars в одном заказе |
| `REFERRAL_PERCENT` | `10` | Процент реферального бонуса |
| `LOG_LEVEL` | `INFO` | Уровень логов: DEBUG, INFO, WARNING, ERROR |
| `RUB_PER_USD` | `100` | Курс ₽/USD для зачисления баланса при пополнении через FreeKassa (СБП) |
| `ORDERS_CHANNEL_ID` | — | ID канала или группы (например `-1001234567890`). Все оплаченные заказы дублируются туда. Добавьте бота в канал/группу как администратора с правом «Публикация сообщений». ID можно узнать, переслав сообщение из чата боту @RawDataBot. |

---

## Итоговый минимум для Railway

Добавьте **вручную** хотя бы:

1. **BOT_TOKEN** — токен от @BotFather  
2. **ADMIN_IDS** — ваш Telegram ID (узнать: @userinfobot)  
3. **BOT_USERNAME** — имя бота без @  

**DATABASE_URL** обычно подставляется Railway, если к сервису бота привязана БД PostgreSQL.

- Для **FreeKassa**: **FREEKASSA_MERCHANT_ID**, **FREEKASSA_SECRET_WORD_1**, **FREEKASSA_SECRET_WORD_2**, **WEBHOOK_BASE_URL**.
- Для **TON**: **TON_WALLET_ADDRESS** (адрес кошелька для приёма TON).
- Для **CryptoBot** (опционально): **CRYPTOBOT_API_TOKEN** из @CryptoBot → Crypto Pay.
