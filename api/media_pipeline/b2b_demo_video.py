"""B2B demo one-video generation pipeline -- "Демо -- 1 тестовый ролик"
(see api.media_pipeline.seller_intake.DEMO_PACKAGE_DURATION). Lets a seller
check quality on exactly ONE test video before committing to a 7/14/30-day
package: 1 hero scene image, 1 short vertical MP4, captions, a platform
description, and an upload-ready mini kit + ZIP.

Two entry points:
- build_demo_video_dry_run() / write_demo_video_dry_run(): planning only,
  ZERO network calls, works even without OPENAI_API_KEY. Always safe.
- run_demo_video_generation(..., apply=True): the ONLY path that may call
  OpenAI, and only for exactly one image ("edit" call, seller-uploaded
  product photo(s) as reference). Fails closed BEFORE any network call if
  package_mode != demo_1_video, references are missing, or the safety caps
  below are not exactly what this module ships with. Never calls
  Higgsfield, never auto-posts, never touches Railway/production.

Safety caps for --apply (hard-coded, not configurable from outside this
module -- see TASK 8 of the owner's spec):
    MAX_IMAGE_CALLS = 1
    RETRIES = 0
    HARD_CAP_USD = 0.50
    no Higgsfield, no auto-posting, local MP4 render only.

If OPENAI_API_KEY is missing at apply time, this module does NOT crash --
it writes a no_api_key report (candidate_status="no_api_key") and returns.
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import asdict
from pathlib import Path

from . import b2b_storage as st
from . import b2b_reference_policy as pol
from . import product_intelligence as pi
from . import seller_intake as si
from .budget import SpendTracker
from .models import ImageRequest
from .openai_images_client import MissingAPIKeyError, OpenAIImagesProvider

# -- safety caps for --apply (see module docstring / TASK 8) ----------------
MODEL = "gpt-image-2"
SIZE = "720x1280"
OUTPUT_FORMAT = "png"
N = 1
RETRIES = 0
MAX_IMAGE_CALLS = 1
HARD_CAP_USD = 0.50
PRICE_PER_IMAGE_USD_ESTIMATE = 0.30
MAX_REFERENCE_IMAGES_SENT = 3  # highest-priority uploaded refs only, keeps the edit call small

TARGET_SIZE = (720, 1280)  # (width, height), 9:16
FPS = 24
VIDEO_DURATION_SECONDS = 15.0
CTA_CARD_SECONDS = 1.5

REFERENCE_ROLE_PRIORITY = ("front", "top", "side", "detail", "packaging", "other")

# TASK 3: universal, category-driven scene context -- never hardcodes a
# specific product (e.g. airfryer). Keys match product_intelligence
# .CATEGORY_TEMPLATES / GENERIC_FALLBACK_TEMPLATE's matched_category values.
SCENE_CONTEXT_BY_CATEGORY = {
    "airfryer_silicone_form": "cozy modern kitchen countertop near an air fryer, warm natural daylight, everyday kitchen use-case context",
    "flashlight": "dark outdoor or car-interior context at night (roadside, camping, or a power outage), the product's beam clearly visible",
    "organizer_container": "tidy home storage shelf, drawer, or closet, a clean before/after home-organization context",
    "kitchen_accessory_generic": "cozy modern kitchen countertop, warm natural daylight, everyday kitchen use-case context",
    "beauty_selfcare_accessory": "clean beauty/vanity table setup, soft flattering light, a self-care routine context",
    "simple_home_utility": "clean modern home desk, entryway, or car interior, an everyday household use-case context",
    "generic_fallback": "simple, clean, neutral setting appropriate to how this product is normally used",
}

ANGLE_FRAMING = {
    "pain_problem": (
        "The scene should visually hint at the everyday frustration the product solves, then "
        "present the product itself as the clear, hero-lit solution."
    ),
    "demo_use_case": (
        "The scene should show the product in active, believable everyday use for its real "
        "purpose, demonstrating exactly how it works."
    ),
    "benefit_convenience": (
        "The scene should emphasize how convenient, easy, and pleasant the product makes "
        "everyday life, with a clean, aspirational feel."
    ),
}

BASE_PROMPT_RULES = (
    "Vertical 9:16 realistic product advertisement photo. The product must be clearly visible "
    "and in sharp focus, matching the uploaded reference photo(s) exactly (same shape, color, "
    "material, proportions -- do not redesign the product). Simple, clean, uncluttered "
    "background appropriate to the scene context below. No text, no captions, no numbers, no "
    "watermark, no logo anywhere in the image. Photorealistic, natural lighting, DSLR-style "
    "photo look. Not CGI, not an illustration, not a 3D render."
)

NEGATIVE_PROMPT = (
    "text, caption, watermark, logo, brand name, extra duplicate products, cluttered "
    "background, CGI look, 3D render, illustration, cartoon, blurry, distorted product shape, "
    "deformed hands, extra limbs"
)

PLANNED_OUTPUT_FILES = (
    "generated/demo-video/demo-video-dry-run.json",
    "generated/demo-video/demo-video-dry-run.md",
    "generated/demo-video/demo-video-candidate.png",
    "generated/demo-video/demo-video-test.mp4",
    "generated/demo-video/demo-video-script.txt",
    "generated/demo-video/demo-video-caption.srt",
    "generated/demo-video/demo-video-platform-description.md",
    "generated/demo-video/demo-video-generation-report.json",
    "generated/demo-video/demo-video-generation-report.md",
    "generated/demo-video/upload-ready/test-video.mp4",
    "generated/demo-video/upload-ready/DESCRIPTION-TO-COPY.md",
    "generated/demo-video/upload-ready/SCRIPT.txt",
    "generated/demo-video/upload-ready/README.md",
    "generated/demo-video/DEMO-ONE-VIDEO-KIT.zip",
)

UPLOAD_READY_README = (
    "# Тестовый ролик -- upload-ready комплект\n\n"
    "Это тестовый ролик для проверки идеи. Это не полный контент-пакет.\n\n"
    "Используйте его, чтобы посмотреть, как система понимает ваш товар и какой "
    "рекламный ролик она предлагает, прежде чем запускать пакет на 7/14/30 дней.\n\n"
    "- `test-video.mp4` -- готовый вертикальный ролик с подписями.\n"
    "- `SCRIPT.txt` -- текст хука/озвучки/CTA.\n"
    "- `DESCRIPTION-TO-COPY.md` -- готовое описание для выбранной площадки "
    "(заголовок, описание, хэштеги, CTA, ссылка на товар).\n"
)

WEAK_DESCRIPTION_WARNING = (
    "Описание/ссылка товара заполнены слабо, перед публикацией проверьте вручную."
)


class B2BDemoVideoError(RuntimeError):
    """Fail-closed error for the demo-video pipeline. Raised BEFORE any
    network call whenever a precondition (package mode, references, safety
    caps) isn't satisfied."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _demo_video_dir(client_id: str, product_id: str, campaign_id: str, repo_root: str = ".") -> Path:
    return st.campaign_generated_dir(client_id, product_id, campaign_id, repo_root) / "demo-video"


