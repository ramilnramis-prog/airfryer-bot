"""Platform metadata + Dzen post generation for the local content factory.
Pure text/data generation -- no network, no OpenAI/Higgsfield calls, no
auto-posting of any kind (nothing here ever calls a social-platform API;
the owner publishes manually)."""
from __future__ import annotations

import json
from pathlib import Path

from . import content_factory_data as fd

BASE_HASHTAGS = ("аэрогриль", "airfryer", "кухня", "лайфхак", "готовим", "рецепт")

PLATFORM_HASHTAGS = {
    "youtube_shorts": BASE_HASHTAGS + ("shorts", "кухонныегаджеты", "готовкадома"),
    "instagram_reels": BASE_HASHTAGS + ("reels", "рецептдня", "домашняякухня", "лайфхакикухни", "кухонныенаходки"),
    "tiktok": BASE_HASHTAGS + ("рекомендации", "находка", "фудтикток"),
    "vk_clips": BASE_HASHTAGS + ("клипы", "кухонныегаджеты", "полезно"),
}

PLATFORM_TONE = {
    "youtube_shorts": "коротко и по делу, с акцентом на пользу",
    "instagram_reels": "тёплый, разговорный, с лёгким лайфстайл-акцентом",
    "tiktok": "живой, разговорный, без рекламного тона",
    "vk_clips": "чуть более информативный, с конкретикой",
}


def _needs_disclaimer(variant: dict) -> bool:
    return variant["product_claim_level"] in ("emotional",) or "scene-02" in variant["scene_order"]


def build_platform_entry(variant: dict, platform: str) -> dict:
    hook = variant["hook_text"]
    cta = variant["CTA"]
    claim = fd.SAFE_CLAIMS[hash(variant["variant_id"] + platform) % len(fd.SAFE_CLAIMS)]

    title = hook if len(hook) <= 60 else hook[:57] + "..."
    short_description = f"{hook} {claim}.".strip()
    caption = f"{hook}\n\n{claim}. {cta}."
    hashtags = [f"#{h}" for h in PLATFORM_HASHTAGS[platform]]

    entry = {
        "platform": platform,
        "title": title,
        "short_description": short_description,
        "caption": caption,
        "hashtags": hashtags,
        "CTA": cta,
        "pinned_comment_idea": fd.PINNED_COMMENT_BANK[hash(variant["variant_id"]) % len(fd.PINNED_COMMENT_BANK)],
        "tone": PLATFORM_TONE[platform],
    }
    if _needs_disclaimer(variant):
        entry["disclaimer"] = fd.DISCLAIMER_TEXT
    return entry


def build_variant_platform_metadata(variant: dict) -> dict:
    return {
        "variant_id": variant["variant_id"],
        "style_type": variant["style_type"],
        "native_format": variant["format"],
        "hook_text": variant["hook_text"],
        "product_claim_level": variant["product_claim_level"],
        "platforms": {p: build_platform_entry(variant, p) for p in fd.FORMATS},
        "creative_angle": variant["creative_angle"],
        "difference_from_other_variants": variant["difference_from_other_variants"],
        "avoid_duplicate_posting_note": variant["avoid_duplicate_posting_note"],
        "recommended_spacing_hours": variant["recommended_spacing_hours"],
        "platform_fit_score": variant["platform_fit_score"],
    }


def write_batch_platform_metadata(campaign_dir: str, batch_name: str = "batch-001",
                                  repo_root: str = ".") -> dict:
    """Reads generated/content-factory/video-renders/<batch_name>/*.json
    (per-variant render metadata) and writes one platform-metadata file per
    variant covering all 4 platforms. Purely local file I/O."""
    render_dir = Path(repo_root) / campaign_dir / "generated/content-factory/video-renders" / batch_name
    out_dir = Path(repo_root) / campaign_dir / "generated/content-factory/platform-metadata" / batch_name
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for render_json in sorted(render_dir.glob("v*.json")):
        variant = json.loads(render_json.read_text(encoding="utf-8"))
        metadata = build_variant_platform_metadata(variant)
        out_path = out_dir / f"{variant['variant_id']}-platform-metadata.json"
        out_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(str(out_path))

    summary = {
        "campaign_code": "coating-protect-2026-07",
        "batch_name": batch_name,
        "variants_covered": len(written),
        "platforms_per_variant": list(fd.FORMATS),
        "files": written,
        "auto_posting_triggered": False,
    }
    summary_path = out_dir / "platform-metadata-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary


