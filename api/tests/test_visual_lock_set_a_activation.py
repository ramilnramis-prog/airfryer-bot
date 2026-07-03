"""Тесты активации Set A как единственного визуального набора кампании
coating-protect-2026-07 (решение владельца: APPROVE SET A).

Покрытие:
1. активен только Set A
2. owner_approved=true
3. Set B/C не входят в active appearance
4. три hooks используют Set A
5. mechanics reference не влияет на внешний вид рук
6. placement reference не передаётся scene-05
7. food-wings-01 не определяет scene-05
8. product canon всегда real-product-v1
9. следующая кампания не наследует Set A автоматически
10. генерация без отдельного разрешения владельца заблокирована
"""
import json
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline.reference_library import cli as rl_cli
from api.media_pipeline.reference_library.activation import (
    VisualSetNotApprovedError, require_owner_approval)

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"
ACTIVE_LOCK_PATH = CAMPAIGN_DIR / "campaign_visual_lock.json"
HISTORICAL_V1_PATH = CAMPAIGN_DIR / "campaign_visual_lock_v1.historical.json"
PROPOSED_V2_PATH = CAMPAIGN_DIR / "campaign_visual_lock_v2.proposed.json"
REAL_EXTERNAL_ROOT = Path("D:/OzonGrowthProject/content/assets")

SET_A_PERSON = "person-b-exhausted-01"
SET_B_PERSON = "person-pain-01"
SET_C_PERSON = "person-rinse-01"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class TestOnlySetAIsActive(unittest.TestCase):
    def test_active_lock_selected_set_is_a(self):
        lock = load_json(ACTIVE_LOCK_PATH)
        self.assertEqual(lock["selected_set"], "A")
        self.assertEqual(lock["visual_set_id"], "coating-protect-visual-set-01")
        self.assertEqual(lock["status"], "active")

    def test_active_appearance_anchor_is_set_a_person(self):
        lock = load_json(ACTIVE_LOCK_PATH)
        appearance = lock["appearance"]
        for field in ("primary_person_asset_id", "primary_hands_asset_id",
                     "primary_clothing_asset_id", "primary_kitchen_asset_id",
                     "primary_lighting_asset_id"):
            self.assertEqual(appearance[field], SET_A_PERSON, field)
        self.assertEqual(appearance["primary_airfryer_asset_id"], "real-airfryer-front-01")
        self.assertEqual(appearance["continuity_group_id"], "coating-protect-appearance-group-A")

    def test_historical_v1_file_still_exists_and_is_marked_superseded(self):
        self.assertTrue(HISTORICAL_V1_PATH.is_file())
        v1 = load_json(HISTORICAL_V1_PATH)
        self.assertIn("_superseded_by", v1)
        self.assertEqual(v1["status"], "historical_reference_pool_superseded")

    def test_proposed_v2_file_untouched_and_still_not_activated(self):
        v2 = load_json(PROPOSED_V2_PATH)
        self.assertFalse(v2["owner_approved"])
        self.assertEqual(v2["status"], "proposed_not_activated")


class TestOwnerApprovedTrue(unittest.TestCase):
    def test_active_lock_owner_approved_is_true(self):
        lock = load_json(ACTIVE_LOCK_PATH)
        self.assertTrue(lock["owner_approved"])

    def test_active_lock_has_approved_at_timestamp(self):
        lock = load_json(ACTIVE_LOCK_PATH)
        self.assertIn("approved_at", lock)
        self.assertTrue(lock["approved_at"])


class TestSetBAndSetCNotInActiveAppearance(unittest.TestCase):
    def test_set_b_and_set_c_anchors_are_not_any_active_primary_asset(self):
        lock = load_json(ACTIVE_LOCK_PATH)
        active_primaries = {v for k, v in lock["appearance"].items()
                           if k.startswith("primary_") and isinstance(v, str)}
        self.assertNotIn(SET_B_PERSON, active_primaries)
        self.assertNotIn(SET_C_PERSON, active_primaries)

    def test_set_b_and_set_c_kept_only_as_rejected_history(self):
        lock = load_json(ACTIVE_LOCK_PATH)
        rejected = lock["rejected_alternatives_for_history"]
        self.assertEqual(rejected["Set_B"]["anchor"], SET_B_PERSON)
        self.assertEqual(rejected["Set_C"]["anchor"], SET_C_PERSON)
        self.assertEqual(rejected["Set_B"]["status"], "rejected_alternative_kept_for_audit_history")
        self.assertEqual(rejected["Set_C"]["status"], "rejected_alternative_kept_for_audit_history")

    def test_supporting_views_empty_no_unproven_merge(self):
        lock = load_json(ACTIVE_LOCK_PATH)
        self.assertEqual(lock["supporting_views"], [])


