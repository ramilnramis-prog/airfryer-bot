"""FastAPI v1 для интеграции с n8n.

Роуты:
  GET  /health
  POST /prepare-telegram-post   (auth)
  POST /generate-pdf            (auth)  -> job
  POST /generate-content        (auth, stub) -> job
  GET  /publish-status          (auth)
Статика:
  /files/photos/{name}  -> фото блюд
  /files/{name}         -> сгенерированные PDF
"""
import time
import sqlite3
import logging

from fastapi import FastAPI, Depends, BackgroundTasks, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from .config import PHOTOS_DIR, GEN_DIR, BASE_URL, REGISTRY_AUTO_MIGRATE
from .auth import require_api_key
from . import db, jobs, registry_db
from .registry import router as registry_router
from .posts import prepare_post

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("api")

app = FastAPI(title="Airfryer Content API", version="1.0")
_START = time.time()


@app.on_event("startup")
def _startup():
    db.init_db()                 # очередь jobs (без изменений)
    # Реестр НЕ мигрируем автоматически в prod — только при явном REGISTRY_AUTO_MIGRATE=1.
    if REGISTRY_AUTO_MIGRATE:
        registry_db.run_migrations()
        log.info("registry: auto-migrate ON")
    else:
        log.info("registry: auto-migrate OFF (run `python -m api.registry_db` to migrate)")
    log.info("API up. photos=%s gen=%s", PHOTOS_DIR, GEN_DIR)


# Статика. Более специфичный префикс (/files/photos) монтируем ПЕРВЫМ.
app.mount("/files/photos", StaticFiles(directory=str(PHOTOS_DIR)), name="photos")
app.mount("/files", StaticFiles(directory=str(GEN_DIR)), name="files")

# Единый реестр (источник истины) — отдельный набор роутов /registry/*
app.include_router(registry_router)


@app.exception_handler(sqlite3.IntegrityError)
async def _on_integrity(request: Request, exc: sqlite3.IntegrityError):
    # FK/UNIQUE/CHECK нарушение -> понятный 409 без stack trace и без секретов
    return JSONResponse(status_code=409, content={"detail": "integrity constraint violated"})


@app.exception_handler(sqlite3.OperationalError)
async def _on_operational(request: Request, exc: sqlite3.OperationalError):
    # БД занята/недоступна -> 503 без stack trace
    return JSONResponse(status_code=503, content={"detail": "database busy or unavailable"})


def _base_url(request: Request) -> str:
    return BASE_URL or str(request.base_url).rstrip("/")


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0", "uptime_sec": int(time.time() - _START)}


@app.post("/prepare-telegram-post")
def prepare_telegram_post(payload: dict, request: Request, _=Depends(require_api_key)):
    rid = payload.get("recipe_id")
    if rid is None:
        raise HTTPException(status_code=400, detail="recipe_id required (1..N)")
    res = prepare_post(int(rid), _base_url(request))
    if res is None:
        raise HTTPException(status_code=404, detail="recipe not found")
    return res


@app.post("/generate-pdf", status_code=202)
def generate_pdf(payload: dict, background: BackgroundTasks,
                 request: Request, _=Depends(require_api_key)):
    if payload.get("source") not in ("markdown", "recipes"):
        raise HTTPException(status_code=400, detail="source must be 'markdown' or 'recipes'")
    job_id = jobs.new_job_id()
    db.create_job(job_id, "generate-pdf")
    log.info("job %s queued: generate-pdf", job_id)
    background.add_task(jobs.run_generate_pdf, job_id, payload, _base_url(request))
    return {"job_id": job_id, "status": "queued"}


@app.post("/generate-content", status_code=202)
def generate_content(payload: dict, background: BackgroundTasks, _=Depends(require_api_key)):
    job_id = jobs.new_job_id()
    db.create_job(job_id, "generate-content")
    log.info("job %s queued: generate-content", job_id)
    background.add_task(jobs.run_generate_content, job_id, payload)
    return {"job_id": job_id, "status": "queued"}


@app.get("/publish-status")
def publish_status(job_id: str, _=Depends(require_api_key)):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job
