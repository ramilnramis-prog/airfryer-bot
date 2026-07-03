"""Тесты фикса ложного adjacent_scene_break и надёжного food count.

Покрытие (по заданию):
1. scene-05 не получает hard fail только потому, что scene-06 уже показывает
   вынутую форму;
2. невозможный физический переход получает transition_impossible;
3. различие состояний двух соседних сцен допустимо;
4. low-confidence food count запускает second pass;
5. second pass не считает картофель куриным бёдрышком;
6. disagreement двух проходов даёт food_count_uncertain;
7. uncertain count блокирует auto-approval победителя;
8. Images API не вызывается при reevaluate;
9. gpt-5.5 (арбитр) не вызывается при reevaluate;
10. старый pilot-report.json не изменяется при reevaluate.
"""
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from api.media_pipeline import cli
from api.media_pipeline.models import SceneSpec
from api.media_pipeline.openai_vision_evaluator import (
    OpenAIVisionEvaluator, _food_count_instructions, _instructions,
    _structured_output_schema)
from api.media_pipeline.vision_provider import (
    FOOD_COUNT_CONFIRMED, FOOD_COUNT_UNCERTAIN, HARD_FAIL_CODES,
    INFORMATIONAL_FLAGS, SCORE_DIMENSIONS, VisionEvaluationRequest,
    needs_food_second_pass, reconcile_food_counts, validate_vision_result,
    vision_result_to_observation)
from api.media_pipeline.visual_qa import (evaluate_candidate, hard_fails,
                                          select_winner)

SPEC = SceneSpec(
    scene_id="scene-05", title="Доставание формы",
    prompt_action="woman lifts the liner by its two oval handles",
    exact_food_count={"item": "chicken thigh", "count": 3},
    relationship_to_next="scene-06 — форма уже вынута, показываем пустую чистую корзину",
    animation_intent="подъём формы + пар",
)


def detail(**overrides):
    base = {
        "visible_count": 3, "partially_occluded_count": 0,
        "uncertain_count": 0, "expected_count": 3, "confidence": 0.95,
        "evidence": "three distinct golden thighs",
        "items": [{"label": "chicken thigh", "location": "front-left"},
                  {"label": "chicken thigh", "location": "front-right"},
                  {"label": "chicken thigh", "location": "back-center"}],
        "region": {"x0": 0.1, "y0": 0.3, "x1": 0.9, "y1": 0.8},
    }
    base.update(overrides)
    return base


def vision_result(**overrides):
    base = {
        "detected_objects": ["silicone liner", "air fryer", "chicken thighs"],
        "handle_count": 2,
        "product_match": True,
        "airfryer_match": True,
        "hand_gender_presentation": "female",
        "hand_anatomy_issues": [],
        "grip_correct": True,
        "food_count": 3,
        "food_count_detail": detail(),
        "text_or_watermark": False,
        "physical_intersections": [],
        "photorealism": True,
        "animation_readiness": True,
        "transition_possible": True,
        "next_scene_state_not_yet_present": True,
        "continuity_issues": [],
        "hard_fail_codes": [],
        "scores": {d: 90 for d in SCORE_DIMENSIONS},
        "confidence": 0.95,
        "explanation": "ok",
    }
    base.update(overrides)
    return base


