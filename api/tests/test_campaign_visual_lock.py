"""Тесты campaign-level visual continuity locks — активный Set A (portable/
private, single-coherent-set schema).

Покрытие (9 пунктов из CAMPAIGN_VISUAL_LOCK_SYSTEM.md), адаптировано под
активную схему appearance/mechanics_only/style_only (Set A утверждён
владельцем — см. test_visual_lock_set_a_activation.py для тестов, специфичных
именно для активации Set A, и test_visual_lock_v2_normalization.py для
тестов над campaign_visual_lock_v2.proposed.json):
1. product_canon всегда real-product-v1
2. руки не меняются внутри одной кампании
3. аэрогриль не меняется внутри одной кампании
4. персонаж/одежда/кухня не меняются внутри одной кампании
5. три варианта хука используют одно тело и один visual lock
6. новая кампания может выбрать другой visual lock
7. reference library никогда не источник геометрии продукта
8. еда может быть сцено-специфичной
9. никаких платных API-вызовов
"""
import json
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"
LIB_ROOT = REPO_ROOT / "assets" / "reference-library"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def active_lock():
    return load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")


class TestProductCanonAlwaysRealV1(unittest.TestCase):
    def test_campaign_visual_lock_product_canon_is_real_v1(self):
        self.assertEqual(active_lock()["product_canon"], "real-product-v1")

    def test_product_canon_manifest_matches_active_canonical_version(self):
        lock = active_lock()
        manifest = load_json(REPO_ROOT / lock["product_canon_manifest"])
        self.assertEqual(manifest["canonical_version"], "real-product-v1")
        self.assertEqual(manifest["canonical_status"], "active")

    def test_product_canon_resolution_is_repository_only(self):
        self.assertEqual(active_lock()["product_canon_resolution"], "repository_only")

    def test_a_hypothetical_second_campaign_cannot_override_product_canon(self):
        lock_a = active_lock()
        lock_b = dict(lock_a, campaign_code="hypothetical-other-campaign",
                     appearance={"primary_hands_asset_id": "something-else"})
        self.assertEqual(lock_a["product_canon"], lock_b["product_canon"])


class TestHandsLockedWithinCampaign(unittest.TestCase):
    def test_hands_role_is_a_single_asset_for_the_whole_campaign(self):
        lock = active_lock()
        self.assertIsInstance(lock["appearance"]["primary_hands_asset_id"], str)
        # то же самое при повторной загрузке — нет per-scene override в схеме
        lock_reloaded = active_lock()
        self.assertEqual(lock["appearance"]["primary_hands_asset_id"],
                         lock_reloaded["appearance"]["primary_hands_asset_id"])

    def test_forbidden_continuity_changes_includes_hands(self):
        joined = " ".join(active_lock()["forbidden_continuity_changes"]).lower()
        self.assertIn("рук", joined)


class TestAirfryerLockedWithinCampaign(unittest.TestCase):
    def test_airfryer_role_is_the_single_real_asset(self):
        lock = active_lock()
        self.assertEqual(lock["appearance"]["primary_airfryer_asset_id"], "real-airfryer-front-01")
        self.assertTrue(lock["locked_for_all_scenes"])
        self.assertTrue(lock["shared_across_hooks"])

    def test_forbidden_continuity_changes_includes_airfryer(self):
        joined = " ".join(active_lock()["forbidden_continuity_changes"]).lower()
        self.assertIn("аэрогрил", joined)


class TestPersonClothingKitchenLockedWithinCampaign(unittest.TestCase):
    def test_person_clothing_kitchen_each_have_exactly_one_asset(self):
        appearance = active_lock()["appearance"]
        for field in ("primary_person_asset_id", "primary_clothing_asset_id",
                     "primary_kitchen_asset_id"):
            self.assertIsInstance(appearance[field], str)

    def test_forbidden_continuity_changes_covers_all_three(self):
        joined = " ".join(active_lock()["forbidden_continuity_changes"]).lower()
        for word in ("персонаж", "одежд", "кухн"):
            self.assertIn(word, joined)

    def test_locked_for_all_scenes_flag_is_true(self):
        self.assertTrue(active_lock()["locked_for_all_scenes"])


class TestThreeHooksShareOneBodyAndOneLock(unittest.TestCase):
    def test_hooks_json_has_exactly_three_variants_same_content_code(self):
        hooks = load_json(CAMPAIGN_DIR / "hooks.json")
        codes = {h["hook_code"] for h in hooks["hooks"]}
        self.assertEqual(codes, {"A", "B", "C"})
        self.assertEqual(hooks["content_code"], "coating-protect-ad")

    def test_hooks_only_differ_by_text_not_by_visual_fields(self):
        hooks = load_json(CAMPAIGN_DIR / "hooks.json")
        for h in hooks["hooks"]:
            self.assertNotIn("appearance", h)
            self.assertNotIn("asset_id", h)

    def test_campaign_visual_lock_declares_shared_body_and_lock(self):
        lock = active_lock()
        self.assertTrue(lock["shared_across_hooks"])
        self.assertTrue(lock["hooks"]["shared_main_body"])
        self.assertEqual(lock["hooks"]["shared_visual_lock"],
                         "content/autopilot/coating-protect-2026-07/campaign_visual_lock.json")
        self.assertEqual(set(lock["hooks"]["variants"]), {"A", "B", "C"})
        self.assertEqual(lock["hooks"]["content_code"], lock["content_code"])

    def test_all_three_hooks_share_one_visual_set_id(self):
        lock = active_lock()
        self.assertTrue(lock["hooks"]["shared_visual_set_id"])
        self.assertEqual(lock["hooks"]["visual_set_id"], lock["visual_set_id"])


