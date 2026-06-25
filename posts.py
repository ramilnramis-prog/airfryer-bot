"""Чтение recipes.json и сборка готового поста для Telegram."""
import json
import random
from .config import RECIPES_FILE, OZON_ARTIKUL

CATEGORY_EMOJI = {
    "Курица": "🍗", "Мясо": "🥩", "Рыба": "🐟", "Овощи": "🥦",
    "Выпечка": "🍞", "Завтраки": "🍳", "Снеки": "🧀", "Десерты": "🍎",
}


def load_recipes():
    with open(RECIPES_FILE, encoding="utf-8") as f:
        return json.load(f)


def _block(value, numbered: bool) -> str:
    if isinstance(value, list):
        if numbered:
            return "\n".join(f"{i}. {x}" for i, x in enumerate(value, 1))
        return "\n".join(f"• {x}" for x in value)
    return str(value) if value else ""


def format_caption(r: dict) -> str:
    emoji = CATEGORY_EMOJI.get(r.get("category", ""), "🍽")
    parts = [f"{emoji} <b>{r['title']}</b>"]
    tt = r.get("total_time")
    parts.append(f"⏱ {tt} · 🍽 в силиконовой форме" if tt
                 else "🍽 Готовим в силиконовой форме — без мытья чаши")
    ing = _block(r.get("ingredients"), numbered=False)
    if ing:
        parts.append(f"\n🧂 <b>Ингредиенты:</b>\n{ing}")
    steps = _block(r.get("steps"), numbered=True)
    if steps:
        parts.append(f"\n👨‍🍳 <b>Приготовление:</b>\n{steps}")
    cat = (r.get("category") or "").lower()
    parts.append(f"\n#аэрогриль #рецепты #{cat}" if cat else "\n#аэрогриль #рецепты")
    text = "\n".join(parts)
    text += ("\n———\n🔥 Готовлю в силиконовой форме — чаша аэрогриля остаётся чистой.\n"
             f"Форма на Ozon, артикул <b>{OZON_ARTIKUL}</b>")
    return text


def prepare_post(recipe_id, base_url: str):
    """recipe_id: 1..N (1-based) ИЛИ None — тогда сервер берёт случайный рецепт.
    Возвращает None, если рецептов нет или id вне диапазона."""
    recipes = load_recipes()
    if not recipes:
        return None
    if recipe_id is None:
        recipe_id = random.randint(1, len(recipes))
    recipe_id = int(recipe_id)
    if recipe_id < 1 or recipe_id > len(recipes):
        return None
    r = recipes[recipe_id - 1]
    img = r.get("image", "")           # напр. "photos/01.jpg"
    name = img.split("/")[-1] if img else ""
    image_url = f"{base_url}/files/photos/{name}" if name else None
    caption = format_caption(r)
    return {
        "status": "ready",
        "caption": caption,
        "text": caption,             # alias для Telegram-бота
        "image_url": image_url,
        "photo": image_url,          # alias для Telegram-бота
        "parse_mode": "HTML",
        "metadata": {
            "recipe_id": recipe_id,
            "title": r.get("title"),
            "category": r.get("category"),
            "total_time": r.get("total_time"),
        },
    }
