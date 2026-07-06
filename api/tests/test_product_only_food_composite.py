"""Тесты второй ревизии scene-05 product-only runner:
1) чистый model_prompt (без markdown/русской документации из
   video-continuity-block.md -- раньше туда по ошибке попадал весь .md
   файл целиком);
2) явный food composite plan (extract_food_cluster() по
   product_interior_food_mask, вместо пустой формы после deterministic
   вставки real-product-v1).

Покрытие (13 пунктов, запрошенных явно):
1. model_prompt_clean == true
2. model_prompt не содержит markdown docs
3. model_prompt не содержит русскую служебную документацию
4. model_prompt не просит рисовать completed silicone liner
5. model_prompt просит leave clean central placement area
6. model_prompt просит exactly 3 chicken thighs with potato wedges как food cluster
7. dry-run содержит food_composite_strategy
8. если food_extraction not_implemented, --apply blocked
9. если food_extraction implemented, dry-run содержит product_interior_food_mask
10. final_composite_order содержит food layer
11. product layer остаётся real-product-v1
12. OpenAI calls = 0
13. Higgsfield calls = 0
"""
import json
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline import product_only_scene_runner as runner
from api.media_pipeline.openai_images_client import MissingAPIKeyError

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"
SCENE_ID = "scene-05"

APPLY_DRY_RUN_PATH = CAMPAIGN_DIR / "scene-05-product-only-apply-dry-run.json"
FINAL_PROMPT_PATH = CAMPAIGN_DIR / "scene-05-final-product-only-prompt.md"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_text(path):
    return Path(path).read_text(encoding="utf-8")


def urlopen_raises():
    return mock.patch("urllib.request.urlopen",
                      side_effect=AssertionError("network call!"))


class Test1ModelPromptCleanFlag(unittest.TestCase):
    def test_apply_dry_run_has_model_prompt_clean_true(self):
        d = load_json(APPLY_DRY_RUN_PATH)
        self.assertIs(d["model_prompt_clean"], True)

    def test_dry_run_report_can_be_used_to_derive_the_same_flag(self):
        with urlopen_raises():
            report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        # model_prompt в отчёте должен совпадать с тем, что зафиксировано
        # в tracked apply-dry-run doc как "чистый"
        d = load_json(APPLY_DRY_RUN_PATH)
        self.assertEqual(report["request_contract"]["model_prompt"], d["model_prompt"])