def choose_references(usable_refs: list, limit: int = MAX_REFERENCE_IMAGES_SENT) -> list:
    """Picks up to `limit` usable references, preferring front/top/side/
    detail/packaging over 'other', in that order -- never invents a
    reference, never falls back to a generated/candidate path (usable_refs
    is already filtered by b2b_reference_policy.assert_campaign_generation_
    allowed before this is called)."""
    if not usable_refs:
        raise B2BDemoVideoError("NO_USABLE_REFERENCES",
                                "no usable product references to choose from")

    def _rank(ref):
        try:
            return REFERENCE_ROLE_PRIORITY.index(ref.role)
        except ValueError:
            return len(REFERENCE_ROLE_PRIORITY)

    ordered = sorted(usable_refs, key=_rank)
    return ordered[:limit]


def resolve_primary_angle(intel_report: dict) -> str:
    """TASK 3 selection rule: an explicit single-angle choice is always
    honored; multi_angle_test (the MVP default) resolves to pain_problem
    when the core problem is a confident, category-matched or manually
    overridden hypothesis, otherwise demo_use_case (safer generic angle for
    a low-confidence guess)."""
    selected = intel_report.get("selected_ad_strategy", "multi_angle_test")
    if selected in ("pain_problem", "demo_use_case", "benefit_convenience"):
        return selected
    core_problem_known = (intel_report.get("matched_category") != "generic_fallback" or
                          intel_report.get("manual_override_present", False))
    return "pain_problem" if core_problem_known else "demo_use_case"


