"""Sequence QA: проверка всей последовательности выбранных кадров.

Наблюдения по парам смежных кадров заполняет агент sequence-director; этот
модуль детерминированно сводит их в вердикт: список сцен на перегенерацию и
approved=true ТОЛЬКО при нуле скачков.
"""
from __future__ import annotations

JUMP_TYPES = [
    "form_jump",
    "airfryer_jump",
    "hands_jump",
    "food_jump",
    "kitchen_jump",
    "light_jump",
    "camera_jump",
    "composition_jump",
]


def check_sequence(transitions: list) -> dict:
    """transitions: [{"pair": ["scene-01","scene-02"], "jumps": {"food_jump": true, ...},
    "details": {"food_jump": "3 бёдрышка стало 4"}}, ...]

    Возвращает {"approved": bool, "scenes_to_regenerate": [...], "transitions": [...]}.
    """
    report = {"approved": True, "scenes_to_regenerate": [], "transitions": []}
    seen = {}
    for t in transitions:
        pair = t.get("pair") or []
        jumps = t.get("jumps") or {}
        details = t.get("details") or {}
        unknown = [j for j in jumps if j not in JUMP_TYPES]
        if unknown:
            raise ValueError(f"unknown jump type(s): {', '.join(unknown)}")
        found = sorted(j for j, flag in jumps.items() if flag)
        report["transitions"].append(
            {"pair": pair, "jumps_found": found,
             "details": {j: details.get(j, "") for j in found}})
        if found and len(pair) == 2:
            report["approved"] = False
            # перегенерируем ПОЗДНИЙ кадр пары (движение продолжается вперёд);
            # sequence-director может вручную указать другой через "regenerate"
            target = t.get("regenerate") or pair[1]
            reason = "; ".join(f"{j}: {details.get(j, '')}".rstrip(": ") for j in found)
            if target in seen:
                seen[target]["reasons"].append(reason)
            else:
                seen[target] = {"scene_id": target, "reasons": [reason]}
    report["scenes_to_regenerate"] = [
        {"scene_id": s["scene_id"], "reason": "; ".join(s["reasons"])}
        for s in seen.values()
    ]
    return report
