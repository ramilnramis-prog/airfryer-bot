"""Dzen article publishing kits: finds ALREADY-WRITTEN Dzen articles across
the campaign, polishes them for copy-paste publishing (placeholders,
softened claims, tags, pinned comment), and generates illustrative image
prompts + (budget-capped) actual images. Never writes brand-new articles
from scratch when a usable one already exists. No auto-posting anywhere --
the owner copies text into Dzen manually.

Real product info baked in everywhere a placeholder is resolved:
- OZON_ARTIKUL = 1931921872
- OZON_LINK    = https://ozon.ru/product/forma-dlya-aerogrilya-silikonovaya-antiprigarnaya-aksessuar-dlya-aerogrilya-forma-dlya-vypechki-1931921872/?hs=1&utm_campaign=vendor_org_1751712_airfryer&utm_medium=social&utm_source=youtube
"""
from __future__ import annotations

import json
import re
from pathlib import Path

OZON_ARTIKUL = "1931921872"
OZON_LINK = ("https://ozon.ru/product/forma-dlya-aerogrilya-silikonovaya-antiprigarnaya-"
            "aksessuar-dlya-aerogrilya-forma-dlya-vypechki-1931921872/"
            "?hs=1&utm_campaign=vendor_org_1751712_airfryer&utm_medium=social&utm_source=youtube")

FORBIDDEN_CLAIM_MARKERS = (
    "100%", "никогда не пачкается", "не пачкается вообще", "вообще не пачкается",
    "вообще не пачкалась", "гарантированно", "идеально для всех", "как новая после готовки",
    "вылечит", "лечит", "безопасно для здоровья", "медицин",
)

# Manual softening rules applied when building article-ready-to-copy.md --
# each (find, replace) pair is checked case-sensitively against the exact
# source article's known problem phrasing (not a blind global regex, so we
# never accidentally rewrite unrelated text).
CLAIM_SOFTENING_RULES = (
    ("чтобы чаша вообще не пачкалась", "чтобы чаша вообще не соприкасалась с едой и жиром"),
)

CANON_SOURCE_PATH = "content/autopilot/coating-protect-2026-07/dzen-article.md"

GENERATED_DZEN_DIR = "content/autopilot/coating-protect-2026-07/generated/content-factory/dzen-posts"

# article_id -> {source_path (relative to repo_root), type, is_canon}
# type follows the enum requested: problem_solution | recipe | lifehack |
# soft_ad | comparison | product_education
_TYPE_MAP = {
    "short_recipe": "recipe",
    "recipe_roundup": "recipe",
    "what_to_cook_in_airfryer": "recipe",
    "airfryer_lifehack": "lifehack",
    "problem_solution": "problem_solution",
    "soft_product_ad": "soft_ad",
    "with_form_vs_without": "comparison",
    "lifestyle_conversational": "soft_ad",
}

_KNOWN_DUPLICATE_GROUPS = (
    # (canonical article_id kept as "ready", rest marked "duplicate")
    ("dzen-001", "batch-003-dzen-001"),
    ("dzen-002", "batch-003-dzen-005"),
    ("dzen-003", "batch-002-dzen-006"),
    ("dzen-004", "batch-002-dzen-001"),
    ("dzen-005", "batch-003-dzen-006"),
    ("dzen-008", "batch-003-dzen-010"),
    ("dzen-009", "batch-003-dzen-008"),
    ("dzen-010", "batch-002-dzen-002"),
)


def _duplicate_lookup() -> dict:
    dup = {}
    for canonical, *dupes in _KNOWN_DUPLICATE_GROUPS:
        for d in dupes:
            dup[d] = canonical
    return dup


def _parse_generated_filename(path: Path) -> tuple:
    """batch-002-dzen-004-airfryer_lifehack.md -> ('batch-002-dzen-004', 'airfryer_lifehack')
    dzen-001-short_recipe.md -> ('dzen-001', 'short_recipe')
    (batch-001 filenames have no 'batch-XXX-' prefix, so the literal 'dzen-N'
    marker is not preceded by a dash -- match on 'dzen-\\d+' without
    requiring a leading dash, not just '-dzen-\\d+'.)"""
    stem = path.stem
    m = re.match(r"^(.*dzen-\d+)-([a-z_]+)$", stem)
    if not m:
        return stem, "unknown"
    return m.group(1), m.group(2)


def _char_count(text: str) -> int:
    return len(text)


def _has_forbidden_claim(text: str) -> list:
    lowered = text.lower()
    return [m for m in FORBIDDEN_CLAIM_MARKERS if m.lower() in lowered]


def _has_image_placeholders(text: str) -> bool:
    return bool(re.search(r"\[ИЗОБРАЖЕНИЕ", text))


def _has_question_or_comment_hook(text: str) -> bool:
    return "?" in text.split("\n\n")[1] if len(text.split("\n\n")) > 1 else "?" in text[:400]


def _has_product_link(text: str) -> bool:
    return "{{OZON_LINK}}" in text or "ozon.ru" in text.lower()


def _has_article_body(text: str) -> bool:
    return len(text.strip()) > 500