def resolve_scene_context(matched_category: str) -> str:
    return SCENE_CONTEXT_BY_CATEGORY.get(matched_category, SCENE_CONTEXT_BY_CATEGORY["generic_fallback"])


def choose_platform(campaign: "st.Campaign") -> str:
    platforms = campaign.platforms or list(st.CAMPAIGN_PLATFORMS)
    video_platforms = [p for p in platforms if p != "dzen"]
    return video_platforms[0] if video_platforms else "youtube_shorts"


def build_image_prompt(product: "st.Product", intel_report: dict, angle: str) -> str:
    scene_context = resolve_scene_context(intel_report["matched_category"])
    angle_framing = ANGLE_FRAMING[angle]
    core_problem = intel_report.get("core_problem_solved", "")
    return (
        f"{BASE_PROMPT_RULES} Scene context: {scene_context}. Product: {product.product_name} "
        f"({product.category or 'consumer product'}). {angle_framing} Core problem this "
        f"product solves for the viewer: {core_problem}"
    )


def build_video_script(intel_report: dict, product: "st.Product", angle: str) -> dict:
    ad_options = {o["strategy_id"]: o for o in intel_report.get("ad_strategy_options", [])}
    angle_option = ad_options.get(angle, {})
    hook = angle_option.get("example_hook") or f"Познакомьтесь с {product.product_name}"
    main_message = angle_option.get("main_message") or intel_report.get("core_problem_solved", "")
    cta = f"Смотрите {product.product_name} по ссылке в описании"
    return {
        "angle": angle,
        "hook": hook,
        "body": main_message,
        "cta": cta,
        "voiceover_text": f"{hook} {main_message} {cta}".strip(),
        "audio_status": "no_voiceover",
    }


def build_caption_timeline(script: dict, duration_seconds: float = VIDEO_DURATION_SECONDS) -> list:
    """3 evenly-spaced caption segments (hook / body / CTA) spanning the
    full clip duration -- same shape as content_factory_renderer's
    caption_timeline (start_sec/end_sec/text), so build_srt()-style tooling
    can reuse it directly."""
    hook_end = round(duration_seconds * 0.25, 2)
    body_end = round(duration_seconds * 0.8, 2)
    return [
        {"start_sec": 0.0, "end_sec": hook_end, "text": script["hook"]},
        {"start_sec": hook_end, "end_sec": body_end, "text": script["body"]},
        {"start_sec": body_end, "end_sec": duration_seconds, "text": script["cta"]},
    ]


def build_script_txt(script: dict) -> str:
    return (
        f"HOOK: {script['hook']}\n\n"
        f"BODY: {script['body']}\n\n"
        f"CTA: {script['cta']}\n\n"
        f"VOICEOVER (metadata only, audio_status={script['audio_status']}): {script['voiceover_text']}\n"
    )


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


def _hashtags_for(product: "st.Product", intel_report: dict) -> list:
    words = set()
    for source in (product.category, intel_report.get("matched_category", "").replace("_", " ")):
        for w in (source or "").split():
            w = "".join(ch for ch in w.lower() if ch.isalnum())
            if len(w) >= 3:
                words.add(w)
    tags = [f"#{w}" for w in sorted(words)][:5]
    tags.append("#реклама")
    return tags


def build_platform_description(product: "st.Product", campaign: "st.Campaign",
                               intel_report: dict, angle: str, platform: str) -> dict:
    ad_options = {o["strategy_id"]: o for o in intel_report.get("ad_strategy_options", [])}
    angle_option = ad_options.get(angle, {})
    marketplace_link = product.marketplace_url or product.marketplace_article or ""

    title = f"{product.product_name} -- {angle_option.get('title', 'реклама')}"[:100]
    description = (angle_option.get("main_message") or intel_report.get("core_problem_solved", ""))
    cta = f"Смотрите {product.product_name} по ссылке в описании"
    hashtags = _hashtags_for(product, intel_report)

    warnings = []
    has_link = bool(product.marketplace_url or product.marketplace_article)
    has_description = bool(product.product_description and len(product.product_description.strip()) >= 10)
    if not (has_link and has_description):
        warnings.append(WEAK_DESCRIPTION_WARNING)

    return {
        "platform": platform,
        "title": title,
        "description": description,
        "hashtags": hashtags,
        "cta": cta,
        "marketplace_link": marketplace_link,
        "warnings": warnings,
    }


