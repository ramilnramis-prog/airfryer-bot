"""Тесты scene-05 C2 (angled/asymmetric framing prompt) -- готовим AI plate,
геометрически совместимый с real-product-v1/product_45deg + APPROVED_TRANSFORM_B,
после отклонения C1 (frontal basket, level hand tabs) и его V2 local-transform
salvage (см. scene-05-qa-report-v2.json: rigid transform не может согласовать
асимметричную высоту ручек product_45deg с level-tabs C1 plate).

Покрытие (12 пунктов, запрошенных явно):
1. C2 prompt is clean, no markdown docs
2. C2 prompt contains "high 3/4 top-down"
3. C2 prompt contains upper-left to lower-right diagonal product axis
4. C2 prompt contains left hand higher than right hand
5. C2 prompt forbids completed silicone liner
6. C2 prompt forbids tray insert / black liner
7. reference_images == []
8. mode == generate
9. dry-run includes expected handle regions derived from product masks
10. dry-run rejects level/frontal basket geometry in QA gates
11. OpenAI calls = 0
12. Higgsfield calls = 0
"""
import json
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline import product_only_scene_runner as runner

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"
SCENE_ID = "scene-05"

C2_DRY_RUN_PATH = CAMPAIGN_DIR / "scene-05-product-only-apply-dry-run-c2.json"
C2_PROMPT_MD_PATH = CAMPAIGN_DIR / "scene-05-final-product-only-prompt-c2.md"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_text(path):
    return Path(path).read_text(encoding="utf-8")


def urlopen_raises():
    return mock.patch("urllib.request.urlopen",
                      side_effect=AssertionError("network call!"))


