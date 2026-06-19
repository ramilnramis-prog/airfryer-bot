"""
Ozon Airfryer — Telegram-бот воронки.

Что делает автоматически:
  • /start в личке  -> приветствие + выдача лид-магнита "50 рецептов" + кнопки (канал, Ozon)
  • по расписанию   -> публикует следующий рецепт из очереди в канал
  • каждый N-й пост -> добавляет мягкий CTA на Ozon

Конфигурация — через переменные окружения (см. .env.example).
Запуск: python bot.py   (long-polling, вебхук не нужен)
"""
import os
import json
import logging
import datetime as dt
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

# ---------- конфигурация ----------
BOT_TOKEN = os.environ["BOT_TOKEN"]                       # обязательный
CHANNEL_ID = os.environ["CHANNEL_ID"]                     # @username или -100xxxxxxxxxx
OZON_ARTIKUL = os.environ.get("OZON_ARTIKUL", "1931921872")
OZON_LINK = os.environ.get("OZON_LINK", "")
TG_CHANNEL_LINK = os.environ.get("TG_CHANNEL_LINK", "")   # https://t.me/your_channel
POST_TIMES = os.environ.get("POST_TIMES", "10:00")        # "10:00" или "10:00,18:00"
TZ = os.environ.get("TZ", "Europe/Moscow")
CTA_EVERY = int(os.environ.get("CTA_EVERY", "4"))         # CTA на Ozon каждый N-й пост

BASE = os.path.dirname(os.path.abspath(__file__))
RECIPES_FILE = os.path.join(BASE, "recipes.json")
LEAD_MAGNET = os.path.join(BASE, "lead_magnet.md")
STATE_FILE = os.path.join(BASE, "state.json")

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s | %(message)s", level=logging.INFO
)
log = logging.getLogger("airfryer-bot")
# httpx логирует полный URL запроса (с токеном бота) — приглушаем, чтобы токен не попадал в логи
logging.getLogger("httpx").setLevel(logging.WARNING)


# ---------- состояние (позиция в очереди) ----------
def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"index": 0, "posts_count": 0}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def load_recipes() -> list:
    with open(RECIPES_FILE, encoding="utf-8") as f:
        return json.load(f)


# ---------- форматирование поста ----------
CATEGORY_EMOJI = {
    "Курица": "🍗", "Мясо": "🥩", "Рыба": "🐟", "Овощи": "🥦",
    "Выпечка": "🍞", "Завтраки": "🍳", "Снеки": "🧀", "Десерты": "🍎",
}


def ozon_line() -> str:
    link = f"\n👉 {OZON_LINK}" if OZON_LINK else ""
    return (
        "\n———\n🔥 Готовлю в силиконовой форме — чаша аэрогриля остаётся чистой.\n"
        f"Форма на Ozon, артикул <b>{OZON_ARTIKUL}</b>{link}"
    )


def _as_block(value, numbered: bool) -> str:
    """ingredients/steps могут быть списком или строкой — приводим к красивому блоку."""
    if isinstance(value, list):
        if numbered:
            return "\n".join(f"{i}. {x}" for i, x in enumerate(value, 1))
        return "\n".join(f"• {x}" for x in value)
    return str(value) if value else ""


def format_recipe(r: dict, number: int, with_cta: bool) -> str:
    emoji = CATEGORY_EMOJI.get(r.get("category", ""), "🍽")
    parts = [f"{emoji} <b>{r['title']}</b>"]

    tt = r.get("total_time")
    parts.append(f"⏱ {tt} · 🍽 в силиконовой форме" if tt
                 else "🍽 Готовим в силиконовой форме — без мытья чаши")

    ing = _as_block(r.get("ingredients"), numbered=False)
    if ing:
        parts.append(f"\n🧂 <b>Ингредиенты:</b>\n{ing}")

    steps = _as_block(r.get("steps"), numbered=True)
    if steps:
        parts.append(f"\n👨‍🍳 <b>Приготовление:</b>\n{steps}")
    elif r.get("mode"):
        parts.append(f"\n🌡 <b>Режим:</b> {r['mode']}")

    cat = r.get("category", "").lower()
    parts.append(f"\n#аэрогриль #рецепты #{cat}" if cat else "\n#аэрогриль #рецепты")

    text = "\n".join(parts)
    if with_cta:
        text += "\n" + ozon_line()
    return text


