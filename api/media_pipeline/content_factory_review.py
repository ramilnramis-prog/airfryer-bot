"""Local owner-review dashboard for the content factory. Pure local HTML
generation -- no network, no OpenAI/Higgsfield calls, no auto-posting. The
owner opens index.html locally and edits/publishes manually."""
from __future__ import annotations

import json
from pathlib import Path

STATUS_VALUES = ("ready_for_owner_review", "needs_edit", "rejected")

_STYLE_BLOCK = """
body { font-family: sans-serif; background:#111; color:#eee; margin:0; padding:20px; }
h1 { font-size: 20px; }
.summary { margin-bottom: 16px; }
.filters { display:flex; gap:12px; flex-wrap:wrap; margin-bottom:20px; background:#1a1a1a;
          padding:12px; border-radius:8px; }
.filters label { font-size:12px; color:#aaa; display:flex; flex-direction:column; gap:4px; }
.filters select { background:#222; color:#eee; border:1px solid #444; border-radius:4px; padding:4px 6px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.card { background:#1c1c1c; border:1px solid #333; border-radius:8px; padding:12px; }
.card.hidden { display:none; }
.status-badge { display:inline-block; padding:3px 8px; border-radius:4px; font-size:12px; font-weight:bold; }
.status-ready { background:#1e5c33; color:#c8ffd9; }
.status-needs-edit { background:#5c4b1e; color:#ffe9b3; }
.status-rejected { background:#5c1e1e; color:#ffc8c8; }
.status-note { font-size:12px; color:#aaa; }
.missing-mp4 { background:#2a2a2a; padding:10px; border-radius:6px; font-size:13px; }
.batch-tag { font-size:11px; color:#888; }
video { max-width: 100%; border-radius:6px; }
pre { white-space: pre-wrap; font-size:12px; background:#111; padding:8px; border-radius:4px; }
a { color:#8ab4ff; }
"""

_FILTER_JS = """
function applyFilters() {
  var batch = document.getElementById('f-batch').value;
  var angle = document.getElementById('f-angle').value;
  var platform = document.getElementById('f-platform').value;
  var status = document.getElementById('f-status').value;
  var cards = document.querySelectorAll('.card');
  cards.forEach(function(card) {
    var ok = true;
    if (batch !== 'all' && card.dataset.batch !== batch) ok = false;
    if (angle !== 'all' && card.dataset.angle !== angle) ok = false;
    if (platform !== 'all' && card.dataset.platform !== platform) ok = false;
    if (status !== 'all' && card.dataset.status !== status) ok = false;
    card.classList.toggle('hidden', !ok);
  });
}
"""


def _status_for(render_meta: dict) -> tuple:
    if render_meta.get("render_status") == "rendered":
        return "ready_for_owner_review", "MP4 rendered locally -- ready for the owner to review and cut/publish manually."
    return "needs_edit", ("MP4 was not rendered (missing local dependency) -- see render plan / "
                          "install_instructions below.")


def _card_html(variant_id: str, render_meta: dict, platform_meta: dict or None,
               script_text: str, video_dir_rel: str, metadata_dir_rel: str,
               batch_name: str, with_filter_attrs: bool = False) -> tuple:
    """Returns (status, html)."""
    status, status_note = _status_for(render_meta)
    status_class = {"ready_for_owner_review": "status-ready",
                    "needs_edit": "status-needs-edit",
                    "rejected": "status-rejected"}[status]
    angle = render_meta.get("creative_angle", "n/a")
    platform = render_meta.get("format", "n/a")

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

    data_attrs = ""
    if with_filter_attrs:
        data_attrs = (f' data-batch="{batch_name}" data-angle="{angle}" '
                     f'data-platform="{platform}" data-status="{status}"')

    html = f"""
    <div class="card"{data_attrs}>
      <span class="batch-tag">{batch_name}</span>
      <h3>{variant_id}</h3>
      <span class="status-badge {status_class}">{status}</span>
      <p class="status-note">{status_note}</p>
      {media_html}
      <p><b>hook:</b> {render_meta['hook_text']}</p>
      <p><b>style_type:</b> {render_meta['style_type']} &nbsp; <b>format:</b> {render_meta['format']}
         &nbsp; <b>angle:</b> {angle}</p>
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
    return status, html


def discover_batches(campaign_dir: str, repo_root: str = ".") -> list:
    video_renders_dir = Path(repo_root) / campaign_dir / "generated/content-factory/video-renders"
    if not video_renders_dir.is_dir():
        return []
    return sorted(d.name for d in video_renders_dir.iterdir() if d.is_dir())


def _collect_batch(campaign_dir: str, batch_name: str, repo_root: str = ".",
                   with_filter_attrs: bool = False) -> dict:
    base = Path(repo_root) / campaign_dir / "generated/content-factory"
    video_dir = base / "video-renders" / batch_name
    metadata_dir = base / "platform-metadata" / batch_name
    video_dir_rel = f"../video-renders/{batch_name}"
    metadata_dir_rel = f"../platform-metadata/{batch_name}"

    cards = []
    status_counts = {"ready_for_owner_review": 0, "needs_edit": 0, "rejected": 0}
    angles = set()
    platforms = set()
    for render_json in sorted(video_dir.glob("*.json")):
        if render_json.name == "batch-summary.json":
            continue
        render_meta = json.loads(render_json.read_text(encoding="utf-8"))
        variant_id = render_meta["variant_id"]

        platform_meta = None
        platform_path = metadata_dir / f"{variant_id}-platform-metadata.json"
        if platform_path.is_file():
            platform_meta = json.loads(platform_path.read_text(encoding="utf-8"))

        script_path = video_dir / f"{variant_id}.txt"
        script_text = script_path.read_text(encoding="utf-8") if script_path.is_file() else "(script not found)"

        status, html = _card_html(variant_id, render_meta, platform_meta, script_text,
                                  video_dir_rel, metadata_dir_rel, batch_name, with_filter_attrs)
        status_counts[status] += 1
        angles.add(render_meta.get("creative_angle", "n/a"))
        platforms.add(render_meta.get("format", "n/a"))
        cards.append(html)

    return {"batch_name": batch_name, "cards": cards, "status_counts": status_counts,
           "angles": angles, "platforms": platforms}


def build_batch_review_page(campaign_dir: str, batch_name: str, repo_root: str = ".",
                            out_path=None) -> str:
    """Single-batch review page (no filters needed -- already scoped to one
    batch): generated/content-factory/review/<batch_name>.html"""
    review_dir = Path(repo_root) / campaign_dir / "generated/content-factory/review"
    review_dir.mkdir(parents=True, exist_ok=True)

    data = _collect_batch(campaign_dir, batch_name, repo_root, with_filter_attrs=False)
    sc = data["status_counts"]

    html = f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Content factory review -- {batch_name}</title>
<style>{_STYLE_BLOCK}</style>
</head><body>
<h1>Content factory review -- {batch_name}</h1>
<p><a href="index.html">&larr; back to all batches</a></p>
<div class="summary">
  <p>ready_for_owner_review: {sc['ready_for_owner_review']} &nbsp;
     needs_edit: {sc['needs_edit']} &nbsp;
     rejected: {sc['rejected']}</p>
  <p style="color:#888; font-size:13px;">Owner reviews, edits, and publishes manually. No auto-posting is performed by this dashboard or any part of the content factory.</p>
</div>
<div class="grid">
{''.join(data['cards'])}
</div>
</body></html>"""

    out = Path(out_path) if out_path else (review_dir / f"{batch_name}.html")
    out.write_text(html, encoding="utf-8")
    return str(out)


