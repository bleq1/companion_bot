import asyncio
import json
import logging
import os
from pathlib import Path

import aiosqlite
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    Message,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
# Несколько админов через запятую: ADMIN_ID=111,222,333
_ADMIN_RAW = os.getenv("ADMIN_ID", "0")
ADMIN_IDS = {int(x.strip()) for x in _ADMIN_RAW.split(",") if x.strip().isdigit()}
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://your-app.vercel.app")
# На хостинге (Railway/Render) приходит PORT; локально — 8080
API_PORT = int(os.getenv("PORT") or os.getenv("API_PORT") or "8080")


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def notify_admins(bot: Bot, text: str, photo_file_id=None, reply_markup=None):
    for aid in ADMIN_IDS:
        try:
            if photo_file_id:
                await bot.send_photo(aid, photo_file_id, caption=text, reply_markup=reply_markup, parse_mode="HTML")
            else:
                await bot.send_message(aid, text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            logger.error(f"notify admin {aid}: {e}")

BASE_DIR = Path(__file__).parent
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "data.db")))
COMPANIONS_PATH = BASE_DIR / "companions.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
router = Router()


# ================== STATES ==================
class RateStates(StatesGroup):
    waiting_for_rating = State()
    waiting_for_comment = State()


class SupportStates(StatesGroup):
    waiting_for_message = State()


class ApplyStates(StatesGroup):
    name = State()
    age = State()
    interests = State()
    about = State()
    soft_skills = State()
    username = State()
    photo = State()
    confirm = State()


class EditStates(StatesGroup):
    choosing_field = State()
    waiting_value = State()


# ================== DATABASE ==================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                companion_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tg_username TEXT,
                name TEXT NOT NULL,
                age INTEGER NOT NULL,
                interests TEXT NOT NULL,
                about TEXT NOT NULL,
                soft_skills TEXT,
                photo_file_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS companions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                age INTEGER NOT NULL,
                interests TEXT NOT NULL,
                about TEXT NOT NULL,
                soft_skills TEXT,
                username TEXT NOT NULL,
                photo_url TEXT,
                photo_file_id TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

        # Seed from JSON if empty
        async with db.execute("SELECT COUNT(*) FROM companions") as cur:
            count = (await cur.fetchone())[0]
        if count == 0 and COMPANIONS_PATH.exists():
            with open(COMPANIONS_PATH, "r", encoding="utf-8") as f:
                items = json.load(f)
            for c in items:
                await db.execute(
                    """INSERT INTO companions
                       (name, age, interests, about, soft_skills, username, photo_url)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        c["name"], c["age"],
                        json.dumps(c["interests"], ensure_ascii=False),
                        c["about"],
                        json.dumps(c.get("soft_skills", []), ensure_ascii=False),
                        c["username"],
                        c.get("photo_url") or None,
                    ),
                )
            await db.commit()
            logger.info("Seeded companions from JSON")


async def add_rating(companion_id, user_id, username, rating, comment):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO ratings (companion_id, user_id, username, rating, comment) VALUES (?, ?, ?, ?, ?)",
            (companion_id, user_id, username, rating, comment),
        )
        await db.commit()


async def get_ratings(companion_id, limit=20):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, rating, comment, username, created_at FROM ratings WHERE companion_id = ? ORDER BY created_at DESC LIMIT ?",
            (companion_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        if not rows:
            return 0.0, []
        avg = sum(r[1] for r in rows) / len(rows)
        return round(avg, 1), rows


async def delete_rating(rating_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM ratings WHERE id = ?", (rating_id,))
        await db.commit()
        return cur.rowcount > 0


async def get_companions(active_only=True):
    async with aiosqlite.connect(DB_PATH) as db:
        q = "SELECT id, name, age, interests, about, soft_skills, username, photo_url, photo_file_id, is_active FROM companions"
        if active_only:
            q += " WHERE is_active = 1"
        q += " ORDER BY id"
        async with db.execute(q) as cur:
            rows = await cur.fetchall()
    result = []
    for r in rows:
        result.append({
            "id": r[0],
            "name": r[1],
            "age": r[2],
            "interests": json.loads(r[3]) if r[3] else [],
            "about": r[4],
            "soft_skills": json.loads(r[5]) if r[5] else [],
            "username": r[6],
            "photo_url": r[7],
            "photo_file_id": r[8],
            "is_active": r[9] if len(r) > 9 else 1,
        })
    return result


async def get_companion(companion_id):
    comps = await get_companions(active_only=False)
    for c in comps:
        if c["id"] == companion_id:
            return c
    return None


async def save_application(data):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO applications
               (user_id, tg_username, name, age, interests, about, soft_skills, photo_file_id, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (
                data["user_id"], data.get("tg_username"),
                data["name"], data["age"], data["interests"],
                data["about"], data.get("soft_skills", ""),
                data.get("photo_file_id"),
            ),
        )
        await db.commit()
        return cur.lastrowid


async def get_pending_applications():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, user_id, tg_username, name, age, interests, about, soft_skills, photo_file_id, created_at FROM applications WHERE status = 'pending' ORDER BY created_at"
        ) as cur:
            return await cur.fetchall()


async def get_application(app_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, user_id, tg_username, name, age, interests, about, soft_skills, photo_file_id, status FROM applications WHERE id = ?",
            (app_id,),
        ) as cur:
            return await cur.fetchone()


async def set_application_status(app_id, status):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE applications SET status = ? WHERE id = ?", (status, app_id))
        await db.commit()


async def approve_application(app_id):
    app = await get_application(app_id)
    if not app:
        return None
    # id, user_id, tg_username, name, age, interests, about, soft_skills, photo_file_id, status
    async with aiosqlite.connect(DB_PATH) as db:
        interests = [x.strip() for x in (app[5] or "").split(",") if x.strip()]
        soft = [x.strip() for x in (app[7] or "").split(",") if x.strip()]
        username = app[2] or f"user_{app[1]}"
        cur = await db.execute(
            """INSERT INTO companions (name, age, interests, about, soft_skills, username, photo_file_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                app[3], app[4],
                json.dumps(interests, ensure_ascii=False),
                app[6],
                json.dumps(soft, ensure_ascii=False),
                username,
                app[8],
            ),
        )
        await db.execute("UPDATE applications SET status = 'approved' WHERE id = ?", (app_id,))
        await db.commit()
        return cur.lastrowid



