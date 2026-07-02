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
# ВАЖНО про переходы между сценами (fix ложного adjacent_scene_break):
# - current_scene_violation — кадр не соответствует СОБСТВЕННОМУ scene spec;
# - transition_impossible — из кадра невозможно естественно перейти в
#   состояние следующей сцены (телепортация, несовместимые immutable objects);
# - то, что финальное состояние СЛЕДУЮЩЕЙ сцены ещё не наступило в текущем
#   кадре, — НЕ дефект (информационный флаг next_scene_state_not_yet_present).
HARD_FAIL_CODES = {
    "product_mismatch", "handle_count", "color_material_changed",
    "airfryer_mismatch", "hands_male", "hand_anatomy", "wrong_grip",
    "food_count_changed", "text_watermark", "impossible_intersection",
    "cgi_look", "not_animatable", "current_scene_violation",
    "transition_impossible", "handle_geometry_mismatch",
}

# Анимационный hard-fail (по кадрам видео, не по одному изображению):
# ручки меняют силуэт/округляются/изгибаются в процессе движения.
HANDLE_DRIFT_CODE = "handle_geometry_drift"

# Информационные флаги: никогда не являются hard fail.
INFORMATIONAL_FLAGS = {"next_scene_state_not_yet_present"}

# Порог уверенности первичного подсчёта еды; ниже — обязателен second pass.
FOOD_COUNT_CONFIDENCE_THRESHOLD = 0.85

# Порог уверенности оценки геометрии ручек; ниже — обязательна отдельная
# проверка crop левой и правой ручки. «handle_count == 2» НЕ достаточен:
# силуэт обязан совпадать с каноническим референсом (см. visual_bible.json
# handle_geometry и handles_reference_crop.png).
HANDLE_GEOMETRY_CONFIDENCE_THRESHOLD = 0.85

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
    # transition-поля (опциональны для обратной совместимости со старыми
    # результатами; structured output схема требует их всегда)
    "transition_possible": (bool, False),
    "next_scene_state_not_yet_present": (bool, False),
    "food_count_detail": ((dict, type(None)), False),
    # геометрия ручек: count == 2 больше НЕ достаточен
    "handle_outer_shape_match": (bool, False),
    "handle_cutout_shape_match": (bool, False),
    "handle_parallel_sides": (bool, False),
    "handle_symmetry": (bool, False),
    "handle_reference_similarity": (float, False),   # 0.0-1.0
    "handle_geometry_confidence": (float, False),    # 0.0-1.0
    "handle_geometry_issues": (list, False),
    "handle_regions": ((dict, type(None)), False),   # {"left": bbox|null, "right": bbox|null}
}

