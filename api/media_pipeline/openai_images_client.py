"""Провайдер OpenAI Images API. Только stdlib.

Модели:
- основная: **gpt-image-2** (по умолчанию; настраивается OPENAI_IMAGE_MODEL);
- legacy fallback: gpt-image-1 (НЕ используется по умолчанию);
- capability map гарантирует, что неподдерживаемые параметры не отправляются:
  gpt-image-2 автоматически обрабатывает image inputs с высокой fidelity,
  поэтому input_fidelity ему НЕ передаётся никогда.

Безопасность:
- OPENAI_API_KEY читается ТОЛЬКО из environment в момент вызова;
- ключ никогда не логируется, не сохраняется в файлы и не попадает в результаты;
- по умолчанию dry-run: без apply=True никакой сети нет вообще;
- бюджет: SpendTracker (estimate до вызова, hard cap, usage после вызова);
- retries отсутствуют by design (первый пилот — без автоматических повторов).

Endpoints:
- POST /v1/images/generations — text-to-image (JSON);
- POST /v1/images/edits — с reference images (multipart, несколько image[]).
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

from .budget import SpendTracker, actual_from_usage
from .models import ImageProvider, ImageRequest, ImageResult

API_BASE = "https://api.openai.com/v1"

PRIMARY_MODEL = "gpt-image-2"
LEGACY_MODEL = "gpt-image-1"

# Какие параметры каким моделям МОЖНО отправлять. Неизвестная модель получает
# самый строгий профиль (ничего лишнего не отправляем).
MODEL_CAPABILITIES = {
    "gpt-image-2": {"input_fidelity": False, "quality": True},
    "gpt-image-1": {"input_fidelity": True, "quality": True},
}
_STRICTEST = {"input_fidelity": False, "quality": False}

# Верхняя ОЦЕНКА цены за 1 изображение для бюджет-гейта (не «стоимость»!):
# реальная цена зависит от модели/качества/размера и берётся из usage ответа.
DEFAULT_PRICE_ESTIMATE_USD = 0.30
DEFAULT_BUDGET_USD = 5.0
MAX_CANDIDATES_PER_REQUEST = 3


class MediaPipelineError(RuntimeError):
    pass


class MissingAPIKeyError(MediaPipelineError):
    """OPENAI_API_KEY не задан в environment (в сообщении ключей нет и быть не может)."""


# Обратная совместимость: бюджетная остановка — подкласс прежней ошибки.
from .budget import BudgetStop as BudgetExceededError  # noqa: E402,F401


def default_image_model() -> str:
    return os.environ.get("OPENAI_IMAGE_MODEL", "").strip() or PRIMARY_MODEL


def model_capabilities(model: str) -> dict:
    return MODEL_CAPABILITIES.get(model, dict(_STRICTEST))


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

    def __init__(self, model: str | None = None,
                 price_per_image_usd: float = DEFAULT_PRICE_ESTIMATE_USD,
                 budget_usd: float = DEFAULT_BUDGET_USD,
                 tracker: SpendTracker | None = None,
                 token_prices: dict | None = None):
        self.model = model or default_image_model()
        self.price_per_image_usd = price_per_image_usd
        self.tracker = tracker or SpendTracker(cap_usd=budget_usd)
        self.token_prices = token_prices  # если заданы — считаем actual из usage

    @property
    def budget_usd(self) -> float:
        return self.tracker.cap_usd

    @property
    def spent_usd(self) -> float:
        return self.tracker.total_estimated()

    # -- внутреннее ---------------------------------------------------------

    @staticmethod
    def _api_key() -> str:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise MissingAPIKeyError(
                "OPENAI_API_KEY отсутствует в environment. Задайте переменную "
                "окружения (НЕ передавайте ключ аргументом и не пишите в файлы).")
        return key

    def _payload_params(self, req: ImageRequest) -> dict:
        """Параметры запроса с фильтром по capability map: неподдерживаемое
        моделью НИКОГДА не отправляется."""
        caps = model_capabilities(self.model)
        params = {"model": self.model, "prompt": req.prompt,
                  "n": req.n, "size": req.size}
        if req.quality and caps.get("quality"):
            params["quality"] = req.quality
        if req.mode == "edit" and req.input_fidelity and caps.get("input_fidelity"):
            params["input_fidelity"] = req.input_fidelity
        return params

    def _planned_payload(self, req: ImageRequest) -> dict:
        """Payload для журнала/dry-run. Секретов не содержит по построению."""
        planned = dict(self._payload_params(req))
        planned["endpoint"] = ("/images/edits" if req.mode == "edit"
                               else "/images/generations")
        if req.mode == "edit":
            planned["reference_images"] = list(req.reference_images)
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

        est = round(request.n * self.price_per_image_usd, 4)
        self.tracker.check("image_generation", est)
        planned = self._planned_payload(request)

        if not apply:
            # DRY-RUN: никакой сети, ключ даже не читается, spend не копится.
            return [ImageResult(
                candidate_id=f"{request.scene_id}-c{i + 1}",
                scene_id=request.scene_id, provider=self.name, model=self.model,
                prompt=request.prompt, dry_run=True,
                estimated_cost_usd=round(est / request.n, 4),
                planned_request=planned,
            ) for i in range(request.n)]

        key = self._api_key()
        params = self._payload_params(request)
        if request.mode == "edit":
            files = [("image[]", ref, Path(ref).read_bytes())
                     for ref in request.reference_images]
            body, ctype = _multipart(params, files)
            http_req = urllib.request.Request(
                f"{API_BASE}/images/edits", data=body,
                headers={"Authorization": f"Bearer {key}", "Content-Type": ctype})
        else:
            body = json.dumps(params).encode()
            http_req = urllib.request.Request(
                f"{API_BASE}/images/generations", data=body,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"})

        # Без retries: одна попытка, ошибка — наверх (первый пилот).
        with urllib.request.urlopen(http_req, timeout=300) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        usage = payload.get("usage")
        self.tracker.record("image_generation", est, usage=usage,
                            actual_usd=actual_from_usage(usage, self.token_prices))

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