async def update_companion_field(companion_id: int, field: str, value):
    allowed = {
        "name", "age", "interests", "about", "soft_skills",
        "username", "photo_url", "photo_file_id", "is_active"
    }
    if field not in allowed:
        raise ValueError(f"Bad field: {field}")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE companions SET {field} = ? WHERE id = ?", (value, companion_id))
        await db.commit()


async def delete_companion(companion_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM companions WHERE id = ?", (companion_id,))
        await db.execute("DELETE FROM ratings WHERE companion_id = ?", (companion_id,))
        await db.commit()


# ================== KEYBOARDS ==================
def main_menu_kb(is_admin=False):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✨ Открыть приложение", web_app=WebAppInfo(url=WEBAPP_URL)))
    builder.row(InlineKeyboardButton(text="👥 Компаньоны", callback_data="companions"))
    builder.row(InlineKeyboardButton(text="📝 Стать компаньоном", callback_data="apply"))
    builder.row(InlineKeyboardButton(text="ℹ️ О проекте", callback_data="about"))
    builder.row(InlineKeyboardButton(text="💬 Связь с поддержкой", callback_data="support"))
    if is_admin:
        builder.row(InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin"))
    return builder.as_markup()


def companions_list_kb(companions):
    builder = InlineKeyboardBuilder()
    for c in companions:
        builder.row(InlineKeyboardButton(text=f"{c['name']}, {c['age']}", callback_data=f"comp_{c['id']}"))
    builder.row(InlineKeyboardButton(text="« Назад", callback_data="back_main"))
    return builder.as_markup()


def companion_card_kb(companion_id):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💬 Начать общение", callback_data=f"chat_{companion_id}"))
    builder.row(InlineKeyboardButton(text="⭐ Оставить оценку", callback_data=f"rate_{companion_id}"))
    builder.row(InlineKeyboardButton(text="📝 Отзывы", callback_data=f"reviews_{companion_id}"))
    builder.row(InlineKeyboardButton(text="« К списку", callback_data="companions"))
    return builder.as_markup()


def rating_kb(companion_id):
    builder = InlineKeyboardBuilder()
    for i in range(1, 6):
        builder.add(InlineKeyboardButton(text=f"{i} ⭐", callback_data=f"setrate_{companion_id}_{i}"))
    builder.adjust(5)
    builder.row(InlineKeyboardButton(text="« Отмена", callback_data=f"comp_{companion_id}"))
    return builder.as_markup()


def admin_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📋 Заявки на модерацию", callback_data="admin_apps"))
    builder.row(InlineKeyboardButton(text="👥 Список компаньонов", callback_data="admin_comps"))
    builder.row(InlineKeyboardButton(text="« В меню", callback_data="back_main"))
    return builder.as_markup()


# ================== HANDLERS ==================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_is_admin = is_admin(message.from_user.id)
    text = (
        "Привет 👋\n\n"
        "Это <b>Компаньон</b> — бесплатная поддержка от живых людей.\n\n"
        "Без диагнозов, без оплаты и без обязательств.\n"
        "Просто человек рядом, когда он нужен.\n\n"
        "Нажми кнопку ниже ↓"
    )
    await message.answer(text, reply_markup=main_menu_kb(user_is_admin), parse_mode="HTML")


@router.callback_query(F.data == "back_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_is_admin = is_admin(callback.from_user.id)
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb(user_is_admin))
    await callback.answer()


@router.callback_query(F.data == "about")
async def about_project(callback: CallbackQuery):
    text = (
        "<b>О проекте</b>\n\n"
        "Мы — небольшая команда людей, которые просто хотят быть рядом, когда это нужно.\n\n"
        "<b>Зачем?</b>\n"
        "Иногда хочется выговориться живому человеку. Без записи, без денег и без ощущения, что ты «пациент».\n\n"
        "<b>Для кого?</b>\n"
        "Для тех, кому тяжело, одиноко, тревожно, или просто хочется поговорить по интересам.\n\n"
        "<b>Важно:</b>\n"
        "• Мы <b>не психологи</b> и не врачи.\n"
        "• Это не терапия и не замена профессиональной помощи.\n\n"
        "поддержка · понимание · диалог"
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="« Назад", callback_data="back_main"))
    await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "companions")