def build_review_dashboard(campaign_dir: str, batches=None, repo_root: str = ".",
                           out_path=None) -> str:
    """Combined dashboard across ALL batches (or the given `batches` list),
    with batch/angle/platform/status filters, written to review/index.html.
    Also (re)writes a standalone per-batch page for each batch covered."""
    review_dir = Path(repo_root) / campaign_dir / "generated/content-factory/review"
    review_dir.mkdir(parents=True, exist_ok=True)

    batch_list = list(batches) if batches else discover_batches(campaign_dir, repo_root)

    all_cards = []
    total_status_counts = {"ready_for_owner_review": 0, "needs_edit": 0, "rejected": 0}
    all_angles = set()
    all_platforms = set()
    batch_pages = []

    for batch_name in batch_list:
        data = _collect_batch(campaign_dir, batch_name, repo_root, with_filter_attrs=True)
        all_cards.extend(data["cards"])
        for k, v in data["status_counts"].items():
            total_status_counts[k] += v
        all_angles |= data["angles"]
        all_platforms |= data["platforms"]
        batch_pages.append(build_batch_review_page(campaign_dir, batch_name, repo_root))

    def _options(values, selected="all"):
        opts = [f'<option value="all">all</option>']
        for v in sorted(values):
            opts.append(f'<option value="{v}">{v}</option>')
        return "".join(opts)

    batch_links = " | ".join(f'<a href="{b}.html">{b}</a>' for b in batch_list)

    html = f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Content factory review -- all batches</title>
<style>{_STYLE_BLOCK}</style>
</head><body>
<h1>Content factory review -- all batches</h1>
<p>Per-batch pages: {batch_links}</p>
<div class="summary">
  <p>ready_for_owner_review: {total_status_counts['ready_for_owner_review']} &nbsp;
     needs_edit: {total_status_counts['needs_edit']} &nbsp;
     rejected: {total_status_counts['rejected']}</p>
  <p style="color:#888; font-size:13px;">Owner reviews, edits, and publishes manually. No auto-posting is performed by this dashboard or any part of the content factory.</p>
</div>
<div class="filters">
  <label>batch <select id="f-batch" onchange="applyFilters()">
    <option value="all">all</option>
    {''.join(f'<option value="{b}">{b}</option>' for b in batch_list)}
  </select></label>
  <label>angle <select id="f-angle" onchange="applyFilters()">{_options(all_angles)}</select></label>
  <label>platform <select id="f-platform" onchange="applyFilters()">{_options(all_platforms)}</select></label>
  <label>status <select id="f-status" onchange="applyFilters()">
    <option value="all">all</option>
    <option value="ready_for_owner_review">ready_for_owner_review</option>
    <option value="needs_edit">needs_edit</option>
    <option value="rejected">rejected</option>
  </select></label>
</div>
<div class="grid" id="grid">
{''.join(all_cards)}
</div>
<script>{_FILTER_JS}</script>
</body></html>"""

    out = Path(out_path) if out_path else (review_dir / "index.html")
    out.write_text(html, encoding="utf-8")
    return str(out)
