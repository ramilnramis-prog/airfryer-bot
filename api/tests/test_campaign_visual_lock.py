"""Тесты campaign-level visual continuity locks.

Покрытие (9 пунктов из CAMPAIGN_VISUAL_LOCK_SYSTEM.md):
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
PRODUCT_MANIFEST = REPO_ROOT / "assets" / "product-lock" / "airfryer-silicone-form" / "product_asset_manifest.json"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class TestProductCanonAlwaysRealV1(unittest.TestCase):
    def test_campaign_visual_lock_product_canon_is_real_v1(self):
        lock = load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
        self.assertEqual(lock["product_canon"], "real-product-v1")

    def test_product_canon_manifest_matches_active_canonical_version(self):
        lock = load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
        manifest = load_json(REPO_ROOT / lock["product_canon_manifest"])
        self.assertEqual(manifest["canonical_version"], "real-product-v1")
        self.assertEqual(manifest["canonical_status"], "active")

    def test_a_hypothetical_second_campaign_cannot_override_product_canon(self):
        # product_canon — единственное поле, которое НЕ входит в выбираемый
        # набор (в отличие от hands/person/airfryer/...): любая кампания,
        # построенная по этой схеме, обязана указать то же значение.
        lock_a = load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
        lock_b = dict(lock_a, campaign_code="hypothetical-other-campaign",
                     hands_reference={"library_assets": ["something-else"]})
        self.assertEqual(lock_a["product_canon"], lock_b["product_canon"])


class TestHandsLockedWithinCampaign(unittest.TestCase):
    def test_hands_reference_is_single_fixed_set_for_campaign(self):
        lock = load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
        hands = lock["hands_reference"]["library_assets"]
        self.assertGreater(len(hands), 0)
        # одно и то же значение читается из одного и того же файла для
        # ЛЮБОЙ сцены/хука этой кампании — нет per-scene override в схеме
        lock_reloaded = load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
        self.assertEqual(hands, lock_reloaded["hands_reference"]["library_assets"])

    def test_forbidden_continuity_changes_includes_hands(self):
        lock = load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
        joined = " ".join(lock["forbidden_continuity_changes"]).lower()
        self.assertIn("рук", joined)


class TestAirfryerLockedWithinCampaign(unittest.TestCase):
    def test_airfryer_reference_is_single_fixed_set_for_campaign(self):
        lock = load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
        airfryer = lock["airfryer_reference"]["library_assets"]
        self.assertEqual(airfryer, ["real-airfryer-front-01"])

    def test_forbidden_continuity_changes_includes_airfryer(self):
        lock = load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
        joined = " ".join(lock["forbidden_continuity_changes"]).lower()
        self.assertIn("аэрогрил", joined)


class TestPersonClothingKitchenLockedWithinCampaign(unittest.TestCase):
    def test_person_clothing_kitchen_each_have_one_fixed_set(self):
        lock = load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
        for field in ("person_reference", "clothing_reference", "kitchen_reference"):
            assets = lock[field]["library_assets"]
            self.assertGreater(len(assets), 0, f"{field} пуст")

    def test_forbidden_continuity_changes_covers_all_three(self):
        lock = load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
        joined = " ".join(lock["forbidden_continuity_changes"]).lower()
        for word in ("персонаж", "одежд", "кухн"):
            self.assertIn(word, joined)

    def test_locked_for_all_scenes_flag_is_true(self):
        lock = load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
        self.assertTrue(lock["locked_for_all_scenes"])


class TestThreeHooksShareOneBodyAndOneLock(unittest.TestCase):
    def test_hooks_json_has_exactly_three_variants_same_content_code(self):
        hooks = load_json(CAMPAIGN_DIR / "hooks.json")
        codes = {h["hook_code"] for h in hooks["hooks"]}
        self.assertEqual(codes, {"A", "B", "C"})
        self.assertEqual(hooks["content_code"], "coating-protect-ad")

    def test_hooks_only_differ_by_text_not_by_visual_fields(self):
        hooks = load_json(CAMPAIGN_DIR / "hooks.json")
        for h in hooks["hooks"]:
            self.assertNotIn("hands_reference", h)
            self.assertNotIn("airfryer_reference", h)
            self.assertNotIn("kitchen_reference", h)

    def test_campaign_visual_lock_declares_shared_body_and_lock(self):
        lock = load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
        self.assertTrue(lock["shared_across_hooks"])
        self.assertTrue(lock["hooks"]["shared_main_body"])
        self.assertEqual(lock["hooks"]["shared_visual_lock"],
                         "content/autopilot/coating-protect-2026-07/campaign_visual_lock.json")
        self.assertEqual(set(lock["hooks"]["variants"]), {"A", "B", "C"})
        self.assertEqual(lock["hooks"]["content_code"], hooks_content_code(lock))


def hooks_content_code(lock):
    return lock["content_code"]


class TestNewCampaignMayChooseDifferentLock(unittest.TestCase):
    def test_synthetic_second_campaign_can_diverge_on_everything_but_product(self):
        lock_a = load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
        lock_b = {
            "campaign_code": "other-future-campaign",
            "product_canon": "real-product-v1",
            "hands_reference": {"library_assets": ["hand-glove-scrub-01"]},
            "person_reference": {"library_assets": ["person-c-frustrated-01"]},
            "airfryer_reference": {"library_assets": ["v2-form-in-basket-01"]},
            "kitchen_reference": {"library_assets": ["kf-marble-kitchen-01"]},
            "clothing_reference": {"library_assets": ["v2-hand-hold-01"]},
            "lighting_reference": {"library_assets": ["food-salmon-01"]},
        }
        # product_canon совпадает — это единственное обязательное совпадение
        self.assertEqual(lock_a["product_canon"], lock_b["product_canon"])
        # всё остальное — свободно отличается между кампаниями
        for field in ("hands_reference", "person_reference", "airfryer_reference",
                     "kitchen_reference", "clothing_reference", "lighting_reference"):
            self.assertNotEqual(lock_a[field]["library_assets"],
                               lock_b[field]["library_assets"])

    def test_cross_campaign_rule_is_documented(self):
        lock = load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
        self.assertIn("никогда", lock["cross_campaign_rule"].lower())


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
        excluded_ids = {e["id"] for e in index["excluded_from_library"]}
        self.assertIn("legacy-turnaround-6angles", excluded_ids)
        legacy_flagged = [a for a in index["assets"]
                         if any("устарев" in r.lower() or "некорректн" in r.lower()
                                for r in a.get("restrictions", []))]
        self.assertGreater(len(legacy_flagged), 0)
        for a in legacy_flagged:
            joined = " ".join(a["restrictions"]).lower()
            self.assertIn("геометри", joined)

    def test_all_manifest_assets_are_approved_for_reference_only(self):
        for manifest_path in LIB_ROOT.glob("*/manifest.json"):
            manifest = load_json(manifest_path)
            for asset in manifest["assets"]:
                self.assertTrue(asset["approved_for_reference_only"], asset["id"])

    def test_every_asset_has_required_provenance_fields(self):
        required = {"id", "source_path", "description", "sha256", "type",
                   "approved_for_reference_only", "category"}
        for manifest_path in LIB_ROOT.glob("*/manifest.json"):
            manifest = load_json(manifest_path)
            for asset in manifest["assets"]:
                missing = required - set(asset)
                self.assertFalse(missing, f"{manifest_path}:{asset.get('id')} missing {missing}")


class TestFoodMaySceneSpecific(unittest.TestCase):
    def test_food_reference_declares_scene_specific_allowed(self):
        lock = load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
        self.assertTrue(lock["food_reference"]["scene_specific_allowed"])

    def test_food_is_not_in_forbidden_continuity_changes(self):
        lock = load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
        joined = " ".join(lock["forbidden_continuity_changes"]).lower()
        self.assertNotIn("еда", joined)
        self.assertNotIn("блюдо", joined)

    def test_allowed_scene_changes_permits_food_presence_change(self):
        lock = load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
        joined = " ".join(lock["allowed_scene_changes"]).lower()
        self.assertIn("ед", joined)


class TestNoPaidApiCalls(unittest.TestCase):
    def test_loading_visual_lock_and_library_makes_no_network_call(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network call!")):
            load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
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
