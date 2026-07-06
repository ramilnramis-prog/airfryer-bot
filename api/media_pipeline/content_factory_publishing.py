"""First 14-day publishing queue: SELECTS from the already-rendered 90 MP4s
and 40 Dzen posts (content-queue.json) -- generates NOTHING new. Pure local
file I/O (selection, copying, CSV/HTML writing) -- no network, no OpenAI/
Higgsfield calls, no auto-posting anywhere in this module."""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from . import content_factory_data as fd
from . import content_factory_planner as planner

NUM_DAYS = 14
VIDEOS_PER_DAY = 3
VIDEO_TIMES = ("12:30", "16:30", "20:30")
DZEN_TIMES = ("10:30", "19:00")

FORBIDDEN_PHRASES = ("100% чисто", "никогда не пачкается", "гарантированно",
                    "идеально для всех аэрогрилей")

# creative_bucket A-E used for daily rotation + the creative-testing-matrix.
NEW_ANGLE_TO_BUCKET = {
    "pain_problem": "A", "recipe": "B",
    "meme_conversational": "C", "fast_hype": "D",
}
STYLE_TO_BUCKET = {
    "clean_ad": "E", "comparison_style": "E",
    "ugc_style": "A", "problem_solution": "A", "before_after": "A",
    "recipe_style": "B", "cozy_kitchen": "B",
    "meme_style": "C",
    "fast_cuts": "D", "animated_caption_style": "D",
}
BUCKET_LABELS = {
    "A": "pain_problem", "B": "recipe", "C": "meme_conversational",
    "D": "fast_hype", "E": "product_beauty_clean",
}

# 14-day bucket rotation: 3 distinct buckets/day, cycling A/B/C/D evenly,
# with the scarce bucket E (only 2 available videos, both from batch-001)
# inserted twice, spaced apart.
DAY_BUCKET_PLAN = [
    ["A", "B", "C"], ["B", "C", "D"], ["A", "C", "D"], ["A", "B", "D"],
    ["A", "B", "C"], ["B", "C", "D"], ["C", "D", "E"], ["A", "B", "D"],
    ["A", "B", "C"], ["B", "C", "D"], ["A", "C", "D"], ["A", "B", "D"],
    ["A", "B", "C"], ["B", "C", "E"],
]
assert len(DAY_BUCKET_PLAN) == NUM_DAYS

# Dzen theme rotation: recipe / lifehack / problem_solution / conversational
DZEN_THEME_PLAN = [
    ("recipe", "lifehack", "problem_solution", "conversational")[i % 4]
    for i in range(NUM_DAYS)
]

DZEN_THEME_POST_TYPES = {
    "recipe": ("short_recipe", "recipe_roundup", "what_to_cook_in_airfryer"),
    "lifehack": ("airfryer_lifehack",),
    "problem_solution": ("problem_solution",),
    "conversational": ("lifestyle_conversational", "soft_product_ad", "with_form_vs_without"),
}


def creative_bucket(render_meta: dict) -> str:
    angle = render_meta.get("creative_angle", "")
    if angle in NEW_ANGLE_TO_BUCKET:
        return NEW_ANGLE_TO_BUCKET[angle]
    return STYLE_TO_BUCKET.get(render_meta.get("style_type", ""), "A")


def passes_quality_filter(render_meta: dict) -> tuple:
    """(ok: bool, reasons: list[str]) -- never raises, always returns a
    verdict so the selection algorithm can just skip failing candidates."""
    reasons = []
    if render_meta.get("render_status") != "rendered":
        reasons.append("mp4_not_rendered")
    mp4_path = render_meta.get("mp4_path")
    if not mp4_path or not Path(mp4_path).is_file():
        reasons.append("mp4_file_missing")
    duration = render_meta.get("duration_target_seconds", 0)
    if not (12 <= duration <= 25):
        reasons.append(f"duration_out_of_range:{duration}")
    size = render_meta.get("target_size")
    if size != [720, 1280]:
        reasons.append(f"wrong_target_size:{size}")
    if render_meta.get("publish_status", "not_published") != "not_published":
        reasons.append("already_published")
    text_blob = " ".join([
        render_meta.get("hook_text", ""), render_meta.get("CTA", ""),
        render_meta.get("voiceover_text", ""),
        " ".join(render_meta.get("on_screen_text", [])),
    ]).lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in text_blob:
            reasons.append(f"forbidden_claim:{phrase}")
    return (len(reasons) == 0, reasons)


