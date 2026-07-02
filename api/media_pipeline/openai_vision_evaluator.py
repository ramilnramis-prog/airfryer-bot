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

import tempfile

from .budget import SpendTracker, actual_from_usage
from .openai_images_client import API_BASE, MissingAPIKeyError
from .vision_provider import (HARD_FAIL_CODES, SCORE_DIMENSIONS,
                              VisionEvaluationRequest, VisionEvaluator,
                              validate_food_count_result,
                              validate_vision_result)

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
            "food_count", "food_count_detail", "text_or_watermark",
            "physical_intersections", "photorealism", "animation_readiness",
            "transition_possible", "next_scene_state_not_yet_present",
            "continuity_issues", "hard_fail_codes", "scores", "confidence",
            "explanation",
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
            "food_count_detail": {
                "type": ["object", "null"],
                "additionalProperties": False,
                "required": ["visible_count", "partially_occluded_count",
                             "uncertain_count", "expected_count", "confidence",
                             "evidence", "items", "region"],
                "properties": {
                    "visible_count": {"type": "integer"},
                    "partially_occluded_count": {"type": "integer"},
                    "uncertain_count": {"type": "integer"},
                    "expected_count": {"type": "integer"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence": {"type": "string"},
                    "items": {"type": "array", "items": {
                        "type": "object", "additionalProperties": False,
                        "required": ["label", "location"],
                        "properties": {"label": {"type": "string"},
                                       "location": {"type": "string"}},
                    }},
                    "region": {
                        "type": ["object", "null"],
                        "additionalProperties": False,
                        "required": ["x0", "y0", "x1", "y1"],
                        "properties": {d: {"type": "number", "minimum": 0,
                                           "maximum": 1}
                                       for d in ("x0", "y0", "x1", "y1")},
                    },
                },
            },
            "text_or_watermark": {"type": "boolean"},
            "physical_intersections": {"type": "array", "items": {"type": "string"}},
            "photorealism": {"type": "boolean"},
            "animation_readiness": {"type": "boolean"},
            "transition_possible": {"type": "boolean"},
            "next_scene_state_not_yet_present": {"type": "boolean"},
            "continuity_issues": {"type": "array", "items": {"type": "string"}},
            "hard_fail_codes": {"type": "array",
                                "items": {"type": "string",
                                          "enum": sorted(HARD_FAIL_CODES)}},
            "scores": {
                # ЦЕЛЫЕ 0-100: запрещает нормализованные шкалы 0-1 и 0-10,
                # которые ложно срезаются порогом min_dimension_score=70
                "type": "object", "additionalProperties": False,
                "required": SCORE_DIMENSIONS,
                "properties": {d: {"type": "integer", "minimum": 0, "maximum": 100}
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
        "NEXT SCENE (context that begins AFTER the current scene's motion "
        f"completes): {req.next_scene_requirements or 'n/a'}\n\n"
        "SCENE TRANSITION RULES — read carefully:\n"
        "1. The candidate frame must match its OWN scene spec (the current "
        "action in progress). If it violates its own spec, use hard fail code "
        "current_scene_violation.\n"
        "2. The NEXT SCENE description is the state AFTER the current motion "
        "finishes. It is NOT a requirement on the current frame. The current "
        "frame must NOT already show the next scene's final state. Use the "
        "next scene ONLY to judge: (a) can the current frame be naturally "
        "animated into that state (set transition_possible accordingly); "
        "(b) do immutable objects match; (c) is the transition physically "
        "possible. If a natural animation into the next state is impossible "
        "(teleportation, incompatible object positions, contradictory "
        "immutable elements), use hard fail code transition_impossible.\n"
        "3. If the next scene's final state is simply not yet present in the "
        "current frame, that is EXPECTED and CORRECT: set "
        "next_scene_state_not_yet_present=true, do NOT report it as a "
        "continuity issue, do NOT use any hard fail code for it, and do NOT "
        "lower adjacent_scene_continuity for it. Score "
        "adjacent_scene_continuity by transition feasibility only.\n\n"
        "FOOD COUNTING RULES — be rigorous:\n"
        "- Count ONLY the target food item from exact_food_count in the scene "
        "spec. Do NOT count potato wedges, garnish, sauce, shadows, "
        "reflections, or two visible parts of the same item as separate "
        "items.\n"
        "- Fill food_count_detail: visible_count (fully visible items), "
        "partially_occluded_count (items partly hidden by the liner edge, "
        "hands or steam), uncertain_count (regions that might or might not "
        "be an item), expected_count (from the spec), confidence, evidence "
        "(what exactly you counted), items (label + short location for EVERY "
        "counted element), region (normalized bounding box x0,y0,x1,y1 of "
        "the liner/food area in the candidate).\n"
        "- If part of the food is hidden by the liner edge or hands, do NOT "
        "report an exact total with high confidence — use "
        "partially_occluded_count/uncertain_count and lower confidence.\n"
        "- food_count = visible_count + partially_occluded_count (best "
        "estimate), or null if you cannot estimate.\n\n"
        "SCORING SCALE: each dimension in scores is an INTEGER from 0 to 100 "
        "(100 = perfect, 70 = minimum acceptable). Do NOT use 0-1 or 0-10 "
        "scales — e.g. an excellent match is 95, not 0.95 and not 9.5.\n\n"
        f"Allowed hard_fail_codes: {', '.join(sorted(HARD_FAIL_CODES))}. "
        "If the air fryer or hands are absent from the frame, set the "
        "corresponding *_match/grip fields to true and hand_gender_presentation "
        "to 'none'. Respond ONLY with the required JSON."
    )


def _food_count_instructions(item_label: str, expected: int) -> str:
    """Точное задание second-pass count evaluator (crop области формы)."""
    return (
        "You are a meticulous food counter. The single image is a close-up "
        "crop of a silicone liner with cooked food.\n"
        f"Count ONLY items of this type: {item_label}.\n"
        "STRICT RULES:\n"
        f"- Do NOT count potato wedges as {item_label}.\n"
        "- Do NOT count garnish, sauce, shadows, reflections or highlights.\n"
        "- Do NOT count two visible parts of one partially hidden item as "
        "two items.\n"
        "- If an item is partly hidden by the liner edge, hands or steam, "
        "put it in target_partially_occluded_count, not in "
        "target_visible_count.\n"
        "- If a region might or might not be an item, put it in "
        "target_uncertain_count and lower your confidence.\n"
        "- Never report an exact confident total when parts of the food area "
        "are occluded.\n"
        f"(For context only, the scene spec expects {expected}; do NOT let "
        "this bias your count — report what you actually see.)\n"
        "List EVERY counted element in items with a short location "
        "description. Respond ONLY with the required JSON."
    )


def _food_count_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["target_visible_count", "target_partially_occluded_count",
                     "target_uncertain_count", "confidence", "evidence",
                     "items"],
        "properties": {
            "target_visible_count": {"type": "integer"},
            "target_partially_occluded_count": {"type": "integer"},
            "target_uncertain_count": {"type": "integer"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {"type": "string"},
            "items": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["label", "location"],
                "properties": {"label": {"type": "string"},
                               "location": {"type": "string"}},
            }},
        },
    }


