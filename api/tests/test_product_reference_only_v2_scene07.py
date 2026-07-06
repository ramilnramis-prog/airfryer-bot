"""Тесты product-reference-only-v2 для scene-07 (CTA beauty shot) -- то же
mode='edit' + 4 product-only reference images, что и scene-05, но
scene-specific prompt/QA (нет еды, ручки+рёбра дна обязаны быть видны,
внизу кадра место под CTA-плашку).

Также покрывает:
- scene-05 v2 остаётся byte-identical после generализации runner'а под
  несколько сцен (SCENE_PROMPTS_V2 lookup);
- незнакомая сцена (не в SCENE_PROMPTS_V2) padает ДО сети с чётким кодом
  ошибки, а не молча переиспользует чужой prompt;
- scene-05 status doc отражает working_candidate_selected /
  pending_final_owner_approval и НЕ помечает кандидат как reference.
"""
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline import product_reference_only_runner as runner

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"

SCENE07_DRY_RUN_PATH = CAMPAIGN_DIR / "scene-07-product-reference-only-v2-apply-dry-run.json"
SCENE05_STATUS_PATH = CAMPAIGN_DIR / "scene-05-generation-attempts-status.json"

GENERATED_PATTERN = re.compile(r"generated[\\/]")
AIRFRYER_MOTION_PATTERN = re.compile(r"real-v1[\\/](airfryer|motion)[\\/]")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def urlopen_raises():
    return mock.patch("urllib.request.urlopen",
                      side_effect=AssertionError("network call!"))


class TestScene05V2UnchangedAfterGeneralization(unittest.TestCase):
    def test_scene05_prompt_still_matches_original_constant(self):
        req, contract = runner.build_request_contract_v2(str(CAMPAIGN_DIR), "scene-05")
        self.assertEqual(contract.model_prompt, runner.FULL_MODEL_PROMPT_V2)

    def test_scene05_qa_gates_still_original(self):
        _prompt, gates = runner.SCENE_PROMPTS_V2["scene-05"]
        self.assertEqual(list(gates), list(runner.QA_GATES_PRODUCT_REFERENCE_ONLY_V2))

    def test_scene05_reference_images_unchanged(self):
        req, contract = runner.build_request_contract_v2(str(CAMPAIGN_DIR), "scene-05")
        self.assertEqual(contract.reference_images, runner.PRODUCT_REFERENCE_IMAGES_V2)


class TestUnconfiguredSceneFailsClosed(unittest.TestCase):
    def test_unconfigured_scene_raises_before_network(self):
        with urlopen_raises():
            with self.assertRaises(runner.ProductReferenceOnlyRunnerError) as ctx:
                runner.build_request_contract_v2(str(CAMPAIGN_DIR), "scene-03")
        self.assertEqual(ctx.exception.code, "SCENE_NOT_CONFIGURED_FOR_V2")

    def test_unconfigured_scene_apply_also_fails_closed(self):
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "sk-fake-not-real"}):
            with urlopen_raises():
                with self.assertRaises(runner.ProductReferenceOnlyRunnerError) as ctx:
                    runner.run_product_reference_only_scene_v2(str(CAMPAIGN_DIR), "scene-99", apply=True)
        self.assertEqual(ctx.exception.code, "SCENE_NOT_CONFIGURED_FOR_V2")


