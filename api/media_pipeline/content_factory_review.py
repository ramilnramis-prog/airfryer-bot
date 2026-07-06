"""Local owner-review dashboard for the content factory. Pure local HTML
generation -- no network, no OpenAI/Higgsfield calls, no auto-posting. The
owner opens index.html locally and edits/publishes manually."""
from __future__ import annotations

import json
from pathlib import Path

STATUS_VALUES = ("ready_for_owner_review", "needs_edit", "rejected")


def _status_for(render_meta: dict) -> tuple:
    if render_meta.get("render_status") == "rendered":
        return "ready_for_owner_review", "MP4 rendered locally -- ready for the owner to review and cut/publish manually."
    return "needs_edit", ("MP4 was not rendered (missing local dependency) -- see render plan / "
                          "install_instructions below.")


def _card_html(variant_id: str, render_meta: dict, platform_meta: dict or None,
               script_text: str, video_dir_rel: str, metadata_dir_rel: str) -> str:
    status, status_note = _status_for(render_meta)
    status_class = {"ready_for_owner_review": "status-ready",
                    "needs_edit": "status-needs-edit",
                    "rejected": "status-rejected"}[status]

    if render_meta.get("render_status") == "rendered":
        media_html = (f'<video controls preload="metadata" width="240">'
                      f'<source src="{video_dir_rel}/{variant_id}.mp4" type="video/mp4">'
                      f'</video>')
    else:
        install = ", ".join(render_meta.get("install_instructions", []) or ["unknown dependency"])
        plan_link = f'{video_dir_rel}/{variant_id}-render-plan.json'
        preview_link = f'{video_dir_rel}/{variant_id}-preview.html'
        media_html = (f'<div class="missing-mp4">MP4 not rendered.<br>'
                      f'Install: {install}<br>'
                      f'<a href="{plan_link}">render plan (json)</a> · '
                      f'<a href="{preview_link}">preview (html)</a></div>')

    platform_links = ""
    if platform_meta:
        platform_links = "<br>".join(
            f"<b>{p}</b>: {platform_meta['platforms'][p]['title']}"
            for p in platform_meta.get("platforms", {})
        )

    return f"""
    <div class="card">
      <h3>{variant_id}</h3>
      <span class="status-badge {status_class}">{status}</span>
      <p class="status-note">{status_note}</p>
      {media_html}
      <p><b>hook:</b> {render_meta['hook_text']}</p>
      <p><b>style_type:</b> {render_meta['style_type']} &nbsp; <b>format:</b> {render_meta['format']}</p>
      <p><b>duration:</b> {render_meta['duration_target_seconds']}s &nbsp;
         <b>claim level:</b> {render_meta['product_claim_level']} &nbsp;
         <b>platform_fit_score:</b> {render_meta.get('platform_fit_score', 'n/a')}</p>
      <details>
        <summary>script</summary>
        <pre>{script_text}</pre>
      </details>
      <details>
        <summary>platform metadata</summary>
        <p>{platform_links or 'not generated'}</p>
        <a href="{metadata_dir_rel}/{variant_id}-platform-metadata.json">full metadata (json)</a>
      </details>
    </div>
    """


def build_review_dashboard(campaign_dir: str, batch_name: str = "batch-001",
                           repo_root: str = ".", out_path=None) -> str:
    base = Path(repo_root) / campaign_dir / "generated/content-factory"
    video_dir = base / "video-renders" / batch_name
    metadata_dir = base / "platform-metadata" / batch_name
    review_dir = base / "review"
    review_dir.mkdir(parents=True, exist_ok=True)

    video_dir_rel = f"../video-renders/{batch_name}"
    metadata_dir_rel = f"../platform-metadata/{batch_name}"

    cards = []
    status_counts = {"ready_for_owner_review": 0, "needs_edit": 0, "rejected": 0}
    for render_json in sorted(video_dir.glob("v*.json")):
        render_meta = json.loads(render_json.read_text(encoding="utf-8"))
        variant_id = render_meta["variant_id"]

        platform_meta = None
        platform_path = metadata_dir / f"{variant_id}-platform-metadata.json"
        if platform_path.is_file():
            platform_meta = json.loads(platform_path.read_text(encoding="utf-8"))

        script_path = video_dir / f"{variant_id}.txt"
        script_text = script_path.read_text(encoding="utf-8") if script_path.is_file() else "(script not found)"

        status, _ = _status_for(render_meta)
        status_counts[status] += 1

        cards.append(_card_html(variant_id, render_meta, platform_meta, script_text,
                                video_dir_rel, metadata_dir_rel))

    html = f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Content factory review -- {batch_name}</title>
<style>
body {{ font-family: sans-serif; background:#111; color:#eee; margin:0; padding:20px; }}
h1 {{ font-size: 20px; }}
.summary {{ margin-bottom: 20px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }}
.card {{ background:#1c1c1c; border:1px solid #333; border-radius:8px; padding:12px; }}
.status-badge {{ display:inline-block; padding:3px 8px; border-radius:4px; font-size:12px; font-weight:bold; }}
.status-ready {{ background:#1e5c33; color:#c8ffd9; }}
.status-needs-edit {{ background:#5c4b1e; color:#ffe9b3; }}
.status-rejected {{ background:#5c1e1e; color:#ffc8c8; }}
.status-note {{ font-size:12px; color:#aaa; }}
.missing-mp4 {{ background:#2a2a2a; padding:10px; border-radius:6px; font-size:13px; }}
video {{ max-width: 100%; border-radius:6px; }}
pre {{ white-space: pre-wrap; font-size:12px; background:#111; padding:8px; border-radius:4px; }}
a {{ color:#8ab4ff; }}
</style>
</head><body>
<h1>Content factory review -- {batch_name}</h1>
<div class="summary">
  <p>ready_for_owner_review: {status_counts['ready_for_owner_review']} &nbsp;
     needs_edit: {status_counts['needs_edit']} &nbsp;
     rejected: {status_counts['rejected']}</p>
  <p style="color:#888; font-size:13px;">Owner reviews, edits, and publishes manually. No auto-posting is performed by this dashboard or any part of the content factory.</p>
</div>
<div class="grid">
{''.join(cards)}
</div>
</body></html>"""

    out = Path(out_path) if out_path else (review_dir / "index.html")
    out.write_text(html, encoding="utf-8")
    return str(out)
