"""CLI визуального конвейера. Dry-run по умолчанию; сеть только с --apply.

Команды:
  plan <campaign_dir>                 — план генерации по scene-specs (без сети)
  generate <campaign_dir> --scene NN  — генерация кандидатов сцены
                                        (--apply для реального вызова OpenAI)
  pilot <campaign_dir> --scene scene-05 — односценовый пилот: 3 кандидата
                                        gpt-image-2 quality=medium + реальный
                                        VisionEvaluator, hard cap $2.00,
                                        без перегенераций; Higgsfield блокирован
  reevaluate <campaign_dir> --scene NN  — повторный visual QA УЖЕ существующих
                                        кандидатов: Images API не вызывается,
                                        только vision (+ food-count second pass
                                        при необходимости)
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

from .budget import BudgetStop, SpendTracker
from .models import CandidateObservation, ImageRequest, SceneSpec
from .openai_images_client import (BudgetExceededError, MissingAPIKeyError,
                                   OpenAIImagesProvider)
from .openai_vision_evaluator import OpenAIVisionEvaluator
from .vision_provider import (VisionEvaluationRequest, VisionSchemaError,
                              needs_food_second_pass, needs_handle_second_pass,
                              reconcile_food_counts, reconcile_handle_geometry,
                              vision_result_to_observation)
from .mock_provider import MockImageProvider
from .pipeline import PipelineGateError, produce_scene, save_report
from .visual_qa import select_winner
from .sequence_qa import check_sequence

PILOT_SCENE = "scene-05"
PILOT_CAP_USD = 2.00
PILOT_QUALITY = "medium"
PILOT_CANDIDATES = 3
PILOT_REGENERATION_ROUNDS = 0

# Канонический крупный crop ручек (visual bible): silhouette-сравнение,
# handle_count == 2 сам по себе недостаточен
HANDLE_REFERENCE_CROP = ("assets/visual-bible/airfryer-silicone-form/"
                         "references/handles_reference_crop.png")


def handle_reference_crop_path() -> str | None:
    p = Path(HANDLE_REFERENCE_CROP)
    return str(p) if p.is_file() else None


# Категоризация референсов кампании для vision evaluator
_REF_CATEGORIES = {
    "forma_6angles": "product",
    "place": "airfryer",
    "h1": "hands", "b3a": "hands", "b3b": "hands",
    "cta": "kitchen", "b1_wings": "food",
}


def categorize_references(paths: list) -> dict:
    cats = {"product": [], "airfryer": [], "hands": [], "kitchen": [], "food": []}
    for p in paths:
        stem = Path(p).stem
        cat = _REF_CATEGORIES.get(stem)
        if cat:
            cats[cat].append(p)
    return cats


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


def cmd_pilot(args) -> int:
    """Односценовый пилот: ТОЛЬКО scene-05, 3 кандидата, quality=medium,
    portrait 1024x1536, все референсы сцены, 0 перегенераций, cap $2.00,
    после генерации — автоматически реальный VisionEvaluator. Higgsfield
    остаётся заблокированным независимо от результата."""
    if args.scene != PILOT_SCENE:
        return _emit({"error": f"пилот разрешён ТОЛЬКО для {PILOT_SCENE}; "
                               f"запрошена {args.scene}. Сцены 01-04 и 06-07 "
                               "генерируются только после решения владельца по пилоту"}, 1)
    specs = {s.scene_id: s for s in _load_specs(args.campaign_dir)}
    spec = specs.get(PILOT_SCENE)
    if spec is None:
        return _emit({"error": f"нет spec для {PILOT_SCENE}"}, 1)

    tracker = SpendTracker(cap_usd=PILOT_CAP_USD)
    provider = OpenAIImagesProvider(tracker=tracker)  # gpt-image-2 / OPENAI_IMAGE_MODEL
    evaluator = OpenAIVisionEvaluator(tracker=tracker)  # gpt-5.4-mini / env; арбитр ВЫКЛ

    out_dir = str(Path(args.campaign_dir) / "generated" / spec.scene_id)
    req = ImageRequest(
        scene_id=spec.scene_id, prompt=spec.prompt_action, n=PILOT_CANDIDATES,
        size="1024x1536", quality=PILOT_QUALITY,
        mode="edit" if spec.required_references else "generate",
        reference_images=list(spec.required_references),
        input_fidelity=None)  # gpt-image-2: fidelity автоматическая
    results = provider.generate(req, out_dir=out_dir, apply=args.apply)

    cats = categorize_references(spec.required_references)
    evaluations, observations = [], []
    for r in results:
        vreq = VisionEvaluationRequest(
            candidate_id=r.candidate_id,
            # в dry-run кандидата ещё нет — подставляем референс, чтобы
            # проверка путей отработала; в apply здесь реальный PNG кандидата
            candidate_image=r.image_path or spec.required_references[0],
            product_references=cats["product"],
            airfryer_references=cats["airfryer"],
            hands_references=cats["hands"],
            kitchen_reference=(cats["kitchen"][0] if cats["kitchen"] else None),
            food_reference=(cats["food"][0] if cats["food"] else None),
            scene_spec={"scene_id": spec.scene_id,
                        "exact_food_count": spec.exact_food_count,
                        "hand_requirements": spec.hand_requirements,
                        "hard_fail_conditions": spec.hard_fail_conditions,
                        "immutable_elements": spec.immutable_elements,
                        "animation_intent": spec.animation_intent},
            next_scene_requirements=spec.relationship_to_next)
        ev = evaluator.evaluate(vreq, apply=args.apply)
        evaluations.append({"candidate_id": r.candidate_id, **ev})
        if ev["result"] is not None:
            observations.append(
                vision_result_to_observation(r.candidate_id, ev["result"]))

    decision = None
    if observations:
        decision = select_winner(spec.scene_id, observations, spec,
                                 round_no=1).to_dict()
        # rounds=0: перегенерации в пилоте нет — при отсутствии победителя стоп.
    return _emit({
        "mode": "apply" if args.apply else "dry-run",
        "pilot_scene": PILOT_SCENE,
        "image_model": provider.model,
        "vision_model": evaluator.model,
        "arbiter": {"enabled": evaluator.arbiter_enabled,
                    "model": evaluator.arbiter_model, "calls": evaluator.arbiter_calls},
        "quality": PILOT_QUALITY,
        "size": "1024x1536 (portrait, ближайший к 9:16)",
        "candidates": PILOT_CANDIDATES,
        "regeneration_rounds": PILOT_REGENERATION_ROUNDS,
        "generation_results": [r.to_dict() for r in results],
        "vision_evaluations": evaluations,
        "decision": decision,
        "budget": tracker.summary(),
        "higgsfield": "BLOCKED — независимо от результата пилота (гейт higgsfield_gate)",
        "recommended_before_full_campaign": [
            "реальное фото аэрогриля владельца спереди",
            "реальное фото выдвинутой корзины аэрогриля"
        ],
    })


def _scene_vision_request(spec, cid: str, image_path: str, cats: dict):
    return VisionEvaluationRequest(
        candidate_id=cid,
        candidate_image=image_path,
        product_references=cats["product"],
        airfryer_references=cats["airfryer"],
        hands_references=cats["hands"],
        kitchen_reference=(cats["kitchen"][0] if cats["kitchen"] else None),
        food_reference=(cats["food"][0] if cats["food"] else None),
        handle_reference_crop=handle_reference_crop_path(),
        scene_spec={"scene_id": spec.scene_id,
                    "exact_food_count": spec.exact_food_count,
                    "hand_requirements": spec.hand_requirements,
                    "hard_fail_conditions": spec.hard_fail_conditions,
                    "immutable_elements": spec.immutable_elements,
                    "animation_intent": spec.animation_intent},
        next_scene_requirements=spec.relationship_to_next)


def cmd_reevaluate(args) -> int:
    """Повторный visual QA УЖЕ сгенерированных кандидатов сцены.

    Images API НЕ вызывается (OpenAIImagesProvider даже не создаётся):
    только основной VisionEvaluator и — при низкой уверенности или
    расхождении с expected_count — second-pass подсчёт еды на crop формы.
    Арбитр (gpt-5.5) выключен."""
    specs = {s.scene_id: s for s in _load_specs(args.campaign_dir)}
    spec = specs.get(args.scene)
    if spec is None:
        return _emit({"error": f"scene не найдена: {args.scene}",
                      "known": sorted(specs)}, 1)
    gen_dir = Path(args.campaign_dir) / "generated" / spec.scene_id
    candidates = sorted(gen_dir.glob(f"{spec.scene_id}-c*.png"))
    if not candidates:
        return _emit({"error": f"нет существующих кандидатов в {gen_dir} — "
                               "reevaluate ничего не генерирует"}, 1)

    tracker = SpendTracker(cap_usd=PILOT_CAP_USD)
    evaluator = OpenAIVisionEvaluator(tracker=tracker)  # арбитр ВЫКЛ
    cats = categorize_references(spec.required_references)
    food_spec = spec.exact_food_count or {}
    expected = food_spec.get("count")
    item_label = food_spec.get("item", "food item")

    evaluations, observations = [], []
    second_pass_calls = 0
    handle_second_pass_calls = 0
    handle_crop = handle_reference_crop_path()
    for img in candidates:
        cid = img.stem
        ev = evaluator.evaluate(_scene_vision_request(spec, cid, str(img), cats),
                                apply=args.apply)
        entry = {"candidate_id": cid, **ev}
        if ev["result"] is not None:
            detail = ev["result"].get("food_count_detail")
            check = needs_food_second_pass(detail, expected)
            entry["food_second_pass_check"] = check
            second = None
            if check["needed"]:
                sp = evaluator.count_food(
                    str(img), item_label, expected,
                    region=(detail or {}).get("region"), apply=args.apply)
                second_pass_calls += 1
                entry["food_second_pass"] = sp
                second = sp["result"]
            recon = reconcile_food_counts(detail, second, expected)
            entry["food_count_resolution"] = recon
            # геометрия ручек: silhouette-проверка, count == 2 недостаточен
            hcheck = needs_handle_second_pass(ev["result"])
            entry["handle_second_pass_check"] = hcheck
            hsecond = None
            if hcheck["needed"] and handle_crop:
                hp = evaluator.verify_handles(
                    str(img), handle_crop,
                    regions=ev["result"].get("handle_regions"),
                    apply=args.apply)
                handle_second_pass_calls += 1
                entry["handle_second_pass"] = hp
                hsecond = hp["result"]
            hrecon = reconcile_handle_geometry(ev["result"], hsecond)
            entry["handle_geometry_resolution"] = hrecon
            observations.append(vision_result_to_observation(
                cid, ev["result"], food_count_final=recon["final_count"],
                food_count_status=recon["status"],
                handle_geometry_ok=hrecon["geometry_ok"],
                handle_geometry_status=hrecon["status"]))
        evaluations.append(entry)

    decision = None
    if observations:
        decision = select_winner(spec.scene_id, observations, spec,
                                 round_no=1).to_dict()
    out = {
        "mode": "apply" if args.apply else "dry-run",
        "command": "reevaluate",
        "scene": spec.scene_id,
        "candidates": [str(p) for p in candidates],
        "vision_model": evaluator.model,
        "arbiter": {"enabled": evaluator.arbiter_enabled,
                    "model": evaluator.arbiter_model,
                    "calls": evaluator.arbiter_calls},
        "images_api_calls": 0,
        "generation_calls": 0,
        "food_second_pass_calls": second_pass_calls,
        "handle_second_pass_calls": handle_second_pass_calls,
        "handle_reference_crop": handle_crop,
        "vision_evaluations": evaluations,
        "decision": decision,
        "budget": tracker.summary(),
        "usage_log": tracker.usage_log,
        "higgsfield": "BLOCKED — reevaluate не открывает гейт higgsfield_gate",
    }
    if args.report_out:
        save_report(args.report_out, out)
        out["report_saved_to"] = args.report_out
    return _emit(out)


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

    p = sub.add_parser("pilot", help="односценовый пилот scene-05 (cap $2.00)")
    p.add_argument("campaign_dir")
    p.add_argument("--scene", required=True, help="разрешена только scene-05")
    p.add_argument("--apply", action="store_true",
                   help="РЕАЛЬНЫЕ платные вызовы OpenAI (нужен OPENAI_API_KEY)")
    p.set_defaults(fn=cmd_pilot)

    p = sub.add_parser("reevaluate",
                       help="повторный visual QA существующих кандидатов "
                            "(Images API не вызывается)")
    p.add_argument("campaign_dir")
    p.add_argument("--scene", required=True, help="например scene-05")
    p.add_argument("--apply", action="store_true",
                   help="РЕАЛЬНЫЕ платные vision-вызовы (генерации нет никогда)")
    p.add_argument("--report-out", default=None,
                   help="сохранить полный JSON-отчёт в указанный файл")
    p.set_defaults(fn=cmd_reevaluate)

    p = sub.add_parser("qa", help="вердикт по наблюдениям кандидатов")
    p.add_argument("observations")
    p.set_defaults(fn=cmd_qa)

    p = sub.add_parser("sequence-qa", help="вердикт по последовательности")
    p.add_argument("transitions")
    p.set_defaults(fn=cmd_sequence_qa)

    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except (MissingAPIKeyError, BudgetExceededError, BudgetStop,
            VisionSchemaError, FileNotFoundError, ValueError, KeyError) as e:
        return _emit({"error": str(e)}, 1)
    except PipelineGateError as e:
        return _emit({"gate_error": str(e)}, 2)


if __name__ == "__main__":
    sys.exit(main())