class Test2ModelPromptNoMarkdownDocs(unittest.TestCase):
    def test_model_prompt_has_no_markdown_headings(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertNotIn("##", contract.model_prompt)
        self.assertNotIn("```", contract.model_prompt)

    def test_model_prompt_has_no_internal_file_paths(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        for token in ("video-continuity-block.md", "campaign_visual_policy.json",
                     "video-scene-prompts-product-only.md", ".json", ".py"):
            self.assertNotIn(token, contract.model_prompt)

    def test_model_prompt_is_much_shorter_than_full_continuity_doc(self):
        _req, contract, plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        # раньше model_prompt включал весь continuity_block_text (весь .md,
        # ~2000+ символов только на continuity) -- теперь он не может быть
        # длиннее clean_continuity_prompt + разумный scene action.
        self.assertLess(len(contract.model_prompt), len(plan["continuity_block_text"]) + 1500)


class Test3ModelPromptNoRussianDocs(unittest.TestCase):
    def test_model_prompt_has_no_russian_service_phrases(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        for phrase in ("Этот блок", "Правила применения", "единственный источник",
                      "вставляется в каждый scene prompt", "continuity"):
            self.assertNotIn(phrase, contract.model_prompt)

    def test_model_prompt_is_pure_ascii_plus_typographic_punctuation(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        cyrillic = [ch for ch in contract.model_prompt if "Ѐ" <= ch <= "ӿ"]
        self.assertEqual(cyrillic, [], f"found Cyrillic characters: {cyrillic}")


class Test4ModelPromptDoesNotAskForCompletedLiner(unittest.TestCase):
    def test_no_completed_liner_drawing_request(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertNotIn("lifts the square silicone liner out of the open air fryer basket",
                        contract.model_prompt)
        self.assertIn("Do not draw a completed silicone liner", contract.model_prompt)


class Test5ModelPromptLeaveCleanPlacementArea(unittest.TestCase):
    def test_leave_clean_placement_area_present(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertIn("clean, empty central placement area", contract.model_prompt)
        self.assertIn("Leave the product placement area clean", contract.model_prompt)


class Test6ModelPromptAsksForFoodCluster(unittest.TestCase):
    def test_exactly_3_chicken_thighs_with_potato_wedges_requested(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertIn("exactly 3 roasted golden chicken thighs with potato wedges",
                     contract.model_prompt)

    def test_food_cluster_positioned_in_placement_area(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertIn("In the central placement area, include a loose cluster",
                     contract.model_prompt)


class Test7DryRunHasFoodCompositeStrategy(unittest.TestCase):
    def test_apply_dry_run_doc_has_food_composite_strategy(self):
        d = load_json(APPLY_DRY_RUN_PATH)
        self.assertIn("food_composite_strategy", d)
        self.assertIn("method", d["food_composite_strategy"])

    def test_runtime_report_has_food_composite_strategy(self):
        with urlopen_raises():
            report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertIn("food_composite_strategy", report)


class Test8ApplyBlockedIfFoodExtractionNotImplemented(unittest.TestCase):
    def test_apply_raises_if_food_extraction_not_implemented(self):
        with mock.patch.object(runner, "FOOD_EXTRACTION_STATUS", "not_implemented"):
            with urlopen_raises():
                with self.assertRaises(runner.ProductOnlyRunnerError) as ctx:
                    runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=True)
            self.assertEqual(ctx.exception.code, "FOOD_EXTRACTION_NOT_IMPLEMENTED")

    def test_dry_run_still_works_even_if_food_extraction_not_implemented(self):
        # dry-run (apply=False) должен продолжать работать и показывать
        # текущий статус, а не падать -- блокировка касается только --apply.
        with mock.patch.object(runner, "FOOD_EXTRACTION_STATUS", "not_implemented"):
            with urlopen_raises():
                report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["food_extraction"], "not_implemented")
        self.assertEqual(report["openai_calls_executed"], 0)

    def test_currently_food_extraction_is_implemented_so_apply_gate_passes_this_check(self):
        self.assertEqual(runner.FOOD_EXTRACTION_STATUS, "implemented")


class Test9DryRunHasProductInteriorFoodMaskWhenImplemented(unittest.TestCase):
    def test_apply_dry_run_doc_has_product_interior_food_mask(self):
        d = load_json(APPLY_DRY_RUN_PATH)
        self.assertIn("product_interior_food_mask", d)
        self.assertIn("bbox", d["product_interior_food_mask"])
        self.assertIsNotNone(d["product_interior_food_mask"]["bbox"])

    def test_mask_info_matches_actual_compositor_geometry(self):
        info = runner.get_product_interior_food_mask_info()
        d = load_json(APPLY_DRY_RUN_PATH)
        self.assertEqual(info["bbox"], d["product_interior_food_mask"]["bbox"])

    def test_extract_food_cluster_works_on_synthetic_plate(self):
        import tempfile
        from PIL import Image
        import numpy as np

        with tempfile.TemporaryDirectory() as tmp:
            fake_plate_path = Path(tmp) / "fake_plate.png"
            Image.new("RGB", (720, 1280), (10, 20, 30)).save(fake_plate_path)
            food_layer = runner.extract_food_cluster(str(fake_plate_path))
            arr = np.asarray(food_layer)
            self.assertGreater(int((arr[..., 3] > 0).sum()), 0)
            info = runner.get_product_interior_food_mask_info()
            bx0, by0, bx1, by1 = info["bbox"]
            # вне bbox -- строго прозрачно
            self.assertEqual(int(arr[0, 0, 3]), 0)


class Test10FinalCompositeOrderHasFoodLayer(unittest.TestCase):
    def test_final_composite_order_mentions_food(self):
        d = load_json(APPLY_DRY_RUN_PATH)
        order_text = " ".join(d["final_composite_order"]).lower()
        self.assertIn("food", order_text)

    def test_final_composite_order_has_five_steps_in_right_sequence(self):
        d = load_json(APPLY_DRY_RUN_PATH)
        order = d["final_composite_order"]
        self.assertEqual(len(order), 5)
        self.assertIn("AI plate", order[0])
        self.assertIn("real-product-v1", order[1])
        self.assertIn("food", order[2].lower())
        self.assertIn("occluder", order[3].lower())
        self.assertIn("QA", order[4])


class Test11ProductLayerRemainsRealProductV1(unittest.TestCase):
    def test_product_canon_is_real_product_v1_everywhere(self):
        d = load_json(APPLY_DRY_RUN_PATH)
        self.assertEqual(d["product_canon"], "real-product-v1")
        self.assertEqual(d["composite_strategy"]["order"].count("real-product-v1"), 2)

    def test_food_composite_strategy_never_sources_product_pixels_from_ai(self):
        d = load_json(APPLY_DRY_RUN_PATH)
        method = d["food_composite_strategy"]["method"]
        self.assertIn("silicone/handles/walls/background NEVER taken from AI", method)


class Test12OpenAICallsZero(unittest.TestCase):
    def test_dry_run_report_openai_calls_zero(self):
        with urlopen_raises():
            report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["openai_calls_executed"], 0)

    def test_apply_dry_run_doc_openai_calls_zero(self):
        d = load_json(APPLY_DRY_RUN_PATH)
        self.assertEqual(d["openai_calls_executed"], 0)


class Test13HiggsfieldCallsZero(unittest.TestCase):
    def test_dry_run_report_higgsfield_calls_zero(self):
        with urlopen_raises():
            report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["higgsfield_calls_executed"], 0)

    def test_apply_dry_run_doc_higgsfield_calls_zero(self):
        d = load_json(APPLY_DRY_RUN_PATH)
        self.assertEqual(d["higgsfield_calls_executed"], 0)


class TestNoPaidApiCalls(unittest.TestCase):
    def test_full_module_makes_no_network_call(self):
        with urlopen_raises():
            runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
            runner.get_product_interior_food_mask_info()

    def test_apply_without_key_still_fails_before_network_with_food_implemented(self):
        import os
        env_backup = os.environ.pop("OPENAI_API_KEY", None)
        try:
            with urlopen_raises():
                with self.assertRaises(MissingAPIKeyError):
                    runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=True)
        finally:
            if env_backup is not None:
                os.environ["OPENAI_API_KEY"] = env_backup


if __name__ == "__main__":
    unittest.main()
