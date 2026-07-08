"""Local content-factory planner: builds video-variant-plan.json and
hook-bank.json for campaign coating-protect-2026-07. Pure planning --
resolves existing scene PNGs on disk (never generates new ones), never
calls OpenAI/Higgsfield, never touches product-lock or campaign_visual_lock.

Reuses only the already-reviewed scene-01..07 candidates from
generated/product-reference-only-scene-v2/ -- those PNGs are read-only
inputs here, never promoted to reference and never re-generated.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import content_factory_data as fd

GEN_SCENE_SUBDIR = "generated/product-reference-only-scene-v2"

# Canonical candidate filename per scene, tried in order; first hit wins.
_CANDIDATE_NAME_CANDIDATES = {
    scene_id: (
        f"{scene_id}-product-reference-only-v2-candidate.png",
        f"{scene_id}-c1.png",
    )
    for scene_id in fd.CAMPAIGN_SCENE_ORDER
}

# Simple heuristic fit table (0-100): how well a style suits a format.
_FORMAT_STYLE_FIT = {
    "youtube_shorts": {
        "clean_ad": 82, "ugc_style": 70, "meme_style": 65, "recipe_style": 88,
        "problem_solution": 85, "before_after": 78, "fast_cuts": 74,
        "cozy_kitchen": 80, "animated_caption_style": 76, "comparison_style": 83,
    },
    "instagram_reels": {
        "clean_ad": 78, "ugc_style": 88, "meme_style": 82, "recipe_style": 80,
        "problem_solution": 79, "before_after": 84, "fast_cuts": 81,
        "cozy_kitchen": 86, "animated_caption_style": 83, "comparison_style": 80,
    },
    "tiktok": {
        "clean_ad": 68, "ugc_style": 90, "meme_style": 92, "recipe_style": 75,
        "problem_solution": 80, "before_after": 85, "fast_cuts": 88,
        "cozy_kitchen": 72, "animated_caption_style": 84, "comparison_style": 78,
    },
    "vk_clips": {
        "clean_ad": 80, "ugc_style": 75, "meme_style": 74, "recipe_style": 82,
        "problem_solution": 81, "before_after": 76, "fast_cuts": 72,
        "cozy_kitchen": 83, "animated_caption_style": 73, "comparison_style": 79,
    },
}

_SPACING_HOURS_BY_STYLE_GROUP = {
    "clean_ad": 24, "recipe_style": 24, "cozy_kitchen": 24,
    "ugc_style": 12, "meme_style": 8, "fast_cuts": 8,
    "problem_solution": 18, "before_after": 12,
    "animated_caption_style": 12, "comparison_style": 18,
}


def resolve_scene_asset(scene_id: str, campaign_dir: str, repo_root: str = ".") -> dict:
    """Resolves the best-available local PNG for a scene. Never generates
    anything -- read-only lookup. exists=False (with path=None) if nothing
    is found; callers must not fail, only mark the asset missing."""
    scene_dir = Path(repo_root) / campaign_dir / GEN_SCENE_SUBDIR / scene_id
    for name in _CANDIDATE_NAME_CANDIDATES.get(scene_id, ()):
        candidate = scene_dir / name
        if candidate.is_file():
            return {"scene_id": scene_id, "path": str(candidate).replace("\\", "/"), "exists": True}
    return {"scene_id": scene_id, "path": None, "exists": False}


def _split_duration(duration: float, n_segments: int) -> list:
    """n_segments contiguous (start,end) windows covering [0, duration]."""
    if n_segments <= 0:
        return []
    step = duration / n_segments
    return [(round(i * step, 2), round((i + 1) * step, 2)) for i in range(n_segments)]


def _build_caption_timeline(scene_order: list, duration: float, hook_text: str,
                            on_screen_text: list, cta: str) -> list:
    windows = _split_duration(duration, len(scene_order))
    timeline = []
    for i, ((start, end), text) in enumerate(zip(windows, on_screen_text)):
        caption = hook_text if i == 0 else (cta if i == len(scene_order) - 1 else text)
        timeline.append({"start_sec": start, "end_sec": end, "text": caption})
    return timeline


def _build_on_screen_text(scene_order: list, hook_text: str, cta: str) -> list:
    out = []
    for i, scene_id in enumerate(scene_order):
        if i == 0:
            out.append(hook_text)
        elif i == len(scene_order) - 1:
            out.append(cta)
        else:
            claim = fd.SAFE_CLAIMS[i % len(fd.SAFE_CLAIMS)]
            out.append(claim)
    return out


def _build_voiceover_text(on_screen_text: list) -> str:
    return " ".join(on_screen_text)


def _risk_notes(hook_text: str, cta: str) -> list:
    notes = ["Только сравнительные/практические формулировки -- без медицинских "
             "и абсолютных обещаний ('100% не пачкается' и т.п. запрещены)."]
    lowered = (hook_text + " " + cta).lower()
    for marker in fd.FORBIDDEN_CLAIM_MARKERS:
        if marker in lowered:
            notes.append(f"ВНИМАНИЕ: обнаружен запрещённый маркер '{marker}' -- требуется правка перед публикацией.")
    return notes


def _variant_id(index: int, format_name: str, style_type: str) -> str:
    return f"v{index:03d}-{format_name}-{style_type}"


def build_variant(index: int, format_name: str, style_type: str,
                  hook_category: str, hook_text: str, campaign_dir: str,
                  repo_root: str = ".") -> dict:
    template = fd.STYLE_TEMPLATES[style_type]
    scene_order = list(template["scene_order"])
    dur_min, dur_max = template["duration_range"]
    duration = dur_min + ((dur_max - dur_min) * ((index * 7) % 10) / 10.0)
    duration = round(max(12.0, min(25.0, duration)), 1)

    cta = fd.CTA_BANK[index % len(fd.CTA_BANK)]
    on_screen_text = _build_on_screen_text(scene_order, hook_text, cta)
    caption_timeline = _build_caption_timeline(scene_order, duration, hook_text, on_screen_text, cta)
    voiceover_text = _build_voiceover_text(on_screen_text)

    required_assets = [resolve_scene_asset(s, campaign_dir, repo_root) for s in scene_order]
    render_possible_locally = all(a["exists"] for a in required_assets)

    other_styles_same_format = [s for s in fd.STYLE_TYPES if s != style_type]
    difference_note = (
        f"Формат {format_name}: стиль '{style_type}' ({template['description']}) "
        f"отличается от {', '.join(other_styles_same_format[:3])}... по монтажному "
        f"темпу и порядку сцен ({'->'.join(scene_order)}); хук из категории "
        f"'{hook_category}' уникален для этого варианта."
    )

    variant = {
        "variant_id": _variant_id(index, format_name, style_type),
        "format": format_name,
        "duration_target_seconds": duration,
        "style_type": style_type,
        "hook_text": hook_text,
        "first_3_seconds": f"Крупный план + текст хука поверх сцены {scene_order[0]}: \"{hook_text}\"",
        "scene_order": scene_order,
        "caption_timeline": caption_timeline,
        "voiceover_text": voiceover_text,
        "on_screen_text": on_screen_text,
        "CTA": cta,
        "product_claim_level": template["product_claim_level"],
        "risk_notes": _risk_notes(hook_text, cta),
        "required_assets": required_assets,
        "render_possible_locally": render_possible_locally,
        "creative_angle": f"{hook_category}:{style_type}",
        "difference_from_other_variants": difference_note,
        "avoid_duplicate_posting_note": (
            "Не публиковать этот вариант и другие варианты с тем же creative_angle "
            "на одной платформе в один день -- см. recommended_spacing_hours."
        ),
        "recommended_spacing_hours": _SPACING_HOURS_BY_STYLE_GROUP.get(style_type, 12),
        "platform_fit_score": _FORMAT_STYLE_FIT[format_name][style_type],
    }
    return variant


def generate_video_variant_plan(campaign_dir: str, repo_root: str = ".") -> dict:
    """Full formats x styles combinatorial grid (4 x 10 = 40 variants),
    each with a distinct hook pulled from the hook bank in rotation. Pure
    local planning -- makes ZERO network calls."""
    hooks = fd.all_hooks_flat()  # [(category, text), ...] len == 110
    variants = []
    index = 0
    for style_type in fd.STYLE_TYPES:
        for format_name in fd.FORMATS:
            hook_category, hook_text = hooks[index % len(hooks)]
            variants.append(build_variant(index + 1, format_name, style_type,
                                          hook_category, hook_text, campaign_dir, repo_root))
            index += 1

    missing_assets = sorted({
        a["scene_id"] for v in variants for a in v["required_assets"] if not a["exists"]
    })

    plan = {
        "campaign_code": "coating-protect-2026-07",
        "generated_by": "content_factory_planner.generate_video_variant_plan",
        "total_variants": len(variants),
        "formats": list(fd.FORMATS),
        "style_types": list(fd.STYLE_TYPES),
        "hook_bank_size": fd.total_hook_count(),
        "missing_scene_assets": missing_assets,
        "openai_calls": 0,
        "higgsfield_calls": 0,
        "generated_outputs_used_as_references": False,
        "variants": variants,
    }
    return plan


def build_angle_variant(index: int, angle: str, format_name: str, style_type: str,
                        hook_text: str, batch_name: str, campaign_dir: str,
                        repo_root: str = ".") -> dict:
    """Same shape as build_variant(), but tagged with an explicit
    creative_angle (pain_problem/recipe/meme_conversational/fast_hype)
    instead of the batch-001 'hook_category:style_type' convention, and with
    angle-specific duration bounds / claim level / tone notes applied."""
    template = fd.STYLE_TEMPLATES[style_type]
    scene_order = list(template["scene_order"])
    dur_min, dur_max = fd.ANGLE_DURATION_OVERRIDE.get(angle) or template["duration_range"]
    duration = dur_min + ((dur_max - dur_min) * ((index * 7) % 10) / 10.0)
    duration = round(max(dur_min, min(dur_max, duration)), 1)

    cta = fd.CTA_BANK[index % len(fd.CTA_BANK)]
    on_screen_text = _build_on_screen_text(scene_order, hook_text, cta)
    caption_timeline = _build_caption_timeline(scene_order, duration, hook_text, on_screen_text, cta)
    voiceover_text = _build_voiceover_text(on_screen_text)

    required_assets = [resolve_scene_asset(s, campaign_dir, repo_root) for s in scene_order]
    render_possible_locally = all(a["exists"] for a in required_assets)

    claim_level = fd.ANGLE_PRODUCT_CLAIM_LEVEL.get(angle, template["product_claim_level"])
    tone_note = fd.ANGLE_TONE_NOTES.get(angle, "")
    risk_notes = _risk_notes(hook_text, cta)
    if tone_note:
        risk_notes.append(tone_note)

    difference_note = (
        f"batch={batch_name} angle={angle}: стиль '{style_type}' ({template['description']}) "
        f"формат {format_name}; сцены {'->'.join(scene_order)}; hook уникален в рамках "
        f"этого batch (позиция #{index})."
    )

    variant = {
        "variant_id": f"{batch_name}-v{index:03d}-{format_name}-{style_type}",
        "format": format_name,
        "duration_target_seconds": duration,
        "style_type": style_type,
        "hook_text": hook_text,
        "first_3_seconds": f"Крупный план + текст хука поверх сцены {scene_order[0]}: \"{hook_text}\"",
        "scene_order": scene_order,
        "caption_timeline": caption_timeline,
        "voiceover_text": voiceover_text,
        "on_screen_text": on_screen_text,
        "CTA": cta,
        "product_claim_level": claim_level,
        "risk_notes": risk_notes,
        "required_assets": required_assets,
        "render_possible_locally": render_possible_locally,
        "creative_angle": angle,
        "difference_from_other_variants": difference_note,
        "avoid_duplicate_posting_note": (
            "Не публиковать этот вариант и другие варианты с тем же creative_angle "
            "на одной платформе в один день -- см. recommended_spacing_hours."
        ),
        "recommended_spacing_hours": _SPACING_HOURS_BY_STYLE_GROUP.get(style_type, 12),
        "platform_fit_score": _FORMAT_STYLE_FIT[format_name][style_type],
    }
    return variant


def generate_angle_batch_variants(angle: str, campaign_dir: str, batch_name: str,
                                  count: int = 20, repo_root: str = ".") -> list:
    """count variants for ONE creative angle, hooks pulled (without repeats,
    as long as count <= the angle's hook-category size) from the angle's
    assigned hook category, styles/formats rotated for scene + platform
    variety. Pure local planning -- ZERO network calls."""
    if angle not in fd.CREATIVE_ANGLES:
        raise ValueError(f"unknown creative_angle {angle!r} -- expected one of {fd.CREATIVE_ANGLES}")

    hook_category = fd.ANGLE_HOOK_CATEGORY[angle]
    hooks = list(fd.HOOK_BANK[hook_category])
    styles = fd.ANGLE_STYLE_TYPES[angle]

    variants = []
    for i in range(count):
        hook_text = hooks[i % len(hooks)]
        style_type = styles[i % len(styles)]
        format_name = fd.FORMATS[i % len(fd.FORMATS)]
        variants.append(build_angle_variant(i + 1, angle, format_name, style_type,
                                            hook_text, batch_name, campaign_dir, repo_root))
    return variants


def write_angle_variant_plan(campaign_dir: str, angle: str, batch_name: str,
                             count: int = 20, repo_root: str = ".", out_path=None) -> dict:
    variants = generate_angle_batch_variants(angle, campaign_dir, batch_name, count, repo_root)
    missing_assets = sorted({
        a["scene_id"] for v in variants for a in v["required_assets"] if not a["exists"]
    })
    plan = {
        "campaign_code": "coating-protect-2026-07",
        "batch_name": batch_name,
        "creative_angle": angle,
        "generated_by": "content_factory_planner.generate_angle_batch_variants",
        "total_variants": len(variants),
        "missing_scene_assets": missing_assets,
        "openai_calls": 0,
        "higgsfield_calls": 0,
        "generated_outputs_used_as_references": False,
        "variants": variants,
    }
    out = Path(out_path) if out_path else (
        Path(repo_root) / campaign_dir /
        f"generated/content-factory/video-variants/video-variant-plan-{batch_name}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    plan["report_path"] = str(out)
    return plan


def generate_hook_bank_doc() -> dict:
    doc = {
        "campaign_code": "coating-protect-2026-07",
        "total_hooks": fd.total_hook_count(),
        "categories": {cat: list(fd.HOOK_BANK[cat]) for cat in fd.HOOK_CATEGORY_ORDER},
        "safe_claims_reference": list(fd.SAFE_CLAIMS),
        "forbidden_claim_markers": list(fd.FORBIDDEN_CLAIM_MARKERS),
    }
    return doc


def write_video_variant_plan(campaign_dir: str, repo_root: str = ".", out_path=None) -> dict:
    plan = generate_video_variant_plan(campaign_dir, repo_root)
    out = Path(out_path) if out_path else (
        Path(repo_root) / campaign_dir / "generated/content-factory/video-variants/video-variant-plan.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    plan["report_path"] = str(out)
    return plan


def write_hook_bank(campaign_dir: str, repo_root: str = ".", out_path=None) -> dict:
    doc = generate_hook_bank_doc()
    out = Path(out_path) if out_path else (
        Path(repo_root) / campaign_dir / "generated/content-factory/video-variants/hook-bank.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    doc["report_path"] = str(out)
    return doc