async def show_companions(callback: CallbackQuery):
    companions = await get_companions()
    if not companions:
        await callback.answer("Пока нет компаньонов", show_alert=True)
        return
    text = (
        "<b>Наши компаньоны</b>\n\n"
        "Выберите человека. Можно оставить оценку и посмотреть отзывы."
    )
    await callback.message.answer(text, reply_markup=companions_list_kb(companions), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("comp_"))
async def show_companion_card(callback: CallbackQuery):
    companion_id = int(callback.data.split("_")[1])
    companion = await get_companion(companion_id)
    if not companion:
        await callback.answer("Не найден", show_alert=True)
        return

    avg, _ = await get_ratings(companion_id)
    rating_text = f"⭐ {avg}/5" if avg > 0 else "Пока нет оценок"
    interests = ", ".join(companion["interests"])
    soft = ", ".join(companion.get("soft_skills") or [])
    soft_line = f"\n\n<b>Софт-скиллы:</b> {soft}" if soft else ""

    text = (
        f"<b>{companion['name']}</b>, {companion['age']}\n"
        f"{rating_text}\n\n"
        f"<b>Интересы:</b> {interests}"
        f"{soft_line}\n\n"
        f"{companion['about']}"
    )
    kb = companion_card_kb(companion_id)

    # photo: prefer file_id, then url
    try:
        if companion.get("photo_file_id"):
            await callback.message.answer_photo(
                photo=companion["photo_file_id"], caption=text, reply_markup=kb, parse_mode="HTML"
            )
        elif companion.get("photo_url"):
            await callback.message.answer_photo(
                photo=companion["photo_url"], caption=text, reply_markup=kb, parse_mode="HTML"
            )
        else:
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Photo failed: {e}")
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("chat_"))
async def start_chat(callback: CallbackQuery):
    companion_id = int(callback.data.split("_")[1])
    companion = await get_companion(companion_id)
    if not companion:
        await callback.answer("Не найден", show_alert=True)
        return
    text = (
        f"Чтобы начать общение с <b>{companion['name']}</b>:\n\n"
        f"👉 @{companion['username']}\n\n"
        f"Можете сказать, что нашли через бот."
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="« Назад", callback_data=f"comp_{companion_id}"))
    await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("rate_"))
