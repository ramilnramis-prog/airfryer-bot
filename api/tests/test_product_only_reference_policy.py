"""Тесты "PRODUCT ONLY MEANS PRODUCT ONLY" policy -- owner decision после
отклонения scene-05 C1/C2/C3 (все три local deterministic compositing
попытки продолжали давать швы/артефакты/misalignment независимо от
transform-точности). В проекте разрешён РОВНО ОДИН постоянный визуальный
reference -- real-product-v1. Ничего сгенерированного (кухня/аэрогриль/
корзина/еда/руки/человек/одежда/свет/generated plates/предыдущие candidate
composites) не может стать reference asset, visual lock или обязательным
image ref -- ни сейчас, ни в будущих видео. C1/C2/C3 outputs остаются
diagnostic/rejected only.

Покрытие (9 пунктов, запрошенных явно):
1. global mandatory reference list contains only real-product-v1
2. no generated C1/C2/C3 output is allowed as reference
3. kitchen/airfryer/basket/food/hands/person/clothing/lighting are not image-locked
4. scene-05 product-reference-only dry-run has reference_images containing only real-product-v1
5. scene-05 product-reference-only dry-run has no references to C1/C2/C3 PNGs
6. prompt does not reuse generated air fryer/food/kitchen as reference
7. prompt still describes scene context textually
8. OpenAI calls = 0
9. Higgsfield calls = 0
"""
import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"

POLICY_PATH = CAMPAIGN_DIR / "campaign_visual_policy.json"
STATUS_PATH = CAMPAIGN_DIR / "scene-05-generation-attempts-status.json"
NEW_PLAN_PATH = CAMPAIGN_DIR / "scene-05-product-reference-only-dry-run.json"

# Any filename produced by the rejected C1/C2/C3 local-compositing experiments.
C1_C2_C3_PNG_PATTERN = re.compile(r"scene-05-c[123][-.]")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class Test1GlobalMandatoryReferenceIsOnlyRealProductV1(unittest.TestCase):
    def test_mandatory_product_reference_field(self):
        policy = load_json(POLICY_PATH)
        self.assertEqual(policy["mandatory_product_reference"], "real-product-v1")

    def test_global_visual_reference_product_canon(self):
        policy = load_json(POLICY_PATH)
        self.assertEqual(policy["global_visual_reference"]["product_canon"], "real-product-v1")

    def test_forbidden_categories_do_not_include_the_product_itself(self):
        policy = load_json(POLICY_PATH)
        forbidden = policy["forbidden_global_reference_categories"]
        self.assertNotIn("product", forbidden)
        self.assertNotIn("real-product-v1", forbidden)


class Test2NoGeneratedC1C2C3OutputAllowedAsReference(unittest.TestCase):
    def test_forbidden_categories_include_generated_plates_and_previous_composites(self):
        policy = load_json(POLICY_PATH)
        forbidden = policy["forbidden_global_reference_categories"]
        self.assertIn("generated_plates", forbidden)
        self.assertIn("previous_candidate_composites", forbidden)

    def test_diagnostic_only_rule_present_in_policy(self):
        policy = load_json(POLICY_PATH)
        rule = policy["diagnostic_only_generated_outputs_rule"]
        self.assertIn("C1/C2/C3", rule)
        self.assertIn("diagnostic", rule.lower())

    def test_status_doc_marks_all_three_attempts_rejected(self):
        status = load_json(STATUS_PATH)
        self.assertEqual(status["attempts"]["C1"]["status"], "rejected")
        self.assertEqual(status["attempts"]["C2"]["status"], "rejected")
        self.assertEqual(status["attempts"]["C3"]["status"], "rejected_for_production_use")

    def test_status_doc_explicitly_forbids_c3_output_as_reference(self):
        status = load_json(STATUS_PATH)
        important = status["attempts"]["C3"]["important"]
        self.assertIn("NOT a reference asset", important)
        self.assertIn("NOT to be reused", important)


class Test3CategoriesNotImageLocked(unittest.TestCase):
    def test_not_image_locked_covers_all_required_categories(self):
        policy = load_json(POLICY_PATH)
        not_locked = policy["not_image_locked"]
        for category in ("kitchen", "airfryer", "basket", "food", "hands", "person",
                         "clothing", "lighting"):
            self.assertIn(category, not_locked)

    def test_forbidden_global_reference_categories_covers_same_set(self):
        policy = load_json(POLICY_PATH)
        forbidden = policy["forbidden_global_reference_categories"]
        for category in ("kitchen", "airfryer", "basket", "food", "hands", "person",
                         "clothing", "lighting"):
            self.assertIn(category, forbidden)

    def test_new_plan_declares_same_categories_not_image_locked(self):
        plan = load_json(NEW_PLAN_PATH)
        for category in ("kitchen", "airfryer", "basket", "food", "hands", "person",
                         "clothing", "lighting"):
            self.assertIn(category, plan["not_image_locked"])


