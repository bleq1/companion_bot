# Telegram-бот «Компаньон» + Mini App

Красивое приложение внутри Telegram + обычный бот.

## Что получилось

### 1. Mini App (красивое приложение)
- Современный тёмный дизайн
- Карточки компаньонов с фото
- Плавные переходы
- Открывается прямо внутри Telegram
- Кнопка «Написать» сразу открывает чат с человеком

### 2. Обычный бот
- Список компаньонов
- Оценки и комментарии
- Поддержка
- Раздел «О проекте»

---

## Как запустить

### Шаг 1. Настройте бота

1. Создайте бота у [@BotFather](https://t.me/BotFather)
2. Получите токен
3. Узнайте свой ID через [@userinfobot](https://t.me/userinfobot)

```bash
cp .env.example .env
```

В `.env` пропишите:
```
BOT_TOKEN=ваш_токен
ADMIN_ID=ваш_id
WEBAPP_URL=https://ваш-сайт.vercel.app
```

### Шаг 2. Запустите бота локально

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Mac/Linux

pip install -r requirements.txt
python bot.py
```

### Шаг 3. Задеплойте Mini App на Vercel (бесплатно)

1. Зарегистрируйтесь на [vercel.com](https://vercel.com)
2. Создайте новый проект → Import
3. Загрузите папку `webapp` (или весь проект)
4. Root Directory укажите `webapp`
5. Deploy

После деплоя скопируйте ссылку (типа `https://companion-xxx.vercel.app`) и вставьте её в `.env` как `WEBAPP_URL`.

### Шаг 4. Подключите Mini App к боту

В [@BotFather](https://t.me/BotFather):
1. `/mybots` → выберите бота
2. **Bot Settings** → **Menu Button**
3. Выберите **Configure menu button**
4. Вставьте ссылку на ваш Vercel-сайт

Или просто используйте кнопку «✨ Открыть приложение» в боте.

---

## Структура

```
companion_bot/
├── bot.py                 # Telegram-бот
├── companions.json        # Анкеты
├── webapp/                # Mini App (красивый интерфейс)
│   ├── index.html
│   ├── style.css
│   └── app.js
├── requirements.txt
├── .env.example
└── README.md
```

## Как добавить своих компаньонов

Редактируйте **два** места:

1. `companions.json` — для бота
2. `webapp/app.js` → массив `COMPANIONS` — для приложения

Формат одинаковый.

---

## Дизайн

- Тёмная тема по умолчанию
- Автоматически подстраивается под тему Telegram
- Шрифты Inter + Playfair Display
- Плавные анимации
- Haptic feedback при действиях