def build_platform_description_md(platform_description: dict) -> str:
    lines = [
        f"# Описание для площадки: {platform_description['platform']}",
        "",
        f"**Заголовок:** {platform_description['title']}",
        "",
        f"**Описание:** {platform_description['description']}",
        "",
        f"**CTA:** {platform_description['cta']}",
        "",
        f"**Ссылка на товар:** {platform_description['marketplace_link'] or '(не указана)'}",
        "",
        f"**Хэштеги:** {' '.join(platform_description['hashtags'])}",
    ]
    if platform_description["warnings"]:
        lines += ["", "## Внимание"]
        for w in platform_description["warnings"]:
            lines.append(f"- {w}")
    return "\n".join(lines) + "\n"


def _safety_gates_summary() -> dict:
    return {
        "max_image_calls": MAX_IMAGE_CALLS,
        "retries": RETRIES,
        "hard_cap_usd": HARD_CAP_USD,
        "higgsfield_calls_allowed": 0,
        "video_api_allowed": False,
        "local_mp4_render_only": True,
        "auto_posting_allowed": False,
    }


def _build_demo_video_plan(client_id: str, product_id: str, campaign_id: str,
                           repo_root: str = ".") -> dict:
    """Shared planning logic for both the dry-run report and the --apply
    runner -- builds the exact same prompt/script/platform description
    either way, so what --apply sends is never a surprise vs. what --dry-run
    showed. Fail-closed: raises B2BDemoVideoError / B2BReferencePolicyError
    before any network-adjacent work if preconditions aren't met."""
    client = st.load_client(client_id, repo_root)
    product = st.load_product(client_id, product_id, repo_root)
    campaign = st.load_campaign(client_id, product_id, campaign_id, repo_root)

    intake = si.load_seller_intake(client_id, product_id, repo_root)
    package_mode = (intake or {}).get("content_package_settings", {}).get("package_duration")
    if package_mode != si.DEMO_PACKAGE_DURATION:
        raise B2BDemoVideoError(
            "WRONG_PACKAGE_MODE",
            f"demo video generation requires package_mode={si.DEMO_PACKAGE_DURATION!r}, "
            f"got {package_mode!r} -- select 'Демо -- 1 тестовый ролик' in step 5 first")

    # TASK 2: fail-closed reference gate -- seller-uploaded references only,
    # generated/candidate/delivery paths are rejected by this same policy
    # used everywhere else in the B2B pipeline.
    usable_refs = pol.assert_campaign_generation_allowed(
        client_id, product_id, repo_root, strict_approved_refs_required=False)
    chosen_refs = choose_references(usable_refs)
    ref_paths = [r.file_path for r in usable_refs]
    forbidden_scan = pol.scan_reference_images_list(ref_paths, repo_root)
    reference_quality = pol.build_reference_quality(client_id, product_id, repo_root)

    envelope = pi.load_product_intelligence(client_id, product_id, repo_root)
    if envelope is None:
        envelope = pi.write_product_intelligence(client_id, product_id, repo_root)
    intel_report = envelope["report"]

    angle = resolve_primary_angle(intel_report)
    image_prompt = build_image_prompt(product, intel_report, angle)
    platform = choose_platform(campaign)
    script = build_video_script(intel_report, product, angle)
    caption_timeline = build_caption_timeline(script)
    platform_description = build_platform_description(product, campaign, intel_report, angle, platform)

    return {
        "client": client, "product": product, "campaign": campaign,
        "package_mode": package_mode,
        "usable_refs": usable_refs, "chosen_refs": chosen_refs,
        "forbidden_scan": forbidden_scan, "reference_quality": reference_quality,
        "envelope": envelope, "intel_report": intel_report,
        "angle": angle, "image_prompt": image_prompt, "platform": platform,
        "script": script, "caption_timeline": caption_timeline,
        "platform_description": platform_description,
    }


