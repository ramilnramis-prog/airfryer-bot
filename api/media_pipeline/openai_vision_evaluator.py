"""OpenAIVisionEvaluator: реальный визуальный анализ кандидатов.

- Основная модель: OPENAI_VISION_MODEL (по умолчанию gpt-5.4-mini) — смотрит
  КАЖДОГО кандидата.
- Арбитр: OPENAI_VISION_ARBITER_MODEL (по умолчанию gpt-5.5) — ВЫКЛЮЧЕН по
  умолчанию, включается флагом arbiter_enabled и вызывается только при спорных
  случаях (см. vision_provider.needs_arbitration), НИКОГДА не для каждого
  изображения.
- Responses API (POST /v1/responses) с image inputs (base64 data URL) и
  structured output (json_schema, strict) — свободному тексту не доверяем,
  результат дополнительно проходит validate_vision_result.
- OPENAI_API_KEY только из environment, не логируется, не сохраняется;
  в dry-run ключ даже не читается и сети нет.
- Каждый вызов проходит бюджет-гейт SpendTracker (категория vision_evaluation).
- Без автоматических retries.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import urllib.request
from pathlib import Path

from .budget import SpendTracker, actual_from_usage
from .openai_images_client import API_BASE, MissingAPIKeyError
from .vision_provider import (SCORE_DIMENSIONS, VisionEvaluationRequest,
                              VisionEvaluator, validate_vision_result)

DEFAULT_VISION_MODEL = "gpt-5.4-mini"
DEFAULT_ARBITER_MODEL = "gpt-5.5"
# Верхняя ОЦЕНКА цены одной оценки для бюджет-гейта (реальная — из usage).
DEFAULT_EVAL_PRICE_ESTIMATE_USD = 0.05


def default_vision_model() -> str:
    return os.environ.get("OPENAI_VISION_MODEL", "").strip() or DEFAULT_VISION_MODEL


def default_arbiter_model() -> str:
    return os.environ.get("OPENAI_VISION_ARBITER_MODEL", "").strip() or DEFAULT_ARBITER_MODEL


def _structured_output_schema() -> dict:
    """JSON schema для structured output (strict)."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "detected_objects", "handle_count", "product_match", "airfryer_match",
            "hand_gender_presentation", "hand_anatomy_issues", "grip_correct",
            "food_count", "text_or_watermark", "physical_intersections",
            "photorealism", "animation_readiness", "continuity_issues",
            "hard_fail_codes", "scores", "confidence", "explanation",
        ],
        "properties": {
            "detected_objects": {"type": "array", "items": {"type": "string"}},
            "handle_count": {"type": "integer"},
            "product_match": {"type": "boolean"},
            "airfryer_match": {"type": "boolean"},
            "hand_gender_presentation": {
                "type": "string", "enum": ["female", "male", "ambiguous", "none"]},
            "hand_anatomy_issues": {"type": "array", "items": {"type": "string"}},
            "grip_correct": {"type": "boolean"},
            "food_count": {"type": ["integer", "null"]},
            "text_or_watermark": {"type": "boolean"},
            "physical_intersections": {"type": "array", "items": {"type": "string"}},
            "photorealism": {"type": "boolean"},
            "animation_readiness": {"type": "boolean"},
            "continuity_issues": {"type": "array", "items": {"type": "string"}},
            "hard_fail_codes": {"type": "array", "items": {"type": "string"}},
            "scores": {
                "type": "object", "additionalProperties": False,
                "required": SCORE_DIMENSIONS,
                "properties": {d: {"type": "number", "minimum": 0, "maximum": 100}
                               for d in SCORE_DIMENSIONS},
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "explanation": {"type": "string"},
        },
    }


def _image_part(path: str) -> dict:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"изображение не найдено: {path}")
    mime = mimetypes.guess_type(str(p))[0] or "image/png"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"}


def _instructions(req: VisionEvaluationRequest) -> str:
    return (
        "You are a strict visual QA judge for e-commerce video frames. "
        "The FIRST image is the CANDIDATE frame. All following images are "
        "REFERENCE images in this order: product references, air fryer "
        "references, hands references, kitchen reference, food reference, "
        "previous approved scene (each group may be absent — see the manifest "
        "below). Compare the candidate against the references and the scene "
        "spec. Count objects carefully (handles, fingers, food items). "
        "Doubt counts AGAINST the candidate.\n\n"
        f"REFERENCE MANIFEST (JSON): {json.dumps(_manifest(req), ensure_ascii=False)}\n\n"
        f"SCENE SPEC (JSON): {json.dumps(req.scene_spec, ensure_ascii=False)}\n\n"
        f"NEXT SCENE REQUIREMENTS: {req.next_scene_requirements or 'n/a'}\n\n"
        "Allowed hard_fail_codes: product_mismatch, handle_count, "
        "color_material_changed, airfryer_mismatch, hands_male, hand_anatomy, "
        "wrong_grip, food_count_changed, text_watermark, "
        "impossible_intersection, cgi_look, not_animatable, adjacent_scene_break. "
        "If the air fryer or hands are absent from the frame, set the "
        "corresponding *_match/grip fields to true and hand_gender_presentation "
        "to 'none'. Respond ONLY with the required JSON."
    )


