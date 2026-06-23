"""Фоновые задачи: генерация PDF и (заглушка v1) генерация контента."""
import uuid
import logging
from .config import GEN_DIR
from . import db
from .pdfgen import build_markdown_pdf, build_recipes_pdf

log = logging.getLogger("api.jobs")


def new_job_id() -> str:
    return str(uuid.uuid4())


def run_generate_pdf(job_id: str, payload: dict, base_url: str):
    log.info("job %s generate-pdf: start", job_id)
    db.set_status(job_id, "processing")
    try:
        source = payload.get("source")
        filename = payload.get("filename") or f"{job_id}.pdf"
        if not filename.endswith(".pdf"):
            filename += ".pdf"
        out = GEN_DIR / filename

        if source == "markdown":
            build_markdown_pdf(payload.get("content", ""), out)
        elif source == "recipes":
            build_recipes_pdf(payload.get("recipe_ids"), out)
        else:
            raise ValueError("source must be 'markdown' or 'recipes'")

        result = {
            "file_path": f"data/gen/{filename}",
            "file_url": f"{base_url}/files/{filename}",
        }
        db.set_status(job_id, "ready", result=result)
        log.info("job %s generate-pdf: ready -> %s", job_id, filename)
    except Exception as e:  # noqa: BLE001
        log.error("job %s generate-pdf: failed: %s", job_id, e)
        db.set_status(job_id, "failed", error=str(e))


def run_generate_content(job_id: str, payload: dict):
    # v1 — ЗАГЛУШКА. Здесь будет генерация текста через LLM (по ключу из env).
    log.info("job %s generate-content (stub): start", job_id)
    db.set_status(job_id, "processing")
    result = {
        "note": "stub v1 — здесь будет генерация через LLM",
        "echo": payload,
        "caption": "Тоже устали мыть аэрогриль? Силиконовая форма решает. (заглушка)",
        "hashtags": ["#аэрогриль", "#рецепты", "#лайфхаккухни"],
    }
    db.set_status(job_id, "ready", result=result)
    log.info("job %s generate-content (stub): ready", job_id)
