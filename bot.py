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

import aiohttp

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

# Интеграция с API-сервисом. Если API_URL задан — пост берётся из API,
# иначе бот генерирует пост локально (как раньше). API_KEY должен совпадать
# с ключом API-сервиса.
API_URL = os.environ.get("API_URL", "").rstrip("/")
API_KEY = os.environ.get("API_KEY", "")

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


def build_lead_magnet_messages(recipes: list, max_len: int = 3500) -> list:
    """Лид-магнит «50 рецептов» ТЕКСТОМ, разбитый на сообщения < max_len символов.

    Раньше бот слал .md-файлом — встроенный просмотрщик Telegram коверкал кодировку.
    Текстовые сообщения Telegram всегда показывает в правильной кодировке на любом телефоне.
    """
    head = ("🎁 <b>50 рецептов для аэрогриля</b>\n"
            "Готовим в силиконовой форме — чашу аэрогриля мыть не надо.\n")
    tail = ("\n———\n👨‍🍳 Полные пошаговые рецепты с фото — в канале каждый день. "
            "Подпишись, чтобы не пропустить 👇")

    # группируем по категориям (в recipes.json они идут вперемешку)
    by_cat: dict = {}
    for r in recipes:
        by_cat.setdefault(r.get("category", "Разное"), []).append(r)
    ordered = ([c for c in CATEGORY_EMOJI if c in by_cat]
               + [c for c in by_cat if c not in CATEGORY_EMOJI])

    lines, n = [], 0
    for cat in ordered:
        lines.append(f"\n{CATEGORY_EMOJI.get(cat, '🍽')} <b>{cat}</b>")
        for r in by_cat[cat]:
            n += 1
            tt = r.get("total_time", "")
            lines.append(f"{n}. {r.get('title', '')}" + (f" — {tt}" if tt else ""))

    body = head + "\n".join(lines) + tail
    if len(body) <= max_len:
        return [body]

    # запас на рост базы: режем по строкам
    chunks, cur = [], head
    for ln in lines:
        if len(cur) + len(ln) + 1 > max_len:
            chunks.append(cur)
            cur = ""
        cur += ln + "\n"
    chunks.append(cur + tail)
    return chunks


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
        "Держи <b>50 рецептов для аэрогриля</b> — список ниже. 🎁\n"
        "Все блюда готовятся в силиконовой форме, чтобы <b>не мыть чашу аэрогриля</b>.\n\n"
        "Полные пошаговые рецепты с фото выходят в канале каждый день — подпишись, чтобы не пропустить 👇",
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )
    # Рецепты отдаём ТЕКСТОМ, а не .md-файлом: встроенный просмотрщик Telegram
    # коверкает кодировку документа, а текст всегда читается корректно.
    try:
        for chunk in build_lead_magnet_messages(load_recipes()):
            await update.message.reply_text(
                chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True
            )
    except Exception as e:
        log.warning("Не удалось отправить список рецептов: %s", e)


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


async def fetch_post_from_api():
    """Готовый пост из API (POST /prepare-telegram-post). None -> локальная генерация.

    Не блокирует event loop (aiohttp). recipe_id не шлём — рецепт выбирает сервер API.
    Ответ маппим: text<-caption, photo<-image_url (API отдаёт оба варианта полей).
    """
    if not API_URL or not API_KEY:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{API_URL}/prepare-telegram-post",
                headers={"x-api-key": API_KEY},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
    except Exception as e:  # noqa: BLE001
        log.warning("API error: %s", e)
        return None


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

    # --- Пост из API; если недоступен/не задан — локальная генерация (fallback) ---
    data = await fetch_post_from_api()
    if data:
        text = data.get("text") or data.get("caption") or ""
        image = data.get("photo") or data.get("image_url")     # строка-URL
        title = (data.get("metadata") or {}).get("title", "Рецепт")
        log.info("Post from API")
    else:
        recipe = recipes[idx]
        text = format_recipe(recipe, state["posts_count"], with_cta)
        image = photo_source(recipe)                            # строка-URL или открытый файл
        title = recipe.get("title", "Рецепт")
        log.info("Fallback to local recipes")
    try:
        if image and len(text) <= CAPTION_LIMIT:
            # фото + полная подпись
            await context.bot.send_photo(
                chat_id=CHANNEL_ID, photo=image, caption=text, parse_mode=ParseMode.HTML
            )
        elif image:
            # подпись длиннее лимита: фото с заголовком + текст отдельным сообщением
            head = f"🍽 <b>{title}</b>"
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
