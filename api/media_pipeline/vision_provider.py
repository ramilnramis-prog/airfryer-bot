"""Интерфейс VisionEvaluator: автоматическая визуальная оценка кандидатов.

До этого модуля реальные пиксели НЕ анализировались автоматически:
visual_qa.py применяет правила к заранее заполненным CandidateObservation
(в тестах — mock, в ручном режиме — агент visual-director глазами).
VisionEvaluator закрывает эту дыру: модель со зрением получает candidate image
+ референсы + scene spec и возвращает структурированный результат, который
проходит JSON schema validation (свободному тексту не доверяем).
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field

from .models import CandidateObservation

# Разрешённые hard-fail коды (синхронно с visual_qa.py / continuity_rules.json)
HARD_FAIL_CODES = {
    "product_mismatch", "handle_count", "color_material_changed",
    "airfryer_mismatch", "hands_male", "hand_anatomy", "wrong_grip",
    "food_count_changed", "text_watermark", "impossible_intersection",
    "cgi_look", "not_animatable", "adjacent_scene_break",
}

SCORE_DIMENSIONS = [
    "product_reference_match", "airfryer_reference_match", "human_continuity",
    "hand_anatomy", "food_continuity", "photorealism", "composition",
    "marketing_clarity", "animation_readiness", "adjacent_scene_continuity",
]

# Схема результата: (тип, обязательное)
VISION_RESULT_FIELDS = {
    "detected_objects": (list, True),
    "handle_count": (int, True),
    "product_match": (bool, True),
    "airfryer_match": (bool, True),
    "hand_gender_presentation": (str, True),   # female | male | ambiguous | none
    "hand_anatomy_issues": (list, True),
    "grip_correct": (bool, True),
    "food_count": ((int, type(None)), True),
    "text_or_watermark": (bool, True),
    "physical_intersections": (list, True),
    "photorealism": (bool, True),
    "animation_readiness": (bool, True),
    "continuity_issues": (list, True),
    "hard_fail_codes": (list, True),
    "scores": (dict, True),
    "confidence": (float, True),               # 0.0-1.0
    "explanation": (str, True),
}


class VisionSchemaError(ValueError):
    """Результат vision-модели не прошёл валидацию схемы."""


def validate_vision_result(data: dict) -> dict:
    """Строгая проверка структуры. Неполный/кривой результат отклоняется."""
    if not isinstance(data, dict):
        raise VisionSchemaError("vision result должен быть объектом")
    for name, (types, required) in VISION_RESULT_FIELDS.items():
        if name not in data:
            if required:
                raise VisionSchemaError(f"отсутствует обязательное поле: {name}")
            continue
        value = data[name]
        ok_types = types if isinstance(types, tuple) else (types,)
        # bool — подтип int; не даём bool пройти как int
        if isinstance(value, bool) and bool not in ok_types:
            raise VisionSchemaError(f"поле {name}: bool вместо {ok_types}")
        if not isinstance(value, ok_types):
            # int допустим там, где ждём float
            if float in ok_types and isinstance(value, int):
                pass
            else:
                raise VisionSchemaError(
                    f"поле {name}: тип {type(value).__name__} не подходит")
    unknown_codes = set(data["hard_fail_codes"]) - HARD_FAIL_CODES
    if unknown_codes:
        raise VisionSchemaError(f"неизвестные hard_fail_codes: {sorted(unknown_codes)}")
    missing_dims = [d for d in SCORE_DIMENSIONS if d not in data["scores"]]
    if missing_dims:
        raise VisionSchemaError(f"scores без измерений: {missing_dims}")
    for d in SCORE_DIMENSIONS:
        s = data["scores"][d]
        if isinstance(s, bool) or not isinstance(s, (int, float)) or not 0 <= s <= 100:
            raise VisionSchemaError(f"score {d} вне диапазона 0-100: {s!r}")
    if not 0.0 <= data["confidence"] <= 1.0:
        raise VisionSchemaError(f"confidence вне [0,1]: {data['confidence']!r}")
    if data["hand_gender_presentation"] not in ("female", "male", "ambiguous", "none"):
        raise VisionSchemaError(
            f"hand_gender_presentation: {data['hand_gender_presentation']!r}")
    return data


@dataclass
class VisionEvaluationRequest:
    candidate_id: str
    candidate_image: str                       # путь к PNG/JPEG кандидата
    product_references: list = field(default_factory=list)
    airfryer_references: list = field(default_factory=list)
    hands_references: list = field(default_factory=list)
    kitchen_reference: str | None = None
    food_reference: str | None = None
    scene_spec: dict = field(default_factory=dict)
    previous_approved_scene: str | None = None  # путь к утверждённому кадру N-1
    next_scene_requirements: str = ""

    def all_reference_paths(self) -> list:
        refs = (list(self.product_references) + list(self.airfryer_references)
                + list(self.hands_references))
        for extra in (self.kitchen_reference, self.food_reference,
                      self.previous_approved_scene):
            if extra:
                refs.append(extra)
        return refs


class VisionEvaluator(abc.ABC):
    """Оценщик кандидата. Реализации: OpenAIVisionEvaluator (реальный),
    MockVisionEvaluator (тесты/репетиции)."""

    name: str = "abstract"
    model: str = ""

    @abc.abstractmethod
    def evaluate(self, request: VisionEvaluationRequest,
                 apply: bool = False) -> dict:
        """Вернуть {'mode': 'dry-run'|'apply', 'result': <validated dict>|None,
        'planned_request': ...}. При apply=False — НИКАКОЙ сети."""


class MockVisionEvaluator(VisionEvaluator):
    name = "mock"
    model = "mock-vision-1"

    def __init__(self, results: dict | None = None):
        """results: {candidate_id: vision_result_dict} — валидируются при выдаче."""
        self.results = results or {}
        self.calls = []

    def evaluate(self, request: VisionEvaluationRequest,
                 apply: bool = False) -> dict:
        self.calls.append({"candidate_id": request.candidate_id, "apply": apply})
        result = self.results.get(request.candidate_id)
        return {"mode": "apply" if apply else "dry-run",
                "result": validate_vision_result(result) if result else None,
                "planned_request": {"candidate_image": request.candidate_image,
                                    "references": request.all_reference_paths()}}


def vision_result_to_observation(candidate_id: str, result: dict) -> CandidateObservation:
    """Перевод validated vision result в CandidateObservation для visual_qa."""
    codes = set(result["hard_fail_codes"])
    return CandidateObservation(
        candidate_id=candidate_id,
        product_matches_reference=(result["product_match"]
                                   and "product_mismatch" not in codes),
        handle_count=result["handle_count"],
        product_color_material_ok="color_material_changed" not in codes,
        airfryer_matches_reference=(result["airfryer_match"]
                                    and "airfryer_mismatch" not in codes),
        airfryer_in_frame=True,  # если прибора нет в кадре, модель обязана вернуть airfryer_match=true
        hands_in_frame=result["hand_gender_presentation"] != "none",
        hands_gender=("female" if result["hand_gender_presentation"] == "none"
                      else result["hand_gender_presentation"]),
        hand_anatomy_ok=(not result["hand_anatomy_issues"]
                         and "hand_anatomy" not in codes),
        product_held="wrong_grip" in codes or not result["grip_correct"],
        grip_on_specified_handles=(result["grip_correct"]
                                   and "wrong_grip" not in codes),
        food_count_actual=result["food_count"],
        has_text_or_watermark=result["text_or_watermark"],
        has_impossible_intersections=(bool(result["physical_intersections"])
                                      or "impossible_intersection" in codes),
        looks_cgi=(not result["photorealism"]) or "cgi_look" in codes,
        animation_ready=(result["animation_readiness"]
                         and "not_animatable" not in codes),
        adjacent_scene_compatible=("adjacent_scene_break" not in codes
                                   and not result["continuity_issues"]),
        scores=dict(result["scores"]),
        notes=result["explanation"],
    )


# ---------------------------------------------------------------------------
# Арбитраж (второй уровень проверки)
# ---------------------------------------------------------------------------

DEFAULT_CONFIDENCE_THRESHOLD = 0.75
ARBITRATION_SCORE_GAP = 5.0


def needs_arbitration(evaluations: list,
                      confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> dict:
    """evaluations: [{"candidate_id", "total", "confidence", "hard_fail_codes",
    "second_opinion_hard_fail_codes"(опц.)}, ...] по одной сцене.

    Арбитраж (дорогая модель) нужен, если:
    - разница total между двумя лучшими < 5 баллов;
    - у кого-то confidence ниже порога;
    - есть спор по hard fail между первым и вторым мнением.
    """
    reasons = []
    ranked = sorted((e for e in evaluations if e.get("total") is not None),
                    key=lambda e: e["total"], reverse=True)
    if len(ranked) >= 2 and (ranked[0]["total"] - ranked[1]["total"]) < ARBITRATION_SCORE_GAP:
        reasons.append(
            f"top-2 gap {round(ranked[0]['total'] - ranked[1]['total'], 2)} < "
            f"{ARBITRATION_SCORE_GAP}")
    low = [e["candidate_id"] for e in evaluations
           if e.get("confidence", 1.0) < confidence_threshold]
    if low:
        reasons.append(f"confidence ниже {confidence_threshold}: {', '.join(low)}")
    for e in evaluations:
        second = e.get("second_opinion_hard_fail_codes")
        if second is not None and set(second) != set(e.get("hard_fail_codes", [])):
            reasons.append(f"спор по hard fail: {e['candidate_id']}")
    return {"needed": bool(reasons), "reasons": reasons}