def scan_all_articles(repo_root: str = ".") -> list:
    """Every candidate Dzen article: the hand-written canon + all 40
    auto-generated dzen-posts. Read-only -- never writes anything."""
    root = Path(repo_root)
    dup_lookup = _duplicate_lookup()
    entries = []

    canon_path = root / CANON_SOURCE_PATH
    if canon_path.is_file():
        text = canon_path.read_text(encoding="utf-8")
        title_match = re.search(r"\*\*(.+?)\*\*", text)
        title = title_match.group(1) if title_match else "Untitled canon article"
        forbidden = _has_forbidden_claim(text)
        entries.append({
            "article_id": "canon-chasha-lyseet",
            "title": title,
            "source_path": str(canon_path).replace("\\", "/"),
            "type": "problem_solution",
            "status": "needs_light_edit" if forbidden else "ready_to_publish",
            "char_count": _char_count(text),
            "has_product_link": True,  # {{OZON_LINK}} placeholder present
            "has_article": True,
            "has_question_or_comment_hook": True,  # has a dedicated pinned-comment section
            "has_image_placeholders": _has_image_placeholders(text),
            "has_existing_image_prompts": False,
            "recommended_publish_priority": "high",
            "notes": ("Style canon article, explicitly named as first priority by the owner. "
                     f"Forbidden claim phrase(s) found: {forbidden}" if forbidden
                     else "Hand-written style-canon article, strong hook, already has image "
                          "placeholders and a pinned-comment section."),
        })

    gen_dir = root / GENERATED_DZEN_DIR
    if gen_dir.is_dir():
        for batch_dir in sorted(gen_dir.iterdir()):
            if not batch_dir.is_dir():
                continue
            for f in sorted(batch_dir.glob("*.md")):
                article_id, post_type = _parse_generated_filename(f)
                text = f.read_text(encoding="utf-8")
                title = text.splitlines()[0].lstrip("# ").strip()
                forbidden = _has_forbidden_claim(text)
                is_duplicate = article_id in dup_lookup

                if is_duplicate:
                    status = "duplicate"
                elif forbidden:
                    status = "needs_light_edit"
                else:
                    status = "ready_to_publish"

                priority = "low" if is_duplicate else ("high" if post_type in
                    ("problem_solution", "lifestyle_conversational") else "medium")

                notes = []
                if is_duplicate:
                    notes.append(f"Duplicate of {dup_lookup[article_id]} (same title/body template).")
                if forbidden:
                    notes.append(f"Forbidden claim phrase(s) found: {forbidden}")
                if not notes:
                    notes.append("Auto-generated, already publish-ready, soft product integration.")

                entries.append({
                    "article_id": article_id,
                    "title": title,
                    "source_path": str(f).replace("\\", "/"),
                    "type": _TYPE_MAP.get(post_type, "product_education"),
                    "status": status,
                    "char_count": _char_count(text),
                    "has_product_link": _has_product_link(text),
                    "has_article": _has_article_body(text),
                    "has_question_or_comment_hook": _has_question_or_comment_hook(text),
                    "has_image_placeholders": _has_image_placeholders(text),
                    "has_existing_image_prompts": False,
                    "recommended_publish_priority": priority,
                    "notes": " ".join(notes),
                })
    return entries


def write_inventory(campaign_dir: str, repo_root: str = ".", out_dir=None) -> dict:
    entries = scan_all_articles(repo_root)
    doc = {
        "campaign_code": "coating-protect-2026-07",
        "total_articles_found": len(entries),
        "ready_to_publish_count": sum(1 for e in entries if e["status"] == "ready_to_publish"),
        "needs_light_edit_count": sum(1 for e in entries if e["status"] == "needs_light_edit"),
        "duplicate_count": sum(1 for e in entries if e["status"] == "duplicate"),
        "articles": entries,
    }
    out = Path(out_dir) if out_dir else (
        Path(repo_root) / campaign_dir / "generated/content-factory/dzen-publishing")
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "dzen-article-inventory.json"
    json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# Dzen Article Inventory -- coating-protect-2026-07", "",
            f"Total found: {doc['total_articles_found']} "
            f"(ready: {doc['ready_to_publish_count']}, "
            f"needs edit: {doc['needs_light_edit_count']}, "
            f"duplicates: {doc['duplicate_count']})", ""]
    for e in entries:
        lines.append(f"## {e['article_id']} -- {e['title']}")
        lines.append(f"- type: {e['type']} | status: {e['status']} | "
                    f"priority: {e['recommended_publish_priority']} | chars: {e['char_count']}")
        lines.append(f"- source: `{e['source_path']}`")
        lines.append(f"- notes: {e['notes']}")
        lines.append("")
    md_path = out / "dzen-article-inventory.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    doc["json_path"] = str(json_path)
    doc["md_path"] = str(md_path)
    return doc


# -- image prompt canon -------------------------------------------------------

IMAGE_STYLE_POSITIVE = (
    "photorealistic home kitchen, warm natural daylight, cozy realistic cooking, "
    "DSLR photo look, realistic food textures, natural imperfections, no text, "
    "no watermark, no logo, not CGI, not illustration, not 3D render"
)

PRODUCT_CANON_DESCRIPTION = (
    "dark charcoal-grey square matte silicone air fryer liner, flat corner handle "
    "tabs with short horizontal slots, ribbed grill bottom, realistic silicone texture"
)

IMAGE_NEGATIVE_BASE = (
    "loop handles, vertical oval holes, duplicate tray, second product, "
    "redesigned product, text, watermark, logo, CGI, 3D render, illustration"
)

PRODUCT_REFERENCE_IMAGES = (
    "real-product-v1:product_45deg_master",
    "real-product-v1:product_top_master",
    "real-product-v1:both_handles_master",
    "real-product-v1:bottom_loop_master",
)

