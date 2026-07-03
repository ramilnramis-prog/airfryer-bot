"""Тесты нормализации campaign visual lock в один цельный набор (v2 proposed).

Проблема, которую закрывают эти тесты: v1 campaign_visual_lock.json держал
НЕСКОЛЬКО person/hands/kitchen/clothing/lighting references одновременно
под одной ролью — это reference pool, а не единый visual set. v2
(campaign_visual_lock_v2.proposed.json) разделяет appearance/mechanics_only/
style_only и допускает РОВНО один primary asset на роль в `appearance`.

Покрытие:
1. в appearance допускается максимум один primary asset на роль
2. supporting assets обязаны иметь тот же continuity_group_id
3. mechanics-only grip не меняет внешность рук
4. placement-only reference не меняет аэрогриль
5. food-style reference не определяет рецепт или количество
6. hooks A/B/C используют один visual_set_id
7. конфликтующие person assets блокируют activation
8. owner_approved=false запрещает платную генерацию
9. никакие API не вызываются
"""
import json
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline.reference_library.activation import (
    VisualSetNotApprovedError, require_owner_approval)

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"
V1_LOCK_PATH = CAMPAIGN_DIR / "campaign_visual_lock.json"
V2_LOCK_PATH = CAMPAIGN_DIR / "campaign_visual_lock_v2.proposed.json"
AUDIT_PATH = (CAMPAIGN_DIR / "generated" / "campaign-visual-lock-review" /
             "visual-lock-audit.json")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class TestAtMostOnePrimaryPerRole(unittest.TestCase):
    def test_appearance_block_has_single_string_per_primary_field(self):
        v2 = load_json(V2_LOCK_PATH)
        appearance = v2["appearance"]
        primary_fields = [k for k in appearance if k.startswith("primary_")]
        self.assertGreater(len(primary_fields), 0)
        for field in primary_fields:
            self.assertIsInstance(appearance[field], str,
                                 f"{field} должен быть ровно ОДНИМ asset_id, не списком")

    def test_alternative_sets_are_also_single_primary_each(self):
        v2 = load_json(V2_LOCK_PATH)
        for alt in v2["alternative_candidate_sets"]:
            for field in alt:
                if field.startswith("primary_"):
                    self.assertIsInstance(alt[field], str, f"{alt['label']}.{field}")

    def test_v1_lock_had_multiple_assets_per_role_this_is_the_problem_being_fixed(self):
        v1 = load_json(V1_LOCK_PATH)
        roles = {}
        for e in v1["locked_elements"]:
            roles.setdefault(e["role"], []).append(e["asset_id"])
        multi_role_count = sum(1 for ids in roles.values() if len(ids) > 1)
        self.assertGreater(multi_role_count, 0,
                          "ожидалось, что v1 содержит reference pool (>1 asset на роль) — "
                          "именно это v2 нормализует в единственный primary")


class TestSupportingViewsShareContinuityGroup(unittest.TestCase):
    def test_supporting_views_all_match_appearance_continuity_group(self):
        v2 = load_json(V2_LOCK_PATH)
        group_id = v2["appearance"]["continuity_group_id"]
        for view in v2["supporting_views"]:
            self.assertEqual(view.get("continuity_group_id"), group_id)

    def test_supporting_views_is_empty_because_nothing_is_proven_identical(self):
        v2 = load_json(V2_LOCK_PATH)
        # По условию задачи: ни один кандидат не подтверждён как тот же
        # человек/руки/одежда/кухня/свет — поэтому supporting_views пуст,
        # а не заполнен по сходству стиля.
        self.assertEqual(v2["supporting_views"], [])

    def test_alternative_sets_have_distinct_continuity_group_ids(self):
        v2 = load_json(V2_LOCK_PATH)
        ids = [v2["appearance"]["continuity_group_id"]] + \
            [alt["continuity_group_id"] for alt in v2["alternative_candidate_sets"]]
        self.assertEqual(len(ids), len(set(ids)), "continuity_group_id должны быть уникальны между наборами")


class TestMechanicsOnlyGripDoesNotChangeHandAppearance(unittest.TestCase):
    def test_grip_motion_reference_flagged_hand_pose_only(self):
        v2 = load_json(V2_LOCK_PATH)
        grip = next(m for m in v2["mechanics_only"] if m["asset_id"] == "real-grip-motion-01")
        self.assertEqual(grip["influence_scope"], "hand_pose_only")
        self.assertTrue(grip["must_not_influence_hand_appearance"])

    def test_grip_motion_reference_is_not_a_primary_hands_asset(self):
        v2 = load_json(V2_LOCK_PATH)
        primaries = {v2["appearance"]["primary_hands_asset_id"]}
        for alt in v2["alternative_candidate_sets"]:
            primaries.add(alt["primary_hands_asset_id"])
        self.assertNotIn("real-grip-motion-01", primaries)


