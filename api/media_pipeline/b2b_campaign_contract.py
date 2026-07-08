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
from . import product_intelligence as pi
from . import seller_intake as si

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

# "Демо -- 1 тестовый ролик" mode: exactly one scene/video, zero Dzen
# content, one publishing day -- lets a seller check quality before
# committing to a 7/14/30-day package. See api.media_pipeline.seller_intake
# .DEMO_PACKAGE_DURATION for the backend value ("demo_1_video").
DEMO_MODE_NOTE = ("Для демо-режима выбран один самый подходящий рекламный угол. В большом "
                 "пакете можно будет протестировать несколько стратегий.")
DEMO_PLAN_EXPLANATION = ("Это демо-план. Он нужен, чтобы проверить один ролик перед запуском "
                        "большого контент-пакета.")

_PACKAGE_DURATION_DAYS = {"7_days": 7, "14_days": 14, "30_days": 30}


def _publishing_days_for_package(package_mode: str) -> int:
    if package_mode == si.DEMO_PACKAGE_DURATION:
        return 1
    return _PACKAGE_DURATION_DAYS.get(package_mode, 14)


def build_campaign_dry_run(client_id: str, product_id: str, campaign_id: str,
                           repo_root: str = ".", strict_approved_refs_required: bool = False) -> dict:
    client = st.load_client(client_id, repo_root)
    product = st.load_product(client_id, product_id, repo_root)
    campaign = st.load_campaign(client_id, product_id, campaign_id, repo_root)

    # Fail-closed reference gate -- raises B2BReferencePolicyError (never
    # silently substitutes a placeholder) if references are missing/invalid.
    # Default (strict_approved_refs_required=False) is the seller MVP policy:
    # >=1 uploaded reference is enough, manual approval is not required to
    # unblock a seller's own dry-run. Pass strict=True for the admin-only
    # policy requiring >=3 approved references.
    usable_refs = pol.assert_campaign_generation_allowed(
        client_id, product_id, repo_root, strict_approved_refs_required=strict_approved_refs_required)
    ref_paths = [r.file_path for r in usable_refs]
    forbidden_scan = pol.scan_reference_images_list(ref_paths, repo_root)
    reference_quality = pol.build_reference_quality(client_id, product_id, repo_root)

    all_refs = st.load_references(client_id, product_id, repo_root)
    usable_paths = {r.file_path for r in usable_refs}
    rejected_refs = [r for r in all_refs if r.file_path not in usable_paths]

    # Product Intelligence Engine -- auto-generate if missing so the dry-run
    # always has a hypothesis to plan around; zero external API calls (local
    # rule-based engine only). See api.media_pipeline.product_intelligence.
    intelligence_envelope = pi.load_product_intelligence(client_id, product_id, repo_root)
    if intelligence_envelope is None:
        intelligence_envelope = pi.write_product_intelligence(client_id, product_id, repo_root)
    intel_report = intelligence_envelope["report"]
    product_intelligence_summary = {
        "core_problem_solved": intel_report["core_problem_solved"],
        "matched_category": intel_report["matched_category"],
        "match_confidence": intel_report["match_confidence"],
        "positioning_mode": intel_report["positioning_mode"],
        "approved_by_owner": intelligence_envelope["approved_by_owner"],
        "top_pain_points": intel_report["pain_points"][:3],
        "top_benefits": intel_report["product_benefits"][:3],
        "use_cases": intel_report["use_cases"],
        "likely_objections": intel_report["likely_objections"],
        "hook_angles": [h for h in intel_report["hook_angles"] if h.get("enabled", True)],
        "video_message_angles": intel_report["video_message_angles"],
        "recommended_content_mix": intel_report["recommended_content_mix"],
        "needs_owner_review": intel_report["needs_owner_review"],
    }

    # package_mode: read from the seller wizard's own intake snapshot (Step 5
    # "Настройки контент-пакета") if it exists; admin-created campaigns that
    # never went through the wizard have no seller-intake.json and default to
    # a full (non-demo) plan, preserving prior behaviour.
    intake = si.load_seller_intake(client_id, product_id, repo_root)
    package_mode = (intake or {}).get("content_package_settings", {}).get("package_duration") or "14_days"
    is_demo_mode = package_mode == si.DEMO_PACKAGE_DURATION

    platforms = campaign.platforms or list(st.CAMPAIGN_PLATFORMS)
    video_platforms = [p for p in platforms if p != "dzen"]

    demo_mode_note = None
    if is_demo_mode:
        ad_options = intel_report.get("ad_strategy_options", [])
        selected_strategy = intel_report.get("selected_ad_strategy", "multi_angle_test")
        if selected_strategy == "multi_angle_test":
            primary_angle = ad_options[0]["strategy_id"] if ad_options else "pain_problem"
            demo_mode_note = DEMO_MODE_NOTE
        else:
            primary_angle = selected_strategy
        demo_platform = video_platforms[0] if video_platforms else (platforms[0] if platforms else "youtube_shorts")

        planned_scenes = [
            {"scene_id": "scene-01", "narrative_beat": SCENE_NARRATIVE_TEMPLATE[0],
             "uses_product_reference": True},
        ]
        planned_video_variants = {
            "total_variants": 1,
            "platforms": [demo_platform],
            "creative_angles": [primary_angle],
            "note": "Демо-режим: один тестовый ролик на одном рекламном угле.",
        }
        planned_dzen_articles = {"total_articles": 0, "article_types": [], "images_per_article": 0}
        planned_publishing_queue = {
            "video_posting_times": ["12:30"],
            "dzen_posting_times": [],
            "note": "Демо-режим: 1 день публикации для теста.",
        }
        estimated_image_calls = 1
        estimated_video_renders = 1
        estimated_cost_usd = round(estimated_image_calls * IMAGE_PRICE_PER_CALL_USD +
                                  estimated_video_renders * VIDEO_RENDER_PRICE_PER_CALL_USD, 2)
    else:
        planned_scenes = [
            {"scene_id": f"scene-{i:02d}", "narrative_beat": beat, "uses_product_reference": True}
            for i, beat in enumerate(SCENE_NARRATIVE_TEMPLATE, start=1)
        ]
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

    content_package_plan = {
        "planned_scenes_count": len(planned_scenes),
        "planned_short_videos_count": planned_video_variants["total_variants"],
        "planned_dzen_articles_count": planned_dzen_articles["total_articles"],
        "planned_article_images_count": (planned_dzen_articles["total_articles"] *
                                        planned_dzen_articles["images_per_article"]),
        "planned_publishing_days": _publishing_days_for_package(package_mode),
        "demo_mode": is_demo_mode,
    }

    safety_policy_summary = {
        "policy": "B2B_PRODUCT_REFERENCE_ONLY_POLICY",
        "strict_approved_refs_required": strict_approved_refs_required,
        "min_approved_references": pol.MIN_APPROVED_REFERENCES,
        "min_seller_flow_references": pol.MIN_SELLER_FLOW_REFERENCES,
        "usable_references_count": len(usable_refs),
        "rejected_references_count": len(rejected_refs),
        "forbidden_path_markers": list(pol.FORBIDDEN_PATH_MARKERS),
        "fails_closed": True,
        "note": ("Generated outputs can never become product references automatically -- "
                "every reference used here was uploaded by the seller, never a "
                "generated/candidate image. Manual approval is an optional admin quality "
                "signal, not a hard requirement for the seller flow (strict_approved_refs_"
                "required=False by default)."),
    }

    plan = {
        "status": "dry_run_only",
        "package_mode": package_mode,
        "client": asdict(client),
        "product": asdict(product),
        "campaign": asdict(campaign),
        "references_used": [asdict(r) for r in usable_refs],
        "references_rejected": [asdict(r) for r in rejected_refs],
        "reference_quality": reference_quality,
        "forbidden_refs_scan": forbidden_scan,
        "safety_policy_summary": safety_policy_summary,
        "product_intelligence": product_intelligence_summary,
        "platforms": platforms,
        "content_package_plan": content_package_plan,
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
    if demo_mode_note:
        plan["demo_mode_note"] = demo_mode_note
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
        "## Package mode",
        "",
        f"- package_mode: {plan['package_mode']}",
        f"- Planned scenes: {plan['content_package_plan']['planned_scenes_count']}",
        f"- Planned short videos: {plan['content_package_plan']['planned_short_videos_count']}",
        f"- Planned Dzen articles: {plan['content_package_plan']['planned_dzen_articles_count']}",
        f"- Planned article images: {plan['content_package_plan']['planned_article_images_count']}",
        f"- Planned publishing days: {plan['content_package_plan']['planned_publishing_days']}",
    ]
    if plan["content_package_plan"]["demo_mode"]:
        lines.append(f"- {DEMO_PLAN_EXPLANATION}")
        if plan.get("demo_mode_note"):
            lines.append(f"- {plan['demo_mode_note']}")
    lines += [
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

    rq = plan["reference_quality"]
    lines += [
        "",
        "## Reference quality",
        "",
        f"- Uploaded: {rq['uploaded_count']} (approved: {rq['approved_count']})",
        f"- Minimum required for seller flow: {rq['minimum_required_for_seller_flow']}",
        f"- Recommended: {rq['recommended_count']}",
        f"- Quality risk: {rq['quality_risk']}",
        f"- {rq['notes']}",
    ]

    pi_summary = plan["product_intelligence"]
    lines += [
        "",
        "## Product intelligence (what the system understood about this product)",
        "",
        f"- Core problem solved: {pi_summary['core_problem_solved']}",
        f"- Matched category: {pi_summary['matched_category']} "
        f"(confidence: {pi_summary['match_confidence']}, "
        f"approved_by_owner: {pi_summary['approved_by_owner']})",
        f"- Positioning mode: {pi_summary['positioning_mode']}",
        "- Top pain points: " + (
            "; ".join(p["pain"] for p in pi_summary["top_pain_points"]) or "-"),
        "- Top benefits: " + (
            "; ".join(b["benefit"] for b in pi_summary["top_benefits"]) or "-"),
        "- Suggested hook angles: " + (
            "; ".join(h["hook"] for h in pi_summary["hook_angles"]) or "-"),
        f"- needs_owner_review: {pi_summary['needs_owner_review']}",
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
        f"- Strict approved-refs mode: "
        f"{plan['safety_policy_summary']['strict_approved_refs_required']}",
        f"- Minimum approved references (admin strict mode): "
        f"{plan['safety_policy_summary']['min_approved_references']}",
        f"- Minimum references (seller flow): "
        f"{plan['safety_policy_summary']['min_seller_flow_references']}",
        f"- Usable references count: "
        f"{plan['safety_policy_summary']['usable_references_count']}",
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
                           repo_root: str = ".", out_path=None,
                           strict_approved_refs_required: bool = False) -> dict:
    plan = build_campaign_dry_run(client_id, product_id, campaign_id, repo_root,
                                  strict_approved_refs_required=strict_approved_refs_required)
    gen_dir = st.campaign_generated_dir(client_id, product_id, campaign_id, repo_root)
    gen_dir.mkdir(parents=True, exist_ok=True)
    out = Path(out_path) if out_path else (gen_dir / "campaign-dry-run.json")
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    plan["report_path"] = str(out)

    md_out = out.with_suffix(".md")
    md_out.write_text(render_campaign_dry_run_md(plan), encoding="utf-8")
    plan["report_md_path"] = str(md_out)

    return plan
