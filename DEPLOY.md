# Деплой бота на Railway (бесплатно)

## 1. Аккаунт
1. Зайди на https://railway.app
2. Войди через GitHub (или Email)

## 2. Новый проект
1. **New Project** → **Deploy from GitHub repo**
   - либо **Empty Project** → **Add Service** → **GitHub Repo**
2. Если репозитория нет — см. ниже «Без GitHub»

### Без GitHub (через CLI) — проще для начала

1. Установи Railway CLI: https://docs.railway.app/guides/cli
   Windows (в PowerShell):
   ```
   iwr https://railway.app/install.ps1 | iex
   ```
2. В папке companion_bot:
   ```
   railway login
   railway init
   railway up
   ```

## 3. Переменные окружения
В Railway → твой сервис → **Variables** добавь:

```
BOT_TOKEN=токен_от_BotFather
ADMIN_ID=твой_id,второй_id
WEBAPP_URL=https://твой-webapp.vercel.app
```

`PORT` Railway выставит сам — не трогай.

## 4. Публичный домен API
1. Railway → сервис → **Settings** → **Networking**
2. **Generate Domain**
3. Получишь ссылку вида:
   `https://companion-bot-production-xxxx.up.railway.app`

## 5. Подключи к Mini App
В `webapp/config.js`:
```js
window.COMPANION_API = "https://companion-bot-production-xxxx.up.railway.app";
```
Перезалей `webapp` на Vercel.

## 6. Проверка
Открой в браузере:
`https://ТВОЙ-ДОМЕН.up.railway.app/api/companions`

Должен вернуться JSON со списком компаньонов.

---

## Альтернатива: Render.com

1. https://render.com → New → Web Service
2. Подключи GitHub-репо с папкой бота
3. Build: `pip install -r requirements.txt`
4. Start: `python bot.py`
5. Instance: Free
6. Environment variables — те же
7. После деплоя: Settings → copy URL

⚠️ На free-плане Render засыпает без запросов ~15 мин.
Railway для бота стабильнее.

---

## Важно
- Бот должен работать **постоянно** (long polling).
- Не выключай сервис в Railway.
- Free-лимиты Railway: следи за usage в Dashboard.


## Сохранение базы (анкеты и отзывы)

На Railway файлы могут сбрасываться при редеплое.

Чтобы `data.db` не пропадала:
1. Service → **Settings** → **Volumes**
2. Add Volume, mount path: `/data`
3. В Variables добавь:
   ```
   DB_PATH=/data/data.db
   ```

В коде путь к базе уже можно задать через env (см. bot.py).