def _load_all_video_metas(campaign_dir: str, repo_root: str = ".") -> list:
    base = Path(repo_root) / campaign_dir / "generated/content-factory/video-renders"
    metas = []
    if not base.is_dir():
        return metas
    for batch_dir in sorted(base.iterdir()):
        if not batch_dir.is_dir():
            continue
        for f in sorted(batch_dir.glob("*.json")):
            if f.name == "batch-summary.json":
                continue
            meta = json.loads(f.read_text(encoding="utf-8"))
            meta["_batch"] = batch_dir.name
            meta["_render_json_path"] = str(f)
            metas.append(meta)
    return metas


def _load_all_dzen_posts(campaign_dir: str, repo_root: str = ".") -> list:
    base = Path(repo_root) / campaign_dir / "generated/content-factory/dzen-posts"
    posts = []
    if not base.is_dir():
        return posts
    for batch_dir in sorted(base.iterdir()):
        if not batch_dir.is_dir():
            continue
        for f in sorted(batch_dir.glob("*.md")):
            name = f.stem  # e.g. "batch-002-dzen-001-problem_solution"
            post_type = name.split("-")[-1] if "-" in name else "unknown"
            # post_type is the LAST dash-separated token in the filename by
            # our own write_dzen_batch*/write_dzen_batch_for_angle naming
            # convention (<post_id>-<post_type>.md); post_type itself may
            # contain underscores but not dashes, so this is safe.
            text = f.read_text(encoding="utf-8")
            posts.append({
                "post_id": name.rsplit("-" + post_type, 1)[0] if post_type != "unknown" else name,
                "post_type": post_type,
                "path": str(f).replace("\\", "/"),
                "title": text.splitlines()[0].lstrip("# ").strip(),
                "chars": len(text),
                "_batch": batch_dir.name,
            })
    return posts