# -- Dzen ------------------------------------------------------------------

DZEN_POST_TYPES = (
    "short_recipe", "recipe_roundup", "airfryer_lifehack", "problem_solution",
    "what_to_cook_in_airfryer", "soft_product_ad", "with_form_vs_without",
)

DZEN_TITLES_BY_TYPE = {
    "short_recipe": (
        "Курица в аэрогриле за 20 минут: простой рецепт",
        "Картофель по-деревенски в аэрогриле",
        "Запеканка в аэрогриле без лишней возни",
        "Быстрый ужин в аэрогриле на каждый день",
    ),
    "recipe_roundup": (
        "5 рецептов для аэрогриля на каждый день",
        "Что приготовить в аэрогриле за неделю: подборка",
        "7 простых блюд в аэрогриле для будней",
    ),
    "airfryer_lifehack": (
        "Лайфхак для аэрогриля, который экономит вечер",
        "Как я упростила уборку после аэрогриля",
        "Маленькая хитрость для тех, у кого есть аэрогриль",
    ),
    "problem_solution": (
        "Почему аэрогриль так долго мыть и что с этим делать",
        "Главная проблема аэрогриля, о которой все молчат",
        "Как перестать тратить вечер на мытьё аэрогриля",
    ),
    "what_to_cook_in_airfryer": (
        "Что приготовить в аэрогриле сегодня вечером",
        "Идеи для ужина в аэрогриле, если лень готовить",
        "Что можно запечь в аэрогриле кроме картошки",
    ),
    "soft_product_ad": (
        "Вещь, которая изменила моё отношение к аэрогрилю",
        "Маленькое дополнение к аэрогрилю, о котором стоит знать",
        "Что я докупила к аэрогрилю через месяц использования",
    ),
    "with_form_vs_without": (
        "С формой и без: разница в уборке после аэрогриля",
        "Пробовала готовить с силиконовой формой и без — вот что заметила",
        "До и после: что реально меняет форма для аэрогриля",
    ),
}


def generate_dzen_content_plan(target_count: int = 32) -> dict:
    posts = []
    idx = 0
    while len(posts) < target_count:
        for post_type in DZEN_POST_TYPES:
            if len(posts) >= target_count:
                break
            titles = DZEN_TITLES_BY_TYPE[post_type]
            title = titles[idx % len(titles)]
            posts.append({
                "post_id": f"dzen-{len(posts) + 1:03d}",
                "post_type": post_type,
                "title": title,
                "soft_product_integration": True,
                "aggressive_promise": False,
                "target_length_chars": "1500-3000",
            })
            idx += 1
    return {
        "campaign_code": "coating-protect-2026-07",
        "total_posts": len(posts),
        "post_types": list(DZEN_POST_TYPES),
        "posts": posts,
    }