# Per-type image plan: (purpose, insert_after, russian_description, prompt_en,
# must_show_product, use_product_reference). aspect_ratio is uniform (9:16,
# matches the vertical video/Dzen-cover convention already used everywhere
# else in this campaign).
IMAGE_PLAN_BY_TYPE = {
    "problem_solution": (
        ("dirty_basket_after_cooking",
         "после первого абзаца (жирные следы, покрытие)",
         "Жирная/грязная чаша аэрогриля после готовки — не отвратительно, просто узнаваемо бытово.",
         "close-up of a black air fryer basket after cooking, visible grease residue and "
         "light grime on the ribs, no mold, no rot, believable everyday mess, warm kitchen "
         "counter background",
         False, False),
        ("sponge_cleaning",
         "после раздела «Что на самом деле портит покрытие»",
         "Мягкая губка и уход за чашей — процесс мытья, без формы в кадре.",
         "hand-less shot of a soft yellow-green sponge with soap suds resting on the edge "
         "of a black air fryer basket being cleaned, warm daylight, no hands, no person",
         False, False),
        ("form_next_to_airfryer",
         "после раздела «Барьер вместо уборки»",
         "Силиконовая форма рядом с открытым аэрогрилем, готова к использованию.",
         f"{PRODUCT_CANON_DESCRIPTION}, sitting on a kitchen counter next to an open black "
         "air fryer with its basket pulled out, clean and empty basket, no food",
         True, True),
        ("form_with_cooked_food",
         "перед разделом «Пара честных оговорок»",
         "Форма с готовым блюдом, чаша под ней чистая.",
         f"{PRODUCT_CANON_DESCRIPTION}, containing cooked chicken thighs and roasted "
         "potato wedges, lifted slightly out of a clean dry black air fryer basket, "
         "steam faintly visible",
         True, True),
        ("product_beauty_shot",
         "в самом конце статьи, перед артикулом",
         "Product beauty shot формы рядом с аэрогрилем — финальный кадр товара.",
         f"{PRODUCT_CANON_DESCRIPTION}, clean and empty, standing alone on a light kitchen "
         "counter with a black air fryer softly blurred in the background, calm composition",
         True, True),
    ),
    "recipe": (
        ("finished_dish_on_plate",
         "в самом начале статьи, сразу после заголовка",
         "Готовое блюдо на тарелке — аппетитный финальный результат.",
         "appetizing plate of roasted chicken thighs and golden potato wedges, garnished "
         "with fresh herbs, on a rustic kitchen table, natural light",
         False, False),
        ("ingredients",
         "после абзаца «Ингредиенты»",
         "Разложенные ингредиенты для рецепта.",
         "raw ingredients laid out on a kitchen counter: chicken thighs, potatoes, garlic, "
         "herbs and spices, olive oil in a small bowl, overhead natural light",
         False, False),
        ("marinating_prep",
         "после абзаца «Как готовить»",
         "Маринование/подготовка продуктов перед готовкой.",
         "raw chicken thighs being seasoned with spices and garlic in a glass bowl, "
         "hands-free close-up, kitchen counter, warm daylight",
         False, False),
        ("dish_in_form_in_airfryer",
         "после абзаца о готовке при температуре",
         "Блюдо в силиконовой форме внутри аэрогриля.",
         f"{PRODUCT_CANON_DESCRIPTION}, filled with raw seasoned chicken and potato wedges, "
         "placed inside an open black air fryer basket, ready to cook",
         True, True),
        ("form_next_to_cleaner_basket",
         "в конце статьи, перед артикулом",
         "Форма рядом с уже более чистой чашей — мягкий довод в пользу формы.",
         f"{PRODUCT_CANON_DESCRIPTION}, clean, sitting next to a black air fryer basket "
         "that looks noticeably cleaner than before, tidy kitchen counter",
         True, True),
    ),
    "lifehack": (
        ("before_after_cleaning",
         "после первого абзаца",
         "До/после уборки чаши — визуальный контраст.",
         "split-style comparison of a greasy black air fryer basket versus a clean dry "
         "black air fryer basket side by side, same kitchen counter, natural light",
         False, False),
        ("clean_kitchen",
         "в середине статьи, после описания лайфхака",
         "Опрятная, уютная кухня — атмосфера результата.",
         "cozy clean modern home kitchen, warm afternoon light, tidy counter, no clutter, "
         "no people",
         False, False),
        ("form_in_use",
         "после практического объяснения лайфхака",
         "Форма в использовании внутри аэрогриля.",
         f"{PRODUCT_CANON_DESCRIPTION}, placed inside an open black air fryer basket, "
         "empty and ready for food, close-up angle",
         True, True),
        ("tidy_cleanup_after_cooking",
         "в конце статьи, перед артикулом",
         "Аккуратная уборка после готовки — форма моется отдельно, чаша сухая.",
         f"{PRODUCT_CANON_DESCRIPTION}, being rinsed under running water in a kitchen sink, "
         "clean and simple, no other dishes",
         True, False),
    ),
    "comparison": (
        ("without_form_mess",
         "после первого абзаца",
         "Готовка без формы — жир и соус прямо на решётке.",
         "black air fryer basket with visible grease and sauce residue directly on the "
         "ribs and walls, realistic everyday mess, warm kitchen light",
         False, False),
        ("with_form_clean",
         "после раздела о готовке с формой",
         "Готовка с формой — решётка и стенки почти сухие.",
         f"{PRODUCT_CANON_DESCRIPTION}, placed inside a black air fryer basket, the "
         "visible basket walls around it clean and dry, no grease",
         True, True),
        ("side_by_side_result",
         "в середине статьи, после сравнения",
         "До/после в одном кадре — визуальное сравнение результата уборки.",
         "two black air fryer baskets side by side on a kitchen counter, one with light "
         "grease residue, one spotless and dry, natural daylight, clear visual contrast",
         False, False),
        ("form_in_hand_area",
         "после практического вывода",
         "Форма крупным планом — рифлёное дно и ручки.",
         f"{PRODUCT_CANON_DESCRIPTION}, close-up angle emphasizing the ribbed bottom and "
         "corner handle tabs, clean kitchen counter background",
         True, True),
        ("product_beauty_shot",
         "в конце статьи, перед артикулом",
         "Product beauty shot формы — финальный кадр товара.",
         f"{PRODUCT_CANON_DESCRIPTION}, clean and empty, standing alone on a light kitchen "
         "counter, calm composition, soft daylight",
         True, True),
    ),
    "soft_ad": (
        ("everyday_kitchen_moment",
         "в самом начале статьи, сразу после заголовка",
         "Бытовой, тёплый кадр кухни — заход в историю.",
         "cozy home kitchen scene, warm afternoon light, black air fryer on the counter, "
         "relaxed everyday atmosphere, no people",
         False, False),
        ("dirty_basket_before",
         "после истории о проблеме с мытьём",
         "Грязная чаша аэрогриля — узнаваемая проблема.",
         "black air fryer basket with visible grease residue after cooking, realistic "
         "everyday mess, warm kitchen counter background",
         False, False),
        ("form_discovery",
         "после раздела о находке/решении",
         "Силиконовая форма рядом с аэрогрилем — момент открытия решения.",
         f"{PRODUCT_CANON_DESCRIPTION}, sitting on a kitchen counter next to an open black "
         "air fryer, clean and empty basket",
         True, True),
        ("form_with_food_result",
         "после практического описания использования",
         "Форма с готовым блюдом — результат использования.",
         f"{PRODUCT_CANON_DESCRIPTION}, containing cooked chicken and vegetables, lifted "
         "slightly out of a clean dry black air fryer basket",
         True, True),
        ("product_beauty_shot",
         "в конце статьи, перед артикулом",
         "Product beauty shot формы — финальный кадр товара.",
         f"{PRODUCT_CANON_DESCRIPTION}, clean and empty, standing alone on a light kitchen "
         "counter, calm composition, soft daylight",
         True, True),
    ),
}

