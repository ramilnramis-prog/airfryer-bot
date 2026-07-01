"""Идемпотентный seed реестра. Повторный запуск НЕ создаёт дубли (всё через стабильные коды).

Заполняет:
  - 1 товар: «Силиконовая форма для аэрогриля» (product_code=airfryer-silicone-form, Ozon 1931921872);
  - 5 каналов: telegram, youtube_shorts, instagram_reels, tiktok, dzen;
  - 1 content: рекламный ролик №2 (content_code=video2-forma-ad);
  - 3 hook-варианта (A/B/C).

Коды стабильны и не зависят от изменяемых name/title. Тексты хуков взяты VERBATIM из реального
файла content/video2-voiceover.md (не выдуманы). content_code основан на реально существующих
именах проекта: content/video2-voiceover.md и content/assets/video2-formaad/.

ВНИМАНИЕ: пишет в БД (config.DB_PATH). На production запускать ТОЛЬКО осознанно.
Запуск:  python -m api.seed_registry --yes
"""
import sys
from . import registry_db as R

PRODUCT_CODE = "airfryer-silicone-form"
CONTENT_CODE = "video2-forma-ad"  # подтверждено файлами: content/video2-voiceover.md, content/assets/video2-formaad/

# источник: content/video2-voiceover.md (хуки 0–3 сек), verbatim
HOOKS = [
    ("A", "Аэрогрильщики, вы вообще знали про такую штуку?"),
    ("B", "Если у тебя есть аэрогриль — это обязано быть у тебя."),
    ("C", "Случайно нашёл вещь, которая изменила мой аэрогриль."),
]
CHANNELS = [
    ("telegram", "Telegram"),
    ("youtube_shorts", "YouTube Shorts"),
    ("instagram_reels", "Instagram Reels"),
    ("tiktok", "TikTok"),
    ("dzen", "Дзен"),
]


def seed() -> dict:
    R.run_migrations()
    report = {"created": {}, "existing": {}}

    product, c = R.create_or_get_product(
        product_code=PRODUCT_CODE,
        name="Силиконовая форма для аэрогриля",
        marketplace="ozon",
        external_id="1931921872",
    )
    (report["created"] if c else report["existing"])["product"] = product["id"]

    channels = {}
    for code, name in CHANNELS:
        ch, c = R.create_or_get_channel(code=code, name=name)
        channels[code] = ch["id"]
        (report["created"] if c else report["existing"]).setdefault("channels", []).append(code)

    content, c = R.create_or_get_content(
        product_id=product["id"],
        content_code=CONTENT_CODE,
        content_type="video",
        title="Ролик 2 — Форма для аэрогриля (must-have)",
        core_idea="Силиконовая форма превращает аэрогриль в универсал: готовит всё, "
                  "достаётся целым, чаша остаётся чистой.",
        audience_segment="Владельцы аэрогрилей",
        pain_or_desire="Must-have аксессуар: открытие + не мыть чашу + готовить всё.",
        hypothesis="Прямое обращение к аэрогрильщикам + рамка must-have повышает удержание.",
        source_path="content/video2-voiceover.md",
    )
    (report["created"] if c else report["existing"])["content"] = content["id"]

    for code, text in HOOKS:
        h, c = R.add_hook(content_id=content["id"], hook_code=code, hook_text=text)
        (report["created"] if c else report["existing"]).setdefault("hooks", []).append(code)

    report["product_id"] = product["id"]
    report["content_id"] = content["id"]
    report["channel_ids"] = channels
    return report


if __name__ == "__main__":
    if "--yes" not in sys.argv:
        print("Seed пишет в БД (config.DB_PATH). На production запускать только осознанно.")
        print("Повтори с флагом подтверждения:  python -m api.seed_registry --yes")
        sys.exit(1)
    import json
    print(json.dumps(seed(), ensure_ascii=False, indent=2))
