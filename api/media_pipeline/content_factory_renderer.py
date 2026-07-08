"""Local MP4 renderer for the content factory. Builds simple Ken-Burns-style
videos (zoom/pan/punch/hold) with on-screen captions and a closing CTA card
from the ALREADY-REVIEWED scene-01..07 candidate PNGs. No network, no
OpenAI/Higgsfield calls, no audio (voiceover_text stays metadata-only at
this stage).

Dependency policy: uses PIL (Pillow) for frame compositing and imageio (with
the bundled imageio-ffmpeg binary) for MP4 encoding. If either is missing,
render_variant() NEVER raises -- it falls back to writing a render-plan JSON
plus a static HTML preview and reports exactly what to install.
"""
from __future__ import annotations

import json
from pathlib import Path

TARGET_SIZE = (720, 1280)  # (width, height), 9:16
FPS = 24
CTA_CARD_SECONDS = 1.5

MOTION_EFFECTS = ("slow_zoom_in", "slow_zoom_out", "pan_left", "pan_right",
                  "punch_zoom", "hold_frame", "quick_cuts")


def check_render_dependencies() -> dict:
    missing = []
    pil_ok = imageio_ok = ffmpeg_ok = False
    try:
        import PIL  # noqa: F401
        pil_ok = True
    except Exception:
        missing.append("Pillow (pip install Pillow)")
    try:
        import imageio  # noqa: F401
        imageio_ok = True
    except Exception:
        missing.append("imageio (pip install imageio)")
    try:
        import imageio_ffmpeg
        imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_ok = True
    except Exception:
        missing.append("imageio-ffmpeg (pip install imageio-ffmpeg) -- bundles a static ffmpeg binary")
    return {
        "pillow_available": pil_ok,
        "imageio_available": imageio_ok,
        "ffmpeg_available": ffmpeg_ok,
        "can_render_mp4": pil_ok and imageio_ok and ffmpeg_ok,
        "install_instructions": missing,
    }


def _placeholder_image(scene_id: str, size=TARGET_SIZE):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", size, (60, 60, 60))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except Exception:
        font = ImageFont.load_default()
    text = f"MISSING ASSET\n{scene_id}"
    draw.multiline_text((size[0] // 2, size[1] // 2), text, fill=(230, 230, 230),
                        font=font, anchor="mm", align="center")
    return img


def _load_scene_image(asset: dict, size=TARGET_SIZE):
    from PIL import Image
    if asset.get("exists") and asset.get("path"):
        try:
            img = Image.open(asset["path"]).convert("RGB")
            if img.size != size:
                img = img.resize(size)
            return img
        except Exception:
            return _placeholder_image(asset["scene_id"], size)
    return _placeholder_image(asset["scene_id"], size)


def _crop_window(img, scale: float, cx: float, cy: float, size=TARGET_SIZE):
    """Crops a `1/scale`-sized window centered at (cx, cy) (fractions 0..1
    of the full image) out of `img` (already `size`), then resizes back up
    to `size`. scale >= 1.0 means zoomed-in."""
    w, h = size
    win_w, win_h = w / scale, h / scale
    left = max(0.0, min(w - win_w, cx * w - win_w / 2))
    top = max(0.0, min(h - win_h, cy * h - win_h / 2))
    box = (left, top, left + win_w, top + win_h)
    return img.resize(size, box=box)


def _ease_out(t: float) -> float:
    return 1 - (1 - t) ** 2


def _frame_for_effect(base_img, effect: str, progress: float, size=TARGET_SIZE):
    """progress in [0, 1] across the scene's on-screen duration."""
    if effect == "slow_zoom_in":
        scale = 1.0 + 0.15 * progress
        return _crop_window(base_img, scale, 0.5, 0.5, size)
    if effect == "slow_zoom_out":
        scale = 1.15 - 0.15 * progress
        return _crop_window(base_img, scale, 0.5, 0.5, size)
    if effect == "pan_left":
        cx = 0.65 - 0.3 * progress
        return _crop_window(base_img, 1.12, cx, 0.5, size)
    if effect == "pan_right":
        cx = 0.35 + 0.3 * progress
        return _crop_window(base_img, 1.12, cx, 0.5, size)
    if effect == "punch_zoom":
        scale = 1.0 + 0.22 * _ease_out(min(1.0, progress * 2.2))
        return _crop_window(base_img, scale, 0.5, 0.45, size)
    if effect == "quick_cuts":
        # No motion -- static per-cut frame; variety comes from fast scene
        # switching (short per-scene windows) at the composition level.
        return base_img
    return base_img  # hold_frame / fallback


def _wrap_and_draw_caption(frame, text: str):
    from PIL import ImageDraw, ImageFont
    if not text:
        return frame
    draw = ImageDraw.Draw(frame, "RGBA")
    try:
        font = ImageFont.truetype("arialbd.ttf", 40)
    except Exception:
        try:
            font = ImageFont.truetype("arial.ttf", 40)
        except Exception:
            font = ImageFont.load_default()

    w, h = frame.size
    max_width = w - 80
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] > max_width and current:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)

    line_height = 50
    block_height = line_height * len(lines) + 40
    bar_top = h - block_height - 60
    draw.rectangle([0, bar_top, w, h - 40], fill=(0, 0, 0, 140))
    y = bar_top + 20
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((w - tw) / 2, y), line, fill=(255, 255, 255, 255), font=font)
        y += line_height
    return frame