class TestScene07DryRunExists(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(SCENE07_DRY_RUN_PATH.is_file())

    def test_candidate_label_and_scene_id(self):
        d = load_json(SCENE07_DRY_RUN_PATH)
        self.assertEqual(d["candidate_label"], "product_reference_only_v2")
        self.assertEqual(d["scene_id"], "scene-07")

    def test_live_dry_run_report(self):
        with urlopen_raises():
            report = runner.run_product_reference_only_scene_v2(str(CAMPAIGN_DIR), "scene-07", apply=False)
        self.assertEqual(report["mode"], "dry-run")
        self.assertEqual(report["candidate_label"], "product_reference_only_v2")


class TestScene07ReferenceImagesSameFourProductOnly(unittest.TestCase):
    def test_reference_images_length_four(self):
        d = load_json(SCENE07_DRY_RUN_PATH)
        self.assertEqual(len(d["reference_images"]), 4)

    def test_reference_images_match_scene05(self):
        d = load_json(SCENE07_DRY_RUN_PATH)
        self.assertEqual(d["reference_images"], [
            "real-product-v1:product_45deg_master",
            "real-product-v1:product_top_master",
            "real-product-v1:both_handles_master",
            "real-product-v1:bottom_loop_master",
        ])

    def test_no_airfryer_motion_generated_or_c1_c2_c3_refs(self):
        d = load_json(SCENE07_DRY_RUN_PATH)
        for p in d["reference_image_paths"]:
            self.assertIsNone(GENERATED_PATTERN.search(p))
            self.assertIsNone(AIRFRYER_MOTION_PATTERN.search(p.replace("/", "\\") + "\\"))
            self.assertNotIn("scene-05-c1", p)
            self.assertNotIn("scene-05-c2", p)
            self.assertNotIn("scene-05-c3", p)


class TestScene07PromptNoFoodHandlesRibsVisible(unittest.TestCase):
    def test_prompt_forbids_food(self):
        self.assertIn("No food inside the form", runner.MODEL_PROMPT_V2_SCENE07)
        self.assertIn("food inside the form", runner.NEGATIVE_PROMPT_V2_SCENE07)

    def test_prompt_requires_handles_and_ribs_visible(self):
        self.assertIn("both flat corner handle tabs", runner.MODEL_PROMPT_V2_SCENE07)
        self.assertIn("ribbed bottom", runner.MODEL_PROMPT_V2_SCENE07)
        self.assertIn("handles or bottom ribs not visible", runner.NEGATIVE_PROMPT_V2_SCENE07)

    def test_prompt_no_hands_no_person(self):
        self.assertIn("No hands, no arms, no fingers, no person", runner.MODEL_PROMPT_V2_SCENE07)

    def test_prompt_leaves_cta_space(self):
        self.assertIn("CTA overlay", runner.MODEL_PROMPT_V2_SCENE07)

    def test_qa_gates_scene07_specific(self):
        names = [g["name"] for g in runner.QA_GATES_PRODUCT_REFERENCE_ONLY_V2_SCENE07]
        self.assertIn("handles_and_ribs_clearly_visible", names)
        self.assertIn("no_food_in_frame", names)
        self.assertIn("cta_space_left_at_bottom", names)
        self.assertNotIn("food_count_exact", names)


class TestScene07OpenAIHiggsfieldCallsZero(unittest.TestCase):
    def test_dry_run_doc_calls_zero(self):
        d = load_json(SCENE07_DRY_RUN_PATH)
        self.assertEqual(d["openai_calls_executed"], 0)
        self.assertEqual(d["higgsfield_calls_executed"], 0)
        self.assertEqual(d["api_spend_usd"], 0)

    def test_live_dry_run_calls_zero(self):
        with urlopen_raises():
            report = runner.run_product_reference_only_scene_v2(str(CAMPAIGN_DIR), "scene-07", apply=False)
        self.assertEqual(report["openai_calls_executed"], 0)
        self.assertEqual(report["higgsfield_calls_executed"], 0)


class TestScene05WorkingCandidateStatus(unittest.TestCase):
    def test_status_is_working_candidate_selected(self):
        d = load_json(SCENE05_STATUS_PATH)
        self.assertEqual(d["status"], "working_candidate_selected")
        self.assertEqual(d["status_detail"], "pending_final_owner_approval")

    def test_working_candidate_not_promoted_to_reference(self):
        d = load_json(SCENE05_STATUS_PATH)
        self.assertTrue(d["working_candidate"]["not_promoted_to_reference"])
        self.assertIn("NOT added to product-lock", d["working_candidate"]["important"])
        self.assertIn("NOT used as a reference", d["working_candidate"]["important"])

    def test_working_candidate_file_matches_v2_candidate(self):
        d = load_json(SCENE05_STATUS_PATH)
        self.assertIn("scene-05-product-reference-only-v2-candidate.png",
                     d["working_candidate"]["file"])

    def test_next_scene_points_to_scene07(self):
        d = load_json(SCENE05_STATUS_PATH)
        self.assertIn("scene-07", d["next_scene_using_this_approach"])


if __name__ == "__main__":
    unittest.main()