async def start_rating(callback: CallbackQuery, state: FSMContext):
    companion_id = int(callback.data.split("_")[1])
    companion = await get_companion(companion_id)
    if not companion:
        await callback.answer("Не найден", show_alert=True)
        return
    await state.update_data(companion_id=companion_id)
    await state.set_state(RateStates.waiting_for_rating)
    await callback.message.answer(
        f"Оцените общение с <b>{companion['name']}</b>:",
        reply_markup=rating_kb(companion_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("setrate_"), RateStates.waiting_for_rating)
async def set_rating(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    companion_id, rating = int(parts[1]), int(parts[2])
    await state.update_data(rating=rating, companion_id=companion_id)
    await state.set_state(RateStates.waiting_for_comment)
    await callback.message.edit_text(
        f"Вы поставили <b>{rating} ⭐</b>\n\nНапишите комментарий или отправьте «-»:",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(RateStates.waiting_for_comment)
async def save_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    comment = message.text.strip() if message.text and message.text.strip() != "-" else None
    await add_rating(
        data["companion_id"], message.from_user.id,
        message.from_user.username, data["rating"], comment,
    )
    await state.clear()
    user_is_admin = is_admin(message.from_user.id)
    await message.answer("Спасибо! Оценка сохранена ❤️", reply_markup=main_menu_kb(user_is_admin))


@router.callback_query(F.data.startswith("reviews_"))
async def show_reviews(callback: CallbackQuery):
    companion_id = int(callback.data.split("_")[1])
    companion = await get_companion(companion_id)
    if not companion:
        await callback.answer("Не найден", show_alert=True)
        return
    avg, reviews = await get_ratings(companion_id)
    admin = is_admin(callback.from_user.id)
    if not reviews:
        text = f"Пока нет отзывов о <b>{companion['name']}</b>."
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="« Назад", callback_data=f"comp_{companion_id}"))
        await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        await callback.answer()
        return

    text = f"<b>Отзывы о {companion['name']}</b>\nСредняя: ⭐ {avg}/5\n\n"
    for r in reviews[:10]:
        rid, rating, comment, username, _ = r
        user = f"@{username}" if username else "Аноним"
        cmt = f" — «{comment}»" if comment else ""
        text += f"#{rid} {'⭐' * rating} от {user}{cmt}\n"

    builder = InlineKeyboardBuilder()
    if admin:
        # Кнопки удаления для каждого отзыва
        for r in reviews[:10]:
            rid, rating, comment, username, _ = r
            label = f"🗑 Удалить #{rid} ({rating}★)"
            builder.row(InlineKeyboardButton(text=label, callback_data=f"delrev_{rid}_{companion_id}"))
    builder.row(InlineKeyboardButton(text="« Назад", callback_data=f"comp_{companion_id}"))
    await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("delrev_"))
async def admin_delete_review(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    parts = callback.data.split("_")
    rating_id = int(parts[1])
    companion_id = int(parts[2])
    ok = await delete_rating(rating_id)
    if ok:
        await callback.answer("Отзыв удалён")
        # Обновляем список
        companion = await get_companion(companion_id)
        avg, reviews = await get_ratings(companion_id)
        if not reviews:
            text = f"Пока нет отзывов о <b>{companion['name'] if companion else ''}</b>."
            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(text="« Назад", callback_data=f"comp_{companion_id}"))
            await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
            return
        text = f"<b>Отзывы о {companion['name']}</b>\nСредняя: ⭐ {avg}/5\n\n"
        builder = InlineKeyboardBuilder()
        for r in reviews[:10]:
            rid, rating, comment, username, _ = r
            user = f"@{username}" if username else "Аноним"
            cmt = f" — «{comment}»" if comment else ""
            text += f"#{rid} {'⭐' * rating} от {user}{cmt}\n"
            builder.row(InlineKeyboardButton(text=f"🗑 Удалить #{rid} ({rating}★)", callback_data=f"delrev_{rid}_{companion_id}"))
        builder.row(InlineKeyboardButton(text="« Назад", callback_data=f"comp_{companion_id}"))
        try:
            await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        except Exception:
            await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await callback.answer("Уже удалён или не найден", show_alert=True)