class TestHooksUseSetA(unittest.TestCase):
    def test_hooks_share_visual_set_id_pointing_to_set_a_lock(self):
        lock = load_json(ACTIVE_LOCK_PATH)
        hooks = load_json(CAMPAIGN_DIR / "hooks.json")
        self.assertEqual({h["hook_code"] for h in hooks["hooks"]}, {"A", "B", "C"})
        self.assertTrue(lock["hooks"]["shared_visual_set_id"])
        self.assertEqual(lock["hooks"]["visual_set_id"], "coating-protect-visual-set-01")

    def test_resolve_campaign_confirms_same_set_for_all_hooks(self):
        if not REAL_EXTERNAL_ROOT.is_dir():
            self.skipTest("внешняя REFERENCE_LIBRARY_ROOT недоступна на этой машине")
        report = rl_cli.resolve_campaign(str(ACTIVE_LOCK_PATH), root=str(REAL_EXTERNAL_ROOT))
        self.assertEqual(report["visual_set_id"], "coating-protect-visual-set-01")
        summary = report["hooks_share_one_resolved_set"]
        self.assertEqual(set(summary["variants"]), {"A", "B", "C"})
        self.assertTrue(summary["same_resolved_set_confirmed"])
        self.assertEqual(summary["visual_set_id"], "coating-protect-visual-set-01")


class TestMechanicsReferenceDoesNotAffectHandAppearance(unittest.TestCase):
    def test_grip_motion_flagged_hand_pose_only(self):
        lock = load_json(ACTIVE_LOCK_PATH)
        grip = next(m for m in lock["mechanics_only"] if m["asset_id"] == "real-grip-motion-01")
        self.assertEqual(grip["influence_scope"], "hand_pose_only")
        self.assertTrue(grip["must_not_influence_hand_appearance"])
        self.assertGreater(len(grip["must_not_influence"]), 0)

    def test_grip_motion_is_not_the_primary_hands_asset(self):
        lock = load_json(ACTIVE_LOCK_PATH)
        self.assertNotEqual(lock["appearance"]["primary_hands_asset_id"], "real-grip-motion-01")


class TestPlacementReferenceNotPassedToScene05(unittest.TestCase):
    def test_placement_reference_flagged_do_not_pass_to_scene_05(self):
        lock = load_json(ACTIVE_LOCK_PATH)
        placement = next(m for m in lock["mechanics_only"] if m["asset_id"] == "v2-form-in-basket-01")
        self.assertTrue(placement["do_not_pass_to_scene_05_generation"])
        self.assertTrue(placement["must_not_influence_airfryer_appearance"])
        self.assertTrue(placement["must_not_influence_product_geometry"])

    def test_dry_run_refs_for_scene_05_exclude_placement_reference(self):
        dry_run = load_json(CAMPAIGN_DIR / "scene-05-generation-dry-run.json")
        all_refs = (dry_run["refs_passed_in_order"]["hands_layer_call_1"] +
                   dry_run["refs_passed_in_order"]["food_layer_call_2"])
        self.assertNotIn("v2-form-in-basket-01", all_refs)
        excluded_ids = {e["asset_id"] for e in dry_run["excluded_from_refs"]}
        self.assertIn("v2-form-in-basket-01", excluded_ids)


class TestFoodWingsDoesNotDefineScene05(unittest.TestCase):
    def test_food_wings_flagged_do_not_pass_to_scene_05(self):
        lock = load_json(ACTIVE_LOCK_PATH)
        food = next(s for s in lock["style_only"] if s["asset_id"] == "food-wings-01")
        self.assertTrue(food["do_not_pass_to_scene_05_generation"])
        self.assertTrue(food["must_not_define_recipe"])
        self.assertTrue(food["must_not_define_food_count"])

    def test_scene_05_food_spec_comes_only_from_scene_spec(self):
        lock = load_json(ACTIVE_LOCK_PATH)
        scene05_food = lock["scene_specific"]["food"]["scene-05"]
        self.assertEqual(scene05_food["item"], "chicken thigh")
        self.assertEqual(scene05_food["count"], 3)

    def test_dry_run_food_layer_refs_are_empty_not_food_wings(self):
        dry_run = load_json(CAMPAIGN_DIR / "scene-05-generation-dry-run.json")
        self.assertEqual(dry_run["refs_passed_in_order"]["food_layer_call_2"], [])