# The canon article already has 4 hand-placed [ИЗОБРАЖЕНИЕ N: ...] markers --
# reuse their exact descriptions/positions instead of inventing generic ones.
CANON_IMAGE_PLAN = (
    ("dirty_basket_with_sponge",
     "после первого абзаца (после [ИЗОБРАЖЕНИЕ 1])",
     "Чаша аэрогриля с жирными следами и губка.",
     "black air fryer basket with visible grease and burnt residue on the ribs, a soft "
     "sponge resting on its edge, no hands, warm kitchen counter light",
     False, False),
    ("form_lowered_into_basket",
     "после раздела «Что на самом деле портит покрытие» (после [ИЗОБРАЖЕНИЕ 2])",
     "Силиконовая форма опускается в чашу.",
     f"{PRODUCT_CANON_DESCRIPTION}, being placed into an open black air fryer basket, "
     "hands-free close-up angle",
     True, True),
    ("form_removed_with_food_clean_basket",
     "после раздела «Барьер вместо уборки» (после [ИЗОБРАЖЕНИЕ 3])",
     "Доставание формы с готовым блюдом, под ней чистая чаша.",
     f"{PRODUCT_CANON_DESCRIPTION}, containing cooked food, lifted slightly out of a "
     "black air fryer basket that looks completely clean and dry underneath",
     True, True),
    ("product_beauty_shot",
     "в конце статьи, перед артикулом (после [ИЗОБРАЖЕНИЕ 4])",
     "Product shot формы рядом с аэрогрилем.",
     f"{PRODUCT_CANON_DESCRIPTION}, clean and empty, standing next to a black air fryer, "
     "calm composition, soft daylight",
     True, True),
)


def build_image_prompts(article_id: str, article_type: str) -> list:
    plan = CANON_IMAGE_PLAN if article_id == "canon-chasha-lyseet" else IMAGE_PLAN_BY_TYPE.get(
        article_type, IMAGE_PLAN_BY_TYPE["soft_ad"])
    prompts = []
    for i, (purpose, insert_after, ru_desc, prompt_specific, must_show, use_ref) in enumerate(plan, start=1):
        prompt_en = f"{IMAGE_STYLE_POSITIVE}, {prompt_specific}"
        negative = IMAGE_NEGATIVE_BASE
        prompts.append({
            "image_id": f"{article_id}-img-{i:02d}",
            "filename": f"{article_id}-img-{i:02d}.png",
            "insert_after_heading": insert_after,
            "purpose": purpose,
            "russian_description": ru_desc,
            "prompt_en": prompt_en,
            "negative_prompt": negative,
            "aspect_ratio": "9:16",
            "must_show_product": must_show,
            "use_product_reference": use_ref,
            "safe_to_generate": True,
            "reference_images": list(PRODUCT_REFERENCE_IMAGES) if use_ref else [],
        })
    return prompts


def write_image_prompts(article_id: str, article_type: str, kit_dir: Path) -> dict:
    prompts = build_image_prompts(article_id, article_type)
    doc = {"article_id": article_id, "total_images": len(prompts), "prompts": prompts}

    json_path = kit_dir / "image-prompts.json"
    json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# Image Prompts -- {article_id}", "", f"Всего картинок: {len(prompts)}", ""]
    for p in prompts:
        lines.append(f"## {p['image_id']}")
        lines.append(f"- **Куда вставить:** {p['insert_after_heading']}")
        lines.append(f"- **Что на картинке (RU):** {p['russian_description']}")
        lines.append(f"- **Prompt (EN):** {p['prompt_en']}")
        lines.append(f"- **Negative prompt:** {p['negative_prompt']}")
        lines.append(f"- **Aspect ratio:** {p['aspect_ratio']}")
        lines.append(f"- **must_show_product:** {p['must_show_product']} | "
                    f"**use_product_reference:** {p['use_product_reference']}")
        lines.append("")
    md_path = kit_dir / "image-prompts.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    doc["json_path"] = str(json_path)
    doc["md_path"] = str(md_path)
    return doc


# -- selection ---------------------------------------------------------------
# 7 articles: the hand-written style-canon (explicit first priority) + 6
# diverse, non-duplicate, already publish-ready generated posts spanning
# problem_solution / recipe / lifehack / soft_ad / comparison. Kept at
# exactly 7 so every selected article fits inside
# max_articles_to_generate_images_now (no article is left prompts-only).
SELECTED_ARTICLE_IDS = (
    "canon-chasha-lyseet",
    "dzen-001",
    "batch-002-dzen-004",
    "batch-002-dzen-003",
    "batch-004-dzen-001",
    "batch-003-dzen-004",
    "dzen-007",
)

SELECTION_REASONS = {
    "canon-chasha-lyseet": "Явно указана владельцем как эталон стиля и первый приоритет.",
    "dzen-001": "Живой рецепт, чёткая структура, не дубликат.",
    "batch-002-dzen-004": "Личный голос, лайфхак-угол, не дубликат.",
    "batch-002-dzen-003": "Сильный проблемный хук, не дубликат.",
    "batch-004-dzen-001": "Разговорный стиль, самая насыщенная история, не дубликат.",
    "batch-003-dzen-004": "Рецептная статья, вариативность блюда (картофель), не дубликат.",
    "dzen-007": "Единственная статья формата сравнения (с формой / без), не дубликат.",
}


def select_articles(repo_root: str = ".") -> list:
    entries = {e["article_id"]: e for e in scan_all_articles(repo_root)}
    selected = []
    for article_id in SELECTED_ARTICLE_IDS:
        entry = entries.get(article_id)
        if entry is None:
            continue
        selected.append({**entry, "selection_reason": SELECTION_REASONS.get(article_id, "")})
    return selected