# ---------- /start: выдача лид-магнита ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    buttons = []
    if TG_CHANNEL_LINK:
        buttons.append([InlineKeyboardButton("📲 Подписаться на канал", url=TG_CHANNEL_LINK)])
    if OZON_LINK:
        buttons.append([InlineKeyboardButton("🛒 Форма на Ozon", url=OZON_LINK)])
    markup = InlineKeyboardMarkup(buttons) if buttons else None

    await update.message.reply_text(
        "Привет! 👋\n\n"
        "Держи <b>50 рецептов для аэрогриля</b> — файл ниже. 🎁\n"
        "Все блюда готовятся в силиконовой форме, чтобы <b>не мыть чашу аэрогриля</b>.\n\n"
        "Новые рецепты выходят в канале каждый день — подпишись, чтобы не пропустить 👇",
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )
    try:
        with open(LEAD_MAGNET, "rb") as doc:
            await update.message.reply_document(doc, filename="50-receptov-aerogril.md")
    except FileNotFoundError:
        log.warning("Лид-магнит %s не найден", LEAD_MAGNET)


# ---------- задача: публикация рецепта в канал ----------
def photo_source(recipe: dict):
    """URL (http) -> строкой; локальный путь вида photos/01.png -> открытым файлом; иначе None."""
    img = recipe.get("image")
    if not img:
        return None
    if img.startswith("http"):
        return img
    path = os.path.join(BASE, img)
    return open(path, "rb") if os.path.exists(path) else None


CAPTION_LIMIT = 1024  # лимит подписи к фото в Telegram


async def post_recipe(context: ContextTypes.DEFAULT_TYPE) -> None:
    recipes = load_recipes()
    if not recipes:
        log.warning("recipes.json пуст")
        return
    state = load_state()
    idx = state["index"] % len(recipes)
    state["posts_count"] += 1
    with_cta = state["posts_count"] % CTA_EVERY == 0

    recipe = recipes[idx]
    text = format_recipe(recipe, state["posts_count"], with_cta)
    image = photo_source(recipe)
    try:
        if image and len(text) <= CAPTION_LIMIT:
            # фото + полная подпись
            await context.bot.send_photo(
                chat_id=CHANNEL_ID, photo=image, caption=text, parse_mode=ParseMode.HTML
            )
        elif image:
            # подпись длиннее лимита: фото с заголовком + текст отдельным сообщением
            head = f"{CATEGORY_EMOJI.get(recipe.get('category',''),'🍽')} <b>{recipe['title']}</b>"
            await context.bot.send_photo(
                chat_id=CHANNEL_ID, photo=image, caption=head, parse_mode=ParseMode.HTML
            )
            await context.bot.send_message(
                chat_id=CHANNEL_ID, text=text, parse_mode=ParseMode.HTML
            )
        else:
            # без картинки — обычный текстовый пост
            await context.bot.send_message(
                chat_id=CHANNEL_ID, text=text, parse_mode=ParseMode.HTML
            )
        state["index"] = idx + 1
        save_state(state)
        log.info("Опубликован рецепт #%s (cta=%s, photo=%s)",
                 state["posts_count"], with_cta, bool(image))
    except Exception as e:  # noqa: BLE001
        log.error("Не удалось опубликовать: %s", e)


def parse_times(raw: str) -> list[dt.time]:
    tz = ZoneInfo(TZ)
    out = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        h, m = chunk.split(":")
        out.append(dt.time(int(h), int(m), tzinfo=tz))
    return out


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    times = parse_times(POST_TIMES)
    for t in times:
        app.job_queue.run_daily(post_recipe, time=t, name=f"post-{t}")
    log.info("Расписание постинга: %s (TZ=%s), CTA каждый %s-й пост",
             [str(t) for t in times], TZ, CTA_EVERY)

    log.info("Бот запущен (long-polling).")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