class Test4NewPlanReferenceImagesOnlyRealProductV1(unittest.TestCase):
    def test_reference_images_is_exactly_real_product_v1(self):
        plan = load_json(NEW_PLAN_PATH)
        self.assertEqual(plan["reference_images"], ["real-product-v1"])

    def test_mandatory_product_reference_matches(self):
        plan = load_json(NEW_PLAN_PATH)
        self.assertEqual(plan["mandatory_product_reference"], "real-product-v1")


class Test5NewPlanHasNoC1C2C3PngReferences(unittest.TestCase):
    def test_reference_images_field_has_no_generated_png(self):
        plan = load_json(NEW_PLAN_PATH)
        for ref in plan["reference_images"]:
            self.assertFalse(C1_C2_C3_PNG_PATTERN.search(ref), f"forbidden png reference: {ref}")

    def test_model_prompt_draft_has_no_c1_c2_c3_png_path(self):
        plan = load_json(NEW_PLAN_PATH)
        prompt = plan["model_prompt_draft"]
        self.assertIsNone(C1_C2_C3_PNG_PATTERN.search(prompt))
        for token in (".png", "generated/product-only-scene"):
            self.assertNotIn(token, prompt)

    def test_forbidden_reference_sources_lists_c1_c2_c3_outputs_as_forbidden_not_used(self):
        plan = load_json(NEW_PLAN_PATH)
        forbidden_sources = " ".join(plan["forbidden_reference_sources"])
        self.assertTrue(C1_C2_C3_PNG_PATTERN.search(forbidden_sources),
                        "forbidden_reference_sources should explicitly name C1/C2/C3 outputs as NOT usable")


class Test6PromptDoesNotReuseGeneratedAssetsAsReference(unittest.TestCase):
    def test_prompt_direction_notes_generated_plates_not_reused(self):
        plan = load_json(NEW_PLAN_PATH)
        direction = plan["scene_prompt_direction"]
        self.assertIn("not image-locked", direction["basket"])
        self.assertIn("not image-locked", direction["kitchen"])

    def test_supersede_reason_explains_why_local_compositing_stopped(self):
        plan = load_json(NEW_PLAN_PATH)
        self.assertIn("PRODUCT ONLY MEANS PRODUCT ONLY", plan["supersede_reason"])


class Test7PromptStillDescribesSceneContextTextually(unittest.TestCase):
    def test_prompt_describes_kitchen_basket_food(self):
        plan = load_json(NEW_PLAN_PATH)
        prompt = plan["model_prompt_draft"]
        for token in ("kitchen", "basket", "chicken thighs", "potato wedges",
                     "flat corner handle tabs", "No hands"):
            self.assertIn(token, prompt)

    def test_prompt_forbids_redesigned_and_fake_handle_variants(self):
        plan = load_json(NEW_PLAN_PATH)
        prompt = plan["model_prompt_draft"]
        for token in ("Do not redesign the handles", "Do not draw loop handles",
                     "Do not draw vertical oval holes",
                     "Do not draw a duplicate tray or a second product"):
            self.assertIn(token, prompt)


class Test8OpenAICallsZero(unittest.TestCase):
    def test_new_plan_openai_calls_zero(self):
        plan = load_json(NEW_PLAN_PATH)
        self.assertEqual(plan["openai_calls_planned"], 0)
        self.assertEqual(plan["openai_calls_executed"], 0)
        self.assertEqual(plan["api_spend_usd"], 0)

    def test_status_doc_openai_calls_zero(self):
        status = load_json(STATUS_PATH)
        self.assertEqual(status["openai_calls_executed_by_this_status_update"], 0)


class Test9HiggsfieldCallsZero(unittest.TestCase):
    def test_new_plan_higgsfield_calls_zero(self):
        plan = load_json(NEW_PLAN_PATH)
        self.assertEqual(plan["higgsfield_calls_planned"], 0)
        self.assertEqual(plan["higgsfield_calls_executed"], 0)

    def test_status_doc_higgsfield_calls_zero(self):
        status = load_json(STATUS_PATH)
        self.assertEqual(status["higgsfield_calls_executed_by_this_status_update"], 0)


class TestFilesExistAndConsistent(unittest.TestCase):
    def test_all_three_files_exist(self):
        self.assertTrue(POLICY_PATH.is_file())
        self.assertTrue(STATUS_PATH.is_file())
        self.assertTrue(NEW_PLAN_PATH.is_file())

    def test_new_plan_status_is_dry_run_only(self):
        plan = load_json(NEW_PLAN_PATH)
        self.assertEqual(plan["status"], "dry_run_only")

    def test_new_plan_retries_and_hard_cap(self):
        plan = load_json(NEW_PLAN_PATH)
        self.assertEqual(plan["retries"], 0)
        self.assertEqual(plan["hard_cap_usd"], 0.50)
        self.assertEqual(plan["max_calls_future_apply"], 1)

    def test_new_plan_does_not_claim_runner_code_was_changed(self):
        plan = load_json(NEW_PLAN_PATH)
        self.assertIn("plan_only", plan["implementation_status"])

    def test_conclusion_no_hands_still_kept(self):
        status = load_json(STATUS_PATH)
        self.assertTrue(status["conclusions_kept"]["no_hands_is_still_the_right_creative_direction"])


if __name__ == "__main__":
    unittest.main()