def _cta_card(variant: dict, fallback_img):
    from PIL import Image
    img = fallback_img.copy().convert("RGB")
    overlay = Image.new("RGB", img.size, (20, 20, 20))
    img = Image.blend(img, overlay, 0.45)
    return _wrap_and_draw_caption(img, variant["CTA"])


def build_srt(caption_timeline: list) -> str:
    def fmt(t: float) -> str:
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    for i, seg in enumerate(caption_timeline, start=1):
        lines.append(str(i))
        lines.append(f"{fmt(seg['start_sec'])} --> {fmt(seg['end_sec'])}")
        lines.append(seg["text"])
        lines.append("")
    return "\n".join(lines)


def build_script_txt(variant: dict) -> str:
    parts = [
        f"variant_id: {variant['variant_id']}",
        f"format: {variant['format']}  style: {variant['style_type']}  "
        f"duration: {variant['duration_target_seconds']}s",
        "",
        f"HOOK: {variant['hook_text']}",
        "",
        "ON-SCREEN TEXT (in order):",
    ]
    for i, (scene_id, text) in enumerate(zip(variant["scene_order"], variant["on_screen_text"]), start=1):
        parts.append(f"  {i}. [{scene_id}] {text}")
    parts.append("")
    parts.append(f"VOICEOVER (metadata only, no audio rendered): {variant['voiceover_text']}")
    parts.append("")
    parts.append(f"CTA: {variant['CTA']}")
    return "\n".join(parts)


def render_variant(variant: dict, out_dir: str, repo_root: str = ".") -> dict:
    """Renders one MP4 (+ .json metadata + .txt script + .srt captions) for
    a single variant. Falls back to a render-plan JSON + HTML preview
    (never raises) if PIL/imageio/ffmpeg aren't available."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    variant_id = variant["variant_id"]

    script_path = out / f"{variant_id}.txt"
    script_path.write_text(build_script_txt(variant), encoding="utf-8")

    srt_path = out / f"{variant_id}.srt"
    srt_path.write_text(build_srt(variant["caption_timeline"]), encoding="utf-8")

    deps = check_render_dependencies()
    effects_used = [MOTION_EFFECTS[i % len(MOTION_EFFECTS)] for i in range(len(variant["scene_order"]))]

    if not deps["can_render_mp4"]:
        plan = {
            "variant_id": variant_id,
            "render_status": "render_plan_only",
            "reason": "Missing local rendering dependency.",
            "install_instructions": deps["install_instructions"],
            "scene_effect_plan": [
                {"scene_id": s, "effect": e, "window": seg}
                for s, e, seg in zip(variant["scene_order"], effects_used, variant["caption_timeline"])
            ],
            "cta_card_seconds": CTA_CARD_SECONDS,
            "target_size": list(TARGET_SIZE),
            "fps": FPS,
        }
        plan_path = out / f"{variant_id}-render-plan.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

        html = _render_plan_html(variant, plan)
        html_path = out / f"{variant_id}-preview.html"
        html_path.write_text(html, encoding="utf-8")

        metadata = {
            **variant, "render_status": "render_plan_only", "mp4_path": None,
            "render_plan_path": str(plan_path), "preview_html_path": str(html_path),
            "script_path": str(script_path), "srt_path": str(srt_path),
            "install_instructions": deps["install_instructions"],
            "openai_calls": 0, "higgsfield_calls": 0,
        }
        meta_path = out / f"{variant_id}.json"
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return metadata

    import imageio

    frames = []
    for scene_id, effect, seg, asset in zip(
        variant["scene_order"], effects_used, variant["caption_timeline"], variant["required_assets"]
    ):
        base_img = _load_scene_image(asset, TARGET_SIZE)
        n_frames = max(1, round((seg["end_sec"] - seg["start_sec"]) * FPS))
        for f_idx in range(n_frames):
            progress = f_idx / max(1, n_frames - 1)
            frame = _frame_for_effect(base_img, effect, progress, TARGET_SIZE).copy()
            frame = _wrap_and_draw_caption(frame, seg["text"])
            frames.append(frame)

    last_asset = variant["required_assets"][-1]
    cta_base = _load_scene_image(last_asset, TARGET_SIZE)
    cta_frame = _cta_card(variant, cta_base)
    frames.extend([cta_frame] * max(1, round(CTA_CARD_SECONDS * FPS)))

    mp4_path = out / f"{variant_id}.mp4"
    writer = imageio.get_writer(str(mp4_path), fps=FPS, codec="libx264", format="FFMPEG")
    try:
        for frame in frames:
            writer.append_data(_pil_to_array(frame))
    finally:
        writer.close()

    metadata = {
        **variant, "render_status": "rendered", "mp4_path": str(mp4_path),
        "total_frames": len(frames), "fps": FPS, "target_size": list(TARGET_SIZE),
        "effects_used": effects_used, "script_path": str(script_path), "srt_path": str(srt_path),
        "openai_calls": 0, "higgsfield_calls": 0,
    }
    meta_path = out / f"{variant_id}.json"
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def _pil_to_array(img):
    import numpy as np
    return np.asarray(img.convert("RGB"))


def _render_plan_html(variant: dict, plan: dict) -> str:
    rows = "".join(
        f"<tr><td>{s['scene_id']}</td><td>{s['effect']}</td>"
        f"<td>{s['window']['start_sec']}s - {s['window']['end_sec']}s</td>"
        f"<td>{s['window']['text']}</td></tr>"
        for s in plan["scene_effect_plan"]
    )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>{variant['variant_id']} render plan</title></head><body>
<h2>{variant['variant_id']} -- render plan only (MP4 not rendered)</h2>
<p>Missing dependency: {', '.join(plan['install_instructions']) or 'unknown'}</p>
<table border="1" cellpadding="6">
<tr><th>scene</th><th>effect</th><th>window</th><th>caption</th></tr>
{rows}
</table>
<p>CTA: {variant['CTA']}</p>
</body></html>"""


