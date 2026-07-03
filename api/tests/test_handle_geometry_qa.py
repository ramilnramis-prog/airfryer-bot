"""Тесты канонической геометрии ручек в visual QA и animation QA.

Покрытие (по заданию):
1. две ручки неправильной округлой формы -> handle_geometry_mismatch;
2. правильные прямые ручки с параллельными сторонами проходят;
3. правильный count не отменяет geometry mismatch;
4. асимметричные ручки отклоняются;
5. изменение ручек в середине видео -> handle_geometry_drift;
6. uncertain geometry блокирует auto-approval;
7. owner override меняет итоговый статус на rejected;
8. старый QA-отчёт сохраняется неизменным;
9. API generation calls = 0 при переоценке.
"""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from api.media_pipeline import cli
from api.media_pipeline.animation_qa import (check_handle_drift,
                                             resolve_animation_status)
from api.media_pipeline.models import SceneSpec
from api.media_pipeline.openai_vision_evaluator import (
    OpenAIVisionEvaluator, _handle_check_instructions,
    _structured_output_schema)
from api.media_pipeline.vision_provider import (
    HANDLE_DRIFT_CODE, HANDLE_GEOMETRY_CONFIRMED, HANDLE_GEOMETRY_UNCERTAIN,
    HARD_FAIL_CODES, SCORE_DIMENSIONS, needs_handle_second_pass,
    reconcile_handle_geometry, validate_vision_result,
    vision_result_to_observation)
from api.media_pipeline.visual_qa import evaluate_candidate, hard_fails, select_winner

SPEC = SceneSpec(
    scene_id="scene-05", title="Доставание формы",
    prompt_action="woman lifts the liner by its two handles",
    exact_food_count={"item": "chicken thigh", "count": 3},
)


def geometry_fields(ok=True, **overrides):
    base = {
        "handle_outer_shape_match": ok,
        "handle_cutout_shape_match": ok,
        "handle_parallel_sides": ok,
        "handle_symmetry": ok,
        "handle_reference_similarity": 0.95 if ok else 0.4,
        "handle_geometry_confidence": 0.95,
        "handle_geometry_issues": [] if ok else ["rounded puffy silhouette"],
        "handle_regions": {"left": {"x0": 0.05, "y0": 0.4, "x1": 0.25, "y1": 0.55},
                           "right": {"x0": 0.6, "y0": 0.25, "x1": 0.85, "y1": 0.4}},
    }
    base.update(overrides)
    return base


def vision_result(**overrides):
    base = {
        "detected_objects": ["silicone liner", "air fryer"],
        "handle_count": 2,
        "product_match": True,
        "airfryer_match": True,
        "hand_gender_presentation": "female",
        "hand_anatomy_issues": [],
        "grip_correct": True,
        "food_count": 3,
        "food_count_detail": None,
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
    base.update(geometry_fields())
    base.update(overrides)
    return base


class TestHandleGeometryHardFail(unittest.TestCase):
    def test_two_rounded_handles_hard_fail(self):
        # (1) ручек ровно две, но силуэт округлый -> handle_geometry_mismatch
        result = validate_vision_result(vision_result(
            **geometry_fields(ok=False)))
        self.assertEqual(result["handle_count"], 2)
        obs = vision_result_to_observation("c1", result)
        fails = hard_fails(obs, SPEC)
        self.assertIn("handle_geometry_mismatch", fails)
        self.assertNotIn("handle_count", fails)  # count-то правильный

    def test_straight_parallel_handles_pass(self):
        # (2) прямые вытянутые ручки с параллельными сторонами проходят
        result = validate_vision_result(vision_result())
        obs = vision_result_to_observation("c1", result)
        self.assertEqual(hard_fails(obs, SPEC), [])
        self.assertTrue(evaluate_candidate(obs, SPEC).passed)

    def test_correct_count_does_not_override_geometry(self):
        # (3) handle_count == 2 не перекрывает mismatch
        result = validate_vision_result(vision_result(
            handle_count=2, handle_outer_shape_match=False))
        obs = vision_result_to_observation("c1", result)
        verdict = evaluate_candidate(obs, SPEC)
        self.assertFalse(verdict.passed)
        self.assertIn("handle_geometry_mismatch", verdict.hard_fails)
        # и наличие кода в HARD_FAIL_CODES/схеме
        self.assertIn("handle_geometry_mismatch", HARD_FAIL_CODES)
        schema = _structured_output_schema()
        self.assertIn("handle_geometry_mismatch",
                      schema["properties"]["hard_fail_codes"]["items"]["enum"])

    def test_asymmetric_handles_rejected(self):
        # (4) асимметрия левой/правой -> hard fail
        result = validate_vision_result(vision_result(handle_symmetry=False))
        obs = vision_result_to_observation("c1", result)
        self.assertIn("handle_geometry_mismatch", hard_fails(obs, SPEC))


class TestHandleDrift(unittest.TestCase):
    FRAMES_OK = [
        {"frame": "frame-0000", "position": "first", "handle_geometry_ok": True},
        {"frame": "frame-0051", "position": "middle", "handle_geometry_ok": True},
        {"frame": "frame-0120", "position": "last", "handle_geometry_ok": True},
    ]

    def test_mid_animation_change_gives_drift(self):
        # (5) ручки испортились в середине клипа -> handle_geometry_drift
        frames = [dict(f) for f in self.FRAMES_OK]
        frames[1]["handle_geometry_ok"] = False
        frames[1]["issues"] = ["cutout morphs into two holes"]
        out = check_handle_drift(frames)
        self.assertEqual(out["hard_fail"], HANDLE_DRIFT_CODE)
        self.assertEqual(out["frames"], ["frame-0051"])

    def test_stable_handles_no_drift(self):
        out = check_handle_drift(self.FRAMES_OK)
        self.assertIsNone(out["hard_fail"])

    def test_bad_first_frame_is_source_mismatch_not_drift(self):
        frames = [dict(f) for f in self.FRAMES_OK]
        frames[0]["handle_geometry_ok"] = False
        out = check_handle_drift(frames)
        self.assertEqual(out["hard_fail"], "handle_geometry_mismatch")

    def test_required_positions_enforced(self):
        with self.assertRaises(ValueError):
            check_handle_drift([{"frame": "frame-0000", "position": "first",
                                 "handle_geometry_ok": True}])


class TestUncertainGeometry(unittest.TestCase):
    def test_low_confidence_triggers_second_pass_and_blocks(self):
        # (6) низкая уверенность -> second pass; uncertain блокирует approval
        result = validate_vision_result(vision_result(
            handle_geometry_confidence=0.5))
        check = needs_handle_second_pass(result)
        self.assertTrue(check["needed"])
        recon = reconcile_handle_geometry(result, None)
        self.assertEqual(recon["status"], HANDLE_GEOMETRY_UNCERTAIN)
        obs = vision_result_to_observation(
            "c1", result, handle_geometry_ok=recon["geometry_ok"],
            handle_geometry_status=recon["status"])
        verdict = evaluate_candidate(obs, SPEC)
        self.assertFalse(verdict.passed)
        self.assertTrue(any("handle_geometry_uncertain" in r
                            for r in verdict.reasons))
        decision = select_winner("scene-05", [obs], SPEC)
        self.assertIsNone(decision.winner_id)

    def test_confident_consistent_primary_needs_no_second_pass(self):
        result = validate_vision_result(vision_result())
        check = needs_handle_second_pass(result)
        self.assertFalse(check["needed"])
        recon = reconcile_handle_geometry(result, None)
        self.assertEqual(recon["status"], HANDLE_GEOMETRY_CONFIRMED)
        self.assertTrue(recon["geometry_ok"])

    def test_second_pass_disagreement_is_uncertain(self):
        result = validate_vision_result(vision_result(
            handle_geometry_confidence=0.5))
        second = {"left_handle_matches_reference": False,
                  "right_handle_matches_reference": True,
                  "outer_silhouette_straight_elongated": False,
                  "cutout_elongated_oval": True, "long_sides_parallel": True,
                  "left_right_symmetric": False,
                  "similarity_to_reference": 0.5, "confidence": 0.9,
                  "issues": ["left handle rounded"]}
        recon = reconcile_handle_geometry(result, second)
        self.assertEqual(recon["status"], HANDLE_GEOMETRY_UNCERTAIN)
        self.assertFalse(recon["geometry_ok"])

    def test_second_pass_instructions_are_specific(self):
        text = _handle_check_instructions()
        self.assertIn("STRAIGHT ELONGATED", text)
        self.assertIn("PARALLEL", text)
        self.assertIn("rounded", text)


class TestOwnerOverrideAndHistory(unittest.TestCase):
    QA = {"qa": {"verdict": "approved"}, "status": "approved_for_owner_review"}
    OVERRIDE = {"previous_status": "approved_for_owner_review",
                "owner_status": "rejected",
                "hard_fail_code": "handle_geometry_mismatch",
                "regeneration_required": True}

    def test_owner_override_changes_final_status(self):
        # (7) override владельца -> rejected_by_owner_needs_regeneration
        self.assertEqual(resolve_animation_status(self.QA, self.OVERRIDE),
                         "rejected_by_owner_needs_regeneration")
        self.assertEqual(resolve_animation_status(self.QA, None),
                         "approved_for_owner_review")
        with self.assertRaises(ValueError):
            resolve_animation_status(self.QA, {"owner_status": "meh"})

    def test_historical_qa_report_preserved_in_repo(self):
        # (8) исторический QA-отчёт не переписан: verdict approved остался,
        # override живёт в отдельном файле
        base = Path("content/autopilot/coating-protect-2026-07/generated/scene-05")
        qa = json.loads((base / "scene-05-animation-qa.json").read_text(encoding="utf-8"))
        self.assertEqual(qa["qa"]["verdict"], "approved")
        self.assertEqual(qa["status"], "approved_for_owner_review")
        override = json.loads((base / "scene-05-animation-owner-override.json")
                              .read_text(encoding="utf-8"))
        self.assertEqual(override["owner_status"], "rejected")
        self.assertEqual(override["hard_fail_code"], "handle_geometry_mismatch")
        self.assertEqual(resolve_animation_status(qa, override),
                         "rejected_by_owner_needs_regeneration")
        self.assertEqual(override["final_status"],
                         "rejected_by_owner_needs_regeneration")


class TestNoGenerationCalls(unittest.TestCase):
    def test_reevaluate_makes_zero_generation_calls(self):
        # (9) переоценка не вызывает ни Images API, ни сеть в dry-run
        with tempfile.TemporaryDirectory() as tmp:
            camp = Path(tmp) / "campaign"
            (camp / "scene-specs").mkdir(parents=True)
            (camp / "scene-specs" / "scene-05.json").write_text(json.dumps({
                "scene_id": "scene-05", "prompt_action": "lift",
                "required_references": [],
                "exact_food_count": {"item": "chicken thigh", "count": 3},
            }), encoding="utf-8")
            gen = camp / "generated" / "scene-05"
            gen.mkdir(parents=True)
            (gen / "scene-05-c1.png").write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
            buf = io.StringIO()
            with mock.patch(
                    "api.media_pipeline.openai_images_client."
                    "OpenAIImagesProvider.generate",
                    side_effect=AssertionError("generation call!")), \
                 mock.patch("urllib.request.urlopen",
                            side_effect=AssertionError("network in dry-run!")), \
                 mock.patch.dict(os.environ, {}, clear=True), \
                 redirect_stdout(buf):
                code = cli.main(["reevaluate", str(camp), "--scene", "scene-05"])
            out = json.loads(buf.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(out["images_api_calls"], 0)
        self.assertEqual(out["generation_calls"], 0)
        self.assertEqual(out["handle_second_pass_calls"], 0)
        self.assertFalse(out["arbiter"]["enabled"])

    def test_verify_handles_dry_run_no_network(self):
        with tempfile.TemporaryDirectory() as d:
            cand = Path(d) / "cand.png"
            ref = Path(d) / "ref.png"
            cand.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
            ref.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
            ev = OpenAIVisionEvaluator()
            with mock.patch("urllib.request.urlopen",
                            side_effect=AssertionError("network in dry-run!")), \
                 mock.patch.dict(os.environ, {}, clear=True):
                out = ev.verify_handles(str(cand), str(ref), apply=False)
        self.assertEqual(out["mode"], "dry-run")
        self.assertIsNone(out["result"])
        self.assertEqual(out["planned_request"]["purpose"],
                         "handle_geometry_second_pass")


if __name__ == "__main__":
    unittest.main()
