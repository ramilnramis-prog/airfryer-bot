"""Оркестрация: раунды генерации → visual QA → выбор → sequence QA → гейт Higgsfield."""
from __future__ import annotations

import json
from pathlib import Path

from .models import CandidateObservation, ImageRequest, SceneSpec, utcnow_iso
from .visual_qa import select_winner
from .sequence_qa import check_sequence

MAX_ROUNDS = 3
CANDIDATES_PER_SCENE = 3


class PipelineGateError(RuntimeError):
    """Попытка пройти этап без выполнения обязательных условий."""


def produce_scene(provider, spec: SceneSpec, observe, out_dir: str,
                  apply: bool = False,
                  candidates: int = CANDIDATES_PER_SCENE,
                  max_rounds: int = MAX_ROUNDS) -> dict:
    """Полный цикл одной сцены: до max_rounds раундов по candidates кандидатов.

    observe(result) -> CandidateObservation — визуальную оценку делает агент
    visual-director (в тестах — mock).

    Возвращает {"decision": SceneDecision.to_dict(), "records": [...], "rounds": N}.
    """
    records = []
    prompt = spec.prompt_action
    decision = None
    for rnd in range(1, max_rounds + 1):
        req = ImageRequest(scene_id=spec.scene_id, prompt=prompt, n=candidates,
                           mode="edit" if spec.required_references else "generate",
                           reference_images=list(spec.required_references),
                           input_fidelity="high" if spec.required_references else None)
        results = provider.generate(req, out_dir=out_dir, apply=apply)
        observations = []
        for r in results:
            obs = observe(r)
            if not isinstance(obs, CandidateObservation):
                obs = CandidateObservation.from_dict(dict(obs))
            observations.append(obs)
            r.qa = None  # заполним после решения
            records.append(r.to_dict())
        decision = select_winner(spec.scene_id, observations, spec, round_no=rnd)
        for rec in records[-len(results):]:
            verdict = next((v for v in decision.verdicts
                            if v["candidate_id"] == rec["candidate_id"]), None)
            rec["qa"] = verdict
        if decision.winner_id is not None:
            break
        # следующий раунд — с конкретными исправлениями
        prompt = f"{spec.prompt_action}\n\n{decision.regeneration_brief}"
    if decision.winner_id is None:
        decision.needs_owner = True
    return {"decision": decision.to_dict(), "records": records,
            "rounds": decision.round}


def run_sequence_qa(transitions: list) -> dict:
    return check_sequence(transitions)


def higgsfield_gate(scene_decisions: list, sequence_report: dict | None,
                    owner_approved: bool = False) -> bool:
    """Единственная дверь к анимации Higgsfield. Бросает PipelineGateError, если:
    - не у каждой сцены есть победитель;
    - sequence QA не выполнен или не approved;
    - нет явного подтверждения владельца (платная генерация)."""
    missing = [d.get("scene_id") for d in scene_decisions if not d.get("winner_id")]
    if missing:
        raise PipelineGateError(
            f"нет победителя у сцен: {', '.join(map(str, missing))} — "
            "Higgsfield запрещён")
    if not sequence_report:
        raise PipelineGateError("sequence QA не выполнялся — Higgsfield запрещён")
    if not sequence_report.get("approved"):
        bad = [s.get("scene_id") for s in
               sequence_report.get("scenes_to_regenerate", [])]
        raise PipelineGateError(
            f"sequence QA не approved (перегенерация: {', '.join(map(str, bad))}) — "
            "Higgsfield запрещён")
    if not owner_approved:
        raise PipelineGateError(
            "нет подтверждения владельца на платную генерацию — Higgsfield запрещён")
    return True


def save_report(path: str, payload: dict) -> None:
    payload = dict(payload)
    payload.setdefault("generated_at", utcnow_iso())
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