def render_batch(campaign_dir: str, limit: int = 10, batch_name: str = "batch-001",
                 repo_root: str = ".", variant_plan_path=None,
                 duration_min_seconds=None, duration_max_seconds=None) -> dict:
    """Renders up to `limit` variants (in plan order) into
    <campaign_dir>/generated/content-factory/video-renders/<batch_name>/.
    Never calls OpenAI/Higgsfield -- purely local file + PIL/imageio work.
    duration_min/max_seconds optionally narrow variant selection (e.g. the
    first batch is required to stay within 12-20s, tighter than the full
    plan's general 12-25s range)."""
    plan_path = Path(variant_plan_path) if variant_plan_path else (
        Path(repo_root) / campaign_dir / "generated/content-factory/video-variants/video-variant-plan.json")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    out_dir = Path(repo_root) / campaign_dir / "generated/content-factory/video-renders" / batch_name
    out_dir.mkdir(parents=True, exist_ok=True)

    def _in_duration_bounds(v):
        d = v["duration_target_seconds"]
        if duration_min_seconds is not None and d < duration_min_seconds:
            return False
        if duration_max_seconds is not None and d > duration_max_seconds:
            return False
        return True

    candidates = [v for v in plan["variants"] if _in_duration_bounds(v)]

    deps = check_render_dependencies()
    results = []
    seen_hooks = set()
    seen_style_types = set()
    selected = []
    # Pass 1: distinct hook AND distinct style_type (maximizes variety).
    for v in candidates:
        if len(selected) >= limit:
            break
        if v["hook_text"] in seen_hooks or v["style_type"] in seen_style_types:
            continue
        seen_hooks.add(v["hook_text"])
        seen_style_types.add(v["style_type"])
        selected.append(v)
    # Pass 2: distinct hook only (style repeats allowed if needed).
    if len(selected) < limit:
        for v in candidates:
            if len(selected) >= limit:
                break
            if v["hook_text"] in seen_hooks:
                continue
            seen_hooks.add(v["hook_text"])
            selected.append(v)
    # Pass 3: fill remaining slots from candidates regardless of dedup.
    if len(selected) < limit:
        for v in candidates:
            if len(selected) >= limit:
                break
            if v not in selected:
                selected.append(v)

    for v in selected:
        results.append(render_variant(v, str(out_dir), repo_root))

    rendered_count = sum(1 for r in results if r["render_status"] == "rendered")
    summary = {
        "campaign_code": plan["campaign_code"],
        "batch_name": batch_name,
        "requested_limit": limit,
        "duration_min_seconds": duration_min_seconds,
        "duration_max_seconds": duration_max_seconds,
        "variants_processed": len(results),
        "rendered_mp4_count": rendered_count,
        "render_plan_only_count": len(results) - rendered_count,
        "dependency_check": deps,
        "openai_calls": 0,
        "higgsfield_calls": 0,
        "out_dir": str(out_dir),
        "results": [
            {"variant_id": r["variant_id"], "render_status": r["render_status"],
             "mp4_path": r.get("mp4_path"), "hook_text": r["hook_text"],
             "style_type": r["style_type"], "format": r["format"]}
            for r in results
        ],
    }
    summary_path = out_dir / "batch-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary
