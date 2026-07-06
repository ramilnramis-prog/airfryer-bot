"""Тесты CALL 1 scene-05 как MASKED IMAGE EDIT утверждённого baseplate B
(вместо прежнего free isolated-RGBA-hands prompt).

Покрытие (явно запрошенные проверки):
1. вне edit mask пиксели совпадают с baseplate B
2. геометрия товара и ручек не меняется
3. фон и DE'MIAND не меняются
4. руки попадают на реальные handle bboxes
5. FOOD остаётся заблокированным
плюс: никакие API не вызываются.
"""
import json
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline.compositor.scene05_baseplate import (
    APPROVED_CANVAS_SIZE, APPROVED_TRANSFORM_B)
from api.media_pipeline.compositor.scene05_debug_preview import (
    compare_to_approved_baseplate, rebuild_layered_scene)
from api.media_pipeline.compositor.scene05_layer_masks import (
    build_all_layer_masks, call1_edit_mask_zones)
from api.media_pipeline.compositor.product_assets import DEFAULT_VIEW

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"
BASEPLATE_B_PNG = (CAMPAIGN_DIR / "generated" / "scene-05-real-baseplate" /
                   "baseplate-B.png")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _rect_area(rect):
    x0, y0, x1, y1 = rect
    return max(0, x1 - x0) * max(0, y1 - y0)


def _rect_intersection(a, b):
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


class TestEditMaskGeometry(unittest.TestCase):
    def setUp(self):
        self.masks = build_all_layer_masks(DEFAULT_VIEW, APPROVED_TRANSFORM_B,
                                           APPROVED_CANVAS_SIZE)
        self.edit_mask = call1_edit_mask_zones(self.masks)

    def test_edit_mask_has_exactly_four_named_zones(self):
        self.assertEqual(set(self.edit_mask),
                         {"left_forearm_hand", "right_forearm_hand",
                          "left_fingers_over_handle", "right_fingers_over_handle"})

    def test_right_forearm_hand_zone_clipped_to_product_bottom(self):
        # (1)/(2): исходная back_hand_right_zone уходит в открытую корзину
        # (y1=538) — для плоского edit это перерисовало бы фон/корзину.
        # Обязана быть обрезана по product_full_bbox y1.
        product_y1 = self.masks["product_full_bbox"][3]
        self.assertEqual(self.edit_mask["right_forearm_hand"][3], product_y1)
        self.assertLess(self.edit_mask["right_forearm_hand"][3],
                        self.masks["back_hand_right_zone"][3])

    def test_edit_mask_stays_above_cast_shadow_and_basket_rim(self):
        # (2)/(3): корзина/рим начинаются на cast_shadow_zone.y0 — маска не
        # должна туда заходить.
        basket_rim_y = self.masks["cast_shadow_zone"][1]
        for name, zone in self.edit_mask.items():
            self.assertLessEqual(zone[3], basket_rim_y,
                               f"{name} заходит в зону корзины/рима")

    def test_edit_mask_does_not_fully_cover_product(self):
        # (2): геометрия товара защищена — маска не покрывает весь товар.
        product_area = _rect_area(self.masks["product_full_bbox"])
        mask_over_product = sum(
            _rect_area(_rect_intersection(z, self.masks["product_full_bbox"]) or (0, 0, 0, 0))
            for z in self.edit_mask.values())
        self.assertLess(mask_over_product, product_area * 0.5,
                        "edit-маска покрывает больше половины товара — "
                        "геометрия товара не была бы защищена")

    def test_finger_zones_land_on_real_handle_bboxes(self):
        # (4): руки/пальцы должны попадать именно на реальные handle bboxes.
        left_intersection = _rect_intersection(
            self.edit_mask["left_fingers_over_handle"], self.masks["left_handle_bbox"])
        right_intersection = _rect_intersection(
            self.edit_mask["right_fingers_over_handle"], self.masks["right_handle_bbox"])
        self.assertIsNotNone(left_intersection, "left fingers zone не пересекает left_handle_bbox")
        self.assertIsNotNone(right_intersection, "right fingers zone не пересекает right_handle_bbox")

    def test_finger_zones_do_not_cover_entire_handle(self):
        # часть ручки (и прорезь) должна остаться видна — палец не должен
        # закрывать handle bbox целиком.
        for side in ("left", "right"):
            finger_zone = self.edit_mask[f"{side}_fingers_over_handle"]
            handle_bbox = self.masks[f"{side}_handle_bbox"]
            overlap = _rect_area(_rect_intersection(finger_zone, handle_bbox) or (0, 0, 0, 0))
            self.assertLess(overlap, _rect_area(handle_bbox),
                           f"{side} fingers zone полностью закрывает handle bbox")


class TestOutsideMaskMatchesBaseplateB(unittest.TestCase):
    def test_clean_rebuild_matches_approved_baseplate_b_outside_watermark(self):
        # (1): PRIMARY INPUT — чистая пересборка, пиксель-в-пиксель совпадает
        # с approved baseplate-B.png вне полосы watermark.
        if not BASEPLATE_B_PNG.is_file():
            self.skipTest("baseplate-B.png не сгенерирован в этом окружении")
        result = rebuild_layered_scene(DEFAULT_VIEW)
        report = compare_to_approved_baseplate(result["image"], str(BASEPLATE_B_PNG))
        self.assertTrue(report["match"], report)
        self.assertLessEqual(report["bad_pixel_fraction"], 0.01)

    def test_prompts_doc_uses_clean_rebuild_not_raw_watermarked_file_as_primary_input(self):
        prompts = (CAMPAIGN_DIR / "scene-05-layer-prompts.md").read_text(encoding="utf-8")
        self.assertIn("rebuild_layered_scene", prompts)
        self.assertIn("TEST PREVIEW", prompts)  # явно упомянут watermark исходного файла
        self.assertIn("используется НЕ он, а его чистая", prompts)


class TestProductAndHandleGeometryUnchanged(unittest.TestCase):
    def test_product_lock_transform_still_approved_transform_b(self):
        self.assertEqual(APPROVED_TRANSFORM_B.scale, 0.56)
        self.assertEqual(APPROVED_TRANSFORM_B.rotation_deg, -1.0)
        self.assertEqual(APPROVED_TRANSFORM_B.translate, (137.24, 20.48))
        self.assertEqual(APPROVED_TRANSFORM_B.perspective, 0.0)

    def test_prompts_forbid_reshaping_or_moving_handles(self):
        prompts = (CAMPAIGN_DIR / "scene-05-layer-prompts.md").read_text(encoding="utf-8")
        self.assertIn("do not reshape, resize, or move the handle", prompts)

    def test_dry_run_hard_fail_list_covers_handle_and_product_geometry(self):
        dry_run = load_json(CAMPAIGN_DIR / "scene-05-generation-dry-run.json")
        joined = " ".join(dry_run["qa_criteria_hard_fail"]).lower()
        self.assertIn("геометрия товара", joined)
        self.assertIn("flat corner tab", joined)


class TestBackgroundAndDemiandUnchanged(unittest.TestCase):
    def test_edit_mask_protected_outside_list_includes_demiand_and_background(self):
        dry_run = load_json(CAMPAIGN_DIR / "scene-05-generation-dry-run.json")
        protected = dry_run["edit_mask"]["protected_outside_mask"]
        joined = " ".join(protected)
        self.assertIn("DE'MIAND", joined)
        self.assertIn("фон", joined)
        self.assertIn("корзина", joined)

    def test_dry_run_hard_fail_list_covers_background_and_demiand(self):
        dry_run = load_json(CAMPAIGN_DIR / "scene-05-generation-dry-run.json")
        joined = " ".join(dry_run["qa_criteria_hard_fail"])
        self.assertIn("DE'MIAND", joined)


class TestFoodRemainsBlocked(unittest.TestCase):
    def test_pilot_call_food_status_is_blocked(self):
        dry_run = load_json(CAMPAIGN_DIR / "scene-05-generation-dry-run.json")
        self.assertEqual(dry_run["planned_generation"]["pilot_call"]["food_status"], "BLOCKED")

    def test_pilot_call_higgsfield_status_is_blocked(self):
        dry_run = load_json(CAMPAIGN_DIR / "scene-05-generation-dry-run.json")
        self.assertEqual(dry_run["planned_generation"]["pilot_call"]["higgsfield_status"], "BLOCKED")

    def test_food_wings_excluded_from_refs(self):
        dry_run = load_json(CAMPAIGN_DIR / "scene-05-generation-dry-run.json")
        excluded_ids = {e["asset_id"] for e in dry_run["excluded_from_refs"]}
        self.assertIn("food-wings-01", excluded_ids)

    def test_pilot_call_scope_is_hands_only(self):
        dry_run = load_json(CAMPAIGN_DIR / "scene-05-generation-dry-run.json")
        self.assertEqual(dry_run["planned_generation"]["pilot_call"]["call_count"], 1)
        self.assertIn("HANDS ONLY", dry_run["planned_generation"]["pilot_call"]["scope"])


class TestNoPaidApiCalls(unittest.TestCase):
    def test_computing_edit_mask_and_rebuild_makes_no_network_call(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network call!")):
            masks = build_all_layer_masks(DEFAULT_VIEW, APPROVED_TRANSFORM_B,
                                          APPROVED_CANVAS_SIZE)
            call1_edit_mask_zones(masks)
            rebuild_layered_scene(DEFAULT_VIEW)

    def test_no_paid_api_surface_in_updated_layer_masks_module(self):
        src = (REPO_ROOT / "api" / "media_pipeline" / "compositor" /
              "scene05_layer_masks.py").read_text(encoding="utf-8").lower()
        for token in ("urllib", "api.openai.com", "openai_api_key",
                     "higgsfield", "requests.", "http://", "https://"):
            self.assertNotIn(token, src, token)

    def test_dry_run_execution_summary_shows_zero_executed(self):
        dry_run = load_json(CAMPAIGN_DIR / "scene-05-generation-dry-run.json")
        self.assertEqual(dry_run["execution_summary"]["openai_images_api_calls_executed"], 0)
        self.assertEqual(dry_run["execution_summary"]["api_spend_usd_executed"], 0)


if __name__ == "__main__":
    unittest.main()