# ---------- SUPPORT ----------
@router.callback_query(F.data == "support")
async def support_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SupportStates.waiting_for_message)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="« Отмена", callback_data="back_main"))
    await callback.message.answer(
        "Напишите сообщение поддержке.\n/cancel — отмена.",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.message(SupportStates.waiting_for_message)
async def support_message(message: Message, state: FSMContext, bot: Bot):
    if message.text and message.text.lower() in ["/cancel", "отмена"]:
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu_kb(is_admin(message.from_user.id)))
        return
    await state.clear()
    user = message.from_user
    text_to_admin = (
        f"📩 <b>Поддержка</b>\n\n"
        f"От: {user.full_name} (@{user.username or 'нет'})\n"
        f"ID: <code>{user.id}</code>\n\n"
        f"{message.text or '[медиа]'}"
    )
    photo_id = message.photo[-1].file_id if message.photo else None
    await notify_admins(bot, text_to_admin, photo_file_id=photo_id)
    await message.answer("Отправлено. Мы ответим в личку.", reply_markup=main_menu_kb(is_admin(user.id)))


# ---------- APPLY (registration) ----------
@router.callback_query(F.data == "apply")
async def apply_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(ApplyStates.name)
    await callback.message.answer(
        "Заявка на компаньона 📝\n\n"
        "Как вас представить? (имя или ник, как в анкете)\n\n"
        "/cancel — отмена"
    )
    await callback.answer()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_menu_kb(is_admin(message.from_user.id)))


@router.message(ApplyStates.name)
async def apply_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(ApplyStates.age)
    await message.answer("Сколько вам лет? (число)")


@router.message(ApplyStates.age)
async def apply_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if not 16 <= age <= 80:
            raise ValueError
    except ValueError:
        await message.answer("Введите возраст числом от 16 до 80")
        return
    await state.update_data(age=age)
    await state.set_state(ApplyStates.interests)
    await message.answer("Интересы через запятую:\nнапример: психология, книги, спорт")


@router.message(ApplyStates.interests)
async def apply_interests(message: Message, state: FSMContext):
    await state.update_data(interests=message.text.strip())
    await state.set_state(ApplyStates.about)
    await message.answer("Коротко о себе — чем можете помочь (2–5 предложений):")


@router.message(ApplyStates.about)
async def apply_about(message: Message, state: FSMContext):
    await state.update_data(about=message.text.strip())
    await state.set_state(ApplyStates.soft_skills)
    await message.answer("Софт-скиллы через запятую (или «-»):\nнапример: эмпатия, терпение, честность")


@router.message(ApplyStates.soft_skills)
async def apply_soft(message: Message, state: FSMContext):
    val = message.text.strip()
    await state.update_data(soft_skills="" if val == "-" else val)
    await state.set_state(ApplyStates.username)
    uname = message.from_user.username
    hint = f"\nСейчас у вас: @{uname}" if uname else "\nУ вас нет username — укажите, как с вами связаться"
    await message.answer(f"Ваш Telegram username (без @):{hint}")


@router.message(ApplyStates.username)
async def apply_username(message: Message, state: FSMContext):
    uname = message.text.strip().lstrip("@")
    await state.update_data(username=uname, tg_username=uname)
    await state.set_state(ApplyStates.photo)
    await message.answer("Пришлите фото для анкеты (или напишите «пропустить»):")


@router.message(ApplyStates.photo)
async def apply_photo(message: Message, state: FSMContext):
    if message.photo:
        await state.update_data(photo_file_id=message.photo[-1].file_id)
    elif message.text and message.text.lower() in ("пропустить", "-", "skip"):
        await state.update_data(photo_file_id=None)
    else:
        await message.answer("Пришлите фото или напишите «пропустить»")
        return

    data = await state.get_data()
    soft = data.get("soft_skills") or "—"
    text = (
        f"<b>Проверьте заявку:</b>\n\n"
        f"<b>{data['name']}</b>, {data['age']}\n"
        f"@{data['username']}\n\n"
        f"<b>Интересы:</b> {data['interests']}\n"
        f"<b>Софт-скиллы:</b> {soft}\n\n"
        f"{data['about']}\n\n"
        f"Отправить на модерацию?"
    )
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Отправить", callback_data="apply_send"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="back_main"),
    )
    await state.set_state(ApplyStates.confirm)
    if data.get("photo_file_id"):
        await message.answer_photo(data["photo_file_id"], caption=text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "apply_send", ApplyStates.confirm)
