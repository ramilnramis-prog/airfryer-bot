"""Master content queue for the local content factory: aggregates every
rendered video (all batches) and every Dzen post (all batches) into one
file with a recommended posting order/spacing. Pure local file I/O -- no
network, no OpenAI/Higgsfield calls, no auto-posting (publish_status stays
"not_published" for every entry; the owner publishes manually)."""
from __future__ import annotations

import json
from pathlib import Path

from . import content_factory_data as fd
from . import content_factory_review as rev

DEFAULT_DZEN_SPACING_HOURS = 24


def _video_status(render_meta: dict) -> str:
    return "ready_for_owner_review" if render_meta.get("render_status") == "rendered" else "needs_edit"


def collect_video_assets(campaign_dir: str, repo_root: str = ".", batches=None) -> list:
    base = Path(repo_root) / campaign_dir / "generated/content-factory/video-renders"
    batch_list = list(batches) if batches else rev.discover_batches(campaign_dir, repo_root)

    items = []
    for batch_name in batch_list:
        batch_dir = base / batch_name
        if not batch_dir.is_dir():
            continue
        for f in sorted(batch_dir.glob("*.json")):
            if f.name == "batch-summary.json":
                continue
            meta = json.loads(f.read_text(encoding="utf-8"))
            items.append({
                "asset_type": "video",
                "asset_id": meta["variant_id"],
                "batch": batch_name,
                "mp4_path": meta.get("mp4_path"),
                "render_status": meta.get("render_status"),
                "hook_text": meta["hook_text"],
                "creative_angle": meta.get("creative_angle"),
                "style_type": meta["style_type"],
                "native_format": meta["format"],
                "platform_targets": list(fd.FORMATS),
                "duration_target_seconds": meta["duration_target_seconds"],
                "recommended_spacing_hours": meta.get("recommended_spacing_hours", 12),
                "platform_fit_score": meta.get("platform_fit_score"),
                "status": _video_status(meta),
                "publish_status": "not_published",
                "owner_notes": "",
            })
    return items


def collect_dzen_assets(campaign_dir: str, repo_root: str = ".", batches=None) -> list:
    base = Path(repo_root) / campaign_dir / "generated/content-factory/dzen-posts"
    if not base.is_dir():
        return []
    batch_list = list(batches) if batches else sorted(
        d.name for d in base.iterdir() if d.is_dir())

    items = []
    for batch_name in batch_list:
        batch_dir = base / batch_name
        for f in sorted(batch_dir.glob("*.md")):
            text = f.read_text(encoding="utf-8")
            items.append({
                "asset_type": "dzen_post",
                "asset_id": f.stem,
                "batch": batch_name,
                "path": str(f).replace("\\", "/"),
                "chars": len(text),
                "recommended_spacing_hours": DEFAULT_DZEN_SPACING_HOURS,
                "status": "ready_for_owner_review",
                "publish_status": "not_published",
                "owner_notes": "",
            })
    return items


def _round_robin_order(items: list, group_key: str) -> list:
    """Interleaves items across their group_key value (e.g. batch) so the
    recommended posting order doesn't stack same-angle/same-batch content
    back to back -- basic anti-spam spacing hygiene."""
    groups = {}
    for item in items:
        groups.setdefault(item[group_key], []).append(item)
    order = []
    while any(groups.values()):
        for key in sorted(groups.keys()):
            bucket = groups[key]
            if bucket:
                order.append(bucket.pop(0))
    return order


def build_content_queue(campaign_dir: str, repo_root: str = ".",
                        video_batches=None, dzen_batches=None) -> dict:
    video_assets = collect_video_assets(campaign_dir, repo_root, video_batches)
    dzen_assets = collect_dzen_assets(campaign_dir, repo_root, dzen_batches)

    video_order = _round_robin_order(video_assets, "batch")
    dzen_order = _round_robin_order(dzen_assets, "batch")

    posting_order = []
    for i, item in enumerate(video_order, start=1):
        posting_order.append({
            "sequence": i, "asset_type": "video", "asset_id": item["asset_id"],
            "batch": item["batch"], "creative_angle": item["creative_angle"],
            "recommended_spacing_hours": item["recommended_spacing_hours"],
        })
    for i, item in enumerate(dzen_order, start=len(posting_order) + 1):
        posting_order.append({
            "sequence": i, "asset_type": "dzen_post", "asset_id": item["asset_id"],
            "batch": item["batch"], "recommended_spacing_hours": item["recommended_spacing_hours"],
        })

    queue = {
        "campaign_code": "coating-protect-2026-07",
        "total_video_assets": len(video_assets),
        "total_dzen_assets": len(dzen_assets),
        "total_assets": len(video_assets) + len(dzen_assets),
        "video_assets": video_assets,
        "dzen_assets": dzen_assets,
        "recommended_posting_order": posting_order,
        "note": ("recommended_posting_order round-robins across batches so the same "
                "creative_angle/batch is never posted twice in a row; spacing between "
                "consecutive entries should respect each item's own "
                "recommended_spacing_hours. All statuses are ready_for_owner_review "
                "and publish_status is not_published -- nothing here has been posted "
                "anywhere automatically."),
        "openai_calls": 0,
        "higgsfield_calls": 0,
        "auto_posting_triggered": False,
    }
    return queue


def write_content_queue(campaign_dir: str, repo_root: str = ".", out_path=None,
                        video_batches=None, dzen_batches=None) -> dict:
    queue = build_content_queue(campaign_dir, repo_root, video_batches, dzen_batches)
    out = Path(out_path) if out_path else (
        Path(repo_root) / campaign_dir / "generated/content-factory/content-queue.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    queue["report_path"] = str(out)
    return queue
