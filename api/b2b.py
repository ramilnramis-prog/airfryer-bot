"""B2B Seller Product Traffic Factory -- server-rendered ADMIN-first MVP.
We (the agency) create clients/products/campaigns manually and hand the
seller a delivery kit -- no seller signup/payment/login yet. No X-API-Key
auth on these routes (unlike /registry) since they're browser-rendered HTML
pages, not a JSON API -- this is an intentional, documented MVP gap; add
real auth before exposing this outside a trusted admin. See
content/b2b/AUTOPOSTING-ROADMAP.md for what comes after this skeleton.
"""
from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .config import ROOT
from .media_pipeline import b2b_storage as st
from .media_pipeline import b2b_reference_policy as pol
from .media_pipeline import b2b_seed as seed
from .media_pipeline.b2b_campaign_contract import write_campaign_dry_run
from .media_pipeline.b2b_delivery_kit import build_delivery_kit_zip

router = APIRouter(prefix="/b2b", tags=["b2b"])

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates" / "b2b"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

REPO_ROOT = str(ROOT)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or uuid.uuid4().hex[:8]


def _find_product(product_id: str):
    for p in st.list_all_products(REPO_ROOT):
        if p.product_id == product_id:
            return p
    return None


def _find_campaign(campaign_id: str):
    for c in st.list_all_campaigns(REPO_ROOT):
        if c.campaign_id == campaign_id:
            return c
    return None


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    rows = []
    products_count = 0
    campaigns_count = 0
    for client in st.list_clients(REPO_ROOT):
        for product in st.list_products(client.client_id, REPO_ROOT):
            products_count += 1
            campaigns = st.list_campaigns(client.client_id, product.product_id, REPO_ROOT)
            campaigns_count += len(campaigns)
            rows.append({"client": client, "product": product, "campaigns": campaigns})
    demo_campaign_exists = (st.campaign_dir(seed.DEMO_CLIENT_ID, seed.DEMO_PRODUCT_ID,
                                            seed.DEMO_CAMPAIGN_ID, REPO_ROOT)
                            / "campaign.json").is_file()
    return templates.TemplateResponse(request, "dashboard.html", {
        "rows": rows,
        "clients_count": len(st.list_clients(REPO_ROOT)),
        "products_count": products_count,
        "campaigns_count": campaigns_count,
        "demo_campaign_id": seed.DEMO_CAMPAIGN_ID,
        "demo_campaign_exists": demo_campaign_exists,
    })


@router.get("/products/new", response_class=HTMLResponse)
def product_new_form(request: Request):
    return templates.TemplateResponse(request, "product_new.html", {
        "marketplaces": st.PRODUCT_MARKETPLACES,
    })


@router.post("/products/new")
async def product_new_submit(
    client_name: str = Form(...),
    contact: str = Form(""),
    product_name: str = Form(...),
    marketplace: str = Form("ozon"),
    marketplace_article: str = Form(""),
    marketplace_url: str = Form(""),
    category: str = Form(""),
    target_audience: str = Form(""),
    main_pain: str = Form(""),
    product_description: str = Form(""),
    reference_images: list[UploadFile] = File(default=[]),
):
    client_id = _slugify(client_name)
    if not (st.client_dir(client_id, REPO_ROOT) / "client.json").is_file():
        st.save_client(st.Client(client_id=client_id, name=client_name, contact=contact), REPO_ROOT)

    product_id = _slugify(product_name)
    product = st.Product(
        product_id=product_id, client_id=client_id, product_name=product_name,
        marketplace=marketplace, marketplace_url=marketplace_url,
        marketplace_article=marketplace_article, category=category,
        target_audience=target_audience, main_pain=main_pain,
        product_description=product_description,
    )
    st.save_product(product, REPO_ROOT)

    uploaded_dir = st.references_dir(client_id, product_id, REPO_ROOT) / "uploaded"
    uploaded_dir.mkdir(parents=True, exist_ok=True)
    for upload in reference_images or []:
        if not getattr(upload, "filename", None):
            continue
        dest = uploaded_dir / upload.filename
        with dest.open("wb") as f:
            shutil.copyfileobj(upload.file, f)
        rel_path = str(dest.relative_to(ROOT)).replace("\\", "/")
        st.add_reference(client_id, product_id, rel_path, role="other",
                         approved=False, repo_root=REPO_ROOT)

    return RedirectResponse(url=f"/b2b/products/{product_id}", status_code=303)


@router.get("/products/{product_id}", response_class=HTMLResponse)
def product_detail(request: Request, product_id: str):
    product = _find_product(product_id)
    if not product:
        raise HTTPException(404, "product not found")
    refs = st.load_references(product.client_id, product_id, REPO_ROOT)
    campaigns = st.list_campaigns(product.client_id, product_id, REPO_ROOT)
    approved_count = sum(1 for r in refs if r.approved)
    return templates.TemplateResponse(request, "product_detail.html", {
        "product": product, "references": refs, "campaigns": campaigns,
        "min_refs": pol.MIN_APPROVED_REFERENCES, "approved_count": approved_count,
        "can_generate": approved_count >= pol.MIN_APPROVED_REFERENCES,
        "roles": st.PRODUCT_REFERENCE_ROLES,
    })