class TestProductCanonAlwaysRealProductV1(unittest.TestCase):
    def test_active_lock_product_canon(self):
        lock = load_json(ACTIVE_LOCK_PATH)
        self.assertEqual(lock["product_canon"], "real-product-v1")
        self.assertEqual(lock["product_canon_resolution"], "repository_only")

    def test_scene_05_plan_product_canon(self):
        plan = load_json(CAMPAIGN_DIR / "scene-05-locked-assets-plan.json")
        self.assertEqual(plan["product_canon"]["value"], "real-product-v1")
        self.assertEqual(plan["product_canon"]["resolution"], "repository_only")


class TestNextCampaignDoesNotInheritSetA(unittest.TestCase):
    def test_cross_campaign_rule_forbids_automatic_inheritance(self):
        lock = load_json(ACTIVE_LOCK_PATH)
        rule = lock["cross_campaign_rule"].lower()
        self.assertIn("не переносится автоматически", rule)
        self.assertIn("выбирает свой набор", rule)

    def test_visual_set_id_is_campaign_specific_not_generic(self):
        lock = load_json(ACTIVE_LOCK_PATH)
        self.assertIn("coating-protect", lock["visual_set_id"])


class TestGenerationBlockedWithoutSeparateApproval(unittest.TestCase):
    def test_require_owner_approval_passes_for_active_visual_lock(self):
        lock = load_json(ACTIVE_LOCK_PATH)
        require_owner_approval(lock)  # visual lock одобрен — не должно бросать

    def test_generation_dry_run_still_shows_zero_executed_calls(self):
        dry_run = load_json(CAMPAIGN_DIR / "scene-05-generation-dry-run.json")
        self.assertEqual(dry_run["execution_summary"]["openai_images_api_calls_executed"], 0)
        self.assertEqual(dry_run["execution_summary"]["higgsfield_api_calls_executed"], 0)
        self.assertEqual(dry_run["execution_summary"]["api_spend_usd_executed"], 0)

    def test_hard_cap_is_at_most_one_dollar(self):
        dry_run = load_json(CAMPAIGN_DIR / "scene-05-generation-dry-run.json")
        self.assertLessEqual(dry_run["hard_cap"]["max_spend_usd_this_stage"], 1.00)
        self.assertEqual(dry_run["hard_cap"]["max_api_calls_executed_this_stage"], 0)

    def test_visual_lock_approval_is_a_separate_gate_from_spend_approval(self):
        # owner_approved у visual lock НЕ означает автоматическое разрешение
        # тратить деньги — это отдельный шаг перед --apply.
        dry_run = load_json(CAMPAIGN_DIR / "scene-05-generation-dry-run.json")
        self.assertIn("отдельное подтверждение", dry_run["next_step_requires_owner_approval"])


class TestNoPaidApiCalls(unittest.TestCase):
    def test_loading_active_lock_and_dry_run_makes_no_network_call(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network call!")):
            load_json(ACTIVE_LOCK_PATH)
            load_json(CAMPAIGN_DIR / "scene-05-locked-assets-plan.json")
            load_json(CAMPAIGN_DIR / "scene-05-generation-dry-run.json")

    def test_no_paid_api_tokens_in_new_active_files(self):
        # "higgsfield" сюда намеренно НЕ входит: dry-run JSON легитимно
        # упоминает его в тексте "Higgsfield — BLOCKED на этом этапе" —
        # это план/статус, а не endpoint/ключ/вызов.
        tokens = ("api.openai.com", "openai_api_key", "http://", "https://")
        paths = [ACTIVE_LOCK_PATH,
                CAMPAIGN_DIR / "scene-05-locked-assets-plan.json",
                CAMPAIGN_DIR / "scene-05-generation-dry-run.json"]
        for path in paths:
            src = path.read_text(encoding="utf-8").lower()
            for token in tokens:
                self.assertNotIn(token, src, f"{path} содержит {token}")


if __name__ == "__main__":
    unittest.main()