def _platform_metadata_for(campaign_dir: str, batch: str, variant_id: str,
                           repo_root: str = ".") -> dict or None:
    path = (Path(repo_root) / campaign_dir / "generated/content-factory/platform-metadata"
           / batch / f"{variant_id}-platform-metadata.json")
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def build_first_14_days_plan(campaign_dir: str, repo_root: str = ".") -> dict:
    all_videos = _load_all_video_metas(campaign_dir, repo_root)
    all_dzen = _load_all_dzen_posts(campaign_dir, repo_root)

    # Bucket pools: prefer the abundant angle-specific batches (002-005)
    # before dipping into the smaller batch-001 pool, keeping each pool's
    # own natural (sorted) order.
    buckets = {"A": [], "B": [], "C": [], "D": [], "E": []}
    for meta in all_videos:
        ok, _reasons = passes_quality_filter(meta)
        if not ok:
            continue
        buckets[creative_bucket(meta)].append(meta)

    for key in buckets:
        buckets[key].sort(key=lambda m: (m["_batch"] != {"A": "batch-002", "B": "batch-003",
                                                          "C": "batch-004", "D": "batch-005"}.get(key, ""),
                                         m["variant_id"]))

    dzen_pools = {theme: [] for theme in DZEN_THEME_POST_TYPES}
    for post in all_dzen:
        for theme, types in DZEN_THEME_POST_TYPES.items():
            if post["post_type"] in types:
                dzen_pools[theme].append(post)
                break
    for theme in dzen_pools:
        dzen_pools[theme].sort(key=lambda p: p["post_id"])

    used_video_ids = set()
    used_dzen_ids = set()
    days = []
    skipped_candidates = []

    for day_num in range(1, NUM_DAYS + 1):
        day_buckets = DAY_BUCKET_PLAN[day_num - 1]
        day_videos = []
        day_hooks = set()
        day_batches_count = {}
        day_styles = set()

        for slot_idx, bucket in enumerate(day_buckets):
            chosen = None
            for candidate in buckets[bucket]:
                vid = candidate["variant_id"]
                if vid in used_video_ids:
                    continue
                if candidate["hook_text"] in day_hooks:
                    continue
                if candidate["style_type"] in day_styles:
                    continue
                if day_batches_count.get(candidate["_batch"], 0) >= 2:
                    continue  # never let one batch dominate (>=3) a single day
                chosen = candidate
                break
            if chosen is None:
                skipped_candidates.append({"day": day_num, "bucket": bucket,
                                          "reason": "no_eligible_candidate_left"})
                continue

            used_video_ids.add(chosen["variant_id"])
            day_hooks.add(chosen["hook_text"])
            day_styles.add(chosen["style_type"])
            day_batches_count[chosen["_batch"]] = day_batches_count.get(chosen["_batch"], 0) + 1

            platform_meta = _platform_metadata_for(campaign_dir, chosen["_batch"],
                                                    chosen["variant_id"], repo_root)
            native = chosen["format"]
            platform_entry = platform_meta["platforms"][native] if platform_meta else {}

            day_videos.append({
                "slot": slot_idx + 1,
                "posting_time": VIDEO_TIMES[slot_idx],
                "variant_id": chosen["variant_id"],
                "batch": chosen["_batch"],
                "creative_angle": chosen.get("creative_angle"),
                "creative_bucket": bucket,
                "bucket_label": BUCKET_LABELS[bucket],
                "hook": chosen["hook_text"],
                "style_type": chosen["style_type"],
                "file_path": chosen["mp4_path"],
                "duration_target_seconds": chosen["duration_target_seconds"],
                "platforms": list(fd.FORMATS),
                "native_platform": native,
                "title": platform_entry.get("title", chosen["hook_text"]),
                "caption": platform_entry.get("caption", ""),
                "hashtags": platform_entry.get("hashtags", []),
                "CTA": chosen.get("CTA") or platform_entry.get("CTA", ""),
                "owner_status": "not_reviewed",
                "publish_status": "not_published",
            })

        theme = DZEN_THEME_PLAN[day_num - 1]
        dzen_time = DZEN_TIMES[day_num % 2]
        chosen_dzen = None
        for candidate in dzen_pools[theme]:
            if candidate["post_id"] not in used_dzen_ids:
                chosen_dzen = candidate
                break
        if chosen_dzen is None:
            # fall back to ANY unused post from ANY theme rather than skip
            # the day entirely.
            for theme_pool in dzen_pools.values():
                for candidate in theme_pool:
                    if candidate["post_id"] not in used_dzen_ids:
                        chosen_dzen = candidate
                        break
                if chosen_dzen:
                    break

        day_dzen = None
        if chosen_dzen:
            used_dzen_ids.add(chosen_dzen["post_id"])
            day_dzen = {
                "posting_time": dzen_time,
                "post_id": chosen_dzen["post_id"],
                "batch": chosen_dzen["_batch"],
                "theme": theme,
                "post_type": chosen_dzen["post_type"],
                "title": chosen_dzen["title"],
                "file_path": chosen_dzen["path"],
                "chars": chosen_dzen["chars"],
                "owner_status": "not_reviewed",
                "publish_status": "not_published",
            }

        days.append({
            "day": day_num,
            "videos": day_videos,
            "dzen_post": day_dzen,
        })

    plan = {
        "campaign_code": "coating-protect-2026-07",
        "num_days": NUM_DAYS,
        "videos_per_day": VIDEOS_PER_DAY,
        "video_posting_times": list(VIDEO_TIMES),
        "dzen_posting_times": list(DZEN_TIMES),
        "days": days,
        "total_videos_selected": sum(len(d["videos"]) for d in days),
        "total_dzen_selected": sum(1 for d in days if d["dzen_post"]),
        "skipped_candidates": skipped_candidates,
        "openai_calls": 0,
        "higgsfield_calls": 0,
        "external_video_api_calls": 0,
        "auto_posting_triggered": False,
        "note": ("Selected ONLY from already-rendered assets (content-queue.json) -- "
                "no new MP4/Dzen generation happened while building this plan."),
    }
    return plan


def write_first_14_days_plan(campaign_dir: str, repo_root: str = ".") -> dict:
    plan = build_first_14_days_plan(campaign_dir, repo_root)
    out_dir = Path(repo_root) / campaign_dir / "generated/content-factory/publishing"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "first-14-days-publishing-plan.json"
    json_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = ["# First 14 Days Publishing Plan -- coating-protect-2026-07", ""]
    for day in plan["days"]:
        md_lines.append(f"## Day {day['day']:02d}")
        for v in day["videos"]:
            md_lines.append(f"- **{v['posting_time']}** [{v['bucket_label']}] "
                           f"`{v['variant_id']}` (batch {v['batch']}) -- {v['hook']}")
            md_lines.append(f"  - file: `{v['file_path']}`")
            md_lines.append(f"  - CTA: {v['CTA']}")
        if day["dzen_post"]:
            dp = day["dzen_post"]
            md_lines.append(f"- **{dp['posting_time']}** [Dzen/{dp['theme']}] "
                           f"`{dp['post_id']}` -- {dp['title']}")
            md_lines.append(f"  - file: `{dp['file_path']}`")
        md_lines.append("")
    md_path = out_dir / "first-14-days-publishing-plan.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    plan["json_path"] = str(json_path)
    plan["md_path"] = str(md_path)
    return plan