@router.post("/products/{product_id}/references/approve")
def approve_reference(product_id: str, file_path: str = Form(...)):
    product = _find_product(product_id)
    if not product:
        raise HTTPException(404, "product not found")
    refs = st.load_references(product.client_id, product_id, REPO_ROOT)
    for r in refs:
        if r.file_path == file_path:
            r.approved = True
    st.save_references(product.client_id, product_id, refs, REPO_ROOT)
    return RedirectResponse(url=f"/b2b/products/{product_id}", status_code=303)


@router.post("/products/{product_id}/references/unapprove")
def unapprove_reference(product_id: str, file_path: str = Form(...)):
    product = _find_product(product_id)
    if not product:
        raise HTTPException(404, "product not found")
    refs = st.load_references(product.client_id, product_id, REPO_ROOT)
    for r in refs:
        if r.file_path == file_path:
            r.approved = False
    st.save_references(product.client_id, product_id, refs, REPO_ROOT)
    return RedirectResponse(url=f"/b2b/products/{product_id}", status_code=303)


@router.post("/products/{product_id}/references/role")
def set_reference_role(product_id: str, file_path: str = Form(...), role: str = Form(...)):
    product = _find_product(product_id)
    if not product:
        raise HTTPException(404, "product not found")
    if role not in st.PRODUCT_REFERENCE_ROLES:
        raise HTTPException(400, f"unknown role {role!r}")
    refs = st.load_references(product.client_id, product_id, REPO_ROOT)
    for r in refs:
        if r.file_path == file_path:
            r.role = role
    st.save_references(product.client_id, product_id, refs, REPO_ROOT)
    return RedirectResponse(url=f"/b2b/products/{product_id}", status_code=303)


@router.post("/products/{product_id}/campaigns/new")
def create_campaign(product_id: str, campaign_goal: str = Form("external_traffic")):
    product = _find_product(product_id)
    if not product:
        raise HTTPException(404, "product not found")
    campaign_id = f"{product_id}-{uuid.uuid4().hex[:6]}"
    campaign = st.Campaign(campaign_id=campaign_id, client_id=product.client_id,
                           product_id=product_id, campaign_goal=campaign_goal, status="draft")
    st.save_campaign(campaign, REPO_ROOT)
    return RedirectResponse(url=f"/b2b/campaigns/{campaign_id}", status_code=303)


@router.get("/campaigns/{campaign_id}", response_class=HTMLResponse)
def campaign_detail(request: Request, campaign_id: str):
    campaign = _find_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, "campaign not found")
    product = _find_product(campaign.product_id)
    gen_dir = st.campaign_generated_dir(campaign.client_id, campaign.product_id,
                                        campaign.campaign_id, REPO_ROOT)
    dry_run_path = gen_dir / "campaign-dry-run.json"
    dry_run_md_path = gen_dir / "campaign-dry-run.md"
    delivery_zip = gen_dir / "delivery" / "DELIVERY-KIT.zip"
    return templates.TemplateResponse(request, "campaign_detail.html", {
        "campaign": campaign, "product": product, "generated_dir": str(gen_dir),
        "dry_run_exists": dry_run_path.is_file(),
        "dry_run_path": str(dry_run_path),
        "dry_run_md_exists": dry_run_md_path.is_file(),
        "dry_run_md_path": str(dry_run_md_path),
        "delivery_kit_exists": delivery_zip.is_file(),
        "delivery_kit_path": str(delivery_zip),
        "generated_subdirs": st.GENERATED_SUBDIRS,
        "min_refs": pol.MIN_APPROVED_REFERENCES,
    })


@router.post("/campaigns/{campaign_id}/dry-run")
def run_campaign_dry_run(campaign_id: str):
    campaign = _find_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, "campaign not found")
    try:
        write_campaign_dry_run(campaign.client_id, campaign.product_id, campaign.campaign_id,
                               REPO_ROOT)
    except pol.B2BReferencePolicyError as e:
        raise HTTPException(422, f"{e.code}: {e}")
    return RedirectResponse(url=f"/b2b/campaigns/{campaign_id}", status_code=303)


@router.post("/campaigns/{campaign_id}/build-delivery-kit")
def build_delivery_kit_route(campaign_id: str):
    campaign = _find_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, "campaign not found")
    try:
        build_delivery_kit_zip(campaign.client_id, campaign.product_id, campaign.campaign_id,
                               REPO_ROOT)
    except pol.B2BReferencePolicyError as e:
        raise HTTPException(422, f"{e.code}: {e}")
    return RedirectResponse(url=f"/b2b/campaigns/{campaign_id}", status_code=303)


@router.get("/campaigns/{campaign_id}/delivery-kit.zip")
def download_delivery_kit(campaign_id: str):
    campaign = _find_campaign(campaign_id)
    if not campaign:
        raise HTTPException(404, "campaign not found")
    gen_dir = st.campaign_generated_dir(campaign.client_id, campaign.product_id,
                                        campaign.campaign_id, REPO_ROOT)
    zip_path = gen_dir / "delivery" / "DELIVERY-KIT.zip"
    if not zip_path.is_file():
        raise HTTPException(404, "delivery kit not built yet")
    return FileResponse(str(zip_path), media_type="application/zip",
                        filename=f"{campaign_id}-DELIVERY-KIT.zip")
