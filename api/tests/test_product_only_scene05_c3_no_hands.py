"""Тесты scene-05 C3 (no-hands result shot) -- после отклонения C1 (frontal
basket, level hand tabs) и C2 (high 3/4 top-down, asymmetric hand tabs, но
hands всё равно не выравниваются достаточно близко к real handle tabs после
per-plate rigid transform, см. scene-05-c2-qa-report.json), владелец решил
прекратить попытки сделать scene-05 кадром "руки поднимают форму за ручки".

Root cause (не решается только текстом prompt): в product-only compositing
руки, держащие ручки, требуют корректного front/back occlusion вокруг
вставленного real-product-v1 слоя; C1 и C2 оба показали, что сгенерированные
руки не выравниваются надёжно с товаром после deterministic overlay.

C3: scene-05 становится no-hands result shot -- готовое блюдо в реальной
форме внутри чистого аэрогриля, без рук/человека в кадре, без lifting
action, без handle-grip взаимодействия. Товар остаётся 100% канонический
real-product-v1.

Покрытие (15 пунктов, запрошенных явно):
1. C3 prompt is clean English, no markdown docs
2. C3 prompt contains no hands
3. C3 prompt contains no person visible
4. C3 prompt forbids completed silicone liner
5. C3 prompt forbids tray insert / black liner
6. C3 dry-run candidate_label == C3
7. C3 dry-run scene_variant == no_hands_result_shot
8. front_hand_extraction == not_needed
9. hands_grip_qa == not_applicable
10. reference_images == []
11. mode == generate
12. product_canon == real-product-v1
13. food_extraction == implemented
14. OpenAI calls = 0
15. Higgsfield calls = 0
"""
import json
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline import product_only_scene_runner as runner

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"
SCENE_ID = "scene-05"

C3_DRY_RUN_PATH = CAMPAIGN_DIR / "scene-05-product-only-apply-dry-run-c3.json"
C3_PROMPT_MD_PATH = CAMPAIGN_DIR / "scene-05-final-product-only-prompt-c3.md"
ACTIVE_DRY_RUN_PATH = CAMPAIGN_DIR / "scene-05-product-only-apply-dry-run.json"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_text(path):
    return Path(path).read_text(encoding="utf-8")


def urlopen_raises():
    return mock.patch("urllib.request.urlopen",
                      side_effect=AssertionError("network call!"))