def _slug(text: str) -> str:
    mapping = {"pain_problem": "pain-problem", "recipe": "recipe",
              "meme_conversational": "meme", "fast_hype": "hype",
              "product_beauty_clean": "beauty"}
    return mapping.get(text, text.replace("_", "-"))


def copy_upload_ready_files(campaign_dir: str, plan: dict, repo_root: str = ".") -> dict:
    """Copies (never moves/deletes) the selected MP4s + Dzen markdown +
    platform-metadata JSON into publishing/upload-ready/day-NN/{videos,
    dzen,metadata}/ with a friendly renamed convention. Originals are
    untouched."""
    base_out = Path(repo_root) / campaign_dir / "generated/content-factory/publishing/upload-ready"
    copied = []

    for day in plan["days"]:
        day_dir = base_out / f"day-{day['day']:02d}"
        videos_dir = day_dir / "videos"
        dzen_dir = day_dir / "dzen"
        metadata_dir = day_dir / "metadata"
        for d in (videos_dir, dzen_dir, metadata_dir):
            d.mkdir(parents=True, exist_ok=True)

        for v in day["videos"]:
            src = Path(v["file_path"])
            if not src.is_file():
                continue
            angle_slug = _slug(v["bucket_label"])
            dest_name = f"day-{day['day']:02d}-video-{v['slot']:02d}-{angle_slug}.mp4"
            dest = videos_dir / dest_name
            shutil.copy2(src, dest)
            copied.append(str(dest))

            meta_dest = metadata_dir / f"day-{day['day']:02d}-video-{v['slot']:02d}-{angle_slug}-metadata.json"
            meta_dest.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
            copied.append(str(meta_dest))

        if day["dzen_post"]:
            dp = day["dzen_post"]
            src = Path(dp["file_path"])
            if src.is_file():
                dest_name = f"day-{day['day']:02d}-dzen-{_slug(dp['theme'])}.md"
                dest = dzen_dir / dest_name
                shutil.copy2(src, dest)
                copied.append(str(dest))

                meta_dest = metadata_dir / f"day-{day['day']:02d}-dzen-{_slug(dp['theme'])}-metadata.json"
                meta_dest.write_text(json.dumps(dp, ensure_ascii=False, indent=2), encoding="utf-8")
                copied.append(str(meta_dest))

    summary = {
        "campaign_code": "coating-protect-2026-07",
        "upload_ready_dir": str(base_out),
        "files_copied": len(copied),
        "files": copied,
        "originals_modified": False,
    }
    return summary


CHECKLIST_COLUMNS = ("day", "time", "platform", "file", "title", "caption", "hashtags",
                    "CTA", "status", "link_after_publish", "views_24h", "likes_24h",
                    "comments_24h", "saves_24h", "orders_note", "owner_notes")


def _empty_metrics_row(day, time_, platform, file_, title, caption, hashtags, cta, status) -> dict:
    return {
        "day": day, "time": time_, "platform": platform, "file": file_, "title": title,
        "caption": caption, "hashtags": hashtags, "CTA": cta, "status": status,
        "link_after_publish": "", "views_24h": "", "likes_24h": "", "comments_24h": "",
        "saves_24h": "", "orders_note": "", "owner_notes": "",
    }