class Test1C2PromptIsCleanNoMarkdown(unittest.TestCase):
    def test_model_prompt_has_no_markdown_headings_or_fences(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertNotIn("##", contract.model_prompt)
        self.assertNotIn("```", contract.model_prompt)

    def test_model_prompt_has_no_internal_file_paths(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        for token in ("video-continuity-block.md", "campaign_visual_policy.json",
                     "video-scene-prompts-product-only.md", ".json", ".py"):
            self.assertNotIn(token, contract.model_prompt)

    def test_model_prompt_is_pure_ascii_plus_typographic_punctuation(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        cyrillic = [ch for ch in contract.model_prompt if "Ѐ" <= ch <= "ӿ"]
        self.assertEqual(cyrillic, [], f"found Cyrillic characters: {cyrillic}")

    def test_c2_dry_run_doc_has_model_prompt_clean_true(self):
        d = load_json(C2_DRY_RUN_PATH)
        self.assertIs(d["model_prompt_clean"], True)


class Test2C2PromptHighThreeQuarterTopDown(unittest.TestCase):
    def test_model_prompt_contains_high_3_4_top_down(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertIn("High 3/4 top-down camera angle", contract.model_prompt)

    def test_geometry_targets_declare_camera_angle(self):
        geometry = runner.get_expected_plate_geometry_c2(str(REPO_ROOT))
        self.assertEqual(geometry["camera_angle"], "high_3_4_top_down")


class Test3C2PromptDiagonalAxis(unittest.TestCase):
    def test_model_prompt_contains_upper_left_to_lower_right_axis(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertIn("diagonal product axis from the upper-left to the lower-right",
                     contract.model_prompt)

    def test_geometry_targets_declare_axis(self):
        geometry = runner.get_expected_plate_geometry_c2(str(REPO_ROOT))
        self.assertEqual(geometry["expected_product_axis"], "upper_left_to_lower_right")


class Test4C2PromptLeftHandHigherThanRight(unittest.TestCase):
    def test_model_prompt_states_left_hand_higher_right_hand_lower(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertIn("the left hand is higher in the frame", contract.model_prompt)
        self.assertIn("the right hand is lower in the frame", contract.model_prompt)

    def test_geometry_targets_left_handle_region_higher_than_right(self):
        # "higher" on screen == smaller y (canvas y grows downward)
        geometry = runner.get_expected_plate_geometry_c2(str(REPO_ROOT))
        left_y0 = geometry["left_future_handle_region"][1]
        right_y0 = geometry["right_future_handle_region"][1]
        self.assertLess(left_y0, right_y0,
                        "left future handle region should sit higher (smaller y) than the right")


class Test5C2PromptForbidsCompletedLiner(unittest.TestCase):
    def test_model_prompt_forbids_completed_silicone_liner(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertIn("Do not draw a completed silicone liner", contract.model_prompt)


class Test6C2PromptForbidsTrayInsertAndBlackLiner(unittest.TestCase):
    def test_model_prompt_forbids_duplicate_tray_insert(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertIn("Do not draw any duplicate tray or basket insert", contract.model_prompt)

    def test_model_prompt_forbids_black_insert_or_liner(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertIn("Do not draw a black insert or black liner inside the basket",
                     contract.model_prompt)


class Test7ReferenceImagesEmpty(unittest.TestCase):
    def test_request_contract_reference_images_empty(self):
        req, _contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertEqual(req.reference_images, [])

    def test_c2_dry_run_doc_reference_images_empty(self):
        d = load_json(C2_DRY_RUN_PATH)
        self.assertEqual(d["reference_images"], [])


class Test8ModeIsGenerate(unittest.TestCase):
    def test_request_and_contract_mode_generate(self):
        req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertEqual(req.mode, "generate")
        self.assertEqual(contract.mode, "generate")

    def test_c2_dry_run_doc_mode_generate(self):
        d = load_json(C2_DRY_RUN_PATH)
        self.assertEqual(d["mode"], "generate")


class Test9DryRunHasExpectedHandleRegionsFromMasks(unittest.TestCase):
    def test_c2_dry_run_doc_has_geometry_compatibility_targets(self):
        d = load_json(C2_DRY_RUN_PATH)
        self.assertIn("geometry_compatibility_targets", d)
        targets = d["geometry_compatibility_targets"]
        self.assertIn("left_future_handle_region", targets)
        self.assertIn("right_future_handle_region", targets)
        self.assertIn("basket_region_target", targets)

    def test_handle_regions_match_actual_product_masks_not_invented(self):
        from api.media_pipeline.compositor.product_assets import DEFAULT_VIEW
        from api.media_pipeline.compositor.scene05_baseplate import (
            APPROVED_CANVAS_SIZE, APPROVED_TRANSFORM_B)
        from api.media_pipeline.compositor.scene05_layer_masks import build_all_layer_masks

        masks = build_all_layer_masks(DEFAULT_VIEW, APPROVED_TRANSFORM_B,
                                      APPROVED_CANVAS_SIZE, str(REPO_ROOT))
        geometry = runner.get_expected_plate_geometry_c2(str(REPO_ROOT))
        self.assertEqual(geometry["left_future_handle_region"], list(masks["left_handle_bbox"]))
        self.assertEqual(geometry["right_future_handle_region"], list(masks["right_handle_bbox"]))
        self.assertEqual(geometry["basket_region_target"], list(masks["product_full_bbox"]))


class Test10DryRunRejectsLevelOrFrontalGeometry(unittest.TestCase):
    def test_geometry_targets_declare_reject_flags(self):
        geometry = runner.get_expected_plate_geometry_c2(str(REPO_ROOT))
        self.assertTrue(geometry["reject_if_handles_level"])
        self.assertTrue(geometry["reject_if_basket_frontal"])
        self.assertTrue(geometry["reject_if_black_insert_drawn"])

    def test_c2_precheck_gates_cover_level_and_frontal_rejection(self):
        names = [g["name"] for g in runner.QA_GATES_C2_GEOMETRY_PRECHECK]
        self.assertIn("basket_perspective_matches_product_45deg", names)
        self.assertIn("future_handle_regions_asymmetric", names)
        self.assertIn("no_level_left_right_tabs", names)
        self.assertIn("no_black_insert_or_liner_in_basket", names)
        self.assertIn("ai_plate_has_clean_empty_product_area", names)
        self.assertIn("hands_near_expected_asymmetric_handle_regions", names)

    def test_c2_precheck_gates_marked_as_precomposite_stage(self):
        for gate in runner.QA_GATES_C2_GEOMETRY_PRECHECK:
            self.assertEqual(gate["stage"], "precheck_before_transform_salvage")

    def test_c2_dry_run_doc_contains_precheck_gates(self):
        d = load_json(C2_DRY_RUN_PATH)
        self.assertIn("qa_gates_c2_geometry_precheck", d)
        names = [g["name"] for g in d["qa_gates_c2_geometry_precheck"]]
        self.assertIn("no_level_left_right_tabs", names)
        self.assertIn("no_black_insert_or_liner_in_basket", names)


class Test11OpenAICallsZero(unittest.TestCase):
    def test_dry_run_report_openai_calls_zero(self):
        with urlopen_raises():
            report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["openai_calls_executed"], 0)

    def test_c2_dry_run_doc_openai_calls_zero(self):
        d = load_json(C2_DRY_RUN_PATH)
        self.assertEqual(d["openai_calls_executed"], 0)
        self.assertEqual(d["api_spend_usd"], 0)


class Test12HiggsfieldCallsZero(unittest.TestCase):
    def test_dry_run_report_higgsfield_calls_zero(self):
        with urlopen_raises():
            report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["higgsfield_calls_executed"], 0)

    def test_c2_dry_run_doc_higgsfield_calls_zero(self):
        d = load_json(C2_DRY_RUN_PATH)
        self.assertEqual(d["higgsfield_calls_executed"], 0)


class TestC2FilesExistAndConsistent(unittest.TestCase):
    def test_c2_dry_run_file_exists(self):
        self.assertTrue(C2_DRY_RUN_PATH.is_file())

    def test_c2_prompt_md_exists(self):
        self.assertTrue(C2_PROMPT_MD_PATH.is_file())

    def test_c2_dry_run_prompt_sha256_matches_live_contract(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        d = load_json(C2_DRY_RUN_PATH)
        self.assertEqual(d["prompt_sha256"], contract.prompt_sha256)

    def test_c2_dry_run_max_calls_retries_hard_cap(self):
        d = load_json(C2_DRY_RUN_PATH)
        self.assertEqual(d["max_calls_future_apply"], 1)
        self.assertEqual(d["retries"], 0)
        self.assertEqual(d["hard_cap_usd"], 0.50)

    def test_c2_dry_run_per_plate_transform_allowed_rigid_only(self):
        d = load_json(C2_DRY_RUN_PATH)
        self.assertTrue(d["per_plate_transform_allowed"])
        self.assertEqual(d["allowed_transform_type"], "rigid_only")

    def test_c2_dry_run_does_not_use_forbidden_appearance_refs(self):
        from api.media_pipeline.product_only_policy import FORBIDDEN_APPEARANCE_ASSET_IDS
        d = load_json(C2_DRY_RUN_PATH)
        flat = json.dumps(d, ensure_ascii=False)
        for asset_id in FORBIDDEN_APPEARANCE_ASSET_IDS:
            # only allowed inside the documentary "previous_attempts" note --
            # confirm it's not present as an actual request field value.
            self.assertNotIn(asset_id, json.dumps({k: v for k, v in d.items()
                                                   if k not in ("forbidden_appearance_asset_ids_not_used",)}))


if __name__ == "__main__":
    unittest.main()
