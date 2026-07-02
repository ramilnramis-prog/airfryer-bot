"""Провайдер OpenAI Images API (gpt-image-1). Только stdlib.

Безопасность:
- OPENAI_API_KEY читается ТОЛЬКО из environment в момент вызова;
- ключ никогда не логируется, не сохраняется в файлы и не попадает в результаты;
- по умолчанию dry-run: БЕЗ apply=True никакой сети нет вообще;
- лимиты: бюджет в USD и число кандидатов на запрос.

Endpoints:
- POST /v1/images/generations — text-to-image (JSON);
- POST /v1/images/edits — c reference images (multipart), поддерживает
  несколько изображений и input_fidelity="high" для точности референса.
"""
from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
import urllib.request
import uuid
from pathlib import Path

from .models import ImageProvider, ImageRequest, ImageResult

API_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-image-1"
# Верхняя оценка цены за 1 изображение 1024x1536 high quality (для бюджет-гейта;
# консервативно с запасом, реальная цена может быть ниже).
DEFAULT_PRICE_PER_IMAGE_USD = 0.30
DEFAULT_BUDGET_USD = 5.0
MAX_CANDIDATES_PER_REQUEST = 3


class MediaPipelineError(RuntimeError):
    pass


class MissingAPIKeyError(MediaPipelineError):
    """OPENAI_API_KEY не задан в environment (в сообщении ключей нет и быть не может)."""


class BudgetExceededError(MediaPipelineError):
    pass


def _multipart(fields: dict, files: list) -> tuple:
    """files: [(field, filename, bytes)] -> (body, content_type). Stdlib multipart."""
    boundary = uuid.uuid4().hex
    buf = io.BytesIO()
    for name, value in fields.items():
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        buf.write(str(value).encode() + b"\r\n")
    for name, filename, data in files:
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(('Content-Disposition: form-data; '
                   f'name="{name}"; filename="{Path(filename).name}"\r\n').encode())
        buf.write(f"Content-Type: {ctype}\r\n\r\n".encode())
        buf.write(data + b"\r\n")
    buf.write(f"--{boundary}--\r\n".encode())
    return buf.getvalue(), f"multipart/form-data; boundary={boundary}"


class OpenAIImagesProvider(ImageProvider):
    name = "openai"

    def __init__(self, model: str = DEFAULT_MODEL,
                 price_per_image_usd: float = DEFAULT_PRICE_PER_IMAGE_USD,
                 budget_usd: float = DEFAULT_BUDGET_USD):
        self.model = model
        self.price_per_image_usd = price_per_image_usd
        self.budget_usd = budget_usd
        self.spent_usd = 0.0

    # -- внутреннее -------------------------------------------------------

    @staticmethod
    def _api_key() -> str:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise MissingAPIKeyError(
                "OPENAI_API_KEY отсутствует в environment. Задайте переменную "
                "окружения (НЕ передавайте ключ аргументом и не пишите в файлы).")
        return key

    def _check_budget(self, n: int) -> float:
        est = round(n * self.price_per_image_usd, 4)
        if self.spent_usd + est > self.budget_usd:
            raise BudgetExceededError(
                f"запрос ~${est} превысит бюджет ${self.budget_usd} "
                f"(потрачено ~${self.spent_usd}). Увеличьте budget_usd осознанно.")
        return est

    def _planned_payload(self, req: ImageRequest) -> dict:
        """Payload для журнала/dry-run. Секретов не содержит по построению."""
        planned = {
            "endpoint": ("/images/edits" if req.mode == "edit"
                         else "/images/generations"),
            "model": self.model,
            "prompt": req.prompt,
            "n": req.n,
            "size": req.size,
        }
        if req.mode == "edit":
            planned["reference_images"] = list(req.reference_images)
            if req.input_fidelity:
                planned["input_fidelity"] = req.input_fidelity
        return planned

    # -- ImageProvider ------------------------------------------------------

    def generate(self, request: ImageRequest, out_dir: str,
                 apply: bool = False) -> list:
        if request.n > MAX_CANDIDATES_PER_REQUEST:
            raise MediaPipelineError(
                f"n={request.n} > лимита {MAX_CANDIDATES_PER_REQUEST} кандидатов")
        if request.mode not in ("generate", "edit"):
            raise MediaPipelineError(f"неизвестный mode: {request.mode}")
        if request.mode == "edit" and not request.reference_images:
            raise MediaPipelineError("mode=edit требует reference_images")

        est = self._check_budget(request.n)
        planned = self._planned_payload(request)

        if not apply:
            # DRY-RUN: никакой сети, ключ даже не читается.
            return [ImageResult(
                candidate_id=f"{request.scene_id}-c{i + 1}",
                scene_id=request.scene_id, provider=self.name, model=self.model,
                prompt=request.prompt, dry_run=True,
                estimated_cost_usd=round(est / request.n, 4),
                planned_request=planned,
            ) for i in range(request.n)]

        key = self._api_key()
        if request.mode == "edit":
            files = []
            for ref in request.reference_images:
                files.append(("image[]", ref, Path(ref).read_bytes()))
            fields = {"model": self.model, "prompt": request.prompt,
                      "n": request.n, "size": request.size}
            if request.input_fidelity:
                fields["input_fidelity"] = request.input_fidelity
            body, ctype = _multipart(fields, files)
            http_req = urllib.request.Request(
                f"{API_BASE}/images/edits", data=body,
                headers={"Authorization": f"Bearer {key}", "Content-Type": ctype})
        else:
            body = json.dumps({"model": self.model, "prompt": request.prompt,
                               "n": request.n, "size": request.size}).encode()
            http_req = urllib.request.Request(
                f"{API_BASE}/images/generations", data=body,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"})

        with urllib.request.urlopen(http_req, timeout=300) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        self.spent_usd = round(self.spent_usd + est, 4)

        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        results = []
        for i, item in enumerate(payload.get("data", [])):
            cid = f"{request.scene_id}-c{i + 1}"
            img_path = out / f"{cid}.png"
            img_path.write_bytes(base64.b64decode(item["b64_json"]))
            results.append(ImageResult(
                candidate_id=cid, scene_id=request.scene_id,
                provider=self.name, model=self.model, prompt=request.prompt,
                revised_prompt=item.get("revised_prompt"),
                image_path=str(img_path), dry_run=False,
                estimated_cost_usd=round(est / request.n, 4),
            ))
        return results