def write_platform_checklists(campaign_dir: str, plan: dict, repo_root: str = ".") -> dict:
    """One row per (video, platform) pair for the 4 platform-specific
    checklists (each video is eligible for cross-posting to all 4
    platforms -- metadata already exists for all 4), one row per Dzen post
    for dzen-checklist.csv, and master-publishing-checklist.csv unions all
    of the above. Metrics columns (views_24h etc.) are left blank for the
    owner to fill in after manual publishing."""
    checklists_dir = Path(repo_root) / campaign_dir / "generated/content-factory/publishing/checklists"
    checklists_dir.mkdir(parents=True, exist_ok=True)

    platform_rows = {p: [] for p in fd.FORMATS}
    dzen_rows = []
    master_rows = []

    for day in plan["days"]:
        for v in day["videos"]:
            platform_meta = _platform_metadata_for(campaign_dir, v["batch"], v["variant_id"], repo_root)
            for platform in fd.FORMATS:
                entry = (platform_meta["platforms"][platform]
                        if platform_meta and platform in platform_meta.get("platforms", {}) else {})
                row = _empty_metrics_row(
                    day["day"], v["posting_time"], platform, v["file_path"],
                    entry.get("title", v["title"]), entry.get("caption", v["caption"]),
                    " ".join(entry.get("hashtags", v["hashtags"])),
                    entry.get("CTA", v["CTA"]), v["owner_status"],
                )
                platform_rows[platform].append(row)
                master_rows.append(row)

        if day["dzen_post"]:
            dp = day["dzen_post"]
            row = _empty_metrics_row(day["day"], dp["posting_time"], "dzen", dp["file_path"],
                                     dp["title"], "", "", "", dp["owner_status"])
            dzen_rows.append(row)
            master_rows.append(row)

    def _write_csv(path, rows):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CHECKLIST_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    file_map = {
        "youtube-shorts-checklist.csv": platform_rows["youtube_shorts"],
        "instagram-reels-checklist.csv": platform_rows["instagram_reels"],
        "tiktok-checklist.csv": platform_rows["tiktok"],
        "vk-clips-checklist.csv": platform_rows["vk_clips"],
        "dzen-checklist.csv": dzen_rows,
        "master-publishing-checklist.csv": master_rows,
    }
    written = {}
    for filename, rows in file_map.items():
        path = checklists_dir / filename
        _write_csv(path, rows)
        written[filename] = {"path": str(path), "rows": len(rows)}

    return {"checklists_dir": str(checklists_dir), "files": written}


CREATIVE_TESTING_GROUPS = {
    "A": {
        "label": "Pain / cleaning problem",
        "creative_angle": "pain_problem",
        "hook_type": "боль/проблема -- узнаваемая бытовая ситуация с грязной, "
                    "жирной корзиной аэрогриля после готовки",
        "first_3_seconds": "крупный план грязной/жирной корзины (или губка/мойка в кадре) "
                          "с текстом-хуком поверх, например 'Опять мыть корзину аэрогриля?'",
        "CTA": "Добавь в корзину, пока не забыл / Смотри артикул в описании",
        "product_benefit": "форма принимает жир и соус на себя -- после готовки проще убрать, "
                          "меньше грязи в корзине",
        "style_types": ("problem_solution", "before_after", "ugc_style"),
        "expected_audience_reaction": ("узнавание проблемы, эмоциональный отклик "
                                       "('это прямо про меня'), высокий save/share потенциал"),
    },
    "B": {
        "label": "Recipe / tasty food",
        "creative_angle": "recipe",
        "hook_type": "полезность/рецепт -- аппетитная еда и конкретный практический результат",
        "first_3_seconds": "крупный план готового блюда (курица/картофель) или формы с "
                          "продуктами, хук в духе 'Быстрый ужин в аэрогриле'",
        "CTA": "Смотри артикул в описании / Сохрани себе на вечер",
        "product_benefit": "подходит для аэрогриля, запекания, картофеля, курицы, запеканок; "
                          "форма принимает жир на себя, готовка + уборка проще",
        "style_types": ("recipe_style", "clean_ad", "cozy_kitchen"),
        "expected_audience_reaction": ("аппетитный отклик, интерес к рецепту, средний-высокий "
                                       "save потенциал (люди сохраняют рецепты)"),
    },
    "C": {
        "label": "Meme / relatable",
        "creative_angle": "meme_conversational",
        "hook_type": "мем/разговорный -- ироничная бытовая ситуация, узнаваемый юмор",
        "first_3_seconds": "текст-хук в разговорном тоне поверх сцены, например "
                          "'Аэрогриль: готовит сам. Мыть — тебе.'",
        "CTA": "Сохрани, если есть аэрогриль / Кинь другу, у кого есть аэрогриль",
        "product_benefit": "форма упрощает то самое неудобство, над которым шутит ролик -- "
                          "мытьё корзины",
        "style_types": ("meme_style", "ugc_style"),
        "expected_audience_reaction": ("смех/узнавание, высокий share потенциал (пересылают "
                                       "друзьям), риск 'кринжа' при переигрывании тона"),
    },
    "D": {
        "label": "Fast hype / curiosity",
        "creative_angle": "fast_hype",
        "hook_type": "любопытство/hype -- прямое обращение, императив, интрига в первые секунды",
        "first_3_seconds": "punch zoom + текст в духе 'Стоп. Если у тебя есть аэрогриль — "
                          "смотри.' в первые 2 секунды, быстрые смены сцен",
        "CTA": "Смотри артикул в описании / Забери себе, чтобы не мыть корзину каждый раз",
        "product_benefit": "удобнее готовить, меньше грязи -- поданное энергично, без сильных claims",
        "style_types": ("fast_cuts", "animated_caption_style", "comparison_style"),
        "expected_audience_reaction": ("быстрый первый впечатление/удержание внимания, высокий "
                                       "completion rate при удачном хуке, но выше риск скролла "
                                       "мимо при слабом первом кадре"),
    },
    "E": {
        "label": "Product beauty / clean CTA",
        "creative_angle": "product_beauty_clean",
        "hook_type": "продуктовая красота -- чистая, спокойная демонстрация формы без давления",
        "first_3_seconds": "крупный план чистой формы, спокойная композиция, минимум текста",
        "CTA": "Ссылка в описании профиля / Смотри артикул в описании",
        "product_benefit": "корзина остаётся чище дольше -- итоговый чистый вид продукта как "
                          "визуальное обещание результата",
        "style_types": ("clean_ad", "comparison_style"),
        "expected_audience_reaction": ("спокойное доверие, подходит как closing/CTA кадр в "
                                       "конце воронки, менее вирусный, более конверсионный"),
    },
}


def _avg_platform_fit(style_types: tuple) -> dict:
    result = {}
    for platform in fd.FORMATS:
        scores = [planner._FORMAT_STYLE_FIT[platform][s] for s in style_types
                 if s in planner._FORMAT_STYLE_FIT[platform]]
        result[platform] = round(sum(scores) / len(scores), 1) if scores else None
    return result


def build_creative_testing_matrix() -> dict:
    groups = []
    for key, g in CREATIVE_TESTING_GROUPS.items():
        groups.append({
            "group": key,
            "label": g["label"],
            "creative_angle": g["creative_angle"],
            "hook_type": g["hook_type"],
            "first_3_seconds": g["first_3_seconds"],
            "CTA": g["CTA"],
            "product_benefit": g["product_benefit"],
            "style_types": list(g["style_types"]),
            "platform_fit": _avg_platform_fit(g["style_types"]),
            "expected_audience_reaction": g["expected_audience_reaction"],
        })
    return {
        "campaign_code": "coating-protect-2026-07",
        "groups": groups,
        "note": ("Platform fit scores are averaged from the existing per-style "
                "platform_fit_score heuristic (content_factory_planner._FORMAT_STYLE_FIT) "
                "-- no new scoring model, no external API involved."),
    }


def write_creative_testing_matrix(campaign_dir: str, repo_root: str = ".") -> dict:
    matrix = build_creative_testing_matrix()
    out_dir = Path(repo_root) / campaign_dir / "generated/content-factory/publishing"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "creative-testing-matrix.json"
    json_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = ["# Creative Testing Matrix -- coating-protect-2026-07", ""]
    for g in matrix["groups"]:
        md_lines.append(f"## Group {g['group']}: {g['label']}")
        md_lines.append(f"- **creative_angle**: {g['creative_angle']}")
        md_lines.append(f"- **hook_type**: {g['hook_type']}")
        md_lines.append(f"- **first_3_seconds**: {g['first_3_seconds']}")
        md_lines.append(f"- **CTA**: {g['CTA']}")
        md_lines.append(f"- **product_benefit**: {g['product_benefit']}")
        md_lines.append(f"- **style_types**: {', '.join(g['style_types'])}")
        md_lines.append(f"- **platform_fit**: {g['platform_fit']}")
        md_lines.append(f"- **expected_audience_reaction**: {g['expected_audience_reaction']}")
        md_lines.append("")
    md_path = out_dir / "creative-testing-matrix.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    matrix["json_path"] = str(json_path)
    matrix["md_path"] = str(md_path)
    return matrix
