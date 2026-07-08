"""Public seller-facing entry point for the B2B content factory --
"Крутая внешняя реклама". Landing page, beta-gated start (wraps the
existing /b2b/seller/* wizard), a public demo, and a lightweight status
page. No X-API-Key auth (same intentional MVP gap as api/b2b.py and
api/b2b_seller_wizard.py). Zero network calls anywhere in this module.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .config import ROOT
from .media_pipeline import b2b_storage as st
from .media_pipeline import product_intelligence as pi
from .media_pipeline import seller_intake as si
from .media_pipeline import b2b_seed as seed
from .media_pipeline import b2b_delivery_kit as dk
from .b2b import _find_product

router = APIRouter(prefix="/traffic-factory", tags=["traffic-factory"])

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

REPO_ROOT = str(ROOT)

BETA_ACCESS_CODE_ENV = "B2B_BETA_ACCESS_CODE"
DEFAULT_BETA_ACCESS_CODE = "SELLER-BETA"


def _beta_access_code() -> str:
    return os.environ.get(BETA_ACCESS_CODE_ENV) or DEFAULT_BETA_ACCESS_CODE


@router.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return templates.TemplateResponse(request, "traffic_factory/landing.html", {})


@router.get("/start", response_class=HTMLResponse)
def start_gate(request: Request):
    return templates.TemplateResponse(request, "traffic_factory/start_gate.html", {"error": False})


@router.post("/start", response_class=HTMLResponse)
def start_gate_submit(request: Request, access_code: str = Form(...)):
    if access_code.strip() != _beta_access_code():
        return templates.TemplateResponse(request, "traffic_factory/start_gate.html", {"error": True})
    return RedirectResponse(url="/b2b/seller/start", status_code=303)


@router.get("/demo", response_class=HTMLResponse)
def demo(request: Request):
    client_id, product_id, campaign_id = seed.DEMO_CLIENT_ID, seed.DEMO_PRODUCT_ID, seed.DEMO_CAMPAIGN_ID
    product = _find_product(product_id)
    if product is None:
        return templates.TemplateResponse(request, "traffic_factory/demo.html", {
            "seeded": False,
        })

    refs = st.load_references(client_id, product_id, REPO_ROOT)
    intelligence = pi.load_product_intelligence(client_id, product_id, REPO_ROOT)
    if intelligence is None:
        intelligence = pi.write_product_intelligence(client_id, product_id, REPO_ROOT)

    gen_dir = st.campaign_generated_dir(client_id, product_id, campaign_id, REPO_ROOT)
    dry_run_exists = (gen_dir / "campaign-dry-run.json").is_file()
    delivery_zip_exists = (gen_dir / "delivery" / "DELIVERY-KIT.zip").is_file()

    return templates.TemplateResponse(request, "traffic_factory/demo.html", {
        "seeded": True, "product": product, "references": refs, "intelligence": intelligence,
        "campaign_id": campaign_id, "dry_run_exists": dry_run_exists,
        "delivery_zip_exists": delivery_zip_exists,
        "delivery_subdirs": dk.DELIVERY_SUBDIRS,
        "delivery_files": ("OWNER-README.md", "PRODUCT-SUMMARY.md", "CAMPAIGN-PLAN.md",
                          "REFERENCE-POLICY.md", "NEXT-STEPS.md", "DELIVERY-KIT.zip"),
    })


@router.get("/status/{request_id}", response_class=HTMLResponse)
def status_page(request: Request, request_id: str):
    product = _find_product(request_id)
    if product is None:
        return templates.TemplateResponse(request, "traffic_factory/status.html", {
            "request_id": request_id, "found": False,
        })

    client_id, product_id = product.client_id, product.product_id
    refs = st.load_references(client_id, product_id, REPO_ROOT)
    intake = si.load_seller_intake(client_id, product_id, REPO_ROOT)
    checklist = si.build_readiness_checklist(client_id, product_id, REPO_ROOT)

    content_package_plan_ready = False
    for campaign in st.list_campaigns(client_id, product_id, REPO_ROOT):
        gen_dir = st.campaign_generated_dir(client_id, product_id, campaign.campaign_id, REPO_ROOT)
        if (gen_dir / "campaign-dry-run.json").is_file():
            content_package_plan_ready = True
            break

    ai_analysis_ready = checklist["product_intelligence_generated"]
    if not checklist["at_least_3_approved_references"]:
        next_step = "Загрузите и одобрите минимум 3 фото товара, затем запустите проверку пакета."
    elif not checklist["primary_problem_approved"]:
        next_step = "Проверьте, правильно ли AI понял ваш товар, и подтвердите анализ."
    elif not content_package_plan_ready:
        next_step = "Запустите проверку будущего контент-пакета (dry-run)."
    else:
        next_step = "Ожидайте ручной проверки владельцем/админом перед реальной генерацией контента."

    return templates.TemplateResponse(request, "traffic_factory/status.html", {
        "request_id": request_id, "found": True, "product": product,
        "draft_saved": intake is not None,
        "product_info_complete": checklist["product_info_complete"],
        "references_uploaded": len(refs) > 0,
        "ai_analysis_ready": ai_analysis_ready,
        "content_package_plan_ready": content_package_plan_ready,
        "next_step": next_step,
    })