class TestTransitionLogic(unittest.TestCase):
    def test_next_scene_state_absent_is_not_hard_fail(self):
        # (1) scene-06 показывает уже вынутую форму, а в кадре scene-05 форма
        # ещё поднимается — это НЕ hard fail
        result = validate_vision_result(vision_result(
            next_scene_state_not_yet_present=True, transition_possible=True))
        obs = vision_result_to_observation("c1", result)
        fails = hard_fails(obs, SPEC)
        self.assertEqual(fails, [])
        verdict = evaluate_candidate(obs, SPEC)
        self.assertTrue(verdict.passed)

    def test_impossible_transition_gets_transition_impossible(self):
        # (2) физически невозможный переход
        result = validate_vision_result(vision_result(
            transition_possible=False,
            hard_fail_codes=["transition_impossible"]))
        obs = vision_result_to_observation("c1", result)
        self.assertIn("transition_impossible", hard_fails(obs, SPEC))
        # transition_possible=False блокирует даже без явного кода
        result2 = validate_vision_result(vision_result(transition_possible=False))
        obs2 = vision_result_to_observation("c2", result2)
        self.assertIn("transition_impossible", hard_fails(obs2, SPEC))

    def test_state_difference_between_adjacent_scenes_is_allowed(self):
        # (3) различие состояний соседних сцен — информация, не дефект
        self.assertIn("next_scene_state_not_yet_present", INFORMATIONAL_FLAGS)
        self.assertNotIn("next_scene_state_not_yet_present", HARD_FAIL_CODES)
        self.assertNotIn("adjacent_scene_break", HARD_FAIL_CODES)
        # структурная схема больше не допускает adjacent_scene_break
        schema = _structured_output_schema()
        allowed = schema["properties"]["hard_fail_codes"]["items"]["enum"]
        self.assertNotIn("adjacent_scene_break", allowed)
        self.assertIn("transition_impossible", allowed)
        self.assertIn("current_scene_violation", allowed)
        # промпт объясняет семантику
        text = _instructions(VisionEvaluationRequest(
            candidate_id="c", candidate_image="x.png",
            scene_spec={"scene_id": "scene-05"},
            next_scene_requirements=SPEC.relationship_to_next))
        self.assertIn("NOT a requirement on the current frame", text)
        self.assertIn("next_scene_state_not_yet_present", text)

    def test_scores_schema_requires_integer_0_100(self):
        # шкала 0-1 / 0-10 запрещена структурно: только integer 0-100
        schema = _structured_output_schema()
        for d in SCORE_DIMENSIONS:
            prop = schema["properties"]["scores"]["properties"][d]
            self.assertEqual(prop["type"], "integer")
            self.assertEqual((prop["minimum"], prop["maximum"]), (0, 100))
        text = _instructions(VisionEvaluationRequest(
            candidate_id="c", candidate_image="x.png",
            scene_spec={"scene_id": "scene-05"}))
        self.assertIn("INTEGER from 0 to 100", text)

    def test_current_scene_violation_separate_code(self):
        result = validate_vision_result(vision_result(
            hard_fail_codes=["current_scene_violation"]))
        obs = vision_result_to_observation("c1", result)
        fails = hard_fails(obs, SPEC)
        self.assertIn("current_scene_violation", fails)
        self.assertNotIn("transition_impossible", fails)


class TestFoodCount(unittest.TestCase):
    def test_low_confidence_triggers_second_pass(self):
        # (4) confidence < 0.85 → second pass
        out = needs_food_second_pass(detail(confidence=0.7), expected=3)
        self.assertTrue(out["needed"])
        # несовпадение с expected → second pass
        out2 = needs_food_second_pass(detail(visible_count=2), expected=3)
        self.assertTrue(out2["needed"])
        # неопределённые элементы → second pass
        out3 = needs_food_second_pass(detail(uncertain_count=1), expected=3)
        self.assertTrue(out3["needed"])
        # уверенный совпавший подсчёт — second pass не нужен
        out4 = needs_food_second_pass(detail(), expected=3)
        self.assertFalse(out4["needed"])

    def test_second_pass_does_not_count_potato(self):
        # (5) точное задание second pass исключает картофель/гарнир/тени/части
        text = _food_count_instructions("chicken thigh", 3)
        self.assertIn("Do NOT count potato wedges", text)
        self.assertIn("garnish", text)
        self.assertIn("shadows", text)
        self.assertIn("two visible parts of one", text)
        self.assertIn("chicken thigh", text)
        # reconcile использует только целевые (thigh) счётчики second pass —
        # посторонние элементы в items не влияют на итог
        second = {"target_visible_count": 3,
                  "target_partially_occluded_count": 0,
                  "target_uncertain_count": 0, "confidence": 0.95,
                  "evidence": "3 thighs; potatoes ignored",
                  "items": [{"label": "chicken thigh", "location": "left"},
                            {"label": "chicken thigh", "location": "right"},
                            {"label": "chicken thigh", "location": "back"},
                            {"label": "potato wedge (not counted)",
                             "location": "between"}]}
        recon = reconcile_food_counts(detail(), second, expected=3)
        self.assertEqual(recon["status"], FOOD_COUNT_CONFIRMED)
        self.assertEqual(recon["final_count"], 3)

    def test_disagreement_gives_food_count_uncertain(self):
        # (6) проходы разошлись → food_count_uncertain, число НЕ утверждается
        second = {"target_visible_count": 2,
                  "target_partially_occluded_count": 0,
                  "target_uncertain_count": 0, "confidence": 0.9,
                  "evidence": "only 2 thighs visible",
                  "items": [{"label": "chicken thigh", "location": "left"},
                            {"label": "chicken thigh", "location": "right"}]}
        recon = reconcile_food_counts(detail(), second, expected=3)
        self.assertEqual(recon["status"], FOOD_COUNT_UNCERTAIN)
        self.assertIsNone(recon["final_count"])

    def test_uncertain_count_blocks_auto_approval(self):
        # (7) uncertain блокирует победителя, но не даёт ложный food_count_changed
        result = validate_vision_result(vision_result())
        obs = vision_result_to_observation(
            "c1", result, food_count_final=None,
            food_count_status=FOOD_COUNT_UNCERTAIN)
        fails = hard_fails(obs, SPEC)
        self.assertNotIn("food_count_changed", fails)  # число не утверждаем
        verdict = evaluate_candidate(obs, SPEC)
        self.assertFalse(verdict.passed)
        self.assertTrue(any("food_count_uncertain" in r for r in verdict.reasons))
        decision = select_winner("scene-05", [obs], SPEC)
        self.assertIsNone(decision.winner_id)

    def test_occlusion_forbids_confident_exact_total(self):
        # частично закрытая еда → best estimate включает occluded, а низкая
        # уверенность триггерит перепроверку
        d = detail(visible_count=2, partially_occluded_count=1, confidence=0.6)
        self.assertTrue(needs_food_second_pass(d, expected=3)["needed"])
        recon = reconcile_food_counts(d, None, expected=3)
        self.assertEqual(recon["status"], FOOD_COUNT_UNCERTAIN)


