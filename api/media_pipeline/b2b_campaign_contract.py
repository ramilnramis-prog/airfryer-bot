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

    all_refs = st.load_references(client_id, product_id, repo_root)
    approved_paths = {r.file_path for r in approved_refs}
    rejected_refs = [r for r in all_refs if r.file_path not in approved_paths]

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

    safety_policy_summary = {
        "policy": "B2B_PRODUCT_REFERENCE_ONLY_POLICY",
        "min_approved_references": pol.MIN_APPROVED_REFERENCES,
        "approved_references_count": len(approved_refs),
        "rejected_references_count": len(rejected_refs),
        "forbidden_path_markers": list(pol.FORBIDDEN_PATH_MARKERS),
        "fails_closed": True,
        "note": ("Generated outputs can never become product references automatically; "
                "every reference used here was uploaded and explicitly approved by the "
                "seller/admin, never a generated/candidate image."),
    }

    plan = {
        "status": "dry_run_only",
        "client": asdict(client),
        "product": asdict(product),
        "campaign": asdict(campaign),
        "references_used": [asdict(r) for r in approved_refs],
        "references_rejected": [asdict(r) for r in rejected_refs],
        "forbidden_refs_scan": forbidden_scan,
        "safety_policy_summary": safety_policy_summary,
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


def render_campaign_dry_run_md(plan: dict) -> str:
    """Human-readable counterpart to the JSON dry-run report."""
    client = plan["client"]
    product = plan["product"]
    campaign = plan["campaign"]
    lines = [
        f"# Campaign dry-run: {campaign['campaign_id']}",
        "",
        f"Status: **{plan['status']}** -- no OpenAI/Higgsfield calls made "
        f"(openai_calls={plan['openai_calls']}, higgsfield_calls={plan['higgsfield_calls']}, "
        f"external_api_calls={plan['external_api_calls']}, "
        f"auto_posting_triggered={plan['auto_posting_triggered']}).",
        "",
        "## Client",
        "",
        f"- {client['name']} ({client['client_id']}) -- contact: {client['contact'] or '-'}",
        "",
        "## Product",
        "",
        f"- {product['product_name']} -- {product['marketplace']} / "
        f"{product['marketplace_article']}",
        f"- category: {product['category'] or '-'}",
        f"- target audience: {product['target_audience'] or '-'}",
        f"- main pain: {product['main_pain'] or '-'}",
        "",
        f"## Approved references used ({len(plan['references_used'])})",
        "",
    ]
    for r in plan["references_used"]:
        lines.append(f"- `{r['file_path']}` (role={r['role']}, notes={r['notes'] or '-'})")
    if not plan["references_used"]:
        lines.append("- (none)")

    lines += [
        "",
        f"## Rejected / unapproved references ({len(plan['references_rejected'])})",
        "",
    ]
    for r in plan["references_rejected"]:
        lines.append(f"- `{r['file_path']}` (role={r['role']}, approved={r['approved']})")
    if not plan["references_rejected"]:
        lines.append("- (none)")

    lines += [
        "",
        "## Content package plan",
        "",
        f"- Planned scenes: {len(plan['planned_scenes'])}",
        f"- Planned video variants: {plan['planned_video_variants']['total_variants']} "
        f"across platforms: {', '.join(plan['planned_video_variants']['platforms']) or '-'}",
        f"- Planned Dzen articles: {plan['planned_dzen_articles']['total_articles']} "
        f"({plan['planned_dzen_articles']['images_per_article']} images each)",
        f"- Publishing platforms: {', '.join(plan['platforms'])}",
        f"- Video posting times: "
        f"{', '.join(plan['planned_publishing_queue']['video_posting_times']) or '-'}",
        f"- Dzen posting times: "
        f"{', '.join(plan['planned_publishing_queue']['dzen_posting_times']) or '-'}",
        "",
        "## Estimated cost",
        "",
        f"- Estimated OpenAI image calls: {plan['estimated_image_calls']}",
        f"- Estimated local MP4 renders: {plan['estimated_video_renders']}",
        f"- Estimated cost: ${plan['estimated_cost_usd']}",
        "",
        "## Safety policy summary",
        "",
        f"- Policy: {plan['safety_policy_summary']['policy']}",
        f"- Minimum approved references required: "
        f"{plan['safety_policy_summary']['min_approved_references']}",
        f"- Approved references count: "
        f"{plan['safety_policy_summary']['approved_references_count']}",
        f"- Rejected references count: "
        f"{plan['safety_policy_summary']['rejected_references_count']}",
        f"- Forbidden path markers: "
        f"{', '.join(plan['safety_policy_summary']['forbidden_path_markers'])}",
        f"- {plan['safety_policy_summary']['note']}",
        "",
        "## Forbidden refs scan",
        "",
        f"- scanned: {plan['forbidden_refs_scan']['scanned']}",
        f"- forbidden_found: {plan['forbidden_refs_scan']['forbidden_found']}",
    ]
    return "\n".join(lines) + "\n"


def write_campaign_dry_run(client_id: str, product_id: str, campaign_id: str,
                           repo_root: str = ".", out_path=None) -> dict:
    plan = build_campaign_dry_run(client_id, product_id, campaign_id, repo_root)
    gen_dir = st.campaign_generated_dir(client_id, product_id, campaign_id, repo_root)
    gen_dir.mkdir(parents=True, exist_ok=True)
    out = Path(out_path) if out_path else (gen_dir / "campaign-dry-run.json")
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    plan["report_path"] = str(out)

    md_out = out.with_suffix(".md")
    md_out.write_text(render_campaign_dry_run_md(plan), encoding="utf-8")
    plan["report_md_path"] = str(md_out)

    return plan