def write_selected_articles_plan(campaign_dir: str, repo_root: str = ".", out_dir=None) -> dict:
    selected = select_articles(repo_root)
    total_found = len(scan_all_articles(repo_root))

    doc = {
        "campaign_code": "coating-protect-2026-07",
        "total_articles_found": total_found,
        "selected_count": len(selected),
        "selection_note": (f"{total_found} candidate articles found (1 hand-written canon + "
                           f"40 auto-generated); selected {len(selected)} diverse, "
                           f"non-duplicate, publish-ready articles (canon article kept first "
                           f"per owner instruction)."),
        "selected_articles": selected,
    }
    out = Path(out_dir) if out_dir else (
        Path(repo_root) / campaign_dir / "generated/content-factory/dzen-publishing")
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "selected-dzen-articles-plan.json"
    json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# Selected Dzen Articles -- coating-protect-2026-07", "",
            doc["selection_note"], ""]
    for i, e in enumerate(selected, start=1):
        lines.append(f"{i}. **{e['article_id']}** -- {e['title']}")
        lines.append(f"   - type: {e['type']} | priority: {e['recommended_publish_priority']}")
        lines.append(f"   - why selected: {e['selection_reason']}")
        lines.append("")
    md_path = out / "selected-dzen-articles-plan.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    doc["json_path"] = str(json_path)
    doc["md_path"] = str(md_path)
    return doc


# -- article kits --------------------------------------------------------------

TAGS_BY_TYPE = {
    "problem_solution": ("аэрогриль", "уходзапокрытием", "кухня", "лайфхак",
                        "силиконоваяформа", "дом", "готовим", "полезныесоветы"),
    "recipe": ("рецепт", "аэрогриль", "курица", "ужин", "простыерецепты",
              "кухня", "готовимдома", "силиконоваяформа"),
    "lifehack": ("лайфхак", "аэрогриль", "уборка", "кухня", "силиконоваяформа",
                "полезныесоветы", "дом", "готовим"),
    "comparison": ("сравнение", "аэрогриль", "силиконоваяформа", "уборка",
                  "кухня", "дотипосле", "полезныесоветы", "дом"),
    "soft_ad": ("аэрогриль", "силиконоваяформа", "кухня", "находка", "лайфхак",
               "дом", "готовимдома", "полезно"),
}

PINNED_COMMENT_TEMPLATE = (
    "Форма из статьи:\n{link}\n\nАртикул на Ozon: {artikul}"
)


def _extract_canon_title_and_body(raw: str) -> tuple:
    """Strips the служебное preamble, '## Заголовок'/'## Текст' scaffolding,
    and the trailing pinned-comment section from the hand-written canon
    article -- returns (title, body_with_image_markers)."""
    title_match = re.search(r"\*\*(.+?)\*\*", raw)
    title = title_match.group(1) if title_match else "Untitled"

    body = raw
    if "## Текст" in body:
        body = body.split("## Текст", 1)[1]
    if "## Закреплённый комментарий" in body:
        body = body.split("## Закреплённый комментарий", 1)[0]
    body = body.strip()
    if body.endswith("---"):
        body = body[:-3].rstrip()
    return title, body