def build_demo_video_dry_run(client_id: str, product_id: str, campaign_id: str,
                             repo_root: str = ".") -> dict:
    ctx = _build_demo_video_plan(client_id, product_id, campaign_id, repo_root)
    estimated_cost = round(N * PRICE_PER_IMAGE_USD_ESTIMATE, 2)

    return {
        "status": "dry_run_only",
        "mode": "dry_run",
        "package_mode": ctx["package_mode"],
        "product_summary": {
            "product_name": ctx["product"].product_name,
            "category": ctx["product"].category,
            "marketplace": ctx["product"].marketplace,
            "marketplace_article": ctx["product"].marketplace_article,
            "marketplace_url": ctx["product"].marketplace_url,
        },
        "client": asdict(ctx["client"]), "product": asdict(ctx["product"]),
        "campaign": asdict(ctx["campaign"]),
        "selected_ad_strategy": ctx["intel_report"].get("selected_ad_strategy", "multi_angle_test"),
        "resolved_angle": ctx["angle"],
        "chosen_platform": ctx["platform"],
        "chosen_product_references": [asdict(r) for r in ctx["chosen_refs"]],
        "usable_product_references": [asdict(r) for r in ctx["usable_refs"]],
        "reference_quality": ctx["reference_quality"],
        "forbidden_refs_scan": ctx["forbidden_scan"],
        "image_prompt": ctx["image_prompt"],
        "negative_prompt": NEGATIVE_PROMPT,
        "script": ctx["script"],
        "caption_timeline": ctx["caption_timeline"],
        "platform_description": ctx["platform_description"],
        "planned_output_files": list(PLANNED_OUTPUT_FILES),
        "estimated_image_calls": N,
        "estimated_local_mp4_renders": 1,
        "estimated_cost_usd": estimated_cost,
        "apply_allowed": False,
        "safety_gates": _safety_gates_summary(),
        "openai_calls": 0,
        "higgsfield_calls": 0,
        "external_api_calls": 0,
        "auto_posting_triggered": False,
    }


def render_demo_video_dry_run_md(plan: dict) -> str:
    lines = [
        f"# Demo video dry-run: {plan['campaign']['campaign_id']}",
        "",
        f"Status: **{plan['status']}** -- no OpenAI/Higgsfield calls made "
        f"(openai_calls={plan['openai_calls']}, higgsfield_calls={plan['higgsfield_calls']}, "
        f"external_api_calls={plan['external_api_calls']}, "
        f"auto_posting_triggered={plan['auto_posting_triggered']}).",
        "",
        f"- package_mode: {plan['package_mode']}",
        f"- selected_ad_strategy: {plan['selected_ad_strategy']}",
        f"- resolved_angle: {plan['resolved_angle']}",
        f"- chosen_platform: {plan['chosen_platform']}",
        "",
        "## Product",
        "",
        f"- {plan['product_summary']['product_name']} ({plan['product_summary']['marketplace']} / "
        f"{plan['product_summary']['marketplace_article'] or '-'})",
        f"- category: {plan['product_summary']['category'] or '-'}",
        "",
        f"## Chosen product references ({len(plan['chosen_product_references'])})",
        "",
    ]
    for r in plan["chosen_product_references"]:
        lines.append(f"- `{r['file_path']}` (role={r['role']})")
    lines += [
        "",
        "## Image prompt (English, sent to the image model)",
        "",
        plan["image_prompt"],
        "",
        "## Negative prompt",
        "",
        plan["negative_prompt"],
        "",
        "## Script",
        "",
        f"- HOOK: {plan['script']['hook']}",
        f"- BODY: {plan['script']['body']}",
        f"- CTA: {plan['script']['cta']}",
        f"- audio_status: {plan['script']['audio_status']}",
        "",
        "## Planned output files",
        "",
    ]
    for f in plan["planned_output_files"]:
        lines.append(f"- {f}")
    lines += [
        "",
        "## Estimated cost",
        "",
        f"- Estimated image calls: {plan['estimated_image_calls']}",
        f"- Estimated local MP4 renders: {plan['estimated_local_mp4_renders']}",
        f"- Estimated cost: ${plan['estimated_cost_usd']}",
        f"- apply_allowed: {plan['apply_allowed']}",
        "",
        "## Safety gates (for --apply)",
        "",
    ]
    for k, v in plan["safety_gates"].items():
        lines.append(f"- {k}: {v}")
    return "\n".join(lines) + "\n"


