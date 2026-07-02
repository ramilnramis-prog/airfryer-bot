"""Тесты gpt-image-2 capability map, VisionEvaluator, бюджета и пилота scene-05."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from api.media_pipeline import cli
from api.media_pipeline.budget import BudgetStop, SpendTracker, actual_from_usage
from api.media_pipeline.models import ImageRequest, SceneSpec
from api.media_pipeline.openai_images_client import OpenAIImagesProvider
from api.media_pipeline.openai_vision_evaluator import OpenAIVisionEvaluator
from api.media_pipeline.pipeline import PipelineGateError, higgsfield_gate
from api.media_pipeline.vision_provider import (VisionEvaluationRequest,
                                                VisionSchemaError,
                                                SCORE_DIMENSIONS,
                                                needs_arbitration,
                                                validate_vision_result,
                                                vision_result_to_observation)
from api.media_pipeline.visual_qa import evaluate_candidate


def make_vision_result(**overrides):
    base = {
        "detected_objects": ["silicone liner", "air fryer"],
        "handle_count": 2,
        "product_match": True,
        "airfryer_match": True,
        "hand_gender_presentation": "female",
        "hand_anatomy_issues": [],
        "grip_correct": True,
        "food_count": 3,
        "text_or_watermark": False,
        "physical_intersections": [],
        "photorealism": True,
        "animation_readiness": True,
        "continuity_issues": [],
        "hard_fail_codes": [],
        "scores": {d: 90 for d in SCORE_DIMENSIONS},
        "confidence": 0.92,
        "explanation": "ok",
    }
    base.update(overrides)
    return base


def temp_png(dir_, name="img.png"):
    p = Path(dir_) / name
    p.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
    return str(p)


class TestCapabilityMap(unittest.TestCase):
    REQ = ImageRequest(scene_id="s", prompt="p", n=3, mode="edit",
                       reference_images=["ref.png"], quality="medium",
                       input_fidelity="high")

    def test_gpt_image_2_never_gets_input_fidelity(self):
        provider = OpenAIImagesProvider(model="gpt-image-2")
        results = provider.generate(self.REQ, out_dir=".", apply=False)
        planned = results[0].planned_request
        self.assertNotIn("input_fidelity", planned)
        self.assertEqual(planned["model"], "gpt-image-2")
        self.assertEqual(planned["quality"], "medium")

    def test_legacy_model_gets_param_only_when_supported(self):
        legacy = OpenAIImagesProvider(model="gpt-image-1")
        planned = legacy.generate(self.REQ, out_dir=".", apply=False)[0].planned_request
        self.assertEqual(planned["input_fidelity"], "high")
        unknown = OpenAIImagesProvider(model="totally-unknown-model")
        planned_u = unknown.generate(self.REQ, out_dir=".", apply=False)[0].planned_request
        self.assertNotIn("input_fidelity", planned_u)
        self.assertNotIn("quality", planned_u)  # строжайший профиль

    def test_default_model_is_gpt_image_2_with_env_override(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(OpenAIImagesProvider().model, "gpt-image-2")
        with mock.patch.dict(os.environ, {"OPENAI_IMAGE_MODEL": "gpt-image-1"}):
            self.assertEqual(OpenAIImagesProvider().model, "gpt-image-1")


class TestVisionEvaluator(unittest.TestCase):
    def _request(self, dir_):
        cand = temp_png(dir_, "cand.png")
        ref = temp_png(dir_, "ref.png")
        return VisionEvaluationRequest(
            candidate_id="c1", candidate_image=cand,
            product_references=[ref], scene_spec={"scene_id": "scene-05"})

    def test_real_evaluator_impossible_without_apply(self):
        with tempfile.TemporaryDirectory() as d:
            ev = OpenAIVisionEvaluator()
            with mock.patch("urllib.request.urlopen",
                            side_effect=AssertionError("network in dry-run!")):
                with mock.patch.dict(os.environ, {}, clear=True):
                    out = ev.evaluate(self._request(d), apply=False)
        self.assertEqual(out["mode"], "dry-run")
        self.assertIsNone(out["result"])
        self.assertEqual(out["planned_request"]["model"], "gpt-5.4-mini")

    def test_evaluator_reads_real_image_paths(self):
        with tempfile.TemporaryDirectory() as d:
            req = self._request(d)
            ev = OpenAIVisionEvaluator()
            out = ev.evaluate(req, apply=False)
            self.assertEqual(out["planned_request"]["image_count"], 2)
            # несуществующий путь — отказ ещё до сети/ключа
            req.candidate_image = str(Path(d) / "missing.png")
            with self.assertRaises(FileNotFoundError):
                ev.evaluate(req, apply=False)

    def test_schema_rejects_incomplete_result(self):
        incomplete = make_vision_result()
        del incomplete["handle_count"]
        with self.assertRaises(VisionSchemaError):
            validate_vision_result(incomplete)
        bad_scores = make_vision_result()
        del bad_scores["scores"]["photorealism"]
        with self.assertRaises(VisionSchemaError):
            validate_vision_result(bad_scores)
        bad_code = make_vision_result(hard_fail_codes=["made_up_code"])
        with self.assertRaises(VisionSchemaError):
            validate_vision_result(bad_code)

    def test_hard_fail_derived_from_vision_result(self):
        result = validate_vision_result(
            make_vision_result(handle_count=4,
                               hard_fail_codes=["handle_count"]))
        obs = vision_result_to_observation("c1", result)
        spec = SceneSpec(scene_id="scene-05",
                         exact_food_count={"item": "chicken thigh", "count": 3})
        verdict = evaluate_candidate(obs, spec)
        self.assertFalse(verdict.passed)
        self.assertIn("handle_count", verdict.hard_fails)


class TestArbitration(unittest.TestCase):
    def test_low_confidence_triggers_arbitration_condition(self):
        out = needs_arbitration([
            {"candidate_id": "c1", "total": 90, "confidence": 0.6,
             "hard_fail_codes": []},
            {"candidate_id": "c2", "total": 80, "confidence": 0.9,
             "hard_fail_codes": []},
        ])
        self.assertTrue(out["needed"])
        self.assertTrue(any("confidence" in r for r in out["reasons"]))

    def test_small_gap_triggers_arbitration_condition(self):
        out = needs_arbitration([
            {"candidate_id": "c1", "total": 88, "confidence": 0.9,
             "hard_fail_codes": []},
            {"candidate_id": "c2", "total": 85, "confidence": 0.9,
             "hard_fail_codes": []},
        ])
        self.assertTrue(out["needed"])

    def test_high_confidence_does_not_call_arbiter(self):
        out = needs_arbitration([
            {"candidate_id": "c1", "total": 95, "confidence": 0.95,
             "hard_fail_codes": []},
            {"candidate_id": "c2", "total": 70, "confidence": 0.9,
             "hard_fail_codes": []},
        ])
        self.assertFalse(out["needed"])
        # арбитр выключен по умолчанию и не может быть вызван без флага
        ev = OpenAIVisionEvaluator()
        self.assertFalse(ev.arbiter_enabled)
        self.assertEqual(ev.arbiter_calls, 0)
        with self.assertRaises(RuntimeError):
            ev.arbitrate(VisionEvaluationRequest(
                candidate_id="c1", candidate_image="x.png"), apply=False)
        self.assertEqual(ev.model, "gpt-5.4-mini")
        self.assertEqual(ev.arbiter_model, "gpt-5.5")


class TestBudget(unittest.TestCase):
    def test_spend_cap_stops_next_call(self):
        t = SpendTracker(cap_usd=1.0)
        t.check("image_generation", 0.9)
        t.record("image_generation", 0.9)
        # следующий запрос превысил бы cap — немедленная остановка
        with self.assertRaises(BudgetStop):
            t.check("image_generation", 0.2)
        t.record("image_generation", 0.2)  # доводим до >= cap
        with self.assertRaises(BudgetStop):
            t.check("vision_evaluation", 0.000001)

    def test_categories_tracked_separately_and_actual_from_usage(self):
        t = SpendTracker(cap_usd=10.0)
        t.record("image_generation", 0.3, usage={"output_tokens": 1000},
                 actual_usd=0.25)
        t.record("vision_evaluation", 0.05, usage={"input_tokens": 500},
                 actual_usd=None)
        s = t.summary()
        self.assertEqual(s["estimated_spend_usd"]["image_generation"], 0.3)
        self.assertEqual(s["estimated_spend_usd"]["vision_evaluation"], 0.05)
        self.assertEqual(s["actual_spend_usd"]["image_generation"], 0.25)
        self.assertFalse(s["actual_spend_usd"]["complete"])  # у vision usage не посчитан
        self.assertEqual(
            actual_from_usage({"input_tokens": 1_000_000},
                              {"input_per_1m": 2.0}), 2.0)
        self.assertIsNone(actual_from_usage({"input_tokens": 10}, None))

    def test_dry_run_does_not_accumulate_spend(self):
        provider = OpenAIImagesProvider(model="gpt-image-2", budget_usd=5.0)
        req = ImageRequest(scene_id="s", prompt="p", n=3)
        provider.generate(req, out_dir=".", apply=False)
        provider.generate(req, out_dir=".", apply=False)
        self.assertEqual(provider.tracker.total_estimated(), 0.0)


class TestPilot(unittest.TestCase):
    def _run_cli(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(argv)
        return code, json.loads(buf.getvalue())

    CAMPAIGN = "content/autopilot/coating-protect-2026-07"

    def test_pilot_rejects_all_other_scenes(self):
        for scene in ["scene-01", "scene-02", "scene-03", "scene-04",
                      "scene-06", "scene-07"]:
            code, out = self._run_cli(["pilot", self.CAMPAIGN, "--scene", scene])
            self.assertEqual(code, 1, scene)
            self.assertIn("scene-05", out["error"])

    def test_pilot_dry_run_scene05(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network in dry-run!")):
            code, out = self._run_cli(["pilot", self.CAMPAIGN,
                                       "--scene", "scene-05"])
        self.assertEqual(code, 0)
        self.assertEqual(out["mode"], "dry-run")
        self.assertEqual(out["image_model"], "gpt-image-2")
        self.assertEqual(out["vision_model"], "gpt-5.4-mini")
        self.assertFalse(out["arbiter"]["enabled"])
        self.assertEqual(out["candidates"], 3)
        self.assertEqual(out["quality"], "medium")
        self.assertEqual(out["regeneration_rounds"], 0)
        self.assertEqual(out["budget"]["cap_usd"], 2.0)
        self.assertEqual(out["budget"]["estimated_spend_usd"]["total"], 0.0)
        self.assertIn("BLOCKED", out["higgsfield"])
        # gpt-image-2 без input_fidelity даже при edit с референсами
        planned = out["generation_results"][0]["planned_request"]
        self.assertNotIn("input_fidelity", planned)
        self.assertEqual(planned["endpoint"], "/images/edits")

    def test_higgsfield_stays_blocked_after_pilot(self):
        decisions = [{"scene_id": "scene-05", "winner_id": "scene-05-c1"}]
        # пилот не даёт sequence QA (одна сцена) и не даёт owner approval
        with self.assertRaises(PipelineGateError):
            higgsfield_gate(decisions, None, owner_approved=False)
        ok_seq = {"approved": True, "scenes_to_regenerate": []}
        with self.assertRaises(PipelineGateError):
            higgsfield_gate(decisions, ok_seq, owner_approved=False)


if __name__ == "__main__":
    unittest.main()