class TestPlacementOnlyDoesNotChangeAirfryer(unittest.TestCase):
    def test_placement_reference_flagged_placement_only(self):
        v2 = load_json(V2_LOCK_PATH)
        placement = next(m for m in v2["mechanics_only"] if m["asset_id"] == "v2-form-in-basket-01")
        self.assertEqual(placement["influence_scope"], "placement_only")
        self.assertTrue(placement["must_not_influence_airfryer_appearance"])
        self.assertTrue(placement["must_not_influence_product_geometry"])

    def test_primary_airfryer_is_always_the_real_asset(self):
        v2 = load_json(V2_LOCK_PATH)
        self.assertEqual(v2["appearance"]["primary_airfryer_asset_id"], "real-airfryer-front-01")
        for alt in v2["alternative_candidate_sets"]:
            self.assertEqual(alt["primary_airfryer_asset_id"], "real-airfryer-front-01")


class TestFoodStyleDoesNotDefineRecipeOrCount(unittest.TestCase):
    def test_food_style_reference_flagged(self):
        v2 = load_json(V2_LOCK_PATH)
        food = next(s for s in v2["style_only"] if s["asset_id"] == "food-wings-01")
        self.assertEqual(food["influence_scope"], "food_style_only")
        self.assertTrue(food["must_not_define_recipe"])
        self.assertTrue(food["must_not_define_food_count"])

    def test_scene_specific_food_is_not_global_canon(self):
        v2 = load_json(V2_LOCK_PATH)
        self.assertFalse(v2["scene_specific"]["food"]["is_global_visual_lock"])
        self.assertEqual(v2["scene_specific"]["food"]["scene-05"]["count"], 3)


class TestHooksShareOneVisualSetId(unittest.TestCase):
    def test_hooks_json_variants_match_v2_hooks_variants(self):
        hooks = load_json(CAMPAIGN_DIR / "hooks.json")
        v2 = load_json(V2_LOCK_PATH)
        codes = {h["hook_code"] for h in hooks["hooks"]}
        self.assertEqual(codes, set(v2["hooks"]["variants"]))

    def test_visual_set_id_is_a_single_string_shared_by_all_hooks(self):
        v2 = load_json(V2_LOCK_PATH)
        self.assertIsInstance(v2["visual_set_id"], str)
        self.assertEqual(v2["hooks"]["visual_set_id"], v2["visual_set_id"])
        self.assertTrue(v2["hooks"]["shared_visual_set_id"])


class TestConflictingPersonAssetsBlockActivation(unittest.TestCase):
    def test_excluded_candidates_are_not_empty(self):
        v2 = load_json(V2_LOCK_PATH)
        self.assertGreater(len(v2["excluded_candidates"]), 0)

    def test_owner_approved_is_false_while_conflicts_and_alternatives_exist(self):
        v2 = load_json(V2_LOCK_PATH)
        self.assertFalse(v2["owner_approved"])
        self.assertGreater(len(v2["alternative_candidate_sets"]), 0)

    def test_audit_documents_person_identity_not_confirmed(self):
        if not AUDIT_PATH.is_file():
            self.skipTest("visual-lock-audit.json не создан локально в этом окружении")
        audit = load_json(AUDIT_PATH)
        self.assertIn("НЕ подтверждено", audit["person_candidates_identity_check"]["answer"])
        self.assertGreater(len(audit["conflicts_summary"]), 0)


class TestOwnerApprovedFalseBlocksGeneration(unittest.TestCase):
    def test_require_owner_approval_raises_for_v2_proposed_lock(self):
        v2 = load_json(V2_LOCK_PATH)
        with self.assertRaises(VisualSetNotApprovedError) as ctx:
            require_owner_approval(v2)
        self.assertEqual(ctx.exception.code, "VISUAL_SET_NOT_APPROVED")

    def test_require_owner_approval_passes_once_flag_flipped(self):
        v2 = dict(load_json(V2_LOCK_PATH), owner_approved=True)
        require_owner_approval(v2)  # не должно бросать

    def test_require_owner_approval_defaults_to_blocking_when_key_missing(self):
        with self.assertRaises(VisualSetNotApprovedError):
            require_owner_approval({"visual_set_id": "x"})


class TestNoPaidApiCalls(unittest.TestCase):
    def test_loading_v2_lock_and_audit_makes_no_network_call(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network call!")):
            load_json(V2_LOCK_PATH)
            if AUDIT_PATH.is_file():
                load_json(AUDIT_PATH)

    def test_no_paid_api_surface_in_activation_module(self):
        src = (REPO_ROOT / "api" / "media_pipeline" / "reference_library" /
              "activation.py").read_text(encoding="utf-8").lower()
        for token in ("urllib", "api.openai.com", "openai_api_key",
                     "higgsfield", "requests.", "http://", "https://"):
            self.assertNotIn(token, src, token)

    def test_no_paid_api_tokens_in_v2_lock_json(self):
        src = V2_LOCK_PATH.read_text(encoding="utf-8").lower()
        for token in ("api.openai.com", "openai_api_key", "higgsfield",
                     "http://", "https://"):
            self.assertNotIn(token, src, token)


if __name__ == "__main__":
    unittest.main()