def write_demo_video_dry_run(client_id: str, product_id: str, campaign_id: str,
                             repo_root: str = ".", out_path=None) -> dict:
    plan = build_demo_video_dry_run(client_id, product_id, campaign_id, repo_root)
    out_dir = _demo_video_dir(client_id, product_id, campaign_id, repo_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = Path(out_path) if out_path else (out_dir / "demo-video-dry-run.json")
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    plan["report_path"] = str(out)

    md_out = out.with_suffix(".md")
    md_out.write_text(render_demo_video_dry_run_md(plan), encoding="utf-8")
    plan["report_md_path"] = str(md_out)
    return plan


# -- local MP4 render (no network) ------------------------------------------

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
        missing.append("imageio-ffmpeg (pip install imageio-ffmpeg)")
    return {
        "pillow_available": pil_ok, "imageio_available": imageio_ok,
        "ffmpeg_available": ffmpeg_ok,
        "can_render_mp4": pil_ok and imageio_ok and ffmpeg_ok,
        "install_instructions": missing,
    }


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


def _zoom_frame(base_img, progress: float, size=TARGET_SIZE):
    scale = 1.0 + 0.15 * progress
    w, h = size
    win_w, win_h = w / scale, h / scale
    left = max(0.0, (w - win_w) / 2)
    top = max(0.0, (h - win_h) / 2)
    box = (left, top, left + win_w, top + win_h)
    return base_img.resize(size, box=box)


def _pil_to_array(img):
    import numpy as np
    return np.asarray(img.convert("RGB"))


def render_demo_video(candidate_image_path: str, caption_timeline: list, cta_text: str,
                      out_dir: str, duration_seconds: float = VIDEO_DURATION_SECONDS) -> dict:
    """Renders demo-video-test.mp4 (+ .srt) from ONE candidate image: a slow
    zoom over the full clip with timed captions, closing on a short CTA
    card. Never calls OpenAI/Higgsfield. Falls back to a render-plan JSON
    (never raises) if PIL/imageio/ffmpeg aren't available -- same honest
    fallback contract as content_factory_renderer.render_variant."""
    from PIL import Image

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    mp4_path = out / "demo-video-test.mp4"
    srt_path = out / "demo-video-caption.srt"
    srt_path.write_text(build_srt(caption_timeline), encoding="utf-8")

    deps = check_render_dependencies()
    if not deps["can_render_mp4"]:
        plan = {
            "render_status": "render_plan_only",
            "reason": "Missing local rendering dependency.",
            "install_instructions": deps["install_instructions"],
            "caption_timeline": caption_timeline,
            "target_size": list(TARGET_SIZE), "fps": FPS,
        }
        plan_path = out / "demo-video-test-render-plan.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"render_status": "render_plan_only", "mp4_path": None,
               "render_plan_path": str(plan_path), "srt_path": str(srt_path),
               "install_instructions": deps["install_instructions"]}

    import imageio

    base_img = Image.open(candidate_image_path).convert("RGB")
    if base_img.size != TARGET_SIZE:
        base_img = base_img.resize(TARGET_SIZE)

    frames = []
    n_frames = max(1, round(duration_seconds * FPS))
    for f_idx in range(n_frames):
        progress = f_idx / max(1, n_frames - 1)
        t = f_idx / FPS
        frame = _zoom_frame(base_img, progress).copy()
        caption = next((seg["text"] for seg in caption_timeline
                        if seg["start_sec"] <= t < seg["end_sec"]), "")
        frame = _wrap_and_draw_caption(frame, caption)
        frames.append(frame)

    cta_base = base_img.copy()
    overlay = Image.new("RGB", cta_base.size, (20, 20, 20))
    cta_frame = Image.blend(cta_base, overlay, 0.45)
    cta_frame = _wrap_and_draw_caption(cta_frame, cta_text)
    frames.extend([cta_frame] * max(1, round(CTA_CARD_SECONDS * FPS)))

    writer = imageio.get_writer(str(mp4_path), fps=FPS, codec="libx264", format="FFMPEG")
    try:
        for frame in frames:
            writer.append_data(_pil_to_array(frame))
    finally:
        writer.close()

    return {"render_status": "rendered", "mp4_path": str(mp4_path),
           "srt_path": str(srt_path), "total_frames": len(frames), "fps": FPS,
           "target_size": list(TARGET_SIZE)}


# -- upload-ready mini kit + ZIP (TASK 6) ------------------------------------