class Test1C3PromptIsCleanEnglishNoMarkdown(unittest.TestCase):
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

    def test_c3_dry_run_doc_has_model_prompt_clean_true(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertIs(d["model_prompt_clean"], True)


class Test2C3PromptContainsNoHands(unittest.TestCase):
    def test_model_prompt_states_no_hands(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertIn("no hands", contract.model_prompt.lower())

    def test_negative_prompt_forbids_hands(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        # negative prompt line lives inside model_prompt, comma-separated
        self.assertIn("hands,", contract.model_prompt)


class Test3C3PromptContainsNoPersonVisible(unittest.TestCase):
    def test_model_prompt_states_no_person(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertIn("no person", contract.model_prompt.lower())

    def test_negative_prompt_forbids_person(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertIn("a person or any part of a person", contract.model_prompt)


class Test4C3PromptForbidsCompletedLiner(unittest.TestCase):
    def test_model_prompt_forbids_completed_silicone_liner(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertIn("Do not draw a completed silicone liner", contract.model_prompt)


class Test5C3PromptForbidsTrayInsertAndBlackLiner(unittest.TestCase):
    def test_model_prompt_forbids_duplicate_tray_insert(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertIn("Do not draw any duplicate tray or basket insert", contract.model_prompt)

    def test_model_prompt_forbids_black_insert_or_liner(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertIn("Do not draw a black insert or black liner inside the basket",
                     contract.model_prompt)


class Test6C3DryRunCandidateLabel(unittest.TestCase):
    def test_c3_dry_run_candidate_label(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["candidate_label"], "C3")

    def test_active_dry_run_candidate_label_updated_to_c3(self):
        d = load_json(ACTIVE_DRY_RUN_PATH)
        self.assertEqual(d["candidate_label"], "C3")


class Test7C3DrySceneVariant(unittest.TestCase):
    def test_c3_dry_run_scene_variant(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["scene_variant"], "no_hands_result_shot")

    def test_active_dry_run_scene_variant(self):
        d = load_json(ACTIVE_DRY_RUN_PATH)
        self.assertEqual(d["scene_variant"], "no_hands_result_shot")


class Test8FrontHandExtractionNotNeeded(unittest.TestCase):
    def test_c3_dry_run_front_hand_extraction(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["front_hand_extraction"], "not_needed")

    def test_active_dry_run_front_hand_extraction(self):
        d = load_json(ACTIVE_DRY_RUN_PATH)
        self.assertEqual(d["front_hand_extraction"], "not_needed")

    def test_runner_constant(self):
        self.assertEqual(runner.FRONT_HAND_EXTRACTION_STATUS_C3, "not_needed")


class Test9HandsGripQaNotApplicable(unittest.TestCase):
    def test_c3_dry_run_hands_grip_qa(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["hands_grip_qa"], "not_applicable")

    def test_active_dry_run_hands_grip_qa(self):
        d = load_json(ACTIVE_DRY_RUN_PATH)
        self.assertEqual(d["hands_grip_qa"], "not_applicable")

    def test_runner_constant(self):
        self.assertEqual(runner.HANDS_GRIP_QA_C3, "not_applicable")


class Test10ReferenceImagesEmpty(unittest.TestCase):
    def test_request_contract_reference_images_empty(self):
        req, _contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertEqual(req.reference_images, [])

    def test_c3_dry_run_reference_images_empty(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["reference_images"], [])


class Test11ModeIsGenerate(unittest.TestCase):
    def test_request_and_contract_mode_generate(self):
        req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertEqual(req.mode, "generate")
        self.assertEqual(contract.mode, "generate")

    def test_c3_dry_run_mode_generate(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["mode"], "generate")


class Test12ProductCanonRealProductV1(unittest.TestCase):
    def test_c3_dry_run_product_canon(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["product_canon"], "real-product-v1")

    def test_pipeline_lock_instruction_still_pixel_faithful(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertIn("pixel-faithful", contract.pipeline_product_lock_instruction)
        self.assertIn("real-product-v1", contract.pipeline_product_lock_instruction)


class Test13FoodExtractionImplemented(unittest.TestCase):
    def test_c3_dry_run_food_extraction(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["food_extraction"], "implemented")

    def test_model_prompt_still_asks_for_exactly_3_chicken_thighs(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertIn("exactly 3 roasted golden chicken thighs with potato wedges",
                     contract.model_prompt)


class Test14OpenAICallsZero(unittest.TestCase):
    def test_dry_run_report_openai_calls_zero(self):
        with urlopen_raises():
            report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["openai_calls_executed"], 0)

    def test_c3_dry_run_doc_openai_calls_zero(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["openai_calls_executed"], 0)
        self.assertEqual(d["api_spend_usd"], 0)


class Test15HiggsfieldCallsZero(unittest.TestCase):
    def test_dry_run_report_higgsfield_calls_zero(self):
        with urlopen_raises():
            report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["higgsfield_calls_executed"], 0)

    def test_c3_dry_run_doc_higgsfield_calls_zero(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["higgsfield_calls_executed"], 0)


class TestC3QaGatesNoHands(unittest.TestCase):
    def test_qa_gates_c3_no_hands_has_13_gates(self):
        self.assertEqual(len(runner.QA_GATES_C3_NO_HANDS), 13)

    def test_qa_gates_c3_no_hands_names(self):
        names = [g["name"] for g in runner.QA_GATES_C3_NO_HANDS]
        for expected in ("no_hands_visible", "no_person_visible",
                         "no_duplicate_ai_product_visible", "no_black_insert_or_black_liner",
                         "no_fake_handles_visible", "basket_perspective_compatible_with_product_45deg",
                         "product_inserted_from_real_product_v1", "product_lock_passed",
                         "food_extracted_only_inside_interior_mask", "food_count_exact",
                         "basket_clean_around_product", "no_text_or_watermark",
                         "manual_review_required"):
            self.assertIn(expected, names)

    def test_hand_related_gates_removed_for_c3(self):
        names = [g["name"] for g in runner.QA_GATES_C3_NO_HANDS]
        for removed in ("hands_interact_with_flat_tabs", "hands_positioned_near_real_handle_tabs",
                        "candidate_rejected_if_product_overlay_breaks_hands"):
            self.assertNotIn(removed, names)

    def test_general_qa_gates_unchanged_for_other_scenes(self):
        # QA_GATES (used by scenes/candidates outside the C3 no-hands variant)
        # must stay untouched -- still 15 gates, hand-related ones intact.
        self.assertEqual(len(runner.QA_GATES), 15)
        names = [g["name"] for g in runner.QA_GATES]
        self.assertIn("hands_positioned_near_real_handle_tabs", names)

    def test_c3_dry_run_doc_contains_qa_gates_c3_no_hands(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertIn("qa_gates_c3_no_hands", d)
        self.assertEqual(len(d["qa_gates_c3_no_hands"]), 13)

    def test_c3_dry_run_doc_lists_removed_gates(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertIn("removed_or_not_applicable_gates", d)
        for removed in ("hands_interact_with_flat_tabs", "hands_positioned_near_real_handle_tabs",
                        "candidate_rejected_if_product_overlay_breaks_hands", "front_hand_extraction"):
            self.assertIn(removed, d["removed_or_not_applicable_gates"])


class TestC3FilesExistAndConsistent(unittest.TestCase):
    def test_c3_dry_run_file_exists(self):
        self.assertTrue(C3_DRY_RUN_PATH.is_file())

    def test_c3_prompt_md_exists(self):
        self.assertTrue(C3_PROMPT_MD_PATH.is_file())

    def test_c3_dry_run_prompt_sha256_matches_live_contract(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["prompt_sha256"], contract.prompt_sha256)

    def test_c3_dry_run_max_calls_retries_hard_cap(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["max_calls_future_apply"], 1)
        self.assertEqual(d["retries"], 0)
        self.assertEqual(d["hard_cap_usd"], 0.50)

    def test_c3_dry_run_per_plate_transform_allowed_rigid_only(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertTrue(d["per_plate_transform_allowed"])
        self.assertEqual(d["allowed_transform_type"], "rigid_only")

    def test_c3_dry_run_composite_order_has_no_hands_layer(self):
        # "handle pixels" (the product's own real handles) and the "(no
        # hands, no person)" description both legitimately contain "hand" --
        # what must be absent is an actual hands/front-hand COMPOSITING STEP.
        d = load_json(C3_DRY_RUN_PATH)
        order_text = " ".join(d["composite_order"]).lower()
        self.assertNotIn("hands layer", order_text)
        self.assertNotIn("front_hand", order_text)
        self.assertNotIn("front-hand", order_text)
        self.assertNotIn("handle-grip alignment", order_text)
        self.assertIn("real-product-v1", " ".join(d["composite_order"]))

    def test_c3_dry_run_does_not_use_forbidden_appearance_refs(self):
        from api.media_pipeline.product_only_policy import FORBIDDEN_APPEARANCE_ASSET_IDS
        d = load_json(C3_DRY_RUN_PATH)
        for asset_id in FORBIDDEN_APPEARANCE_ASSET_IDS:
            self.assertNotIn(asset_id, json.dumps({k: v for k, v in d.items()
                                                   if k not in ("forbidden_appearance_asset_ids_not_used",)}))

    def test_hooks_abc_unchanged(self):
        text = load_text(CAMPAIGN_DIR / "video-scene-prompts-product-only.md")
        for hook in ("Аэрогрильщики, вы вообще знали про такую штуку?",
                    "Если у тебя есть аэрогриль — это обязано быть у тебя.",
                    "Недорогая вещь, которая помогает беречь аэрогриль за несколько тысяч."):
            self.assertIn(hook, text)


if __name__ == "__main__":
    unittest.main()