def _make_campaign(tmp: str) -> str:
    """Временная кампания: scene-spec (без required_references, чтобы не
    зависеть от внешних файлов) + 3 фейковых PNG-кандидата + pilot-report.json."""
    camp = Path(tmp) / "campaign"
    (camp / "scene-specs").mkdir(parents=True)
    spec = {
        "scene_id": "scene-05", "title": "t", "prompt_action": "lift",
        "required_references": [],
        "exact_food_count": {"item": "chicken thigh", "count": 3},
        "relationship_to_next": "scene-06 — форма вынута, корзина пустая",
    }
    (camp / "scene-specs" / "scene-05.json").write_text(
        json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    gen = camp / "generated" / "scene-05"
    gen.mkdir(parents=True)
    for i in (1, 2, 3):
        (gen / f"scene-05-c{i}.png").write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
    (gen / "pilot-report.json").write_text('{"v1": "immutable"}', encoding="utf-8")
    return str(camp)


class TestReevaluateSafety(unittest.TestCase):
    def _run_cli(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(argv)
        return code, json.loads(buf.getvalue())

    def test_reevaluate_never_touches_images_api(self):
        # (8) Images API не вызывается: генерация и сеть замучены на AssertionError
        with tempfile.TemporaryDirectory() as tmp:
            camp = _make_campaign(tmp)
            with mock.patch(
                    "api.media_pipeline.openai_images_client."
                    "OpenAIImagesProvider.generate",
                    side_effect=AssertionError("Images API call in reevaluate!")), \
                 mock.patch("urllib.request.urlopen",
                            side_effect=AssertionError("network in dry-run!")), \
                 mock.patch.dict(os.environ, {}, clear=True):
                code, out = self._run_cli(["reevaluate", camp,
                                           "--scene", "scene-05"])
        self.assertEqual(code, 0)
        self.assertEqual(out["images_api_calls"], 0)
        self.assertEqual(out["generation_calls"], 0)
        self.assertEqual(len(out["candidates"]), 3)
        self.assertEqual(out["mode"], "dry-run")

    def test_reevaluate_never_calls_gpt55(self):
        # (9) арбитр gpt-5.5 не вызывается
        with tempfile.TemporaryDirectory() as tmp:
            camp = _make_campaign(tmp)
            with mock.patch.object(
                    OpenAIVisionEvaluator, "arbitrate",
                    side_effect=AssertionError("gpt-5.5 called!")), \
                 mock.patch("urllib.request.urlopen",
                            side_effect=AssertionError("network in dry-run!")):
                code, out = self._run_cli(["reevaluate", camp,
                                           "--scene", "scene-05"])
        self.assertEqual(code, 0)
        self.assertFalse(out["arbiter"]["enabled"])
        self.assertEqual(out["arbiter"]["calls"], 0)
        for ev in out["vision_evaluations"]:
            self.assertEqual(ev["planned_request"]["model"], "gpt-5.4-mini")

    def test_reevaluate_leaves_old_pilot_report_untouched(self):
        # (10) старый pilot-report.json байт-в-байт неизменен
        with tempfile.TemporaryDirectory() as tmp:
            camp = _make_campaign(tmp)
            report = Path(camp) / "generated" / "scene-05" / "pilot-report.json"
            before = report.read_bytes()
            v2 = str(Path(camp) / "generated" / "scene-05" / "pilot-report-v2.json")
            with mock.patch("urllib.request.urlopen",
                            side_effect=AssertionError("network in dry-run!")):
                code, out = self._run_cli(["reevaluate", camp,
                                           "--scene", "scene-05",
                                           "--report-out", v2])
            self.assertEqual(code, 0)
            self.assertEqual(report.read_bytes(), before)
            self.assertTrue(Path(v2).is_file())  # v2 — отдельный файл

    def test_reevaluate_requires_existing_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            camp = _make_campaign(tmp)
            shutil.rmtree(Path(camp) / "generated")
            code, out = self._run_cli(["reevaluate", camp,
                                       "--scene", "scene-05"])
        self.assertEqual(code, 1)
        self.assertIn("ничего не генерирует", out["error"])


if __name__ == "__main__":
    unittest.main()
