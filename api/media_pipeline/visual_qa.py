"""Детерминированный визуальный QA: hard-fail правила + scoring + выбор победителя.

Наблюдения (CandidateObservation) заполняет агент visual-director, глядя на
изображения; этот модуль применяет к ним ЖЁСТКИЕ правила, чтобы вердикты были
воспроизводимыми и не зависели от «настроения» агента.
"""
from __future__ import annotations

from .models import CandidateObservation, CandidateVerdict, SceneDecision, SceneSpec

# 10 измерений scoring (continuity_rules.json — источник правды для людей,
# этот список — для кода; менять синхронно).
DIMENSIONS = [
    "product_reference_match",
    "airfryer_reference_match",
    "human_continuity",
    "hand_anatomy",
    "food_continuity",
    "photorealism",
    "composition",
    "marketing_clarity",
    "animation_readiness",
    "adjacent_scene_continuity",
]

MIN_DIMENSION_SCORE = 70
MIN_TOTAL_SCORE = 80


def hard_fails(obs: CandidateObservation, spec: SceneSpec) -> list:
    """Список кодов hard-fail (пустой список = кандидат допущен к scoring)."""
    fails = []
    if not obs.product_matches_reference:
        fails.append("product_mismatch")
    if obs.handle_count != 2:
        fails.append("handle_count")
    if not obs.product_color_material_ok:
        fails.append("color_material_changed")
    if obs.airfryer_in_frame and not obs.airfryer_matches_reference:
        fails.append("airfryer_mismatch")
    if obs.hands_in_frame and obs.hands_gender != "female":
        fails.append("hands_male")
    if obs.hands_in_frame and not obs.hand_anatomy_ok:
        fails.append("hand_anatomy")
    if obs.product_held and not obs.grip_on_specified_handles:
        fails.append("wrong_grip")
    if spec.exact_food_count is not None and obs.food_count_status == "confirmed":
        # при food_count_uncertain число НЕ утверждается и hard fail по счёту
        # не ставится — блокировка идёт статусом в evaluate_candidate
        expected = spec.exact_food_count.get("count")
        if expected is not None and obs.food_count_actual != expected:
            fails.append("food_count_changed")
    if obs.has_text_or_watermark:
        fails.append("text_watermark")
    if obs.has_impossible_intersections:
        fails.append("impossible_intersection")
    if obs.looks_cgi:
        fails.append("cgi_look")
    if not obs.animation_ready:
        fails.append("not_animatable")
    if not obs.matches_own_scene_spec:
        # кадр нарушает СОБСТВЕННЫЙ scene spec
        fails.append("current_scene_violation")
    if not obs.adjacent_scene_compatible:
        # невозможно естественно анимировать кадр в состояние следующей сцены;
        # то, что состояние следующей сцены ещё не наступило, — НЕ hard fail
        fails.append("transition_impossible")
    return fails


def evaluate_candidate(obs: CandidateObservation, spec: SceneSpec) -> CandidateVerdict:
    v = CandidateVerdict(candidate_id=obs.candidate_id)
    v.hard_fails = hard_fails(obs, spec)
    if v.hard_fails:
        v.passed = False
        v.reasons = [f"hard fail: {code}" for code in v.hard_fails]
        return v

    missing = [d for d in DIMENSIONS if d not in obs.scores]
    if missing:
        v.passed = False
        v.reasons = [f"scoring incomplete: missing {', '.join(missing)}"]
        return v

    v.scores = {d: obs.scores[d] for d in DIMENSIONS}
    v.total = round(sum(v.scores.values()) / len(DIMENSIONS), 1)
    if obs.food_count_status != "confirmed":
        # количество еды не подтверждено двумя проходами: победителем стать
        # нельзя, но и неверное число не утверждаем
        v.passed = False
        v.reasons = ["food_count_uncertain: количество еды не подтверждено — "
                     "автоматическое утверждение запрещено"]
        return v
    low = [d for d, s in v.scores.items() if s < MIN_DIMENSION_SCORE]
    if low:
        v.passed = False
        v.reasons = [f"below min dimension score {MIN_DIMENSION_SCORE}: {', '.join(low)}"]
    elif v.total < MIN_TOTAL_SCORE:
        v.passed = False
        v.reasons = [f"total {v.total} below min {MIN_TOTAL_SCORE}"]
    else:
        v.passed = True
    return v


def build_regeneration_brief(verdicts: list) -> str:
    """Конкретный бриф для image-producer из причин отклонения всех кандидатов."""
    lines = ["REGENERATION BRIEF — все кандидаты отклонены:"]
    for v in verdicts:
        why = "; ".join(v.reasons) if v.reasons else "не прошёл пороги"
        lines.append(f"- {v.candidate_id}: {why}")
    codes = {c for v in verdicts for c in v.hard_fails}
    fixes = {
        "product_mismatch": "усилить reference image формы (forma_6angles.png), режим edit + high input fidelity",
        "handle_count": "явно в промпт: 'exactly TWO oval cut-out handles on OPPOSITE walls'",
        "color_material_changed": "явно: 'matte graphite-gray silicone, not glossy, no color shift'",
        "airfryer_mismatch": "добавить референс аэрогриля (place.png), 'the same black air fryer'",
        "hands_male": "явно: 'woman's hands, early 30s, neat short nails, no jewelry'",
        "hand_anatomy": "'natural hand anatomy, five fingers per hand', упростить позу рук",
        "wrong_grip": "'held ONLY by the two oval cut-out handles, thumbs on top'",
        "food_count_changed": "явно указать точное число единиц еды из scene spec",
        "text_watermark": "'no text, no captions, no watermarks, no logos' в конец промпта",
        "impossible_intersection": "упростить композицию, убрать перекрытия объектов",
        "cgi_look": "'photographic, realistic skin and materials, not 3D render, not illustration'",
        "not_animatable": "оставить пространство для движения по animation_intent, не обрезать объект",
        "current_scene_violation": "привести кадр в соответствие с СОБСТВЕННЫМ scene spec (действие, состояние объектов, композиция)",
        "transition_impossible": "обеспечить физически возможное продолжение движения в следующую сцену (позиции immutable-объектов должны допускать анимацию перехода)",
    }
    todo = [fixes[c] for c in sorted(codes) if c in fixes]
    if todo:
        lines.append("Исправить в следующем раунде:")
        lines.extend(f"* {t}" for t in todo)
    return "\n".join(lines)


def select_winner(scene_id: str, observations: list, spec: SceneSpec,
                  round_no: int = 1) -> SceneDecision:
    """Ровно один победитель либо winner_id=None + regeneration brief."""
    verdicts = [evaluate_candidate(o, spec) for o in observations]
    passed = [v for v in verdicts if v.passed]
    decision = SceneDecision(
        scene_id=scene_id, round=round_no, winner_id=None,
        verdicts=[v.to_dict() for v in verdicts],
    )
    if passed:
        winner = max(passed, key=lambda v: (v.total, v.candidate_id))
        decision.winner_id = winner.candidate_id
        decision.rejection_reasons = {
            v.candidate_id: ("; ".join(v.reasons) if v.reasons
                             else f"проиграл по total ({v.total} vs {winner.total})")
            for v in verdicts if v.candidate_id != winner.candidate_id
        }
    else:
        decision.rejection_reasons = {
            v.candidate_id: "; ".join(v.reasons) for v in verdicts
        }
        decision.regeneration_brief = build_regeneration_brief(verdicts)
    return decision
