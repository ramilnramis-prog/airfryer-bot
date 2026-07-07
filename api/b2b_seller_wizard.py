"""Seller-facing onboarding wizard for the B2B content factory -- a guided,
6-step path for a non-technical seller: product basics -> reference photos
-> customer positioning -> AI analysis review -> content package settings ->
readiness checklist. Wraps the existing building blocks (b2b_storage,
b2b_reference_policy, product_intelligence, seller_intake, b2b_campaign_
contract, b2b_delivery_kit) behind one linear flow instead of the
free-form admin `/b2b/products/*` pages.

No X-API-Key auth (same intentional MVP gap as api/b2b.py). Zero network
calls anywhere in this module.
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .config import ROOT
from .media_pipeline import b2b_storage as st
from .media_pipeline import b2b_reference_policy as pol
from .media_pipeline import product_intelligence as pi
from .media_pipeline import seller_intake as si
from .media_pipeline.b2b_campaign_contract import write_campaign_dry_run
from .media_pipeline.b2b_delivery_kit import build_delivery_kit_zip
from .b2b import _slugify, _find_product

router = APIRouter(prefix="/b2b/seller", tags=["b2b-seller-wizard"])

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates" / "b2b"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

REPO_ROOT = str(ROOT)

# STEP 2 upload slots -> reference role
REFERENCE_UPLOAD_SLOTS = (
    ("front_photo", "front", "Фото товара спереди"),
    ("top_photo", "top", "Фото сверху"),
    ("side_photo", "side", "Фото сбоку"),
    ("detail_photo", "detail", "Фото деталей / ручки / текстура"),
    ("packaging_photo", "packaging", "Фото упаковки (если есть)"),
)


def _require_product(product_id: str):
    product = _find_product(product_id)
    if not product:
        raise HTTPException(404, "product not found")
    return product


def _get_or_create_wizard_campaign(product: "st.Product", settings: dict) -> "st.Campaign":
    existing = st.list_campaigns(product.client_id, product.product_id, REPO_ROOT)
    if existing:
        return existing[0]
    platforms = settings.get("platforms") or list(st.CAMPAIGN_PLATFORMS)
    campaign_id = f"{product.product_id}-{uuid.uuid4().hex[:6]}"
    campaign = st.Campaign(campaign_id=campaign_id, client_id=product.client_id,
                           product_id=product.product_id, campaign_goal="external_traffic",
                           platforms=platforms, status="draft")
    st.save_campaign(campaign, REPO_ROOT)
    return campaign


# -- STEP 1: product basics ---------------------------------------------------

@router.get("/start", response_class=HTMLResponse)
def step1_form(request: Request):
    return templates.TemplateResponse(request, "wizard/step1.html", {
        "marketplaces": st.PRODUCT_MARKETPLACES,
    })


@router.post("/start")
def step1_submit(
    client_name: str = Form(...),
    contact: str = Form(""),
    product_name: str = Form(...),
    marketplace: str = Form("ozon"),
    marketplace_article: str = Form(""),
    marketplace_url: str = Form(""),
    price: str = Form(""),
    category: str = Form(""),
    short_product_description: str = Form(""),
):
    client_id = _slugify(client_name)
    if not (st.client_dir(client_id, REPO_ROOT) / "client.json").is_file():
        st.save_client(st.Client(client_id=client_id, name=client_name, contact=contact), REPO_ROOT)

    product_id = _slugify(product_name)
    existing = _find_product(product_id)
    product = st.Product(
        product_id=product_id, client_id=client_id, product_name=product_name,
        marketplace=marketplace, marketplace_article=marketplace_article,
        marketplace_url=marketplace_url, price=price, category=category,
        product_description=short_product_description,
        # preserve positioning fields already collected in a previous visit
        target_audience=existing.target_audience if existing else "",
        main_pain=existing.main_pain if existing else "",
        who_is_this_for=existing.who_is_this_for if existing else "",
        what_problem_does_it_usually_solve=existing.what_problem_does_it_usually_solve if existing else "",
        why_people_buy_it=existing.why_people_buy_it if existing else "",
        top_3_benefits=existing.top_3_benefits if existing else "",
        use_cases=existing.use_cases if existing else "",
        common_questions=existing.common_questions if existing else "",
        objections=existing.objections if existing else "",
        what_should_not_be_claimed=existing.what_should_not_be_claimed if existing else "",
        tone_preference=existing.tone_preference if existing else "",
    )
    st.save_product(product, REPO_ROOT)

    si.update_seller_intake(client_id, product_id, REPO_ROOT, product_basics={
        "product_name": product_name, "marketplace": marketplace,
        "marketplace_article": marketplace_article, "marketplace_url": marketplace_url,
        "price": price, "category": category,
        "short_product_description": short_product_description,
    })
    si.sync_readiness_checklist(client_id, product_id, REPO_ROOT)

    return RedirectResponse(url=f"/b2b/seller/{product_id}/step2", status_code=303)


# -- STEP 2: reference photos --------------------------------------------------

@router.get("/{product_id}/step2", response_class=HTMLResponse)
def step2_form(request: Request, product_id: str):
    product = _require_product(product_id)
    refs = st.load_references(product.client_id, product_id, REPO_ROOT)
    refs_by_role = {}
    for r in refs:
        refs_by_role.setdefault(r.role, []).append(r)
    return templates.TemplateResponse(request, "wizard/step2.html", {
        "product": product, "slots": REFERENCE_UPLOAD_SLOTS, "refs_by_role": refs_by_role,
        "references": refs,
    })


@router.post("/{product_id}/step2")
async def step2_submit(
    product_id: str,
    front_photo: UploadFile = File(default=None),
    top_photo: UploadFile = File(default=None),
    side_photo: UploadFile = File(default=None),
    detail_photo: UploadFile = File(default=None),
    packaging_photo: UploadFile = File(default=None),
    additional_photos: list[UploadFile] = File(default=[]),
):
    product = _require_product(product_id)
    client_id = product.client_id
    uploaded_dir = st.references_dir(client_id, product_id, REPO_ROOT) / "uploaded"
    uploaded_dir.mkdir(parents=True, exist_ok=True)

    named_uploads = [
        (front_photo, "front"), (top_photo, "top"), (side_photo, "side"),
        (detail_photo, "detail"), (packaging_photo, "packaging"),
    ]
    saved_count = 0
    for upload, role in named_uploads:
        if upload is None or not getattr(upload, "filename", None):
            continue
        dest = uploaded_dir / upload.filename
        with dest.open("wb") as f:
            shutil.copyfileobj(upload.file, f)
        rel_path = str(dest.relative_to(ROOT)).replace("\\", "/")
        st.add_reference(client_id, product_id, rel_path, role=role,
                         approved=False, repo_root=REPO_ROOT)
        saved_count += 1

    for upload in additional_photos or []:
        if not getattr(upload, "filename", None):
            continue
        dest = uploaded_dir / upload.filename
        with dest.open("wb") as f:
            shutil.copyfileobj(upload.file, f)
        rel_path = str(dest.relative_to(ROOT)).replace("\\", "/")
        st.add_reference(client_id, product_id, rel_path, role="other",
                         approved=False, repo_root=REPO_ROOT)
        saved_count += 1

    refs = st.load_references(client_id, product_id, REPO_ROOT)
    si.update_seller_intake(client_id, product_id, REPO_ROOT, reference_uploads={
        "total_uploaded": len(refs),
        "uploaded_this_step": saved_count,
        "roles_present": sorted({r.role for r in refs}),
    })
    si.sync_readiness_checklist(client_id, product_id, REPO_ROOT)

    return RedirectResponse(url=f"/b2b/seller/{product_id}/step3", status_code=303)


# -- STEP 3: customer & positioning -------------------------------------------

@router.get("/{product_id}/step3", response_class=HTMLResponse)
def step3_form(request: Request, product_id: str):
    product = _require_product(product_id)
    return templates.TemplateResponse(request, "wizard/step3.html", {
        "product": product, "tone_options": ("calm", "emotional", "expert", "funny",
                                             "premium", "simple"),
    })


@router.post("/{product_id}/step3")
def step3_submit(
    product_id: str,
    who_is_this_for: str = Form(""),
    what_problem_does_it_usually_solve: str = Form(""),
    why_people_buy_it: str = Form(""),
    top_3_benefits: str = Form(""),
    use_cases: str = Form(""),
    common_questions: str = Form(""),
    objections: str = Form(""),
    what_should_not_be_claimed: str = Form(""),
    tone_preference: str = Form(""),
):
    product = _require_product(product_id)
    product.who_is_this_for = who_is_this_for
    product.what_problem_does_it_usually_solve = what_problem_does_it_usually_solve
    product.why_people_buy_it = why_people_buy_it
    product.top_3_benefits = top_3_benefits
    product.use_cases = use_cases
    product.common_questions = common_questions
    product.objections = objections
    product.what_should_not_be_claimed = what_should_not_be_claimed
    product.tone_preference = tone_preference
    st.save_product(product, REPO_ROOT)

    si.update_seller_intake(product.client_id, product_id, REPO_ROOT, customer_positioning={
        "who_is_this_for": who_is_this_for,
        "what_problem_does_it_usually_solve": what_problem_does_it_usually_solve,
        "why_people_buy_it": why_people_buy_it,
        "top_3_benefits": top_3_benefits,
        "use_cases": use_cases,
        "common_questions": common_questions,
        "objections": objections,
        "forbidden_claims": what_should_not_be_claimed,
        "tone_preference": tone_preference,
    })

    envelope = pi.regenerate_product_intelligence(product.client_id, product_id, REPO_ROOT)
    si.update_seller_intake(product.client_id, product_id, REPO_ROOT, product_intelligence_summary={
        "matched_category": envelope["report"]["matched_category"],
        "match_confidence": envelope["report"]["match_confidence"],
        "core_problem_solved": envelope["report"]["core_problem_solved"],
        "approved_by_owner": envelope["approved_by_owner"],
    })
    si.sync_readiness_checklist(product.client_id, product_id, REPO_ROOT)

    return RedirectResponse(url=f"/b2b/seller/{product_id}/step4", status_code=303)


# -- STEP 4: AI analysis review -----------------------------------------------

@router.get("/{product_id}/step4", response_class=HTMLResponse)
def step4_form(request: Request, product_id: str):
    product = _require_product(product_id)
    envelope = pi.load_product_intelligence(product.client_id, product_id, REPO_ROOT)
    if envelope is None:
        envelope = pi.write_product_intelligence(product.client_id, product_id, REPO_ROOT)
    return templates.TemplateResponse(request, "wizard/step4.html", {
        "product": product, "intelligence": envelope,
        "positioning_modes": pi.POSITIONING_MODES,
    })


@router.post("/{product_id}/step4/approve")
def step4_approve(product_id: str, approval_notes: str = Form("")):
    product = _require_product(product_id)
    pi.approve_product_intelligence(product.client_id, product_id, REPO_ROOT, approval_notes)
    si.sync_readiness_checklist(product.client_id, product_id, REPO_ROOT)
    return RedirectResponse(url=f"/b2b/seller/{product_id}/step4", status_code=303)


@router.post("/{product_id}/step4/primary-problem")
def step4_primary_problem(product_id: str, problem_text: str = Form(...)):
    product = _require_product(product_id)
    try:
        pi.set_primary_problem(product.client_id, product_id, REPO_ROOT, problem_text)
    except pi.ProductIntelligenceError as e:
        raise HTTPException(422, f"{e.code}: {e}")
    return RedirectResponse(url=f"/b2b/seller/{product_id}/step4", status_code=303)


@router.post("/{product_id}/step4/regenerate")
def step4_regenerate(product_id: str):
    product = _require_product(product_id)
    pi.regenerate_product_intelligence(product.client_id, product_id, REPO_ROOT)
    si.sync_readiness_checklist(product.client_id, product_id, REPO_ROOT)
    return RedirectResponse(url=f"/b2b/seller/{product_id}/step4", status_code=303)


@router.post("/{product_id}/step4/hook-toggle")
def step4_hook_toggle(product_id: str, index: int = Form(...), enabled: str = Form("false")):
    product = _require_product(product_id)
    try:
        pi.toggle_hook_angle(product.client_id, product_id, REPO_ROOT, index,
                             enabled.lower() in ("1", "true", "on", "yes"))
    except pi.ProductIntelligenceError as e:
        raise HTTPException(422, f"{e.code}: {e}")
    return RedirectResponse(url=f"/b2b/seller/{product_id}/step4", status_code=303)


@router.post("/{product_id}/step4/positioning-mode")
def step4_positioning_mode(product_id: str, mode: str = Form(...)):
    product = _require_product(product_id)
    try:
        pi.set_positioning_mode(product.client_id, product_id, REPO_ROOT, mode)
    except pi.ProductIntelligenceError as e:
        raise HTTPException(422, f"{e.code}: {e}")
    return RedirectResponse(url=f"/b2b/seller/{product_id}/step4", status_code=303)


# -- STEP 5: content package settings -----------------------------------------

@router.get("/{product_id}/step5", response_class=HTMLResponse)
def step5_form(request: Request, product_id: str):
    product = _require_product(product_id)
    intake = si.load_seller_intake(product.client_id, product_id, REPO_ROOT) or {}
    settings = intake.get("content_package_settings", {})
    return templates.TemplateResponse(request, "wizard/step5.html", {
        "product": product, "platforms": st.CAMPAIGN_PLATFORMS,
        "durations": si.PACKAGE_DURATIONS, "content_types": si.CONTENT_TYPES,
        "settings": settings,
    })


@router.post("/{product_id}/step5")
def step5_submit(
    product_id: str,
    platforms: list[str] = Form(default=[]),
    package_duration: str = Form("14_days"),
    content_types: list[str] = Form(default=[]),
):
    product = _require_product(product_id)
    settings = {
        "platforms": platforms,
        "package_duration": package_duration,
        "content_types": content_types,
        "manual_or_autopost": "manual_upload_ready_kit",
    }
    si.update_seller_intake(product.client_id, product_id, REPO_ROOT,
                            content_package_settings=settings)
    si.sync_readiness_checklist(product.client_id, product_id, REPO_ROOT)
    return RedirectResponse(url=f"/b2b/seller/{product_id}/step6", status_code=303)


# -- STEP 6: readiness checklist -----------------------------------------------

@router.get("/{product_id}/step6", response_class=HTMLResponse)
def step6_form(request: Request, product_id: str, saved: str = None):
    product = _require_product(product_id)
    checklist = si.sync_readiness_checklist(product.client_id, product_id, REPO_ROOT)
    intelligence = pi.load_product_intelligence(product.client_id, product_id, REPO_ROOT)
    return templates.TemplateResponse(request, "wizard/step6.html", {
        "product": product, "checklist": checklist, "intelligence": intelligence,
        "min_refs": pol.MIN_APPROVED_REFERENCES, "saved": bool(saved),
    })


@router.post("/{product_id}/step6/save-draft")
def step6_save_draft(product_id: str):
    product = _require_product(product_id)
    si.sync_readiness_checklist(product.client_id, product_id, REPO_ROOT)
    return RedirectResponse(url=f"/b2b/seller/{product_id}/step6?saved=1", status_code=303)


@router.post("/{product_id}/step6/dry-run")
def step6_run_dry_run(product_id: str):
    product = _require_product(product_id)
    checklist = si.build_readiness_checklist(product.client_id, product_id, REPO_ROOT)
    if not checklist["can_run_dry_run"]:
        raise HTTPException(422, "NOT_ENOUGH_APPROVED_REFERENCES: need at least "
                                 f"{pol.MIN_APPROVED_REFERENCES} approved product references")
    intake = si.load_seller_intake(product.client_id, product_id, REPO_ROOT) or {}
    campaign = _get_or_create_wizard_campaign(product, intake.get("content_package_settings", {}))
    try:
        write_campaign_dry_run(campaign.client_id, campaign.product_id, campaign.campaign_id, REPO_ROOT)
    except pol.B2BReferencePolicyError as e:
        raise HTTPException(422, f"{e.code}: {e}")
    return RedirectResponse(url=f"/b2b/campaigns/{campaign.campaign_id}", status_code=303)


@router.post("/{product_id}/step6/create-package")
def step6_create_package(product_id: str):
    product = _require_product(product_id)
    checklist = si.build_readiness_checklist(product.client_id, product_id, REPO_ROOT)
    if not checklist["can_run_dry_run"]:
        raise HTTPException(422, "NOT_ENOUGH_APPROVED_REFERENCES: need at least "
                                 f"{pol.MIN_APPROVED_REFERENCES} approved product references")
    intake = si.load_seller_intake(product.client_id, product_id, REPO_ROOT) or {}
    campaign = _get_or_create_wizard_campaign(product, intake.get("content_package_settings", {}))
    try:
        write_campaign_dry_run(campaign.client_id, campaign.product_id, campaign.campaign_id, REPO_ROOT)
        build_delivery_kit_zip(campaign.client_id, campaign.product_id, campaign.campaign_id, REPO_ROOT)
    except pol.B2BReferencePolicyError as e:
        raise HTTPException(422, f"{e.code}: {e}")
    return RedirectResponse(url=f"/b2b/campaigns/{campaign.campaign_id}", status_code=303)