def write_dzen_content_plan(campaign_dir: str, repo_root: str = ".", out_path=None,
                            target_count: int = 32) -> dict:
    plan = generate_dzen_content_plan(target_count)
    out = Path(out_path) if out_path else (
        Path(repo_root) / campaign_dir / "generated/content-factory/dzen-posts/dzen-content-plan.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    plan["report_path"] = str(out)
    return plan


_RECIPE_BODY_BY_TYPE = {
    "short_recipe": (
        "Ингредиенты: куриные бёдра (3-4 шт), картофель (3-4 шт среднего размера), "
        "соль, чёрный перец, немного растительного масла, чеснок (2-3 зубчика) и "
        "любимые специи для курицы — подойдёт паприка, сушёный тимьян или готовая "
        "смесь для гриля.\n\n"
        "Как готовить: разрежьте картофель на дольки среднего размера, посолите и "
        "сбрызните маслом. Куриные бёдра натрите специями и измельчённым чесноком, "
        "дайте полежать 10-15 минут, пока разогревается аэрогриль. Выложите картофель "
        "и курицу в форму для аэрогриля так, чтобы кусочки не перекрывали друг друга "
        "слишком плотно — тогда всё пропечётся равномерно и получит красивую корочку "
        "со всех сторон.\n\n"
        "Готовьте при 190-200°C около 18-22 минут, один раз перевернув курицу и "
        "встряхнув картофель на середине готовки. Проверить готовность курицы просто: "
        "проколите самый толстый кусок — сок должен быть прозрачным, без розового "
        "оттенка.\n\n"
        "Отдельный плюс такого способа — форма для аэрогриля берёт на себя "
        "практически весь жир и соус, которые выделяются при готовке. Корзина и "
        "решётка аэрогриля остаются заметно чище, чем если готовить без формы "
        "напрямую на решётке. После ужина достаточно ополоснуть форму под водой — "
        "и никакого въевшегося жира на металлических частях аэрогриля."
    ),
    "recipe_roundup": (
        "Если аэрогриль появился у вас недавно, велика вероятность, что вы уже "
        "устали думать, что в нём готовить, кроме картошки фри. Собрала подборку "
        "простых блюд, которые удобно готовить в будни, когда времени и сил на "
        "готовку немного.\n\n"
        "1. Куриные бёдра с овощами — курица, болгарский перец, кабачок и лук "
        "кольцами, всё сбрызнуть маслом и присыпать специями.\n"
        "2. Картофельные дольки по-деревенски — картофель, паприка, чеснок и "
        "немного оливкового масла, 20 минут при 200°C.\n"
        "3. Простая запеканка из остатков вчерашнего ужина — рис или картофель, "
        "немного сыра сверху, 10-12 минут до румяной корочки.\n"
        "4. Овощи гриль с прованскими травами — кабачки, баклажаны, помидоры, "
        "идеально как гарнир или отдельное лёгкое блюдо.\n"
        "5. Куриные крылышки в соусе — маринуются заранее, готовятся 18-20 минут "
        "до хрустящей корочки.\n\n"
        "Общий принцип для всех этих блюд один: используйте форму для аэрогриля, "
        "чтобы жир, соус и маринад оставались внутри неё, а не стекали на решётку "
        "и стенки корзины. Особенно это заметно, если готовите несколько дней "
        "подряд — без формы нагар накапливается быстро, а с ней корзина остаётся "
        "чистой значительно дольше, и мыть приходится только саму форму."
    ),
    "airfryer_lifehack": (
        "Если вы часто готовите в аэрогриле, то наверняка уже знаете: самая "
        "утомительная часть процесса — не сама готовка, а мытьё корзины после неё. "
        "Жир и капли соуса попадают в мелкие отверстия решётки, засыхают там, и "
        "отмыть их обычной губкой почти нереально — приходится или замачивать "
        "надолго, или тереть щёткой с усилием.\n\n"
        "Один простой лайфхак, который реально экономит вечер — использовать "
        "силиконовую форму, которая ставится прямо в корзину аэрогриля перед "
        "готовкой. Она квадратная, с ручками по бокам, чтобы удобно доставать её "
        "горячей, и рифлёным дном — благодаря рёбрам продукты не лежат в собственном "
        "соку, а лишний жир стекает в промежутки между рёбрами.\n\n"
        "Как это работает на практике: вы кладёте продукты не прямо на решётку, а в "
        "форму, и готовите как обычно. Весь жир и соус, которые раньше оседали на "
        "металлических частях аэрогриля, теперь остаются внутри формы. После готовки "
        "решётка и стенки корзины остаются почти сухими, а помыть нужно только саму "
        "форму — она гладкая, и грязь с неё смывается быстро, без долгого замачивания.\n\n"
        "Особенно заметна разница после жирных блюд вроде курицы с кожей или "
        "картофеля с большим количеством масла — именно тогда без формы приходится "
        "тратить на мытьё едва ли не больше времени, чем на саму готовку."
    ),
    "problem_solution": (
        "Проблема знакома, пожалуй, каждому, у кого есть аэрогриль: жир и капли "
        "соуса попадают прямо на решётку и стенки корзины во время готовки, а "
        "потом их приходится долго и муторно отмывать — иногда с замачиванием на "
        "ночь, иногда со специальными средствами для жира.\n\n"
        "Особенно остро это чувствуется после курицы с кожей, жирного мяса или "
        "картофеля с большим количеством масла — тогда нагар на решётке засыхает "
        "почти намертво, и обычная губка с ним не справляется.\n\n"
        "Решение на самом деле довольно простое — нужна прослойка между едой и "
        "самой корзиной аэрогриля. Силиконовая форма, которая ставится внутрь "
        "корзины, берёт весь жир и соус на себя: продукты готовятся в ней, а не "
        "напрямую на решётке. Рифлёное дно формы позволяет лишнему жиру стекать в "
        "промежутки между рёбрами, а не скапливаться под едой.\n\n"
        "После готовки решётка и стенки корзины остаются практически чистыми, и "
        "мыть нужно только саму форму — она гладкая и отмывается быстро, без "
        "долгого оттирания щёткой. Уборка после готовки в итоге занимает в разы "
        "меньше времени, а сама корзина аэрогриля дольше остаётся в приличном "
        "состоянии, без въевшегося нагара."
    ),
    "what_to_cook_in_airfryer": (
        "Если стоите перед аэрогрилем и не знаете, что приготовить сегодня "
        "вечером — вот несколько простых идей, которые не требуют долгой "
        "подготовки и сложных ингредиентов.\n\n"
        "Куриные бёдра с картофелем — классика, которая почти никогда не "
        "подводит: курица получается сочной внутри и с хрустящей корочкой "
        "снаружи, а картофель пропитывается соком от курицы.\n\n"
        "Овощи гриль — кабачки, баклажаны, болгарский перец, немного оливкового "
        "масла и соли. Отличный лёгкий вариант на ужин или гарнир к мясу.\n\n"
        "Небольшая запеканка — если в холодильнике остались варёный рис, "
        "картофель или макароны, можно быстро собрать запеканку с яйцом и сыром.\n\n"
        "Разогрев готовых блюд — аэрогриль отлично разогревает вчерашнюю еду без "
        "лишней сухости, в отличие от микроволновки.\n\n"
        "Отдельный совет для всех этих вариантов: используйте форму для аэрогриля "
        "под основным блюдом. Так жир и соус не растекаются по корзине и решётке, "
        "а после ужина остаётся помыть только форму, а не всю корзину целиком — "
        "это особенно ценно в будний вечер, когда хочется поскорее закончить с "
        "готовкой и уборкой."
    ),
    "soft_product_ad": (
        "Через какое-то время после покупки аэрогриля я поняла, что самое "
        "неудобное в нём — не сама готовка, а уборка после неё. Жир и соус "
        "оседают на решётке и стенках корзины, засыхают там, и отмыть это без "
        "долгого замачивания практически невозможно.\n\n"
        "Перепробовала разные способы: специальные средства для жира, щётки "
        "пожёстче, замачивание на ночь — помогало, но каждый раз уходило много "
        "времени и сил, особенно после плотного ужина, когда меньше всего хочется "
        "стоять у раковины.\n\n"
        "В итоге докупила силиконовую форму для аэрогриля — квадратную, с ручками "
        "по бокам для удобного захвата и рифлёным дном, чтобы лишний жир стекал в "
        "промежутки между рёбрами, а не скапливался под едой. Она ставится прямо в "
        "корзину аэрогриля перед готовкой.\n\n"
        "Использую её для курицы, картофеля, овощей и небольших запеканок — "
        "подходит практически для всего, что обычно готовлю в аэрогриле. Весь жир "
        "теперь остаётся в форме, а не на решётке, и после готовки мою только её — "
        "быстро, без долгого оттирания. Корзина аэрогриля при этом остаётся чище "
        "заметно дольше, чем раньше."
    ),
    "with_form_vs_without": (
        "Решила на практике сравнить: готовка в аэрогриле без формы и с "
        "силиконовой формой — и вот что заметила по итогам нескольких недель.\n\n"
        "Без формы: продукты готовятся прямо на решётке, жир и соус стекают вниз "
        "и оседают на металлических прутьях и стенках корзины. После готовки, "
        "особенно жирных блюд вроде курицы с кожей, решётку приходится отмачивать "
        "и оттирать щёткой — иногда это занимает больше времени, чем сама готовка.\n\n"
        "С формой: продукты готовятся внутри силиконовой формы, а не напрямую на "
        "решётке. Рифлёное дно формы позволяет жиру стекать в промежутки между "
        "рёбрами, но он остаётся внутри формы, а не попадает на решётку и стенки "
        "корзины. После готовки решётка почти сухая, а помыть нужно только саму "
        "форму — она гладкая, и грязь смывается быстро под простой водой.\n\n"
        "Разница особенно заметна после жирных блюд: курицы с кожей, картофеля с "
        "большим количеством масла, блюд с соусом. Без формы уборка после таких "
        "ужинов растягивается надолго, а с формой — занимает буквально пару минут. "
        "Для меня это оказалось той самой мелочью, которая реально меняет "
        "ежедневный опыт использования аэрогриля."
    ),
}


def build_dzen_markdown_post(post: dict) -> str:
    title = post["title"]
    hook = (
        "Знакомая ситуация: включаете аэрогриль, готовите вкусный ужин, а потом "
        "полчаса, а то и дольше, отмываете корзину от жира и нагара? Если да — "
        "этот пост как раз для вас."
    )
    body = _RECIPE_BODY_BY_TYPE.get(post["post_type"], _RECIPE_BODY_BY_TYPE["airfryer_lifehack"])
    outro = (
        "\n\nЕсли вы уже сталкивались с этой проблемой, наверняка пробовали разные "
        "способы её решить — от специальных средств для жира до долгого "
        "замачивания решётки на ночь. Работает, но отнимает время и силы, которых "
        "после готовки обычно и так немного. Именно поэтому многие постепенно "
        "переходят на более простой вариант: прослойку между едой и корзиной, "
        "которая берёт основную часть жира и соуса на себя."
    )
    cta = (
        "Если тоже устали каждый раз отмывать корзину аэрогриля — попробуйте "
        "силиконовую форму для аэрогриля: она подходит для курицы, картофеля, "
        "овощей и запеканок, а мыть после готовки нужно только её, а не всю "
        "корзину целиком. Подробности и где купить — в описании."
    )

    md = f"# {title}\n\n{hook}\n\n{body}{outro}\n\n{cta}\n"
    return md


def write_dzen_batch(campaign_dir: str, plan: dict, count: int = 10,
                     repo_root: str = ".", batch_name: str = "batch-001") -> dict:
    out_dir = Path(repo_root) / campaign_dir / "generated/content-factory/dzen-posts" / batch_name
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for post in plan["posts"][:count]:
        md = build_dzen_markdown_post(post)
        out_path = out_dir / f"{post['post_id']}-{post['post_type']}.md"
        out_path.write_text(md, encoding="utf-8")
        written.append({"post_id": post["post_id"], "path": str(out_path), "chars": len(md)})

    summary = {
        "campaign_code": "coating-protect-2026-07",
        "batch_name": batch_name,
        "posts_written": len(written),
        "files": written,
        "auto_posting_triggered": False,
    }
    summary_path = out_dir / "dzen-batch-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary
