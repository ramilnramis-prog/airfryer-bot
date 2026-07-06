"""Manual performance-tracking loop for the content factory: builds the
master tracker + daily input files the owner fills in BY HAND after
publishing, and a local analyzer that reads those manually-entered metrics
back in. No network, no OpenAI/Higgsfield/external API calls anywhere in
this module, no auto-posting -- publishing stays 100% manual."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from . import content_factory_data as fd
from . import content_factory_publishing as pub

TRACKER_COLUMNS = (
    "day", "planned_time", "platform", "asset_type", "asset_path", "variant_id",
    "batch", "creative_angle", "style_type", "hook_text", "title", "caption",
    "hashtags", "CTA", "publish_status", "published_url", "published_at",
    "views_1h", "views_3h", "views_24h", "views_48h", "likes_24h", "comments_24h",
    "shares_24h", "saves_24h", "clicks_24h", "orders_note", "revenue_note",
    "owner_rating", "owner_notes", "decision",
)

DAILY_INPUT_COLUMNS = (
    "day", "planned_time", "platform", "asset_type", "file", "title", "hook_text",
    "published_url", "views_24h", "likes_24h", "comments_24h", "saves_24h",
    "clicks_24h", "orders_note", "owner_notes",
)

DECISION_VALUES = ("keep", "remake", "reject", "unknown")


def _platform_entry(campaign_dir: str, batch: str, variant_id: str, platform: str,
                    repo_root: str = ".") -> dict:
    path = (Path(repo_root) / campaign_dir / "generated/content-factory/platform-metadata"
           / batch / f"{variant_id}-platform-metadata.json")
    if not path.is_file():
        return {}
    meta = json.loads(path.read_text(encoding="utf-8"))
    return meta.get("platforms", {}).get(platform, {})


def build_master_tracker_rows(campaign_dir: str, repo_root: str = ".") -> list:
    """182 rows (42 videos x 4 platforms + 14 dzen posts) mirroring
    master-publishing-checklist.csv, extended with the full tracking
    columns the owner fills in by hand after publishing."""
    plan_path = (Path(repo_root) / campaign_dir /
                "generated/content-factory/publishing/first-14-days-publishing-plan.json")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    rows = []
    for day in plan["days"]:
        for v in day["videos"]:
            for platform in fd.FORMATS:
                entry = _platform_entry(campaign_dir, v["batch"], v["variant_id"], platform, repo_root)
                rows.append({
                    "day": day["day"], "planned_time": v["posting_time"], "platform": platform,
                    "asset_type": "video", "asset_path": v["file_path"],
                    "variant_id": v["variant_id"], "batch": v["batch"],
                    "creative_angle": v.get("creative_angle") or "", "style_type": v["style_type"],
                    "hook_text": v["hook"], "title": entry.get("title", v["title"]),
                    "caption": entry.get("caption", v["caption"]),
                    "hashtags": " ".join(entry.get("hashtags", v["hashtags"])),
                    "CTA": entry.get("CTA", v["CTA"]), "publish_status": "not_published",
                    "published_url": "", "published_at": "",
                    "views_1h": "", "views_3h": "", "views_24h": "", "views_48h": "",
                    "likes_24h": "", "comments_24h": "", "shares_24h": "", "saves_24h": "",
                    "clicks_24h": "", "orders_note": "", "revenue_note": "",
                    "owner_rating": "", "owner_notes": "", "decision": "unknown",
                })
        if day["dzen_post"]:
            dp = day["dzen_post"]
            rows.append({
                "day": day["day"], "planned_time": dp["posting_time"], "platform": "dzen",
                "asset_type": "dzen", "asset_path": dp["file_path"],
                "variant_id": dp["post_id"], "batch": dp["batch"],
                "creative_angle": dp.get("theme", ""), "style_type": dp.get("post_type", ""),
                "hook_text": "", "title": dp["title"], "caption": "", "hashtags": "", "CTA": "",
                "publish_status": "not_published", "published_url": "", "published_at": "",
                "views_1h": "", "views_3h": "", "views_24h": "", "views_48h": "",
                "likes_24h": "", "comments_24h": "", "shares_24h": "", "saves_24h": "",
                "clicks_24h": "", "orders_note": "", "revenue_note": "",
                "owner_rating": "", "owner_notes": "", "decision": "unknown",
            })
    return rows


def write_master_tracker(campaign_dir: str, repo_root: str = ".") -> dict:
    rows = build_master_tracker_rows(campaign_dir, repo_root)
    out_dir = Path(repo_root) / campaign_dir / "generated/content-factory/performance-tracking"
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "master-performance-tracker.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRACKER_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    json_path = out_dir / "master-performance-tracker.json"
    doc = {
        "campaign_code": "coating-protect-2026-07",
        "total_rows": len(rows),
        "columns": list(TRACKER_COLUMNS),
        "rows": rows,
        "openai_calls": 0, "higgsfield_calls": 0, "auto_posting_triggered": False,
    }
    json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"csv_path": str(csv_path), "json_path": str(json_path), "total_rows": len(rows)}


def write_daily_input_files(campaign_dir: str, repo_root: str = ".") -> dict:
    """One CSV per day, containing ONLY that day's rows (3 videos x 4
    platforms + 1 dzen post = 13 rows/day), with owner-friendly manual-fill
    columns only (no bulky caption/hashtags noise)."""
    rows = build_master_tracker_rows(campaign_dir, repo_root)
    out_dir = (Path(repo_root) / campaign_dir /
              "generated/content-factory/performance-tracking/daily-input")
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for day_num in range(1, pub.NUM_DAYS + 1):
        day_rows = [r for r in rows if r["day"] == day_num]
        daily_rows = [{
            "day": r["day"], "planned_time": r["planned_time"], "platform": r["platform"],
            "asset_type": r["asset_type"], "file": r["asset_path"], "title": r["title"],
            "hook_text": r["hook_text"], "published_url": "", "views_24h": "",
            "likes_24h": "", "comments_24h": "", "saves_24h": "", "clicks_24h": "",
            "orders_note": "", "owner_notes": "",
        } for r in day_rows]

        path = out_dir / f"day-{day_num:02d}-metrics.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=DAILY_INPUT_COLUMNS)
            writer.writeheader()
            writer.writerows(daily_rows)
        written.append({"day": day_num, "path": str(path), "rows": len(daily_rows)})

    return {"daily_input_dir": str(out_dir), "files": written}


# -- analyzer ---------------------------------------------------------------

_METRIC_FIELDS_FROM_DAILY = ("published_url", "views_24h", "likes_24h", "comments_24h",
                            "saves_24h", "clicks_24h", "orders_note", "owner_notes")


def _read_csv_rows(path: Path) -> list:
    if not path.is_file():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _to_number(value) -> float or None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def merge_tracker_with_daily_input(campaign_dir: str, repo_root: str = ".") -> list:
    """Master tracker rows (context: hook/angle/style/platform) overlaid
    with whatever the owner has manually filled into daily-input/*.csv so
    far. Rows the owner hasn't touched yet keep their blank tracker values
    -- this never fails on missing/partial data."""
    tracker_dir = Path(repo_root) / campaign_dir / "generated/content-factory/performance-tracking"
    tracker_rows = _read_csv_rows(tracker_dir / "master-performance-tracker.csv")
    daily_dir = tracker_dir / "daily-input"

    daily_lookup = {}
    for day_num in range(1, pub.NUM_DAYS + 1):
        for row in _read_csv_rows(daily_dir / f"day-{day_num:02d}-metrics.csv"):
            key = (row.get("day"), row.get("platform"), row.get("file"))
            daily_lookup[key] = row

    merged = []
    for row in tracker_rows:
        key = (row.get("day"), row.get("platform"), row.get("asset_path"))
        daily_row = daily_lookup.get(key)
        merged_row = dict(row)
        if daily_row:
            for field in _METRIC_FIELDS_FROM_DAILY:
                value = daily_row.get(field, "")
                if value:
                    merged_row[field] = value
        merged.append(merged_row)
    return merged


def _engagement_rate(row: dict) -> float or None:
    views = _to_number(row.get("views_24h"))
    if not views or views <= 0:
        return None
    parts = [_to_number(row.get(k)) or 0 for k in ("likes_24h", "comments_24h", "shares_24h", "saves_24h")]
    return sum(parts) / views


def _has_any_metric_data(rows: list) -> bool:
    return any(_to_number(r.get("views_24h")) is not None for r in rows)


def _group_average(rows: list, key: str, metric_fn) -> list:
    buckets = {}
    for row in rows:
        group_key = row.get(key) or "unknown"
        val = metric_fn(row)
        if val is None:
            continue
        buckets.setdefault(group_key, []).append(val)
    out = [{"key": k, "avg": round(sum(v) / len(v), 4), "n": len(v)} for k, v in buckets.items()]
    out.sort(key=lambda x: x["avg"], reverse=True)
    return out


def analyze_performance(campaign_dir: str, repo_root: str = ".") -> dict:
    rows = merge_tracker_with_daily_input(campaign_dir, repo_root)
    video_rows = [r for r in rows if r.get("asset_type") == "video"]

    if not rows or not _has_any_metric_data(rows):
        return {
            "campaign_code": "coating-protect-2026-07",
            "has_data": False,
            "note": "ожидаются метрики после публикаций -- заполните daily-input/*.csv, "
                    "затем запустите анализ снова.",
            "best_videos_by_views_24h": [], "best_videos_by_engagement_rate": [],
            "best_hooks": [], "best_creative_angle": [], "best_style_type": [],
            "best_platform": [], "weak_videos": [], "repeated_patterns": [],
            "recommendations_for_next_batch": [
                "Дождитесь первых 24-48 часов после публикации, затем занесите метрики "
                "в daily-input/*.csv и запустите analyze-content-performance снова."
            ],
            "openai_calls": 0, "higgsfield_calls": 0, "external_api_calls": 0,
        }

    with_views = [r for r in video_rows if _to_number(r.get("views_24h")) is not None]
    best_by_views = sorted(with_views, key=lambda r: _to_number(r["views_24h"]), reverse=True)

    with_engagement = [(r, _engagement_rate(r)) for r in video_rows]
    with_engagement = [(r, e) for r, e in with_engagement if e is not None]
    with_engagement.sort(key=lambda pair: pair[1], reverse=True)

    def _video_summary(r, extra=None):
        d = {"variant_id": r.get("variant_id"), "platform": r.get("platform"),
            "hook_text": r.get("hook_text"), "creative_angle": r.get("creative_angle"),
            "style_type": r.get("style_type"), "views_24h": r.get("views_24h")}
        if extra is not None:
            d["engagement_rate"] = round(extra, 4)
        return d

    best_videos_by_views = [_video_summary(r) for r in best_by_views[:10]]
    best_videos_by_engagement = [_video_summary(r, e) for r, e in with_engagement[:10]]

    best_hooks = _group_average(video_rows, "hook_text", _engagement_rate)[:10]
    best_angles = _group_average(video_rows, "creative_angle", _engagement_rate)[:10]
    best_styles = _group_average(video_rows, "style_type", _engagement_rate)[:10]
    best_platforms = _group_average(video_rows, "platform", _engagement_rate)

    weak_videos = [_video_summary(r, e) for r, e in
                  sorted(with_engagement, key=lambda pair: pair[1])[:10]]
    weak_videos += [dict(_video_summary(r), decision=r.get("decision"))
                   for r in video_rows if r.get("decision") == "reject"]

    repeated_patterns = []
    if best_videos_by_views:
        top_angles = [v["creative_angle"] for v in best_videos_by_views[:5] if v["creative_angle"]]
        if top_angles:
            common = max(set(top_angles), key=top_angles.count)
            if top_angles.count(common) >= 3:
                repeated_patterns.append(f"{common} appears in {top_angles.count(common)}/5 top videos by views")
        top_styles = [v["style_type"] for v in best_videos_by_views[:5] if v["style_type"]]
        if top_styles:
            common_style = max(set(top_styles), key=top_styles.count)
            if top_styles.count(common_style) >= 3:
                repeated_patterns.append(f"{common_style} appears in {top_styles.count(common_style)}/5 top videos by views")

    recommendations = []
    if best_angles:
        recommendations.append(f"Усилить угол '{best_angles[0]['key']}' (лучший engagement rate "
                              f"{best_angles[0]['avg']}) в следующей пачке.")
    if best_hooks:
        recommendations.append(f"Повторить/варьировать хук '{best_hooks[0]['key']}' -- показал "
                              f"лучший engagement rate ({best_hooks[0]['avg']}).")
    if best_platforms:
        recommendations.append(f"Больше публиковать на '{best_platforms[0]['key']}' -- "
                              f"лучшая площадка по engagement rate.")
    if weak_videos:
        recommendations.append("Пересмотреть/не повторять подходы слабых роликов (см. weak_videos).")

    return {
        "campaign_code": "coating-protect-2026-07",
        "has_data": True,
        "rows_with_data": len(with_views),
        "best_videos_by_views_24h": best_videos_by_views,
        "best_videos_by_engagement_rate": best_videos_by_engagement,
        "best_hooks": best_hooks,
        "best_creative_angle": best_angles,
        "best_style_type": best_styles,
        "best_platform": best_platforms,
        "weak_videos": weak_videos,
        "repeated_patterns": repeated_patterns,
        "recommendations_for_next_batch": recommendations,
        "openai_calls": 0, "higgsfield_calls": 0, "external_api_calls": 0,
    }


def write_performance_summary(campaign_dir: str, repo_root: str = ".") -> dict:
    report = analyze_performance(campaign_dir, repo_root)
    out_dir = Path(repo_root) / campaign_dir / "generated/content-factory/performance-tracking/reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "performance-summary.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not report["has_data"]:
        md = ("# Performance Summary -- coating-protect-2026-07\n\n"
             f"{report['note']}\n\n"
             "## Recommendations\n\n" +
             "\n".join(f"- {r}" for r in report["recommendations_for_next_batch"]) + "\n")
    else:
        lines = ["# Performance Summary -- coating-protect-2026-07", "",
                 f"Rows with data: {report['rows_with_data']}", ""]
        lines.append("## Best videos by views_24h")
        for v in report["best_videos_by_views_24h"]:
            lines.append(f"- {v['variant_id']} ({v['platform']}) -- {v['views_24h']} views -- {v['hook_text']}")
        lines.append("")
        lines.append("## Best videos by engagement rate")
        for v in report["best_videos_by_engagement_rate"]:
            lines.append(f"- {v['variant_id']} ({v['platform']}) -- engagement {v['engagement_rate']} -- {v['hook_text']}")
        lines.append("")
        lines.append("## Best hooks")
        for h in report["best_hooks"]:
            lines.append(f"- {h['key']} -- avg engagement {h['avg']} (n={h['n']})")
        lines.append("")
        lines.append("## Best creative angle")
        for a in report["best_creative_angle"]:
            lines.append(f"- {a['key']} -- avg engagement {a['avg']} (n={a['n']})")
        lines.append("")
        lines.append("## Best style type")
        for s in report["best_style_type"]:
            lines.append(f"- {s['key']} -- avg engagement {s['avg']} (n={s['n']})")
        lines.append("")
        lines.append("## Best platform")
        for p in report["best_platform"]:
            lines.append(f"- {p['key']} -- avg engagement {p['avg']} (n={p['n']})")
        lines.append("")
        lines.append("## Weak videos")
        for v in report["weak_videos"]:
            lines.append(f"- {v['variant_id']} ({v['platform']}) -- {v.get('hook_text', '')}")
        lines.append("")
        lines.append("## Repeated patterns")
        for p in report["repeated_patterns"]:
            lines.append(f"- {p}")
        lines.append("")
        lines.append("## Recommendations for next batch")
        for r in report["recommendations_for_next_batch"]:
            lines.append(f"- {r}")
        md = "\n".join(lines) + "\n"

    md_path = out_dir / "performance-summary.md"
    md_path.write_text(md, encoding="utf-8")

    report["json_path"] = str(json_path)
    report["md_path"] = str(md_path)
    return report


def build_next_batch_recommendations(campaign_dir: str, repo_root: str = ".") -> dict:
    summary = analyze_performance(campaign_dir, repo_root)

    if not summary["has_data"]:
        return {
            "campaign_code": "coating-protect-2026-07",
            "has_data": False,
            "hypotheses_being_tested": [
                "pain_problem angle drives higher saves/shares than recipe angle",
                "fast_hype style has higher completion rate on TikTok than on YouTube Shorts",
                "meme_conversational hooks get more comments (relatable humor invites replies)",
                "product_beauty_clean (batch-001 clean_ad/comparison_style) works best as a "
                "closing/CTA-style asset rather than a standalone hook",
            ],
            "success_metrics_definition": {
                "views_24h": "> 500 considered a solid start for this account size (adjust once "
                            "baseline data exists)",
                "engagement_rate": "(likes+comments+shares+saves)/views -- above 0.05 (5%) is "
                                  "considered strong for short-form video",
            },
            "when_to_generate_batch_006": ("After at least 7 days of the 14-day queue have real "
                                          "views_24h data filled in daily-input/*.csv -- earlier "
                                          "than that, the sample is too small to trust."),
            "angles_to_reinforce": [],
            "hooks_to_repeat": [],
            "repeat_winning_hooks": [],
            "remake_underperforming_angles": [],
            "generate_more_of": [],
            "avoid_next_time": [],
            "next_batch_prompt_notes": [
                "No performance data yet -- keep batch-006 planning on hold until "
                "performance-summary.json reports has_data=true."
            ],
        }

    top_angle = summary["best_creative_angle"][0]["key"] if summary["best_creative_angle"] else None
    top_hook = summary["best_hooks"][0]["key"] if summary["best_hooks"] else None
    weak_angles = [w.get("creative_angle") for w in summary["weak_videos"] if w.get("creative_angle")]

    return {
        "campaign_code": "coating-protect-2026-07",
        "has_data": True,
        "repeat_winning_hooks": [h["key"] for h in summary["best_hooks"][:5]],
        "remake_underperforming_angles": sorted(set(weak_angles)),
        "generate_more_of": [top_angle] if top_angle else [],
        "avoid_next_time": sorted(set(weak_angles)),
        "next_batch_prompt_notes": [
            f"Top-performing angle so far: {top_angle}." if top_angle else "",
            f"Top-performing hook so far: {top_hook}." if top_hook else "",
            "Generate batch-006 leaning into the angle(s) above; keep style/scene variety "
            "the same as before (no new image generation needed for this decision itself).",
        ],
    }


def write_next_batch_recommendations(campaign_dir: str, repo_root: str = ".") -> dict:
    rec = build_next_batch_recommendations(campaign_dir, repo_root)
    out_dir = Path(repo_root) / campaign_dir / "generated/content-factory/performance-tracking/reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "next-batch-recommendations.json"
    json_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# Next Batch Recommendations -- coating-protect-2026-07", ""]
    if not rec["has_data"]:
        lines.append("Данных ещё нет. Ниже -- гипотезы и критерии успеха на будущее.\n")
        lines.append("## Hypotheses being tested")
        for h in rec["hypotheses_being_tested"]:
            lines.append(f"- {h}")
        lines.append("")
        lines.append("## Success metrics")
        for k, v in rec["success_metrics_definition"].items():
            lines.append(f"- **{k}**: {v}")
        lines.append("")
        lines.append(f"## When to generate batch-006\n{rec['when_to_generate_batch_006']}\n")
        lines.append("## Next batch prompt notes")
        for n in rec["next_batch_prompt_notes"]:
            lines.append(f"- {n}")
    else:
        lines.append("## Repeat winning hooks")
        for h in rec["repeat_winning_hooks"]:
            lines.append(f"- {h}")
        lines.append("")
        lines.append("## Remake underperforming angles")
        for a in rec["remake_underperforming_angles"]:
            lines.append(f"- {a}")
        lines.append("")
        lines.append("## Generate more of")
        for a in rec["generate_more_of"]:
            lines.append(f"- {a}")
        lines.append("")
        lines.append("## Avoid next time")
        for a in rec["avoid_next_time"]:
            lines.append(f"- {a}")
        lines.append("")
        lines.append("## Next batch prompt notes")
        for n in rec["next_batch_prompt_notes"]:
            if n:
                lines.append(f"- {n}")
    md_path = out_dir / "next-batch-recommendations.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    rec["json_path"] = str(json_path)
    rec["md_path"] = str(md_path)
    return rec