def _insert_image_markers(body: str, prompts: list) -> str:
    """Inserts '📷 [Фото N — purpose]' markers between paragraphs, spaced
    evenly through the article body (used for the 6 generated articles that
    have no existing [ИЗОБРАЖЕНИЕ] placeholders)."""
    paragraphs = [p for p in body.split("\n\n") if p.strip()]
    n_images = len(prompts)
    n_paragraphs = len(paragraphs)
    if n_paragraphs == 0:
        return body

    # Evenly distribute insertion points across paragraph gaps (never before
    # the very first paragraph -- that's the hook).
    step = max(1, n_paragraphs // (n_images + 1))
    out = [paragraphs[0]]
    img_idx = 0
    for i, para in enumerate(paragraphs[1:], start=1):
        out.append(para)
        if img_idx < n_images and i % step == 0 and i < n_paragraphs - 1:
            marker = f"📷 [Фото {img_idx + 1} -- {prompts[img_idx]['russian_description']}]"
            out.append(marker)
            img_idx += 1
    # Any remaining images (rounding) go right before the end.
    while img_idx < n_images:
        marker = f"📷 [Фото {img_idx + 1} -- {prompts[img_idx]['russian_description']}]"
        out.append(marker)
        img_idx += 1
    return "\n\n".join(out)


def _replace_canon_image_markers(body: str, prompts: list) -> str:
    """The canon article already has [ИЗОБРАЖЕНИЕ N: ...] markers -- convert
    them to the same friendly '📷 [Фото N — ...]' style used elsewhere,
    matched by position (1st marker -> prompts[0], etc.)."""
    counter = {"i": 0}

    def _sub(match):
        idx = counter["i"]
        counter["i"] += 1
        if idx < len(prompts):
            return f"📷 [Фото {idx + 1} -- {prompts[idx]['russian_description']}]"
        return match.group(0)

    return re.sub(r"\[ИЗОБРАЖЕНИЕ \d+:[^\]]*\]", _sub, body)


def build_article_kit(article_id: str, campaign_dir: str, repo_root: str = ".",
                      out_dir=None) -> dict:
    entries = {e["article_id"]: e for e in scan_all_articles(repo_root)}
    entry = entries.get(article_id)
    if entry is None:
        raise ValueError(f"unknown article_id {article_id!r}")

    raw = Path(repo_root, entry["source_path"]).read_text(encoding="utf-8")
    article_type = entry["type"]
    prompts = build_image_prompts(article_id, article_type)

    if article_id == "canon-chasha-lyseet":
        title, body = _extract_canon_title_and_body(raw)
        body = _replace_placeholders(body)
        body = _soften_claims(body)
        body = _replace_canon_image_markers(body, prompts)
    else:
        title = raw.splitlines()[0].lstrip("# ").strip()
        body = "\n\n".join(raw.split("\n\n")[1:]).strip()  # drop the "# Title" line
        body = _replace_placeholders(body)
        body = _soften_claims(body)
        body = _ensure_product_link_and_artikul(body)
        body = _insert_image_markers(body, prompts)

    # _ensure_product_link_and_artikul is idempotent (checks presence first) --
    # safe to call here for the canon path too, even though its own source
    # text already mentions the artikul after placeholder replacement.
    body = _ensure_product_link_and_artikul(body)

    tags = TAGS_BY_TYPE.get(article_type, TAGS_BY_TYPE["soft_ad"])
    tags_line = " ".join(f"#{t}" for t in tags)
    pinned_comment_text = PINNED_COMMENT_TEMPLATE.format(link=OZON_LINK, artikul=OZON_ARTIKUL)
    pinned_quote = "\n".join(f"> {line}" if line else ">" for line in pinned_comment_text.splitlines())

    # The artikul + link live inline in `body` (either from the source
    # article itself or via _ensure_product_link_and_artikul above) -- the
    # trailing block below adds ONLY the pinned-comment preview and tags,
    # never repeating the artikul/link a second time.
    final_article = (
        f"# {title}\n\n{body}\n\n---\n\n"
        f"**Закреплённый комментарий (скопировать отдельно):**\n"
        f"{pinned_quote}\n\n"
        f"**Теги:** {tags_line}\n"
    )

    kit_dir = Path(out_dir) if out_dir else (
        Path(repo_root) / campaign_dir / "generated/content-factory/dzen-publishing/articles" / article_id)
    kit_dir.mkdir(parents=True, exist_ok=True)

    article_path = kit_dir / "article-ready-to-copy.md"
    article_path.write_text(final_article, encoding="utf-8")

    pinned_path = kit_dir / "PINNED-COMMENT.txt"
    pinned_path.write_text(PINNED_COMMENT_TEMPLATE.format(link=OZON_LINK, artikul=OZON_ARTIKUL) + "\n",
                           encoding="utf-8")

    tags_path = kit_dir / "TAGS.txt"
    tags_path.write_text(tags_line + "\n", encoding="utf-8")

    image_doc = write_image_prompts(article_id, article_type, kit_dir)

    checklist_lines = [
        f"# Publishing Checklist -- {article_id}", "",
        f"Статья: {title}", "",
        "## Что сделать",
        "- [ ] Скопировать текст из `article-ready-to-copy.md` в редактор Дзена",
        f"- [ ] Вставить {len(prompts)} картинок(и) из папки `images/` на места маркеров 📷 в тексте",
        "- [ ] Удалить сами маркеры 📷 после вставки картинок",
        "- [ ] Скопировать текст из `PINNED-COMMENT.txt` в закреплённый комментарий под статьёй",
        "- [ ] Скопировать теги из `TAGS.txt` в поле тегов Дзена",
        "- [ ] Проверить, что ссылка на Ozon работает",
        "- [ ] Опубликовать вручную",
        "",
        "## Картинки для вставки",
    ]
    for p in prompts:
        checklist_lines.append(f"- `{p['filename']}` -- {p['insert_after_heading']}: {p['russian_description']}")
    checklist_path = kit_dir / "publishing-checklist.md"
    checklist_path.write_text("\n".join(checklist_lines) + "\n", encoding="utf-8")

    return {
        "article_id": article_id,
        "kit_dir": str(kit_dir),
        "article_path": str(article_path),
        "pinned_comment_path": str(pinned_path),
        "tags_path": str(tags_path),
        "image_prompts_json_path": image_doc["json_path"],
        "image_prompts_md_path": image_doc["md_path"],
        "checklist_path": str(checklist_path),
        "total_image_prompts": len(prompts),
    }


def _replace_placeholders(text: str) -> str:
    text = text.replace("{{OZON_ARTIKUL}}", OZON_ARTIKUL)
    text = text.replace("{{OZON_LINK}}", OZON_LINK)
    return text


def _soften_claims(text: str) -> str:
    for find, replace in CLAIM_SOFTENING_RULES:
        text = text.replace(find, replace)
    return text


def _ensure_product_link_and_artikul(text: str) -> str:
    if OZON_ARTIKUL not in text:
        text += (f"\n\n**Форма на Ozon — артикул {OZON_ARTIKUL}.** Ссылка на товар — "
                 f"в закреплённом комментарии под статьёй.")
    return text


def build_all_selected_kits(campaign_dir: str, repo_root: str = ".") -> list:
    selected = select_articles(repo_root)
    return [build_article_kit(e["article_id"], campaign_dir, repo_root) for e in selected]


# -- image generation ---------------------------------------------------------
# Budget/call hard limits for THIS publishing-kit image batch (separate from,
# but same shape as, the per-scene campaign runner's contract).
MAX_ARTICLES_TO_GENERATE_IMAGES_NOW = 7
MAX_IMAGES_PER_ARTICLE = 5
MAX_TOTAL_IMAGE_CALLS = 35
MAX_RETRIES = 0
CAMPAIGN_IMAGE_GENERATION_HARD_CAP_USD = 12.00


def _resolve_reference_paths(reference_image_ids: list, repo_root: str) -> list:
    from . import product_reference_only_runner as por
    paths = []
    for ref_id in reference_image_ids:
        if ref_id not in por.PRODUCT_REFERENCE_ASSET_PATHS:
            raise ValueError(f"unknown product reference id: {ref_id!r}")
        rel = por.PRODUCT_REFERENCE_ASSET_PATHS[ref_id]
        full = str(Path(repo_root) / rel)
        if not Path(full).is_file():
            raise ValueError(f"product reference image missing on disk: {full}")
        paths.append(full)
    return paths


def compute_image_generation_plan(repo_root: str = ".") -> dict:
    """Budget/limit check BEFORE any network call -- selected_articles_count,
    images_per_article, total_images_planned, estimated_cost_usd, and which
    articles (if any) must be deferred to prompts-only because they exceed
    MAX_ARTICLES_TO_GENERATE_IMAGES_NOW."""
    from . import product_reference_only_runner as por
    selected = select_articles(repo_root)
    to_generate = selected[:MAX_ARTICLES_TO_GENERATE_IMAGES_NOW]
    deferred = selected[MAX_ARTICLES_TO_GENERATE_IMAGES_NOW:]

    per_article = []
    total_images = 0
    for entry in to_generate:
        prompts = build_image_prompts(entry["article_id"], entry["type"])[:MAX_IMAGES_PER_ARTICLE]
        per_article.append({"article_id": entry["article_id"], "images_planned": len(prompts)})
        total_images += len(prompts)

    total_images = min(total_images, MAX_TOTAL_IMAGE_CALLS)
    estimated_cost = round(total_images * por.PRICE_PER_IMAGE_USD_ESTIMATE, 4)

    return {
        "selected_articles_count": len(selected),
        "articles_to_generate_now": [e["article_id"] for e in to_generate],
        "articles_deferred_prompts_only": [e["article_id"] for e in deferred],
        "images_per_article": per_article,
        "total_images_planned": total_images,
        "estimated_cost_usd": estimated_cost,
        "max_articles_to_generate_images_now": MAX_ARTICLES_TO_GENERATE_IMAGES_NOW,
        "max_images_per_article": MAX_IMAGES_PER_ARTICLE,
        "max_total_image_calls": MAX_TOTAL_IMAGE_CALLS,
        "max_retries": MAX_RETRIES,
        "campaign_image_generation_hard_cap_usd": CAMPAIGN_IMAGE_GENERATION_HARD_CAP_USD,
        "within_limits": (len(to_generate) <= MAX_ARTICLES_TO_GENERATE_IMAGES_NOW
                         and total_images <= MAX_TOTAL_IMAGE_CALLS
                         and estimated_cost <= CAMPAIGN_IMAGE_GENERATION_HARD_CAP_USD),
    }


def generate_images_for_all_selected_articles(campaign_dir: str, repo_root: str = ".",
                                              apply: bool = True) -> dict:
    """Generates real images (apply=True) for up to MAX_ARTICLES_TO_GENERATE_
    IMAGES_NOW articles' image-prompts (each already capped at
    MAX_IMAGES_PER_ARTICLE), sharing ONE campaign-wide SpendTracker so the
    $12 hard cap applies across the whole batch, not per-article. n=1,
    retries=0 per image, no automatic second attempt on failure/timeout."""
    from .openai_images_client import OpenAIImagesProvider
    from .budget import SpendTracker
    from .models import ImageRequest
    from . import product_reference_only_runner as por

    plan = compute_image_generation_plan(repo_root)
    tracker = SpendTracker(cap_usd=CAMPAIGN_IMAGE_GENERATION_HARD_CAP_USD)
    provider = OpenAIImagesProvider(model=por.MODEL, tracker=tracker,
                                    price_per_image_usd=por.PRICE_PER_IMAGE_USD_ESTIMATE)

    entries = {e["article_id"]: e for e in select_articles(repo_root)}
    article_reports = []
    total_calls = 0

    for article_id in plan["articles_to_generate_now"]:
        entry = entries[article_id]
        kit_dir = (Path(repo_root) / campaign_dir /
                  "generated/content-factory/dzen-publishing/articles" / article_id)
        prompts = build_image_prompts(article_id, entry["type"])[:MAX_IMAGES_PER_ARTICLE]
        images_dir = kit_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        image_results = []
        for p in prompts:
            if total_calls >= MAX_TOTAL_IMAGE_CALLS:
                image_results.append({"image_id": p["image_id"], "filename": p["filename"],
                                      "candidate_status": "skipped_hard_limit",
                                      "reason": "max_total_image_calls reached"})
                continue

            full_prompt = f"{p['prompt_en']}\n\nNegative prompt (avoid): {p['negative_prompt']}"
            try:
                reference_paths = (_resolve_reference_paths(p["reference_images"], repo_root)
                                   if p["use_product_reference"] else [])
                req = ImageRequest(
                    scene_id=p["image_id"], prompt=full_prompt, n=1, size="720x1280",
                    mode="edit" if p["use_product_reference"] else "generate",
                    reference_images=reference_paths, output_format="png",
                )
                results = provider.generate(req, out_dir=str(images_dir), apply=apply)
                total_calls += 1
                result = results[0]

                final_path = images_dir / p["filename"]
                if result.image_path and Path(result.image_path).is_file():
                    Path(result.image_path).replace(final_path)
                    candidate_status = "pending_manual_review"
                    saved_path = str(final_path)
                else:
                    candidate_status = "rejected_api_error"
                    saved_path = None

                image_results.append({
                    "image_id": p["image_id"], "filename": p["filename"],
                    "candidate_status": candidate_status, "image_path": saved_path,
                    "prompt": full_prompt, "mode": req.mode,
                    "reference_images": p["reference_images"] if p["use_product_reference"] else [],
                    "estimated_cost_usd": result.estimated_cost_usd,
                })
            except TimeoutError as e:
                total_calls += 1
                image_results.append({"image_id": p["image_id"], "filename": p["filename"],
                                      "candidate_status": "no_candidate_timeout",
                                      "error_message": str(e)})
            except Exception as e:  # noqa: BLE001 -- any failure maps to a reported outcome
                total_calls += 1
                image_results.append({"image_id": p["image_id"], "filename": p["filename"],
                                      "candidate_status": "rejected_api_error",
                                      "error_type": type(e).__name__, "error_message": str(e)})

        article_report = {
            "article_id": article_id,
            "images_attempted": len(prompts),
            "images_generated": sum(1 for r in image_results if r["candidate_status"] == "pending_manual_review"),
            "results": image_results,
        }
        article_reports.append(article_report)

        report_json = kit_dir / "image-generation-report.json"
        report_json.write_text(json.dumps(article_report, ensure_ascii=False, indent=2), encoding="utf-8")
        md_lines = [f"# Image Generation Report -- {article_id}", "",
                   f"Attempted: {article_report['images_attempted']} | "
                   f"Generated: {article_report['images_generated']}", ""]
        for r in image_results:
            md_lines.append(f"- `{r['filename']}` -- {r['candidate_status']}")
        (kit_dir / "image-generation-report.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    summary = {
        "campaign_code": "coating-protect-2026-07",
        "plan": plan,
        "openai_calls_executed": total_calls,
        "higgsfield_calls_executed": 0,
        "total_actual_spend_usd": tracker.total_actual(),
        "total_estimated_spend_usd": tracker.total_estimated(),
        "article_reports": article_reports,
        "candidate_status_note": ("Every image is pending_manual_review, rejected_api_error, "
                                  "or no_candidate_timeout -- never auto-accepted."),
    }
    return summary


# -- TODAY-PUBLISH -------------------------------------------------------------

TODAY_PUBLISH_ARTICLE_ID = "canon-chasha-lyseet"


def build_today_publish(campaign_dir: str, repo_root: str = ".",
                        article_id: str = TODAY_PUBLISH_ARTICLE_ID) -> dict:
    """Copies (never moves) the first-priority article's kit into
    dzen-publishing/TODAY-PUBLISH/ with the renamed convention the owner
    asked for. Falls back gracefully (still writes the folder, just without
    images/) if image generation hasn't happened for this article yet."""
    import shutil

    kit_dir = (Path(repo_root) / campaign_dir /
              "generated/content-factory/dzen-publishing/articles" / article_id)
    if not kit_dir.is_dir():
        raise ValueError(f"no kit built yet for article_id {article_id!r} -- run build_article_kit first")

    out_dir = Path(repo_root) / campaign_dir / "generated/content-factory/dzen-publishing/TODAY-PUBLISH"
    out_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    file_map = {
        "article-ready-to-copy.md": "ARTICLE-TO-COPY.md",
        "PINNED-COMMENT.txt": "PINNED-COMMENT.txt",
        "TAGS.txt": "TAGS.txt",
        "image-prompts.md": "IMAGE-PROMPTS-TO-GENERATE.md",
        "publishing-checklist.md": "CHECKLIST.txt",
    }
    for src_name, dest_name in file_map.items():
        src = kit_dir / src_name
        if src.is_file():
            dest = out_dir / dest_name
            shutil.copy2(src, dest)
            copied.append(str(dest))

    images_src = kit_dir / "images"
    images_generated = False
    if images_src.is_dir() and any(images_src.glob("*.png")):
        images_dest = out_dir / "images"
        images_dest.mkdir(parents=True, exist_ok=True)
        for f in images_src.glob("*.png"):
            dest = images_dest / f.name
            shutil.copy2(f, dest)
            copied.append(str(dest))
        images_generated = True

    return {
        "today_publish_dir": str(out_dir),
        "article_id": article_id,
        "files_copied": len(copied),
        "files": copied,
        "images_generated": images_generated,
        "originals_modified": False,
    }


# -- dashboard -----------------------------------------------------------------

def _article_dashboard_status(kit_dir: Path) -> str:
    images_dir = kit_dir / "images"
    prompts_path = kit_dir / "image-prompts.json"
    if images_dir.is_dir() and any(images_dir.glob("*.png")):
        return "images_generated"
    if prompts_path.is_file():
        return "prompts_only"
    return "needs_images"


def build_dzen_publishing_dashboard(campaign_dir: str, repo_root: str = ".", out_path=None) -> str:
    selected = select_articles(repo_root)
    articles_root = (Path(repo_root) / campaign_dir /
                     "generated/content-factory/dzen-publishing/articles")

    cards = []
    for e in selected:
        article_id = e["article_id"]
        kit_dir = articles_root / article_id
        status = _article_dashboard_status(kit_dir)
        images_dir = kit_dir / "images"
        image_files = sorted(images_dir.glob("*.png")) if images_dir.is_dir() else []

        thumbs = "".join(
            f'<img src="articles/{article_id}/images/{f.name}" alt="{f.name}" '
            f'style="width:100px;height:178px;object-fit:cover;border-radius:4px;margin:2px;">'
            for f in image_files
        )
        status_class = {
            "ready_to_publish": "status-ready", "images_generated": "status-ready",
            "prompts_only": "status-needs-edit", "needs_images": "status-needs-edit",
            "published_manually": "status-rejected",
        }.get(status, "status-needs-edit")

        cards.append(f"""
        <div class="card">
          <h3>{article_id}</h3>
          <p><b>{e['title']}</b></p>
          <span class="status-badge {status_class}">{status}</span>
          <p>type: {e['type']} | priority: {e['recommended_publish_priority']} | images: {len(image_files)}</p>
          <p>{thumbs or '(нет картинок)'}</p>
          <p>
            <a href="articles/{article_id}/article-ready-to-copy.md">article-ready-to-copy.md</a> &nbsp;|&nbsp;
            <a href="articles/{article_id}/image-prompts.md">image-prompts.md</a> &nbsp;|&nbsp;
            <a href="articles/{article_id}/PINNED-COMMENT.txt">pinned comment</a> &nbsp;|&nbsp;
            <a href="articles/{article_id}/TAGS.txt">tags</a>
          </p>
        </div>""")

    html = f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Dzen publishing kits -- coating-protect-2026-07</title>
<style>
body {{ font-family: sans-serif; background:#111; color:#eee; margin:0; padding:20px; }}
h1 {{ font-size: 20px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }}
.card {{ background:#1c1c1c; border:1px solid #333; border-radius:8px; padding:12px; }}
.status-badge {{ display:inline-block; padding:3px 8px; border-radius:4px; font-size:12px; font-weight:bold; }}
.status-ready {{ background:#1e5c33; color:#c8ffd9; }}
.status-needs-edit {{ background:#5c4b1e; color:#ffe9b3; }}
.status-rejected {{ background:#5c1e1e; color:#ffc8c8; }}
a {{ color:#8ab4ff; }}
</style>
</head><body>
<h1>Dzen publishing kits -- coating-protect-2026-07</h1>
<p><a href="dzen-article-inventory.md">full inventory</a> &nbsp;|&nbsp;
   <a href="selected-dzen-articles-plan.md">selection plan</a> &nbsp;|&nbsp;
   <a href="TODAY-PUBLISH/ARTICLE-TO-COPY.md">TODAY-PUBLISH</a></p>
<p style="color:#888; font-size:13px;">Owner copies text/images/tags/pinned comment manually into Dzen. No auto-posting anywhere.</p>
<div class="grid">
{''.join(cards)}
</div>
</body></html>"""

    out = Path(out_path) if out_path else (
        Path(repo_root) / campaign_dir / "generated/content-factory/dzen-publishing/index.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return str(out)


# -- owner zip -----------------------------------------------------------------

def build_owner_zip(campaign_dir: str, repo_root: str = ".", out_path=None) -> dict:
    """Zips the ENTIRE dzen-publishing/ tree (inventory, selection plan,
    TODAY-PUBLISH, every article kit with its text/images/pinned-comment/
    tags/checklist, the dashboard) -- one flat deliverable for the owner.
    Read-only against sources; only writes the zip itself."""
    import zipfile

    base = Path(repo_root) / campaign_dir / "generated/content-factory/dzen-publishing"
    out = Path(out_path) if out_path else (base / "DZEN-PUBLISHING-KIT.zip")

    added = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(base.rglob("*")):
            if f.is_file() and f.resolve() != out.resolve():
                arcname = str(f.relative_to(base)).replace("\\", "/")
                zf.write(f, arcname=arcname)
                added.append(arcname)

    return {"zip_path": str(out), "files_added": len(added), "size_bytes": out.stat().st_size}
