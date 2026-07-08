"""Seller onboarding wizard storage -- aggregates the state of a single
seller's wizard walk-through (product basics, reference uploads, customer
positioning, product intelligence summary, content package settings,
readiness checklist) into one snapshot file:

    content/b2b/clients/<client_id>/products/<product_id>/seller-intake.json

This is a convenience snapshot for the wizard UI/readiness-checklist -- the
underlying source of truth for each section still lives in its own place
(Product/ProductReference in b2b_storage, the intelligence report in
product_intelligence). Pure local file I/O, zero network calls.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import b2b_storage as st
from . import b2b_reference_policy as pol
from . import product_intelligence as pi

CONTENT_TYPES = ("short_videos", "platform_descriptions", "dzen_articles",
                 "article_images", "publishing_plan", "performance_tracker",
                 "delivery_zip")
PACKAGE_DURATIONS = ("7_days", "14_days", "30_days")
MANUAL_OR_AUTOPOST_OPTIONS = ("manual_upload_ready_kit",)
MIN_UPLOADED_REFERENCES = 3

# Human-readable labels for seller-facing UI -- backend values unchanged.
CONTENT_TYPE_LABELS = {
    "short_videos": "Короткие видео",
    "platform_descriptions": "Описания под площадки",
    "dzen_articles": "Статьи для Дзена",
    "article_images": "Картинки к статьям",
    "publishing_plan": "План публикаций",
    "performance_tracker": "Трекер результатов",
    "delivery_zip": "ZIP с материалами",
}
PACKAGE_DURATION_LABELS = {
    "7_days": "7 дней",
    "14_days": "14 дней",
    "30_days": "30 дней",
}
MANUAL_OR_AUTOPOST_LABELS = {
    "manual_upload_ready_kit": "Готовый ZIP для ручной публикации",
}

READINESS_CHECKLIST_ITEMS = (
    "product_info_complete",
    "marketplace_article_or_link_present",
    "at_least_1_uploaded_reference",
    "at_least_3_uploaded_references",
    "at_least_3_approved_references",
    "customer_positioning_present",
    "product_intelligence_generated",
    "primary_problem_approved",
    "platforms_selected",
    "package_duration_selected",
)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seller_intake_path(client_id: str, product_id: str, repo_root: str = ".") -> Path:
    return st.product_dir(client_id, product_id, repo_root) / "seller-intake.json"


def _new_intake() -> dict:
    now = utcnow_iso()
    return {
        "product_basics": {},
        "reference_uploads": {},
        "customer_positioning": {},
        "product_intelligence_summary": {},
        "content_package_settings": {},
        "readiness_checklist": {},
        "created_at": now,
        "updated_at": now,
    }


def load_seller_intake(client_id: str, product_id: str, repo_root: str = "."):
    path = seller_intake_path(client_id, product_id, repo_root)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save(intake: dict, client_id: str, product_id: str, repo_root: str = ".") -> Path:
    path = seller_intake_path(client_id, product_id, repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(intake, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def update_seller_intake(client_id: str, product_id: str, repo_root: str = ".",
                         **section_updates) -> dict:
    """Merges section_updates (e.g. product_basics={...}) into the existing
    seller-intake.json, creating it if missing. Unknown section names are
    rejected -- fail closed rather than silently writing a typo'd key."""
    intake = load_seller_intake(client_id, product_id, repo_root) or _new_intake()
    valid_sections = {"product_basics", "reference_uploads", "customer_positioning",
                      "product_intelligence_summary", "content_package_settings",
                      "readiness_checklist"}
    for section, value in section_updates.items():
        if section not in valid_sections:
            raise ValueError(f"unknown seller-intake section {section!r}")
        intake.setdefault(section, {}).update(value)
    intake["updated_at"] = utcnow_iso()
    _save(intake, client_id, product_id, repo_root)
    return intake


def build_readiness_checklist(client_id: str, product_id: str, repo_root: str = ".") -> dict:
    """Recomputes all readiness checklist items from the current state of
    Product / references / product-intelligence.json / seller-intake content
    package settings. Never trusts stale cached booleans.

    Seller MVP flow only requires >=1 uploaded product photo to proceed
    (can_run_dry_run) -- manual admin approval is a separate, non-blocking
    quality signal (at_least_3_approved_references), not a hard gate. See
    api.media_pipeline.b2b_reference_policy for the two-mode policy this
    mirrors."""
    product = st.load_product(client_id, product_id, repo_root)
    refs = st.load_references(client_id, product_id, repo_root)
    approved_refs = [r for r in refs if r.approved]
    uploaded_count = len(refs)
    approved_count = len(approved_refs)
    intelligence = pi.load_product_intelligence(client_id, product_id, repo_root)
    intake = load_seller_intake(client_id, product_id, repo_root) or _new_intake()
    settings = intake.get("content_package_settings", {})

    checklist = {
        "product_info_complete": bool(
            product.product_name and product.category and product.product_description),
        "marketplace_article_or_link_present": bool(
            product.marketplace_article or product.marketplace_url),
        "at_least_1_uploaded_reference": uploaded_count >= pol.MIN_SELLER_FLOW_REFERENCES,
        "at_least_3_uploaded_references": uploaded_count >= MIN_UPLOADED_REFERENCES,
        "at_least_3_approved_references": approved_count >= pol.MIN_APPROVED_REFERENCES,
        "customer_positioning_present": bool(
            product.who_is_this_for or product.what_problem_does_it_usually_solve or
            product.why_people_buy_it),
        "product_intelligence_generated": intelligence is not None,
        "primary_problem_approved": bool(intelligence and intelligence.get("approved_by_owner")),
        "platforms_selected": bool(settings.get("platforms")),
        "package_duration_selected": bool(settings.get("package_duration")),
        "uploaded_count": uploaded_count,
        "approved_count": approved_count,
        "usable_product_reference_count": uploaded_count,
        "seller_uploaded_reference_count": uploaded_count,
    }
    checklist["can_run_dry_run"] = checklist["at_least_1_uploaded_reference"]
    return checklist


def sync_readiness_checklist(client_id: str, product_id: str, repo_root: str = ".") -> dict:
    checklist = build_readiness_checklist(client_id, product_id, repo_root)
    update_seller_intake(client_id, product_id, repo_root, readiness_checklist=checklist)
    return checklist
