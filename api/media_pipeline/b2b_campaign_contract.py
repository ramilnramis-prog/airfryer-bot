"""Universal B2B campaign generation contract -- DRY-RUN ONLY at this step.
Describes what WOULD be generated for a client/product/campaign without
making any OpenAI/Higgsfield/external API call. Always gated by the
fail-closed reference policy first (api.media_pipeline.b2b_reference_policy)
-- a campaign with no/insufficient approved product references never gets a
plan at all, it gets a clear policy error instead."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from . import b2b_storage as st
from . import b2b_reference_policy as pol

# Planning constants -- same shape/order of magnitude as the proven
# single-campaign pipeline (content_factory_planner / product_reference_
# only_runner / content_factory_dzen_publishing), generalized per seller.
PLANNED_SCENE_COUNT = 7
PLANNED_VIDEO_VARIANT_COUNT = 40          # 4 platforms x 10 creative styles
PLANNED_DZEN_ARTICLE_COUNT = 7
PLANNED_IMAGES_PER_DZEN_ARTICLE = 5
IMAGE_PRICE_PER_CALL_USD = 0.30
VIDEO_RENDER_PRICE_PER_CALL_USD = 0.0     # local PIL+ffmpeg renderer, no per-call API cost

SCENE_NARRATIVE_TEMPLATE = (
    "hook/attention", "problem", "product introduction", "usage/food prep",
    "result", "cleaning/benefit", "CTA beauty shot",
)

CREATIVE_ANGLES = ("pain_problem", "recipe", "meme_conversational", "fast_hype",
                  "product_beauty_clean")

DZEN_ARTICLE_TYPES = ("problem_solution", "recipe", "lifehack", "soft_ad", "comparison")


def build_campaign_dry_run(client_id: str, product_id: str, campaign_id: str,
                           repo_root: str = ".") -> dict:
    client = st.load_client(client_id, repo_root)
    product = st.load_product(client_id, product_id, repo_root)
    campaign = st.load_campaign(client_id, product_id, campaign_id, repo_root)

    # Fail-closed reference gate -- raises B2BReferencePolicyError (never
    # silently substitutes a placeholder) if references are missing/invalid.
    approved_refs = pol.assert_campaign_generation_allowed(client_id, product_id, repo_root)
    ref_paths = [r.file_path for r in approved_refs]
    forbidden_scan = pol.scan_reference_images_list(ref_paths, repo_root)

    planned_scenes = [
        {"scene_id": f"scene-{i:02d}", "narrative_beat": beat, "uses_product_reference": True}
        for i, beat in enumerate(SCENE_NARRATIVE_TEMPLATE, start=1)
    ]

    platforms = campaign.platforms or list(st.CAMPAIGN_PLATFORMS)
    video_platforms = [p for p in platforms if p != "dzen"]
    planned_video_variants = {
        "total_variants": PLANNED_VIDEO_VARIANT_COUNT,
        "platforms": video_platforms,
        "creative_angles": list(CREATIVE_ANGLES),
        "note": ("Same combinatorial shape as the proven single-campaign pipeline: "
                "creative angle x platform, each variant reusing only the approved "
                "product references, no new image generation for the variant grid itself."),
    }

    dzen_enabled = "dzen" in platforms
    planned_dzen_articles = {
        "total_articles": PLANNED_DZEN_ARTICLE_COUNT if dzen_enabled else 0,
        "article_types": list(DZEN_ARTICLE_TYPES) if dzen_enabled else [],
        "images_per_article": PLANNED_IMAGES_PER_DZEN_ARTICLE if dzen_enabled else 0,
    }

    planned_publishing_queue = {
        "video_posting_times": ["12:30", "16:30", "20:30"] if video_platforms else [],
        "dzen_posting_times": ["10:30", "19:00"] if dzen_enabled else [],
        "note": "14-day rotating queue, same shape as the proven single-campaign pipeline.",
    }

    estimated_image_calls = (
        PLANNED_SCENE_COUNT +
        (planned_dzen_articles["total_articles"] * planned_dzen_articles["images_per_article"])
    )
    estimated_video_renders = PLANNED_VIDEO_VARIANT_COUNT if video_platforms else 0
    estimated_cost_usd = round(estimated_image_calls * IMAGE_PRICE_PER_CALL_USD +
                              estimated_video_renders * VIDEO_RENDER_PRICE_PER_CALL_USD, 2)

    plan = {
        "status": "dry_run_only",
        "client": asdict(client),
        "product": asdict(product),
        "campaign": asdict(campaign),
        "references_used": [asdict(r) for r in approved_refs],
        "forbidden_refs_scan": forbidden_scan,
        "platforms": platforms,
        "planned_scenes": planned_scenes,
        "planned_video_variants": planned_video_variants,
        "planned_dzen_articles": planned_dzen_articles,
        "planned_publishing_queue": planned_publishing_queue,
        "estimated_image_calls": estimated_image_calls,
        "estimated_video_renders": estimated_video_renders,
        "estimated_cost_usd": estimated_cost_usd,
        "openai_calls": 0,
        "higgsfield_calls": 0,
        "external_api_calls": 0,
        "auto_posting_triggered": False,
    }
    return plan


def write_campaign_dry_run(client_id: str, product_id: str, campaign_id: str,
                           repo_root: str = ".", out_path=None) -> dict:
    plan = build_campaign_dry_run(client_id, product_id, campaign_id, repo_root)
    gen_dir = st.campaign_generated_dir(client_id, product_id, campaign_id, repo_root)
    gen_dir.mkdir(parents=True, exist_ok=True)
    out = Path(out_path) if out_path else (gen_dir / "campaign-dry-run.json")
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    plan["report_path"] = str(out)
    return plan
