"""Campaign-level batch runner for the product-reference-only-v2 pipeline.

Owner decision: automate the WHOLE coating-protect-2026-07 campaign (all 7
scenes) through the same mechanism proven on scene-05/scene-07 -- mode="edit"
with the SAME 4 product-only reference images
(product_reference_only_runner.PRODUCT_REFERENCE_IMAGES_V2) for every scene,
everything else described in text. No scene ever gets an image reference
other than the product; no generated/C1/C2/C3/candidate PNG is ever used as
a reference (structurally guaranteed -- reference_images always come from
PRODUCT_REFERENCE_IMAGES_V2, never a caller-supplied path).

Scene status vocabulary (per scene, in the campaign report):
- "configured": scene has a valid v2 prompt and is not skipped by any flag
  (dry-run terminal state -- "would run if --apply were passed").
- "selected_existing": scene already has an owner-selected working candidate
  (see campaign-selected-working-candidates.json) -- skipped when
  --skip-selected is set (skip_selected defaults to True).
- "skipped": scene already has a generated output on disk -- skipped when
  --skip-existing is set.
- "pending_apply": scene is configured and not skipped, but --apply run
  never reached it because stop_on_error halted the loop at an earlier
  scene.
- (apply mode only) after a real call: the scene's OWN candidate_status
  (pending_manual_review / rejected / no_candidate_timeout /
  rejected_api_error) -- never "accepted" automatically.

This runner makes AT MOST ONE OpenAI call per scene (same fail-closed
contract as product_reference_only_runner: MAX_CALLS=1, RETRIES=0,
HARD_CAP_USD=0.50 per scene), plus a campaign-wide spend ceiling
(CAMPAIGN_TOTAL_HARD_CAP_USD). apply=False (dry-run) makes ZERO network
calls, ever -- even when scenes=None (whole campaign).

Report output path (mode-specific default, overridable via out_path):
- apply=False (dry-run, default): <campaign_dir>/campaign-product-reference-only-v2-dry-run.json
- apply=True (default):           <campaign_dir>/generated/product-reference-only-campaign/apply-summary.json
An apply run NEVER writes to the tracked dry-run path, and a dry-run run
NEVER writes to the (gitignored) generated/ apply-summary path -- the two
modes always target different files unless the caller passes an explicit
out_path.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import product_reference_only_runner as por

CAMPAIGN_TOTAL_HARD_CAP_USD = 5.00
SELECTED_CANDIDATES_FILENAME = "campaign-selected-working-candidates.json"

_SCENE_KEY_RE = re.compile(r"^scene-\d\d$")

# Paths/filenames that must NEVER appear as a reference, scanned for
# explicitly (defense in depth -- reference_images is already structurally
# built only from PRODUCT_REFERENCE_IMAGES_V2, never a free-form path, but
# this scan makes the guarantee auditable in the report rather than merely
# asserted).
_FORBIDDEN_PATH_SEGMENTS = ("generated", "airfryer", "motion")
_FORBIDDEN_FILENAME_MARKERS = (
    "airfryer_front_master.png", "clean_basket_master.png",
    "product_in_basket_master.png", "grip_motion_master.png",
    "scene-01-c", "scene-02-c", "scene-03-c", "scene-04-c",
    "scene-05-c", "scene-06-c", "scene-07-c",
    "product-reference-only-v2-candidate", "product-reference-only-candidate",
)


class ProductReferenceOnlyCampaignError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def scan_forbidden_refs(reference_image_paths: list) -> dict:
    """Audits a list of resolved reference paths against the forbidden
    list. Always expected to come back clean, since reference_images is
    only ever built from PRODUCT_REFERENCE_IMAGES_V2 -- kept as an explicit,
    reportable check rather than a silent assumption."""
    findings = []
    for raw in reference_image_paths:
        normalized = str(raw).replace("\\", "/")
        parts = normalized.split("/")
        for segment in _FORBIDDEN_PATH_SEGMENTS:
            if segment in parts:
                findings.append({"path": normalized, "reason": f"forbidden_path_segment:{segment}"})
        for marker in _FORBIDDEN_FILENAME_MARKERS:
            if marker in normalized:
                findings.append({"path": normalized, "reason": f"forbidden_filename_marker:{marker}"})
    return {"scanned": len(reference_image_paths), "forbidden_found": len(findings) > 0,
           "findings": findings}


def load_selected_candidates(campaign_dir) -> dict:
    """{scene_id: {...}} of scenes with an owner-selected working candidate
    (campaign-selected-working-candidates.json) -- returns {} if the
    registry file doesn't exist yet. Never treats an entry here as a
    reference; it is purely a skip-selected marker."""
    p = Path(campaign_dir) / SELECTED_CANDIDATES_FILENAME
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if _SCENE_KEY_RE.match(k) and isinstance(v, dict)}


def scene_output_dir(campaign_dir, scene_id: str) -> Path:
    return Path(campaign_dir) / "generated" / "product-reference-only-scene-v2" / scene_id


def scene_has_existing_generated_output(campaign_dir, scene_id: str) -> bool:
    out_dir = scene_output_dir(campaign_dir, scene_id)
    if not out_dir.is_dir():
        return False
    return any(out_dir.glob(f"{scene_id}-c*.png"))


def plan_scene(campaign_dir, scene_id: str, skip_existing: bool, skip_selected: bool,
              repo_root: str, selected_candidates: dict) -> dict:
    """Builds ONE scene's plan entry. Never makes a network call -- even
    for scenes that will later be applied, this only builds the request
    contract (dry-run-safe by construction, same as
    product_reference_only_runner.build_request_contract_v2)."""
    entry = {"scene_id": scene_id}

    if scene_id not in por.SCENE_PROMPTS_V2:
        entry["status"] = "not_configured"
        entry["reason"] = f"{scene_id} is not in product_reference_only_runner.SCENE_PROMPTS_V2"
        return entry

    if skip_selected and scene_id in selected_candidates:
        entry.update({
            "status": "selected_existing",
            "reason": "scene has an owner-selected working candidate (--skip-selected)",
            "selected_candidate": selected_candidates[scene_id],
            "reference_images": [],
            "reference_image_paths": [],
            "estimated_spend_usd": 0.0,
            "will_call_openai": False,
        })
        return entry

    if skip_existing and scene_has_existing_generated_output(campaign_dir, scene_id):
        entry.update({
            "status": "skipped",
            "reason": "existing generated output found on disk (--skip-existing)",
            "reference_images": [],
            "reference_image_paths": [],
            "estimated_spend_usd": 0.0,
            "will_call_openai": False,
        })
        return entry

    req, contract = por.build_request_contract_v2(campaign_dir, scene_id, repo_root)
    est = round(por.PRICE_PER_IMAGE_USD_ESTIMATE * contract.n, 4)
    ref_paths_norm = [str(p).replace("\\", "/") for p in contract.reference_image_paths]
    entry.update({
        "status": "configured",
        "candidate_label": por.CANDIDATE_LABEL_V2,
        "model": contract.model, "mode": contract.mode, "endpoint": contract.endpoint,
        "size": contract.size, "n": contract.n, "retries": contract.retries,
        "max_calls": contract.max_calls, "hard_cap_usd": contract.hard_cap_usd,
        "prompt_sha256": contract.prompt_sha256,
        "reference_images": list(contract.reference_images),
        "reference_image_paths": ref_paths_norm,
        "forbidden_refs_scan": scan_forbidden_refs(ref_paths_norm),
        "estimated_spend_usd": est,
        "will_call_openai": True,
    })
    return entry


def run_campaign(campaign_dir, scenes=None, apply: bool = False,
                 skip_existing: bool = False, skip_selected: bool = True,
                 stop_on_error: bool = True, repo_root: str = ".",
                 out_path=None) -> dict:
    """Single entry point for the whole campaign.

    apply=False (default): pure planning, ZERO network calls, works even
    without OPENAI_API_KEY. Every non-skipped scene gets status
    "configured".

    apply=True: for each non-skipped scene (in campaign order, or the
    explicit `scenes` list/order if given), makes EXACTLY ONE real OpenAI
    call via product_reference_only_runner.run_product_reference_only_scene_v2
    (same MAX_CALLS=1/RETRIES=0/HARD_CAP_USD=0.50 contract per scene, plus
    CAMPAIGN_TOTAL_HARD_CAP_USD across the whole run). stop_on_error=True
    (default) halts the loop at the first scene that errors or times out --
    remaining scenes are marked "pending_apply" (queued, never reached),
    NOT silently retried or skipped as if intentional.

    skip_selected=True by default -- scene-05/scene-07 (already selected
    working candidates) are NOT regenerated unless the caller explicitly
    passes skip_selected=False."""
    scene_list = list(scenes) if scenes else list(por.CAMPAIGN_SCENE_ORDER)
    selected_candidates = load_selected_candidates(campaign_dir)

    scene_reports = []
    total_estimated = 0.0
    total_actual = 0.0
    openai_calls_executed = 0
    halted = False

    for scene_id in scene_list:
        if halted:
            entry = {"scene_id": scene_id, "status": "pending_apply",
                     "reason": "campaign halted at an earlier scene (stop_on_error)"}
            scene_reports.append(entry)
            continue

        entry = plan_scene(campaign_dir, scene_id, skip_existing, skip_selected,
                           repo_root, selected_candidates)

        if entry["status"] != "configured":
            scene_reports.append(entry)
            continue

        total_estimated += entry["estimated_spend_usd"]

        if not apply:
            scene_reports.append(entry)
            continue

        # -- apply=True: exactly one real call for this scene ---------------
        if total_actual + por.HARD_CAP_USD > CAMPAIGN_TOTAL_HARD_CAP_USD:
            entry["status"] = "skipped_campaign_hard_cap"
            entry["reason"] = (f"campaign_total_hard_cap_usd={CAMPAIGN_TOTAL_HARD_CAP_USD} would be "
                              f"exceeded (spent so far ${total_actual:.2f})")
            scene_reports.append(entry)
            if stop_on_error:
                halted = True
            continue

        try:
            result = por.run_product_reference_only_scene_v2(
                campaign_dir, scene_id, apply=True, repo_root=repo_root)
        except Exception as e:  # noqa: BLE001 -- any failure maps to a reported, non-retried outcome
            entry["status"] = "rejected_api_error"
            entry["error_type"] = type(e).__name__
            entry["error_message"] = str(e)
            scene_reports.append(entry)
            openai_calls_executed += 1
            if stop_on_error:
                halted = True
            continue

        openai_calls_executed += 1
        entry["apply_result"] = result
        entry["status"] = result.get("candidate_status", "pending_manual_review")
        spend = result.get("api_spend_usd")
        total_actual += spend if isinstance(spend, (int, float)) else 0.0
        scene_reports.append(entry)
        if entry["status"] in ("no_candidate_timeout", "rejected_api_error") and stop_on_error:
            halted = True

    report = {
        "campaign_code": "coating-protect-2026-07",
        "mode": "apply" if apply else "dry-run",
        "scenes_requested": scene_list,
        "skip_existing": skip_existing,
        "skip_selected": skip_selected,
        "stop_on_error": stop_on_error,
        "scene_reports": scene_reports,
        "max_calls_per_scene": por.MAX_CALLS,
        "retries": por.RETRIES,
        "hard_cap_usd_per_scene": por.HARD_CAP_USD,
        "campaign_total_hard_cap_usd": CAMPAIGN_TOTAL_HARD_CAP_USD,
        "total_estimated_spend_usd": round(total_estimated, 4),
        "total_actual_spend_usd": round(total_actual, 4) if apply else 0,
        "openai_calls_executed": openai_calls_executed if apply else 0,
        "higgsfield_calls_executed": 0,
        "image_generation_timeout_seconds": por.resolve_image_generation_timeout_seconds()[0],
        "reference_policy": {
            "mandatory_product_reference": "real-product-v1",
            "allowed_reference_images": list(por.PRODUCT_REFERENCE_IMAGES_V2),
            "forbidden_product_lock_assets": list(por.FORBIDDEN_PRODUCT_LOCK_ASSETS),
            "forbidden_reference_sources": list(por.FORBIDDEN_REFERENCE_SOURCES),
        },
        "candidate_status_note": ("per-scene candidate_status after a real apply is always one of "
                                  "pending_manual_review, rejected, no_candidate_timeout, or "
                                  "rejected_api_error -- never accepted automatically."),
    }

    out_dir = Path(campaign_dir)
    if out_path:
        report_path = Path(out_path)
    elif apply:
        report_path = (out_dir / "generated" / "product-reference-only-campaign"
                       / "apply-summary.json")
    else:
        report_path = out_dir / "campaign-product-reference-only-v2-dry-run.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report