def build_upload_ready_kit(demo_video_dir: str, mp4_path: str, script: dict,
                           platform_description: dict) -> dict:
    upload_dir = Path(demo_video_dir) / "upload-ready"
    upload_dir.mkdir(parents=True, exist_ok=True)

    import shutil
    dest_mp4 = upload_dir / "test-video.mp4"
    shutil.copyfile(mp4_path, dest_mp4)

    desc_path = upload_dir / "DESCRIPTION-TO-COPY.md"
    desc_path.write_text(build_platform_description_md(platform_description), encoding="utf-8")

    script_path = upload_dir / "SCRIPT.txt"
    script_path.write_text(build_script_txt(script), encoding="utf-8")

    readme_path = upload_dir / "README.md"
    readme_path.write_text(UPLOAD_READY_README, encoding="utf-8")

    return {"upload_ready_dir": str(upload_dir), "mp4_path": str(dest_mp4),
           "description_path": str(desc_path), "script_path": str(script_path),
           "readme_path": str(readme_path)}


def build_demo_video_kit_zip(demo_video_dir: str, upload_ready: dict, out_path=None) -> dict:
    upload_dir = Path(upload_ready["upload_ready_dir"])
    out = Path(out_path) if out_path else (Path(demo_video_dir) / "DEMO-ONE-VIDEO-KIT.zip")

    added = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(upload_dir.rglob("*")):
            if f.is_file():
                arcname = f"upload-ready/{f.relative_to(upload_dir).as_posix()}"
                zf.write(f, arcname=arcname)
                added.append(arcname)

    return {"zip_path": str(out), "files_added": len(added)}


# -- apply: the ONLY path that may call OpenAI (TASK 8 safety gates) --------

