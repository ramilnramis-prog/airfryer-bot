"""CLI визуального конвейера. Dry-run по умолчанию; сеть только с --apply.

Команды:
  plan <campaign_dir>                 — план генерации по scene-specs (без сети)
  generate <campaign_dir> --scene NN  — генерация кандидатов сцены
                                        (--apply для реального вызова OpenAI)
  qa <observations.json>              — детерминированный вердикт по наблюдениям
  sequence-qa <transitions.json>      — вердикт по последовательности

Выход всегда — структурированный JSON в stdout.
Коды выхода: 0 ок; 1 ошибка валидации/данных; 2 нарушение гейта.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import CandidateObservation, ImageRequest, SceneSpec
from .openai_images_client import (BudgetExceededError, MissingAPIKeyError,
                                   OpenAIImagesProvider)
from .mock_provider import MockImageProvider
from .pipeline import PipelineGateError, produce_scene
from .visual_qa import select_winner
from .sequence_qa import check_sequence


def _load_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_specs(campaign_dir: str) -> list:
    spec_dir = Path(campaign_dir) / "scene-specs"
    if not spec_dir.is_dir():
        raise FileNotFoundError(f"нет каталога scene-specs в {campaign_dir}")
    return [SceneSpec.from_dict(_load_json(str(p)))
            for p in sorted(spec_dir.glob("scene-*.json"))]


def _emit(obj, code: int = 0) -> int:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    return code


def cmd_plan(args) -> int:
    specs = _load_specs(args.campaign_dir)
    provider = OpenAIImagesProvider()
    plan = {"mode": "dry-run", "campaign_dir": args.campaign_dir,
            "provider": provider.name, "model": provider.model,
            "candidates_per_scene": args.candidates,
            "max_rounds": args.max_rounds,
            "budget_usd": provider.budget_usd,
            "estimated_cost_usd_round1": round(
                len(specs) * args.candidates * provider.price_per_image_usd, 2),
            "scenes": []}
    for s in specs:
        plan["scenes"].append({
            "scene_id": s.scene_id, "title": s.title,
            "mode": "edit" if s.required_references else "generate",
            "reference_images": s.required_references,
            "prompt_preview": (s.prompt_action[:160] + "…")
            if len(s.prompt_action) > 160 else s.prompt_action,
        })
    return _emit(plan)


def cmd_generate(args) -> int:
    specs = {s.scene_id: s for s in _load_specs(args.campaign_dir)}
    spec = specs.get(args.scene)
    if spec is None:
        return _emit({"error": f"scene не найдена: {args.scene}",
                      "known": sorted(specs)}, 1)
    if args.provider == "mock":
        provider = MockImageProvider()
    else:
        provider = OpenAIImagesProvider(budget_usd=args.budget_usd)
    out_dir = str(Path(args.campaign_dir) / "generated" / spec.scene_id)
    req = ImageRequest(
        scene_id=spec.scene_id, prompt=spec.prompt_action,
        n=args.candidates,
        mode="edit" if spec.required_references else "generate",
        reference_images=list(spec.required_references),
        input_fidelity="high" if spec.required_references else None)
    req_results = provider.generate(req, out_dir=out_dir, apply=args.apply)
    return _emit({"mode": "apply" if args.apply else "dry-run",
                  "scene_id": spec.scene_id,
                  "results": [r.to_dict() for r in req_results]})


def cmd_qa(args) -> int:
    data = _load_json(args.observations)
    spec = SceneSpec.from_dict(data["scene_spec"])
    observations = [CandidateObservation.from_dict(o)
                    for o in data["candidates"]]
    decision = select_winner(data.get("scene_id", spec.scene_id),
                             observations, spec,
                             round_no=data.get("round", 1))
    return _emit(decision.to_dict())


def cmd_sequence_qa(args) -> int:
    data = _load_json(args.transitions)
    transitions = data["transitions"] if isinstance(data, dict) else data
    report = check_sequence(transitions)
    return _emit(report, 0 if report["approved"] else 2)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m api.media_pipeline.cli", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="план генерации (dry-run)")
    p.add_argument("campaign_dir")
    p.add_argument("--candidates", type=int, default=3)
    p.add_argument("--max-rounds", type=int, default=3)
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("generate", help="генерация кандидатов сцены")
    p.add_argument("campaign_dir")
    p.add_argument("--scene", required=True, help="например scene-01")
    p.add_argument("--candidates", type=int, default=3)
    p.add_argument("--provider", choices=["openai", "mock"], default="openai")
    p.add_argument("--budget-usd", type=float, default=5.0)
    p.add_argument("--apply", action="store_true",
                   help="РЕАЛЬНЫЙ платный вызов API (нужен OPENAI_API_KEY в env)")
    p.set_defaults(fn=cmd_generate)

    p = sub.add_parser("qa", help="вердикт по наблюдениям кандидатов")
    p.add_argument("observations")
    p.set_defaults(fn=cmd_qa)

    p = sub.add_parser("sequence-qa", help="вердикт по последовательности")
    p.add_argument("transitions")
    p.set_defaults(fn=cmd_sequence_qa)

    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except (MissingAPIKeyError, BudgetExceededError, FileNotFoundError,
            ValueError, KeyError) as e:
        return _emit({"error": str(e)}, 1)
    except PipelineGateError as e:
        return _emit({"gate_error": str(e)}, 2)


if __name__ == "__main__":
    sys.exit(main())