def _manifest(req: VisionEvaluationRequest) -> dict:
    return {
        "candidate": Path(req.candidate_image).name,
        "product_references": [Path(p).name for p in req.product_references],
        "airfryer_references": [Path(p).name for p in req.airfryer_references],
        "hands_references": [Path(p).name for p in req.hands_references],
        "kitchen_reference": Path(req.kitchen_reference).name if req.kitchen_reference else None,
        "food_reference": Path(req.food_reference).name if req.food_reference else None,
        "previous_approved_scene": (Path(req.previous_approved_scene).name
                                    if req.previous_approved_scene else None),
    }


class OpenAIVisionEvaluator(VisionEvaluator):
    name = "openai"

    def __init__(self, model: str | None = None,
                 tracker: SpendTracker | None = None,
                 price_per_eval_usd: float = DEFAULT_EVAL_PRICE_ESTIMATE_USD,
                 arbiter_enabled: bool = False,
                 arbiter_model: str | None = None,
                 token_prices: dict | None = None):
        self.model = model or default_vision_model()
        self.tracker = tracker or SpendTracker(cap_usd=1.0)
        self.price_per_eval_usd = price_per_eval_usd
        self.arbiter_enabled = arbiter_enabled
        self.arbiter_model = arbiter_model or default_arbiter_model()
        self.token_prices = token_prices
        self.arbiter_calls = 0

    @staticmethod
    def _api_key() -> str:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise MissingAPIKeyError(
                "OPENAI_API_KEY отсутствует в environment. Задайте переменную "
                "окружения (НЕ передавайте ключ аргументом и не пишите в файлы).")
        return key

    # -- основной вызов -----------------------------------------------------

    def evaluate(self, request: VisionEvaluationRequest,
                 apply: bool = False) -> dict:
        return self._call(request, self.model, apply=apply)

    def arbitrate(self, request: VisionEvaluationRequest,
                  apply: bool = False) -> dict:
        """Второй уровень (дорогая модель). Только при arbiter_enabled и только
        для спорных случаев — вызывающая сторона обязана проверить
        needs_arbitration(); этот метод не вызывается для каждого изображения."""
        if not self.arbiter_enabled:
            raise RuntimeError(
                "арбитр выключен (arbiter_enabled=False) — включается отдельным "
                "флагом и только для спорных случаев")
        self.arbiter_calls += 1
        return self._call(request, self.arbiter_model, apply=apply)

    # -- внутреннее -----------------------------------------------------------

    def _call(self, request: VisionEvaluationRequest, model: str,
              apply: bool) -> dict:
        # Читаем реальные файлы всегда (и в dry-run): пути обязаны существовать.
        image_paths = [request.candidate_image] + request.all_reference_paths()
        for p in image_paths:
            if not Path(p).is_file():
                raise FileNotFoundError(f"изображение не найдено: {p}")

        est = self.price_per_eval_usd
        self.tracker.check("vision_evaluation", est)

        planned = {
            "endpoint": "/responses", "model": model,
            "structured_output": "json_schema:vision_evaluation (strict)",
            "candidate_image": request.candidate_image,
            "reference_images": request.all_reference_paths(),
            "image_count": len(image_paths),
            "estimated_cost_usd": est,
        }
        if not apply:
            # DRY-RUN: сети нет, ключ не читается, spend не копится.
            return {"mode": "dry-run", "result": None, "planned_request": planned}

        key = self._api_key()
        content = [{"type": "input_text", "text": _instructions(request)}]
        content += [_image_part(p) for p in image_paths]
        body = json.dumps({
            "model": model,
            "input": [{"role": "user", "content": content}],
            "text": {"format": {"type": "json_schema",
                                "name": "vision_evaluation", "strict": True,
                                "schema": _structured_output_schema()}},
        }).encode()
        http_req = urllib.request.Request(
            f"{API_BASE}/responses", data=body,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"})
        # Без retries: одна попытка (первый пилот).
        with urllib.request.urlopen(http_req, timeout=300) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        usage = payload.get("usage")
        self.tracker.record("vision_evaluation", est, usage=usage,
                            actual_usd=actual_from_usage(usage, self.token_prices))

        raw = _extract_output_text(payload)
        result = validate_vision_result(json.loads(raw))
        return {"mode": "apply", "result": result, "planned_request": planned,
                "model": model}


def _extract_output_text(payload: dict) -> str:
    """Достаёт текст structured output из ответа Responses API."""
    if "output_text" in payload:
        return payload["output_text"]
    for item in payload.get("output", []):
        for part in item.get("content", []):
            if part.get("type") in ("output_text", "text"):
                return part.get("text", "")
    raise ValueError("в ответе Responses API нет output text")