def run_demo_video_generation(client_id: str, product_id: str, campaign_id: str,
                              repo_root: str = ".", apply: bool = False) -> dict:
    """apply=False: builds the same plan as write_demo_video_dry_run() but
    does not write any files (callers wanting the dry-run report should use
    write_demo_video_dry_run() instead -- this branch exists only so the
    function signature mirrors the rest of the codebase's runner pattern).

    apply=True: enforces the hard-coded safety caps BEFORE any network
    call, makes AT MOST one OpenAI image edit call using up to
    MAX_REFERENCE_IMAGES_SENT seller-uploaded product references, then
    renders the local MP4, writes the platform description, builds the
    upload-ready mini kit + ZIP, and a generation report. Never calls
    Higgsfield, never auto-posts. If OPENAI_API_KEY is missing, does not
    raise -- writes a no_api_key report and returns it."""
    ctx = _build_demo_video_plan(client_id, product_id, campaign_id, repo_root)
    out_dir = _demo_video_dir(client_id, product_id, campaign_id, repo_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not apply:
        plan = build_demo_video_dry_run(client_id, product_id, campaign_id, repo_root)
        plan["candidate_status"] = "planned_only"
        return plan

    # TASK 8: safety gates -- fail closed, BEFORE any network call.
    if ctx["package_mode"] != si.DEMO_PACKAGE_DURATION:
        raise B2BDemoVideoError("WRONG_PACKAGE_MODE", "package_mode must be demo_1_video for --apply")
    if len(ctx["usable_refs"]) < pol.MIN_SELLER_FLOW_REFERENCES:
        raise B2BDemoVideoError("NO_REFERENCES_UPLOADED",
                                f"need >= {pol.MIN_SELLER_FLOW_REFERENCES} uploaded product reference")
    if MAX_IMAGE_CALLS != 1:
        raise B2BDemoVideoError("MAX_CALLS_VIOLATION", f"max_image_calls={MAX_IMAGE_CALLS} != 1")
    if RETRIES != 0:
        raise B2BDemoVideoError("RETRIES_VIOLATION", f"retries={RETRIES} != 0")
    if HARD_CAP_USD > 0.50:
        raise B2BDemoVideoError("HARD_CAP_TOO_HIGH", f"hard_cap_usd={HARD_CAP_USD} > 0.50")

    ref_paths = [str(Path(repo_root) / r.file_path) for r in ctx["chosen_refs"]]
    req = ImageRequest(scene_id="demo-video", prompt=ctx["image_prompt"], n=N, size=SIZE,
                       mode="edit", reference_images=ref_paths, output_format=OUTPUT_FORMAT)
    tracker = SpendTracker(cap_usd=HARD_CAP_USD)
    provider = OpenAIImagesProvider(model=MODEL, tracker=tracker,
                                    price_per_image_usd=PRICE_PER_IMAGE_USD_ESTIMATE)

    report_base = {
        "status": "apply",
        "mode": "apply",
        "package_mode": ctx["package_mode"],
        "resolved_angle": ctx["angle"],
        "chosen_platform": ctx["platform"],
        "chosen_product_references": [asdict(r) for r in ctx["chosen_refs"]],
        "image_prompt": ctx["image_prompt"],
        "negative_prompt": NEGATIVE_PROMPT,
        "script": ctx["script"],
        "safety_gates": _safety_gates_summary(),
        "higgsfield_calls": 0,
        "auto_posting_triggered": False,
        "external_api_calls": 0,
    }

    try:
        results = provider.generate(req, out_dir=str(out_dir), apply=True)
    except MissingAPIKeyError:
        # TASK 8: never crash dirty -- honest no_api_key report instead.
        script_path = out_dir / "demo-video-script.txt"
        script_path.write_text(build_script_txt(ctx["script"]), encoding="utf-8")
        srt_path = out_dir / "demo-video-caption.srt"
        srt_path.write_text(build_srt(ctx["caption_timeline"]), encoding="utf-8")
        pd_path = out_dir / "demo-video-platform-description.md"
        pd_path.write_text(build_platform_description_md(ctx["platform_description"]), encoding="utf-8")

        report = {
            **report_base,
            "candidate_status": "no_api_key",
            "openai_calls": 0,
            "api_spend_usd": 0.0,
            "budget": tracker.summary(),
            "files_written": [str(script_path), str(srt_path), str(pd_path)],
            "note": ("OPENAI_API_KEY отсутствует в environment -- реальный вызов не выполнен. "
                    "Скрипт/подписи/описание площадки сохранены, изображение и MP4 не созданы."),
        }
        report_path = out_dir / "demo-video-generation-report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_path"] = str(report_path)
        return report

    candidate_result = results[0]
    candidate_src = Path(candidate_result.image_path)
    candidate_path = out_dir / "demo-video-candidate.png"
    if candidate_src != candidate_path:
        candidate_src.replace(candidate_path)

    render_result = render_demo_video(str(candidate_path), ctx["caption_timeline"],
                                      ctx["script"]["cta"], str(out_dir))

    script_path = out_dir / "demo-video-script.txt"
    script_path.write_text(build_script_txt(ctx["script"]), encoding="utf-8")
    pd_path = out_dir / "demo-video-platform-description.md"
    pd_path.write_text(build_platform_description_md(ctx["platform_description"]), encoding="utf-8")

    upload_ready = None
    kit_zip = None
    if render_result["render_status"] == "rendered":
        upload_ready = build_upload_ready_kit(str(out_dir), render_result["mp4_path"],
                                              ctx["script"], ctx["platform_description"])
        kit_zip = build_demo_video_kit_zip(str(out_dir), upload_ready)

    report = {
        **report_base,
        "candidate_status": "generated",
        "candidate_image_path": str(candidate_path),
        "render_result": render_result,
        "upload_ready": upload_ready,
        "kit_zip": kit_zip,
        "openai_calls": 1,
        "api_spend_usd": tracker.total_actual(),
        "budget": tracker.summary(),
        "script_path": str(script_path),
        "platform_description_path": str(pd_path),
    }
    report_path = out_dir / "demo-video-generation-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)

    md_lines = [
        f"# Demo video generation report",
        "",
        f"- candidate_status: {report['candidate_status']}",
        f"- render_status: {render_result['render_status']}",
        f"- mp4: {render_result.get('mp4_path') or '(not rendered)'}",
        f"- upload_ready_kit: {'yes' if upload_ready else 'no'}",
        f"- kit_zip: {kit_zip['zip_path'] if kit_zip else '(not built)'}",
        f"- api_spend_usd: {report['api_spend_usd']}",
        f"- openai_calls: {report['openai_calls']} | higgsfield_calls: {report['higgsfield_calls']} | "
        f"auto_posting_triggered: {report['auto_posting_triggered']}",
    ]
    report_md_path = out_dir / "demo-video-generation-report.md"
    report_md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    report["report_md_path"] = str(report_md_path)
    return report
