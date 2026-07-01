"""HTTP-слой реестра. Тело — dict (стиль проекта). Защита: X-API-Key + проверка миграции
на уровне роутера. Все create-операции идемпотентны по стабильным кодам (registry_db).
Ошибки sqlite (FK/занятость) перехватываются в main.py и НЕ отдают stack trace.
"""
from fastapi import APIRouter, Depends, HTTPException

from .auth import require_api_key
from . import registry_db as R
from . import content_package as CP


def _require_migrated():
    if not R.schema_present():
        raise HTTPException(
            status_code=503,
            detail="registry schema not migrated; run: python -m api.registry_db "
                   "(or set REGISTRY_AUTO_MIGRATE=1)",
        )


router = APIRouter(
    prefix="/registry",
    tags=["registry"],
    dependencies=[Depends(require_api_key), Depends(_require_migrated)],
)


def _need(payload: dict, *keys):
    miss = [k for k in keys if payload.get(k) in (None, "")]
    if miss:
        raise HTTPException(status_code=400, detail=f"missing fields: {', '.join(miss)}")


# ---------- товары ----------
@router.post("/products")
def create_product(payload: dict):
    _need(payload, "product_code", "name")
    row, created = R.create_or_get_product(
        product_code=payload["product_code"],
        name=payload["name"],
        marketplace=payload.get("marketplace", "ozon"),
        external_id=payload.get("external_id"),
        status=payload.get("status", "active"),
    )
    return {"created": created, "product": row}


@router.get("/products/{product_code}")
def get_product(product_code: str):
    row = R.get_product_by_code(product_code)
    if not row:
        raise HTTPException(status_code=404, detail="product not found")
    return {"product": row}


@router.patch("/products/{product_code}")
def patch_product(product_code: str, payload: dict):
    """Дополнить/изменить товар (например, добавить external_id позже). Код не меняется."""
    if not R.get_product_by_code(product_code):
        raise HTTPException(status_code=404, detail="product not found")
    allowed = {k: payload[k] for k in R._PRODUCT_UPDATABLE if k in payload}
    return {"product": R.update_product(product_code, **allowed)}


# ---------- контент ----------
@router.post("/contents")
def create_content(payload: dict):
    _need(payload, "product_id", "content_code", "content_type", "title")
    row, created = R.create_or_get_content(
        product_id=payload["product_id"],
        content_code=payload["content_code"],
        content_type=payload["content_type"],
        title=payload["title"],
        core_idea=payload.get("core_idea"),
        audience_segment=payload.get("audience_segment"),
        pain_or_desire=payload.get("pain_or_desire"),
        hypothesis=payload.get("hypothesis"),
        source_path=payload.get("source_path"),
        status=payload.get("status", "draft"),
    )
    return {"created": created, "content": row}


@router.get("/contents/{content_id}/summary")
def content_summary(content_id: int):
    s = R.content_summary(content_id)
    if not s:
        raise HTTPException(status_code=404, detail="content not found")
    return s


# ---------- хуки ----------
@router.post("/hooks")
def add_hook(payload: dict):
    _need(payload, "content_id", "hook_code")
    row, created = R.add_hook(
        content_id=payload["content_id"], hook_code=payload["hook_code"],
        hook_text=payload.get("hook_text"), version=payload.get("version", 1),
        status=payload.get("status", "draft"))
    return {"created": created, "hook": row}


# ---------- каналы ----------
@router.post("/channels")
def create_channel(payload: dict):
    _need(payload, "code", "name")
    row, created = R.create_or_get_channel(
        code=payload["code"], name=payload["name"], status=payload.get("status", "active"))
    return {"created": created, "channel": row}


@router.get("/channels")
def list_channels():
    return {"items": R.list_channels()}