async def apply_send(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    data["user_id"] = callback.from_user.id
    data["tg_username"] = data.get("username") or callback.from_user.username
    app_id = await save_application(data)
    await state.clear()

    # notify admin
    if ADMIN_IDS:
        soft = data.get("soft_skills") or "—"
        text = (
            f"🆕 <b>Новая заявка #{app_id}</b>\n\n"
            f"<b>{data['name']}</b>, {data['age']}\n"
            f"@{data.get('username')} | id <code>{callback.from_user.id}</code>\n\n"
            f"<b>Интересы:</b> {data['interests']}\n"
            f"<b>Софт-скиллы:</b> {soft}\n\n"
            f"{data['about']}"
        )
        kb = InlineKeyboardBuilder()
        kb.row(
            InlineKeyboardButton(text="✅ Принять", callback_data=f"adm_ok_{app_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_no_{app_id}"),
        )
        await notify_admins(
            bot, text,
            photo_file_id=data.get("photo_file_id"),
            reply_markup=kb.as_markup(),
        )

    await callback.message.answer(
        "Заявка отправлена на модерацию ✅\nМы напишем, когда её рассмотрят.",
        reply_markup=main_menu_kb(is_admin(callback.from_user.id)),
    )
    await callback.answer()


# ---------- ADMIN ----------
@router.callback_query(F.data == "admin")
async def admin_panel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    pending = await get_pending_applications()
    text = f"<b>Админ-панель</b>\n\nЗаявок на модерации: <b>{len(pending)}</b>"
    await callback.message.answer(text, reply_markup=admin_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_apps")
async def admin_apps(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    apps = await get_pending_applications()
    if not apps:
        await callback.answer("Нет заявок", show_alert=True)
        return
    for app in apps:
        # id, user_id, tg_username, name, age, interests, about, soft_skills, photo_file_id, created_at
        soft = app[7] or "—"
        text = (
            f"<b>Заявка #{app[0]}</b>\n"
            f"<b>{app[3]}</b>, {app[4]}\n"
            f"@{app[2] or '—'} | id <code>{app[1]}</code>\n\n"
            f"<b>Интересы:</b> {app[5]}\n"
            f"<b>Софт-скиллы:</b> {soft}\n\n"
            f"{app[6]}"
        )
        kb = InlineKeyboardBuilder()
        kb.row(
            InlineKeyboardButton(text="✅ Принять", callback_data=f"adm_ok_{app[0]}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_no_{app[0]}"),
        )
        if app[8]:
            await callback.message.answer_photo(app[8], caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")
        else:
            await callback.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("adm_ok_"))
async def admin_approve(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    app_id = int(callback.data.split("_")[2])
    app = await get_application(app_id)
    if not app or app[9] != "pending":
        await callback.answer("Уже обработана", show_alert=True)
        return
    new_id = await approve_application(app_id)
    await callback.message.answer(f"✅ Заявка #{app_id} принята. Компаньон id={new_id}")
    try:
        await bot.send_message(
            app[1],
            f"🎉 Вашу заявку на компаньона одобрили!\nТеперь вы в списке. Спасибо, что с нами.",
        )
    except Exception:
        pass
    await callback.answer("Принято")


@router.callback_query(F.data.startswith("adm_no_"))
async def admin_reject(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    app_id = int(callback.data.split("_")[2])
    app = await get_application(app_id)
    if not app or app[9] != "pending":
        await callback.answer("Уже обработана", show_alert=True)
        return
    await set_application_status(app_id, "rejected")
    await callback.message.answer(f"❌ Заявка #{app_id} отклонена")
    try:
        await bot.send_message(app[1], "К сожалению, заявку на компаньона отклонили. Можно подать снова позже.")
    except Exception:
        pass
    await callback.answer("Отклонено")


@router.callback_query(F.data == "admin_comps")
async def admin_comps(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    comps = await get_companions(active_only=False)
    if not comps:
        await callback.answer("Пусто", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for c in comps:
        status = "" if c.get("is_active", 1) else " [выкл]"
        builder.row(
            InlineKeyboardButton(
                text=f"{c['name']}, {c['age']}{status}",
                callback_data=f"adm_comp_{c['id']}"
            )
        )
    builder.row(InlineKeyboardButton(text="« Назад", callback_data="admin"))
    await callback.message.answer(
        "<b>Компаньоны</b>\nВыберите анкету для управления:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_comp_"))
async def admin_comp_card(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    companion_id = int(callback.data.split("_")[2])
    c = await get_companion(companion_id)
    if not c:
        await callback.answer("Не найден", show_alert=True)
        return

    interests = ", ".join(c["interests"])
    soft = ", ".join(c.get("soft_skills") or [])
    text = (
        f"<b>Управление: {c['name']}</b> (id {c['id']})\n\n"
        f"Возраст: {c['age']}\n"
        f"Username: @{c['username']}\n"
        f"Интересы: {interests}\n"
        f"Софт-скиллы: {soft or '—'}\n\n"
        f"{c['about']}"
    )
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✏️ Имя", callback_data=f"ed_name_{companion_id}"),
           InlineKeyboardButton(text="✏️ Возраст", callback_data=f"ed_age_{companion_id}"))
    kb.row(InlineKeyboardButton(text="✏️ Интересы", callback_data=f"ed_interests_{companion_id}"),
           InlineKeyboardButton(text="✏️ Софт-скиллы", callback_data=f"ed_soft_skills_{companion_id}"))
    kb.row(InlineKeyboardButton(text="✏️ О себе", callback_data=f"ed_about_{companion_id}"),
           InlineKeyboardButton(text="✏️ Username", callback_data=f"ed_username_{companion_id}"))
    kb.row(InlineKeyboardButton(text="🖼 Фото", callback_data=f"ed_photo_{companion_id}"))
    kb.row(InlineKeyboardButton(text="📝 Отзывы / удалить", callback_data=f"reviews_{companion_id}"))
    kb.row(InlineKeyboardButton(text="🗑 Удалить анкету", callback_data=f"adel_{companion_id}"))
    kb.row(InlineKeyboardButton(text="« К списку", callback_data="admin_comps"))

    try:
        if c.get("photo_file_id"):
            await callback.message.answer_photo(c["photo_file_id"], caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")
        elif c.get("photo_url"):
            await callback.message.answer_photo(c["photo_url"], caption=text, reply_markup=kb.as_markup(), parse_mode="HTML")
        else:
            await callback.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("ed_"))
async def admin_edit_field(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    # ed_name_3 / ed_soft_skills_3 / ed_photo_3
    parts = callback.data.split("_")
    # ed, field..., id
    companion_id = int(parts[-1])
    field = "_".join(parts[1:-1])  # name | age | interests | about | soft_skills | username | photo

    field_titles = {
        "name": "имя",
        "age": "возраст (число)",
        "interests": "интересы через запятую",
        "about": "текст «о себе»",
        "soft_skills": "софт-скиллы через запятую",
        "username": "username без @",
        "photo": "фото (пришлите картинку или «удалить»)",
    }
    title = field_titles.get(field, field)

    await state.set_state(EditStates.waiting_value)
    await state.update_data(edit_id=companion_id, edit_field=field)
    await callback.message.answer(
        f"Введите новое значение для <b>{title}</b>:\n/cancel — отмена",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(EditStates.waiting_value)
async def admin_save_field(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    companion_id = data["edit_id"]
    field = data["edit_field"]

    if field == "photo":
        if message.photo:
            await update_companion_field(companion_id, "photo_file_id", message.photo[-1].file_id)
            await update_companion_field(companion_id, "photo_url", None)
            msg = "Фото обновлено ✅"
        elif message.text and message.text.lower() in ("удалить", "убрать", "-", "delete"):
            await update_companion_field(companion_id, "photo_file_id", None)
            await update_companion_field(companion_id, "photo_url", None)
            msg = "Фото удалено ✅"
        else:
            await message.answer("Пришлите фото или напишите «удалить»")
            return
    elif field == "age":
        try:
            age = int(message.text.strip())
        except ValueError:
            await message.answer("Введите число")
            return
        await update_companion_field(companion_id, "age", age)
        msg = f"Возраст: {age} ✅"
    elif field in ("interests", "soft_skills"):
        items = [x.strip() for x in message.text.split(",") if x.strip()]
        await update_companion_field(companion_id, field, json.dumps(items, ensure_ascii=False))
        msg = f"Обновлено: {', '.join(items)} ✅"
    elif field == "username":
        uname = message.text.strip().lstrip("@")
        await update_companion_field(companion_id, "username", uname)
        msg = f"Username: @{uname} ✅"
    else:
        await update_companion_field(companion_id, field, message.text.strip())
        msg = "Сохранено ✅"

    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="« К анкете", callback_data=f"adm_comp_{companion_id}"))
    kb.row(InlineKeyboardButton(text="« К списку", callback_data="admin_comps"))
    await message.answer(msg, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("adel_"))
async def admin_delete_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    companion_id = int(callback.data.split("_")[1])
    c = await get_companion(companion_id)
    if not c:
        await callback.answer("Не найден", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="Да, удалить", callback_data=f"adelok_{companion_id}"),
        InlineKeyboardButton(text="Отмена", callback_data=f"adm_comp_{companion_id}"),
    )
    await callback.message.answer(
        f"Точно удалить анкету <b>{c['name']}</b>?\nЭто необратимо (отзывы тоже удалятся).",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adelok_"))
async def admin_delete_ok(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    companion_id = int(callback.data.split("_")[1])
    c = await get_companion(companion_id)
    name = c["name"] if c else str(companion_id)
    await delete_companion(companion_id)
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="« К списку", callback_data="admin_comps"))
    await callback.message.answer(f"Анкета <b>{name}</b> удалена.", reply_markup=kb.as_markup(), parse_mode="HTML")
    await callback.answer("Удалено")



# ================== PUBLIC API (для Mini App) ==================
# Храним bot instance для proxy фото
_bot_ref: Bot | None = None


async def api_companions(request: web.Request):
    """Список компаньонов для приложения."""
    comps = await get_companions(active_only=True)
    out = []
    for c in comps:
        item = {
            "id": c["id"],
            "name": c["name"],
            "age": c["age"],
            "interests": c["interests"],
            "soft_skills": c.get("soft_skills") or [],
            "about": c["about"],
            "username": c["username"],
            "photo_url": None,
        }
        # Публичный URL фото: либо внешняя ссылка, либо proxy через наш API
        if c.get("photo_url"):
            item["photo_url"] = c["photo_url"]
        elif c.get("photo_file_id"):
            # Относительный proxy — фронт подставит origin API
            item["photo_url"] = f"/api/photo/{c['id']}"
        out.append(item)
    return web.json_response(out, headers={
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-store",
    })


async def api_photo(request: web.Request):
    """Отдаёт фото компаньона (proxy из Telegram, токен не светится на фронте)."""
    companion_id = int(request.match_info["id"])
    c = await get_companion(companion_id)
    if not c:
        return web.Response(status=404, text="not found")

    # Внешний URL
    if c.get("photo_url"):
        raise web.HTTPFound(c["photo_url"])

    file_id = c.get("photo_file_id")
    if not file_id or not _bot_ref:
        return web.Response(status=404, text="no photo")

    try:
        file = await _bot_ref.get_file(file_id)
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
        from aiohttp import ClientSession
        async with ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return web.Response(status=502, text="telegram error")
                data = await resp.read()
                content_type = resp.headers.get("Content-Type", "image/jpeg")
        return web.Response(
            body=data,
            content_type=content_type,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=3600",
            },
        )
    except Exception as e:
        logger.error(f"photo proxy error: {e}")
        return web.Response(status=500, text="error")


async def api_options(request: web.Request):
    return web.Response(headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    })


def create_api_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/api/companions", api_companions)
    app.router.add_get("/api/photo/{id}", api_photo)
    app.router.add_route("OPTIONS", "/api/companions", api_options)
    app.router.add_route("OPTIONS", "/api/photo/{id}", api_options)
    return app


# ================== MAIN ==================
async def main():
    global _bot_ref
    if not BOT_TOKEN:
        raise ValueError("Укажите BOT_TOKEN в .env файле")
    await init_db()
    bot = Bot(token=BOT_TOKEN)
    _bot_ref = bot
    dp = Dispatcher()
    dp.include_router(router)

    # HTTP API для Mini App (актуальные анкеты + фото)
    api_app = create_api_app()
    runner = web.AppRunner(api_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", API_PORT)
    await site.start()
    logger.info(f"API для приложения: http://0.0.0.0:{API_PORT}/api/companions")

    logger.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