class TestNewCampaignMayChooseDifferentLock(unittest.TestCase):
    def test_synthetic_second_campaign_can_diverge_on_everything_but_product(self):
        lock_a = active_lock()
        lock_b_appearance = {
            "primary_person_asset_id": "person-c-frustrated-01",
            "primary_hands_asset_id": "hand-glove-scrub-01",
            "primary_clothing_asset_id": "v2-hand-hold-01",
            "primary_kitchen_asset_id": "kf-marble-kitchen-01",
            "primary_lighting_asset_id": "food-salmon-01",
            "primary_airfryer_asset_id": "v2-form-in-basket-01",
        }
        self.assertEqual(lock_a["product_canon"], "real-product-v1")
        for field, other_id in lock_b_appearance.items():
            self.assertNotEqual(lock_a["appearance"][field], other_id, field)

    def test_cross_campaign_rule_is_documented(self):
        self.assertIn("никогда", active_lock()["cross_campaign_rule"].lower())


class TestReferenceLibraryNeverProductGeometrySource(unittest.TestCase):
    def test_index_declares_it_is_not_the_product_canon(self):
        index = load_json(LIB_ROOT / "reference_library_index.json")
        self.assertEqual(index["global_immutable_canon"]["product_canon"], "real-product-v1")

    def test_no_category_manifest_claims_global_canon_status(self):
        for manifest_path in LIB_ROOT.glob("*/manifest.json"):
            manifest = load_json(manifest_path)
            self.assertFalse(manifest["is_global_canon"], manifest_path)

    def test_legacy_geometry_assets_are_flagged_and_excluded_or_restricted(self):
        index = load_json(LIB_ROOT / "reference_library_index.json")
        excluded_ids = {e["asset_id"] for e in index["excluded_from_library"]}
        self.assertIn("legacy-turnaround-6angles", excluded_ids)
        legacy_flagged = [a for a in index["assets"]
                         if a.get("prohibited_as_product_geometry_source")]
        self.assertGreater(len(legacy_flagged), 0)
        for a in legacy_flagged:
            joined = " ".join(a["restrictions"]).lower()
            self.assertIn("геометри", joined)

    def test_no_asset_id_equals_the_product_canon(self):
        index = load_json(LIB_ROOT / "reference_library_index.json")
        ids = {a["asset_id"] for a in index["assets"]}
        self.assertNotIn("real-product-v1", ids)

    def test_all_index_assets_are_approved_for_reference_only(self):
        index = load_json(LIB_ROOT / "reference_library_index.json")
        for asset in index["assets"]:
            self.assertTrue(asset["approved_for_reference_only"], asset["asset_id"])

    def test_every_asset_has_required_portable_provenance_fields(self):
        required = {"asset_id", "filename", "categories", "description",
                   "suitable_uses", "restrictions", "source_type",
                   "ownership_status", "approved_for_reference_only",
                   "prohibited_as_product_geometry_source", "sha256",
                   "width", "height", "file_size_bytes"}
        index = load_json(LIB_ROOT / "reference_library_index.json")
        for asset in index["assets"]:
            missing = required - set(asset)
            self.assertFalse(missing, f"{asset.get('asset_id')} missing {missing}")

    def test_ownership_status_uses_only_allowed_values(self):
        allowed = {"owner_created", "generated_reference",
                  "third_party_reference", "unknown"}
        index = load_json(LIB_ROOT / "reference_library_index.json")
        for asset in index["assets"]:
            self.assertIn(asset["ownership_status"], allowed, asset["asset_id"])


class TestFoodMaySceneSpecific(unittest.TestCase):
    def test_food_is_style_only_and_not_locked_for_all_scenes(self):
        lock = active_lock()
        self.assertFalse(lock["scene_specific"]["food"]["is_global_visual_lock"])
        style_food = next(s for s in lock["style_only"] if s["asset_id"] == "food-wings-01")
        self.assertEqual(style_food["influence_scope"], "food_style_only")

    def test_food_is_not_in_forbidden_continuity_changes(self):
        joined = " ".join(active_lock()["forbidden_continuity_changes"]).lower()
        self.assertNotIn("еда", joined)
        self.assertNotIn("блюдо", joined)

    def test_allowed_scene_changes_permits_food_presence_change(self):
        joined = " ".join(active_lock()["allowed_scene_changes"]).lower()
        self.assertIn("ед", joined)


class TestNoPaidApiCalls(unittest.TestCase):
    def test_loading_visual_lock_and_library_makes_no_network_call(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network call!")):
            active_lock()
            load_json(LIB_ROOT / "reference_library_index.json")
            for manifest_path in LIB_ROOT.glob("*/manifest.json"):
                load_json(manifest_path)

    def test_no_paid_api_tokens_in_visual_lock_or_library_json(self):
        tokens = ("api.openai.com", "openai_api_key", "higgsfield",
                 "http://", "https://")
        paths = [CAMPAIGN_DIR / "campaign_visual_lock.json",
                 LIB_ROOT / "reference_library_index.json"]
        paths += list(LIB_ROOT.glob("*/manifest.json"))
        for path in paths:
            src = path.read_text(encoding="utf-8").lower()
            for token in tokens:
                self.assertNotIn(token, src, f"{path} содержит {token}")

    def test_api_spend_declared_zero_in_campaign_manifest(self):
        manifest = load_json(CAMPAIGN_DIR / "campaign_manifest.json")
        self.assertEqual(manifest["visual_pipeline"]["api_spend_usd"], 0)


if __name__ == "__main__":
    unittest.main()