def _cropped_food_region(image_path: str, region: dict | None) -> tuple:
    """Возвращает (путь, cropped: bool). Кроп области формы + upscale x2 через
    Pillow; при отсутствии Pillow или региона — исходное изображение."""
    if not region:
        return image_path, False
    try:
        from PIL import Image
    except ImportError:
        return image_path, False
    with Image.open(image_path) as im:
        w, h = im.size
        margin = 0.05
        x0 = max(0.0, min(region["x0"], region["x1"]) - margin)
        y0 = max(0.0, min(region["y0"], region["y1"]) - margin)
        x1 = min(1.0, max(region["x0"], region["x1"]) + margin)
        y1 = min(1.0, max(region["y0"], region["y1"]) + margin)
        if x1 - x0 < 0.05 or y1 - y0 < 0.05:  # вырожденный регион
            return image_path, False
        box = (int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h))
        crop = im.crop(box)
        crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        crop.save(tmp, format="PNG")
        tmp.close()
        return tmp.name, True


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

    # -- second-pass подсчёт еды ---------------------------------------------

    def count_food(self, image_path: str, item_label: str, expected: int,
                   region: dict | None = None, apply: bool = False) -> dict:
        """Second-pass count evaluator: получает ТОЛЬКО изображение блюда/формы
        (crop области формы, если Pillow доступен и регион задан) и точное
        задание посчитать именно целевую еду. Модель — основная (gpt-5.4-mini),
        НЕ арбитр. Вызывается только когда needs_food_second_pass сказал да."""
        if not Path(image_path).is_file():
            raise FileNotFoundError(f"изображение не найдено: {image_path}")
        crop_path, cropped = _cropped_food_region(image_path, region)
        est = self.price_per_eval_usd
        self.tracker.check("vision_evaluation", est)
        planned = {
            "endpoint": "/responses", "model": self.model,
            "structured_output": "json_schema:food_count (strict)",
            "purpose": "food_count_second_pass",
            "candidate_image": image_path,
            "cropped": cropped,
            "image_count": 1,
            "estimated_cost_usd": est,
        }
        if not apply:
            return {"mode": "dry-run", "result": None, "planned_request": planned}

        key = self._api_key()
        content = [{"type": "input_text",
                    "text": _food_count_instructions(item_label, expected)},
                   _image_part(crop_path)]
        body = json.dumps({
            "model": self.model,
            "input": [{"role": "user", "content": content}],
            "text": {"format": {"type": "json_schema",
                                "name": "food_count", "strict": True,
                                "schema": _food_count_schema()}},
        }).encode()
        http_req = urllib.request.Request(
            f"{API_BASE}/responses", data=body,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(http_req, timeout=300) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        usage = payload.get("usage")
        self.tracker.record("vision_evaluation", est, usage=usage,
                            actual_usd=actual_from_usage(usage, self.token_prices))
        raw = _extract_output_text(payload)
        result = validate_food_count_result(json.loads(raw))
        return {"mode": "apply", "result": result, "planned_request": planned,
                "model": self.model}

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