# Схема food_count_detail: (тип, обязательное внутри detail)
FOOD_COUNT_DETAIL_FIELDS = {
    "visible_count": (int, True),
    "partially_occluded_count": (int, True),
    "uncertain_count": (int, True),
    "expected_count": (int, True),
    "confidence": (float, True),
    "evidence": (str, True),
    "items": (list, True),        # [{"label", "location"}] — расположение каждого
    "region": ((dict, type(None)), False),  # normalized bbox области формы/еды
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
    detail = data.get("food_count_detail")
    if detail is not None:
        validate_food_count_detail(detail)
    return data


def validate_food_count_detail(detail: dict) -> dict:
    """Проверка структуры food_count_detail (первичный подсчёт)."""
    if not isinstance(detail, dict):
        raise VisionSchemaError("food_count_detail должен быть объектом")
    for name, (types, required) in FOOD_COUNT_DETAIL_FIELDS.items():
        if name not in detail:
            if required:
                raise VisionSchemaError(f"food_count_detail без поля: {name}")
            continue
        value = detail[name]
        ok_types = types if isinstance(types, tuple) else (types,)
        if isinstance(value, bool):
            raise VisionSchemaError(f"food_count_detail.{name}: bool недопустим")
        if not isinstance(value, ok_types):
            if float in ok_types and isinstance(value, int):
                continue
            raise VisionSchemaError(
                f"food_count_detail.{name}: тип {type(value).__name__} не подходит")
    if not 0.0 <= detail["confidence"] <= 1.0:
        raise VisionSchemaError(
            f"food_count_detail.confidence вне [0,1]: {detail['confidence']!r}")
    for c in ("visible_count", "partially_occluded_count", "uncertain_count"):
        if detail[c] < 0:
            raise VisionSchemaError(f"food_count_detail.{c} < 0")
    return detail


# Схема результата second-pass подсчёта (только целевая еда, crop формы)
FOOD_COUNT_SECOND_PASS_FIELDS = {
    "target_visible_count": (int, True),
    "target_partially_occluded_count": (int, True),
    "target_uncertain_count": (int, True),
    "confidence": (float, True),
    "evidence": (str, True),
    "items": (list, True),
}


def validate_food_count_result(data: dict) -> dict:
    """Проверка структуры результата second-pass count evaluator."""
    if not isinstance(data, dict):
        raise VisionSchemaError("food count result должен быть объектом")
    for name, (types, required) in FOOD_COUNT_SECOND_PASS_FIELDS.items():
        if name not in data and required:
            raise VisionSchemaError(f"food count result без поля: {name}")
        value = data[name]
        ok_types = types if isinstance(types, tuple) else (types,)
        if isinstance(value, bool):
            raise VisionSchemaError(f"food count result.{name}: bool недопустим")
        if not isinstance(value, ok_types):
            if float in ok_types and isinstance(value, int):
                continue
            raise VisionSchemaError(
                f"food count result.{name}: тип {type(value).__name__} не подходит")
    if not 0.0 <= data["confidence"] <= 1.0:
        raise VisionSchemaError(f"confidence вне [0,1]: {data['confidence']!r}")
    return data


def food_count_best_estimate(detail: dict) -> int:
    """Лучшая оценка первичного прохода: видимые + частично закрытые."""
    return int(detail["visible_count"]) + int(detail["partially_occluded_count"])


def needs_food_second_pass(detail: dict | None, expected: int | None,
                           threshold: float = FOOD_COUNT_CONFIDENCE_THRESHOLD) -> dict:
    """Нужен ли second-pass подсчёт на crop области формы.

    Триггеры: нет detail вовсе; confidence < threshold; best estimate не
    совпадает с expected_count; есть неопределённые элементы."""
    if expected is None:
        return {"needed": False, "reasons": ["expected_count не задан спеком"]}
    if detail is None:
        return {"needed": True, "reasons": ["нет food_count_detail в первичной оценке"]}
    reasons = []
    if detail["confidence"] < threshold:
        reasons.append(f"confidence {detail['confidence']} < {threshold}")
    if food_count_best_estimate(detail) != expected:
        reasons.append(
            f"best estimate {food_count_best_estimate(detail)} != expected {expected}")
    if detail["uncertain_count"] > 0:
        reasons.append(f"uncertain_count {detail['uncertain_count']} > 0")
    return {"needed": bool(reasons), "reasons": reasons}


FOOD_COUNT_CONFIRMED = "confirmed"
FOOD_COUNT_UNCERTAIN = "food_count_uncertain"


def reconcile_food_counts(detail: dict | None, second_result: dict | None,
                          expected: int | None,
                          threshold: float = FOOD_COUNT_CONFIDENCE_THRESHOLD) -> dict:
    """Сводит первичный и second-pass подсчёты в статус.

    - second pass не выполнялся (не требовался) → confirmed по первичному;
    - оба прохода согласны и second pass уверен → confirmed;
    - расхождение проходов или низкая уверенность → food_count_uncertain:
      автоматическое утверждение победителя запрещено, но НЕ утверждаем
      неверное число (final_count=None)."""
    if expected is None:
        return {"status": FOOD_COUNT_CONFIRMED, "final_count": None,
                "reasons": ["expected_count не задан спеком"]}
    if second_result is None:
        if detail is None:
            return {"status": FOOD_COUNT_UNCERTAIN, "final_count": None,
                    "reasons": ["нет ни первичного detail, ни second pass"]}
        check = needs_food_second_pass(detail, expected, threshold)
        if check["needed"]:
            return {"status": FOOD_COUNT_UNCERTAIN, "final_count": None,
                    "reasons": ["second pass требовался, но не выполнен"]
                    + check["reasons"]}
        return {"status": FOOD_COUNT_CONFIRMED,
                "final_count": food_count_best_estimate(detail),
                "reasons": ["первичный подсчёт уверен и совпал с ожиданием"]}
    second_best = (int(second_result["target_visible_count"])
                   + int(second_result["target_partially_occluded_count"]))
    reasons = []
    if second_result["target_uncertain_count"] > 0:
        reasons.append(
            f"second pass: uncertain_count {second_result['target_uncertain_count']} > 0")
    if second_result["confidence"] < threshold:
        reasons.append(
            f"second pass confidence {second_result['confidence']} < {threshold}")
    primary_best = food_count_best_estimate(detail) if detail else None
    if primary_best is not None and primary_best != second_best:
        reasons.append(
            f"расхождение проходов: primary {primary_best} vs second {second_best}")
    if reasons:
        return {"status": FOOD_COUNT_UNCERTAIN, "final_count": None,
                "reasons": reasons}
    return {"status": FOOD_COUNT_CONFIRMED, "final_count": second_best,
            "reasons": [f"оба прохода согласны: {second_best}"]}


# ---------------------------------------------------------------------------
# Геометрия ручек: silhouette-проверка против канонического референса.
# «Ровно две ручки» — необходимое, но НЕ достаточное условие.
# ---------------------------------------------------------------------------

HANDLE_GEOMETRY_CONFIRMED = "confirmed"
HANDLE_GEOMETRY_UNCERTAIN = "handle_geometry_uncertain"

# Булевы сигналы первичной оценки; False любого => handle_geometry_mismatch
HANDLE_GEOMETRY_SIGNALS = ("handle_outer_shape_match", "handle_cutout_shape_match",
                           "handle_parallel_sides", "handle_symmetry")

# Схема результата second-pass проверки ручек (crop левой и правой ручки)
HANDLE_CHECK_FIELDS = {
    "left_handle_matches_reference": (bool, True),
    "right_handle_matches_reference": (bool, True),
    "outer_silhouette_straight_elongated": (bool, True),
    "cutout_elongated_oval": (bool, True),
    "long_sides_parallel": (bool, True),
    "left_right_symmetric": (bool, True),
    "similarity_to_reference": (float, True),   # 0.0-1.0
    "confidence": (float, True),                # 0.0-1.0
    "issues": (list, True),
}


def validate_handle_check_result(data: dict) -> dict:
    """Проверка структуры результата second-pass проверки ручек."""
    if not isinstance(data, dict):
        raise VisionSchemaError("handle check result должен быть объектом")
    for name, (types, required) in HANDLE_CHECK_FIELDS.items():
        if name not in data:
            if required:
                raise VisionSchemaError(f"handle check без поля: {name}")
            continue
        value = data[name]
        ok_types = types if isinstance(types, tuple) else (types,)
        if isinstance(value, bool) and bool not in ok_types:
            raise VisionSchemaError(f"handle check.{name}: bool недопустим")
        if not isinstance(value, ok_types):
            if float in ok_types and isinstance(value, int) and not isinstance(value, bool):
                continue
            raise VisionSchemaError(
                f"handle check.{name}: тип {type(value).__name__} не подходит")
    for f in ("similarity_to_reference", "confidence"):
        if not 0.0 <= data[f] <= 1.0:
            raise VisionSchemaError(f"handle check.{f} вне [0,1]: {data[f]!r}")
    return data


def handle_geometry_primary_ok(result: dict) -> bool:
    """Первичная оценка: True только если все silhouette-сигналы совпали и
    код handle_geometry_mismatch не выставлен."""
    if "handle_geometry_mismatch" in result.get("hard_fail_codes", []):
        return False
    return all(result.get(sig, True) for sig in HANDLE_GEOMETRY_SIGNALS)


def needs_handle_second_pass(result: dict,
                             threshold: float = HANDLE_GEOMETRY_CONFIDENCE_THRESHOLD) -> dict:
    """Нужна ли отдельная проверка crop левой и правой ручки.

    Триггеры: низкая уверенность первичной оценки; противоречие сигналов
    (mismatch при высокой заявленной similarity и наоборот); отсутствие полей
    геометрии в результате (старая схема)."""
    if not all(sig in result for sig in HANDLE_GEOMETRY_SIGNALS):
        return {"needed": True,
                "reasons": ["в первичной оценке нет полей геометрии ручек"]}
    reasons = []
    conf = result.get("handle_geometry_confidence")
    if conf is None or conf < threshold:
        reasons.append(f"handle_geometry_confidence {conf} < {threshold}")
    sim = result.get("handle_reference_similarity")
    ok = handle_geometry_primary_ok(result)
    if sim is not None:
        if ok and sim < 0.8:
            reasons.append(f"сигналы ok, но similarity {sim} < 0.8 — противоречие")
        if not ok and sim >= 0.9:
            reasons.append(f"сигналы mismatch, но similarity {sim} >= 0.9 — противоречие")
    return {"needed": bool(reasons), "reasons": reasons}


def reconcile_handle_geometry(result: dict, second: dict | None,
                              threshold: float = HANDLE_GEOMETRY_CONFIDENCE_THRESHOLD) -> dict:
    """Сводит первичную оценку и second-pass в статус геометрии ручек.

    Возвращает {"status": confirmed|handle_geometry_uncertain,
                "geometry_ok": bool, "reasons": [...]}.
    - second pass не выполнялся и не требовался -> confirmed по первичной;
    - проходы согласны и second pass уверен -> confirmed;
    - расхождение/низкая уверенность -> handle_geometry_uncertain:
      кандидат НЕ утверждается автоматически (uncertain != mismatch)."""
    primary_ok = handle_geometry_primary_ok(result)
    if second is None:
        check = needs_handle_second_pass(result, threshold)
        if check["needed"]:
            return {"status": HANDLE_GEOMETRY_UNCERTAIN, "geometry_ok": primary_ok,
                    "reasons": ["second pass требовался, но не выполнен"]
                    + check["reasons"]}
        return {"status": HANDLE_GEOMETRY_CONFIRMED, "geometry_ok": primary_ok,
                "reasons": ["первичная оценка уверенная и непротиворечивая"]}
    second_ok = (second["left_handle_matches_reference"]
                 and second["right_handle_matches_reference"]
                 and second["outer_silhouette_straight_elongated"]
                 and second["cutout_elongated_oval"]
                 and second["long_sides_parallel"]
                 and second["left_right_symmetric"])
    reasons = []
    if second["confidence"] < threshold:
        reasons.append(f"second pass confidence {second['confidence']} < {threshold}")
    if primary_ok != second_ok:
        reasons.append(f"расхождение проходов: primary {primary_ok} vs second {second_ok}")
    if reasons:
        return {"status": HANDLE_GEOMETRY_UNCERTAIN,
                "geometry_ok": primary_ok and second_ok, "reasons": reasons}
    return {"status": HANDLE_GEOMETRY_CONFIRMED, "geometry_ok": second_ok,
            "reasons": [f"оба прохода согласны: geometry_ok={second_ok}"]}


@dataclass
class VisionEvaluationRequest:
    candidate_id: str
    candidate_image: str                       # путь к PNG/JPEG кандидата
    product_references: list = field(default_factory=list)
    airfryer_references: list = field(default_factory=list)
    hands_references: list = field(default_factory=list)
    kitchen_reference: str | None = None
    food_reference: str | None = None
    # крупный канонический crop ручек (visual bible) — сравнение силуэта,
    # не только количества
    handle_reference_crop: str | None = None
    scene_spec: dict = field(default_factory=dict)
    previous_approved_scene: str | None = None  # путь к утверждённому кадру N-1
    next_scene_requirements: str = ""

    def all_reference_paths(self) -> list:
        refs = (list(self.product_references) + list(self.airfryer_references)
                + list(self.hands_references))
        for extra in (self.kitchen_reference, self.food_reference,
                      self.handle_reference_crop, self.previous_approved_scene):
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


def vision_result_to_observation(candidate_id: str, result: dict,
                                 food_count_final: int | None = ...,
                                 food_count_status: str | None = None,
                                 handle_geometry_ok: bool | None = None,
                                 handle_geometry_status: str | None = None) -> CandidateObservation:
    """Перевод validated vision result в CandidateObservation для visual_qa.

    food_count_final/food_count_status приходят из reconcile_food_counts;
    если не переданы — используется первичный food_count со статусом confirmed.
    Различие состояния текущего и следующего кадров само по себе НЕ дефект:
    adjacent_scene_compatible ломается только transition_impossible."""
    codes = set(result["hard_fail_codes"])
    if food_count_final is ...:
        food_count_final = result["food_count"]
    if handle_geometry_ok is None:
        handle_geometry_ok = handle_geometry_primary_ok(result)
    return CandidateObservation(
        candidate_id=candidate_id,
        product_matches_reference=(result["product_match"]
                                   and "product_mismatch" not in codes),
        handle_count=result["handle_count"],
        handle_geometry_ok=handle_geometry_ok,
        handle_geometry_status=handle_geometry_status or HANDLE_GEOMETRY_CONFIRMED,
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
        food_count_actual=food_count_final,
        food_count_status=food_count_status or FOOD_COUNT_CONFIRMED,
        has_text_or_watermark=result["text_or_watermark"],
        has_impossible_intersections=(bool(result["physical_intersections"])
                                      or "impossible_intersection" in codes),
        looks_cgi=(not result["photorealism"]) or "cgi_look" in codes,
        animation_ready=(result["animation_readiness"]
                         and "not_animatable" not in codes),
        matches_own_scene_spec="current_scene_violation" not in codes,
        adjacent_scene_compatible=("transition_impossible" not in codes
                                   and result.get("transition_possible", True)),
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
