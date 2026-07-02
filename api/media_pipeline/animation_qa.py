"""Детерминированные правила animation QA: дрейф геометрии ручек по кадрам
видео и разрешение итогового статуса с учётом owner override.

Наблюдения по кадрам заполняет агент animation-qa (глазами, сравнивая кадры
с исходным PNG и каноническим reference crop ручек); этот модуль применяет
жёсткие правила, чтобы вердикты были воспроизводимыми.
"""
from __future__ import annotations

from .vision_provider import HANDLE_DRIFT_CODE

# Кадры, обязательные к проверке геометрии ручек: первый, несколько средних,
# последний (агент обязан отсмотреть минимум эти позиции).
REQUIRED_FRAME_POSITIONS = ("first", "middle", "last")


def check_handle_drift(frame_observations: list) -> dict:
    """frame_observations: [{"frame": "frame-0000", "position": "first|middle|last",
    "handle_geometry_ok": bool, "issues": [str, ...]}, ...] в порядке времени.

    Правила:
    - первый кадр обязан совпадать с каноническим референсом
      (handle_geometry_ok=False на первом кадре -> handle_geometry_mismatch
      источника, не drift);
    - если первый кадр ok, а любой средний/последний кадр не ok (ручки
      округлились, изогнулись, утолщились, сменили силуэт) ->
      hard fail handle_geometry_drift;
    - обязаны присутствовать позиции first, middle и last.
    """
    if not frame_observations:
        raise ValueError("нет наблюдений по кадрам")
    positions = {f.get("position") for f in frame_observations}
    missing = [p for p in REQUIRED_FRAME_POSITIONS if p not in positions]
    if missing:
        raise ValueError(f"не проверены обязательные позиции кадров: {missing}")

    first = frame_observations[0]
    if not first["handle_geometry_ok"]:
        return {"hard_fail": "handle_geometry_mismatch",
                "frames": [first.get("frame", "first")],
                "detail": "геометрия ручек неверна уже в первом кадре — "
                          "дефект исходного кадра, не анимации",
                "issues": list(first.get("issues", []))}
    bad = [f for f in frame_observations[1:] if not f["handle_geometry_ok"]]
    if bad:
        return {"hard_fail": HANDLE_DRIFT_CODE,
                "frames": [f.get("frame", "?") for f in bad],
                "detail": "ручки меняют силуэт в процессе движения "
                          "(округление/изгиб/утолщение/морфинг)",
                "issues": [i for f in bad for i in f.get("issues", [])]}
    return {"hard_fail": None, "frames": [], "detail": "геометрия ручек "
            "стабильна во всех проверенных кадрах", "issues": []}


def resolve_animation_status(qa_report: dict, owner_override: dict | None) -> str:
    """Итоговый статус анимации сцены.

    - без override: approved -> approved_for_owner_review, иначе rejected;
    - owner override (решение владельца) имеет приоритет над автоматическим
      QA и не переписывает исторический отчёт — только итоговый статус.
    """
    if owner_override is not None:
        if owner_override.get("owner_status") == "rejected":
            return "rejected_by_owner_needs_regeneration"
        if owner_override.get("owner_status") == "approved":
            return "approved_by_owner"
        raise ValueError(
            f"неизвестный owner_status: {owner_override.get('owner_status')!r}")
    verdict = (qa_report.get("qa", {}).get("verdict")
               or qa_report.get("verdict"))
    return ("approved_for_owner_review" if verdict == "approved"
            else "rejected_needs_regeneration")