# ---------- публикации ----------
@router.post("/publications")
def create_publication(payload: dict):
    _need(payload, "content_id", "channel_id", "publication_code")
    extra = {k: payload[k] for k in (
        "external_publication_id", "scheduled_at", "published_at", "destination_url",
        "tracking_url", "utm_source", "utm_medium", "utm_campaign", "utm_content",
        "error_message") if k in payload}
    row, created = R.create_or_get_publication(
        content_id=payload["content_id"], channel_id=payload["channel_id"],
        publication_code=payload["publication_code"], hook_id=payload.get("hook_id"),
        status=payload.get("status", "draft"), **extra)
    return {"created": created, "publication": row}


@router.get("/publications/{publication_code}")
def get_publication(publication_code: str):
    row = R.get_publication_by_code(publication_code)
    if not row:
        raise HTTPException(status_code=404, detail="publication not found")
    return {"publication": row}


@router.patch("/publications/{publication_code}")
def patch_publication(publication_code: str, payload: dict):
    if not R.get_publication_by_code(publication_code):
        raise HTTPException(status_code=404, detail="publication not found")
    allowed = {k: payload[k] for k in R._PUB_UPDATABLE if k in payload}
    return {"publication": R.update_publication(publication_code, **allowed)}


@router.get("/publications")
def list_publications(product_id: int = None, channel: str = None, status: str = None):
    return {"items": R.list_publications(product_id=product_id, channel_code=channel, status=status)}


@router.get("/publications/{publication_code}/summary")
def publication_summary(publication_code: str):
    s = R.publication_summary(publication_code)
    if not s:
        raise HTTPException(status_code=404, detail="publication not found")
    return s


# ---------- снимки метрик / коммерции ----------
@router.post("/metric-snapshots")
def add_metric_snapshot(payload: dict):
    _need(payload, "publication_id", "source")
    metrics = {k: payload[k] for k in R._METRIC_FIELDS if k in payload}
    row, created = R.add_metric_snapshot(
        publication_id=payload["publication_id"], source=payload["source"],
        captured_at=payload.get("captured_at"), **metrics)
    return {"created": created, "metric_snapshot": row}


@router.post("/commerce-snapshots")
def add_commerce_snapshot(payload: dict):
    _need(payload, "product_id", "source", "attribution_type")
    if payload["attribution_type"] not in (
            "direct", "platform_reported", "utm_reported", "estimated", "unattributed"):
        raise HTTPException(status_code=400, detail="invalid attribution_type")
    metrics = {k: payload[k] for k in R._COMMERCE_FIELDS if k in payload}  # revenue_minor/spend_minor — INTEGER
    row, created = R.add_commerce_snapshot(
        product_id=payload["product_id"], source=payload["source"],
        attribution_type=payload["attribution_type"], captured_at=payload.get("captured_at"),
        publication_id=payload.get("publication_id"), currency=payload.get("currency", "RUB"),
        **metrics)
    return {"created": created, "commerce_snapshot": row}


# ---------- журнал решений ----------
@router.post("/decisions")
def add_decision(payload: dict):
    _need(payload, "publication_id", "decision")
    if payload["decision"] not in ("SCALE", "ITERATE", "HOLD", "STOP", "INVESTIGATE"):
        raise HTTPException(status_code=400, detail="invalid decision")
    R.add_decision_record(
        publication_id=payload["publication_id"], decision=payload["decision"],
        reason=payload.get("reason"), evidence_json=payload.get("evidence_json"),
        data_window_start=payload.get("data_window_start"),
        data_window_end=payload.get("data_window_end"))
    return {"ok": True}


# ---------- content package (мост skill -> реестр, только draft) ----------
@router.post("/content-packages")
def import_content_package(payload: dict):
    """Транзакционный идемпотентный импорт: product -> content -> hooks -> publications (draft).
    Формат — api/CONTENT_PACKAGE.md. Ничего не публикует; статусы кроме draft отклоняются."""
    try:
        return CP.import_package(payload)
    except CP.ProductNotFoundError as e:
        raise HTTPException(status_code=404, detail={"error": str(e), "field": e.field})
    except CP.PackageConflict as e:
        raise HTTPException(status_code=409, detail={"error": str(e), "field": e.field})
    except CP.PackageError as e:
        raise HTTPException(status_code=400, detail={"error": str(e), "field": e.field})
