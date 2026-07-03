"""Тесты детерминированного layer skeleton поверх approved baseplate-B.

Владелец: SELECT B. Transform B зафиксирован (scale=0.56, rotation=-1.0,
translate=(137.24,20.48), canvas 720x1280). Маски вычисляются ИЗ реального
product layer + этого transform (scene05_layer_masks.py), не рисуются на
глаз поверх baseplate-B.png.

Покрытие (по заданию):
1. tracked selection фиксирует B и точный transform;
2. generated selection не является единственным источником решения;
3. product_front_occluder перекрывает food layer;
4. food не выходит за interior mask;
5. back hand остаётся позади product;
6. front fingers остаются поверх handles;
7. cast shadow находится ниже product;
8. product pixels и handle geometry не меняются;
9. layered rebuild совпадает с baseplate-B;
10. никакие API не вызываются.
"""
import json
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw

from api.media_pipeline.compositor.layer_compositor import SceneLayers, compose
from api.media_pipeline.compositor.product_assets import DEFAULT_VIEW, load_view
from api.media_pipeline.compositor.scene05_baseplate import (
    APPROVED_CANVAS_SIZE, APPROVED_TRANSFORM_B, APPROVED_VARIANT,
    BASEPLATE_VARIANTS, variant_transform)
from api.media_pipeline.compositor.scene05_debug_preview import (
    compare_to_approved_baseplate, rebuild_layered_scene)
from api.media_pipeline.compositor.scene05_layer_masks import (
    build_all_layer_masks, product_front_occluder_mask,
    product_interior_food_mask, product_full_mask)

TRACKED_SELECTION = Path(
    "content/autopilot/coating-protect-2026-07/scene-05-baseplate-selection.json")
GENERATED_SELECTION = Path(
    "content/autopilot/coating-protect-2026-07/generated/scene-05-real-baseplate/"
    "baseplate-selection.json")
BASEPLATE_B_PNG = Path(
    "content/autopilot/coating-protect-2026-07/generated/scene-05-real-baseplate/"
    "baseplate-B.png")


class TestTrackedSelection(unittest.TestCase):
    def test_tracked_selection_fixes_B_and_exact_transform(self):
        # (1) версионируемый файл фиксирует B и ТОЧНЫЙ transform
        data = json.loads(TRACKED_SELECTION.read_text(encoding="utf-8"))
        self.assertEqual(data["selected_variant"], "B")
        self.assertTrue(data["owner_approved"])
        t = data["transform"]
        self.assertEqual(t["scale"], APPROVED_TRANSFORM_B.scale)
        self.assertEqual(t["rotation_deg"], APPROVED_TRANSFORM_B.rotation_deg)
        self.assertEqual(tuple(t["translate"]), APPROVED_TRANSFORM_B.translate)
        self.assertEqual(t["canvas_size"], list(APPROVED_CANVAS_SIZE))
        self.assertEqual(data["rejected_alternatives"]["A"]["status"],
                         "rejected_alternative")
        self.assertEqual(data["rejected_alternatives"]["C"]["status"],
                         "rejected_alternative")
        self.assertFalse(data["rejected_alternatives"]["A"]["deleted"])
        self.assertFalse(data["rejected_alternatives"]["C"]["deleted"])

    def test_generated_selection_is_not_the_only_source_of_truth(self):
        # (2) tracked-файл существует независимо от generated/ (который не
        # версионируется и может быть удалён/пересобран без потери решения)
        self.assertTrue(TRACKED_SELECTION.is_file(),
                        "версионируемый файл решения обязателен, не только generated/")
        # даже если бы generated-файла не было, tracked остаётся источником истины
        tracked = json.loads(TRACKED_SELECTION.read_text(encoding="utf-8"))
        self.assertIn("baseplate", tracked)
        self.assertIn("sha256", tracked["baseplate"])

    def test_approved_transform_matches_variant_B_computation(self):
        product, _mask, _handles = load_view(DEFAULT_VIEW)
        computed = variant_transform(BASEPLATE_VARIANTS["B"], product.size)
        self.assertAlmostEqual(computed.scale, APPROVED_TRANSFORM_B.scale, places=6)
        self.assertAlmostEqual(computed.rotation_deg,
                               APPROVED_TRANSFORM_B.rotation_deg, places=6)
        self.assertAlmostEqual(computed.translate[0],
                               APPROVED_TRANSFORM_B.translate[0], places=1)
        self.assertAlmostEqual(computed.translate[1],
                               APPROVED_TRANSFORM_B.translate[1], places=1)


class TestDeterministicMasks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.masks = build_all_layer_masks(DEFAULT_VIEW, APPROVED_TRANSFORM_B,
                                          APPROVED_CANVAS_SIZE)

    def test_food_never_exits_interior_mask(self):
        # (4) interior mask — строгое подмножество full mask (форма
        # физически ограничивает, куда может лечь еда)
        full = np.asarray(self.masks["product_full_mask"]) > 128
        interior = np.asarray(self.masks["product_interior_food_mask"]) > 128
        self.assertTrue(interior.sum() > 0, "interior mask пуста")
        self.assertTrue(np.array_equal(interior & full, interior),
                        "interior mask выходит за пределы product_full_mask")
        self.assertLess(interior.sum(), full.sum())

    def test_front_occluder_covers_food_layer_edges(self):
        # (3) occluder (борт+ручки) окружает food-зону: occluder ∪ interior
        # == full, occluder ∩ interior == ∅, occluder касается каждой
        # стороны bbox формы (значит, "накрывает" края еды со всех сторон)
        full = np.asarray(self.masks["product_full_mask"]) > 128
        interior = np.asarray(self.masks["product_interior_food_mask"]) > 128
        occluder = np.asarray(self.masks["product_front_occluder_mask"]) > 128
        self.assertTrue(np.array_equal(occluder | interior, full))
        self.assertEqual(int((occluder & interior).sum()), 0)
        occ_bbox = self.masks["product_front_occluder_mask"].getbbox()
        int_bbox = self.masks["product_interior_food_mask"].getbbox()
        # occluder bbox строго охватывает interior bbox со всех сторон
        self.assertLessEqual(occ_bbox[0], int_bbox[0])
        self.assertLessEqual(occ_bbox[1], int_bbox[1])
        self.assertGreaterEqual(occ_bbox[2], int_bbox[2])
        self.assertGreaterEqual(occ_bbox[3], int_bbox[3])

    def test_cast_shadow_is_below_product(self):
        # (7) тень падающая, НИЖЕ формы (форма её не касается)
        shadow_top = self.masks["cast_shadow_zone"][1]
        product_bottom = self.masks["product_full_bbox"][3]
        self.assertGreaterEqual(shadow_top, product_bottom)

    def test_product_pixels_and_handles_unchanged(self):
        # (8) геометрия ручек и товара — точные значения, воспроизводимые
        # из real-product-v1 + transform B (не приблизительные)
        self.assertEqual(self.masks["product_full_bbox"], (145, 28, 595, 380))
        self.assertEqual(self.masks["left_handle_bbox"], (190, 44, 275, 100))
        self.assertEqual(self.masks["right_handle_bbox"], (549, 166, 595, 259))
        # маски ручек не пусты и не совпадают друг с другом (это разные ручки)
        left = np.asarray(self.masks["left_handle_mask"])
        right = np.asarray(self.masks["right_handle_mask"])
        self.assertGreater(left.sum(), 0)
        self.assertGreater(right.sum(), 0)


class TestLayerOrdering(unittest.TestCase):
    """Проверка порядка слоёв через реальный layer_compositor, не только
    геометрию зон."""

    def _synthetic(self):
        product = Image.new("RGBA", (100, 80), (0, 0, 0, 0))
        d = ImageDraw.Draw(product)
        d.rectangle((10, 10, 90, 70), fill=(70, 70, 75, 255))
        d.rectangle((0, 30, 10, 50), fill=(70, 70, 75, 255))  # left handle
        left_mask = Image.new("L", product.size, 0)
        ImageDraw.Draw(left_mask).rectangle((0, 30, 10, 50), fill=255)
        bg = Image.new("RGBA", (150, 120), (200, 200, 200, 255))
        return product, {"left": left_mask}, bg

    def test_back_hand_stays_behind_product(self):
        # (5) back_hand композится ДО product: там, где они пересекаются,
        # итоговый пиксель — от продукта, не от "руки"
        product, handles, bg = self._synthetic()
        back_hand = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        ImageDraw.Draw(back_hand).rectangle((5, 5, 60, 60), fill=(255, 0, 0, 255))
        layers = SceneLayers(background=bg, product=product,
                             product_transform=__import__(
                                 "api.media_pipeline.compositor.perspective",
                                 fromlist=["RigidTransform"]).RigidTransform(
                                     translate=(20, 20)),
                             back_hand=back_hand, handle_masks=handles)
        result = compose(layers, validate=False)
        # точка внутри product-прямоугольника (20+10..20+90, 20+10..20+70)
        # и внутри back_hand-прямоугольника (5..60,5..60): пересечение (30,30)
        px = result["image"].convert("RGB").getpixel((30, 30))
        self.assertEqual(px, (70, 70, 75), "product должен перекрывать back_hand")

    def test_front_fingers_stay_on_top_of_handles(self):
        # (6) front_hand композится ПОСЛЕ product: над ручкой виден палец
        product, handles, bg = self._synthetic()
        from api.media_pipeline.compositor.perspective import RigidTransform

        front_hand = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        # прямо над левой ручкой (product placed at translate (20,20) ->
        # left handle canvas area x:20..30, y:50..70)
        ImageDraw.Draw(front_hand).rectangle((18, 48, 32, 72), fill=(255, 0, 200, 255))
        layers = SceneLayers(background=bg, product=product,
                             product_transform=RigidTransform(translate=(20, 20)),
                             front_hand=front_hand, handle_masks=handles)
        result = compose(layers, validate=False)
        px = result["image"].convert("RGB").getpixel((25, 60))
        self.assertEqual(px, (255, 0, 200), "front_hand должен перекрывать ручку")
        # ручка при этом физически не изменена — occlusion, не редактирование
        handle_alpha = result["handle_masks_canvas"]["left"].getpixel((25, 60))
        self.assertGreater(handle_alpha, 0, "ручка всё ещё существует под пальцем")


class TestRebuildMatchesBaseplateB(unittest.TestCase):
    def test_layered_rebuild_matches_approved_baseplate(self):
        # (9) пересборка из исходных слоёв (без placeholder) совпадает с
        # утверждённым baseplate-B.png (эталон только для сверки)
        if not BASEPLATE_B_PNG.is_file():
            self.skipTest("baseplate-B.png не сгенерирован в этом окружении")
        result = rebuild_layered_scene(DEFAULT_VIEW)
        self.assertTrue(result["validation"]["passed"])
        report = compare_to_approved_baseplate(result["image"], str(BASEPLATE_B_PNG))
        self.assertTrue(report["match"], report)
        self.assertLessEqual(report["bad_pixel_fraction"], 0.01)

    def test_transform_not_altered_on_mismatch_path(self):
        # при (гипотетическом) несовпадении transform НЕ должен меняться —
        # это гарантируется тем, что APPROVED_TRANSFORM_B — константа модуля,
        # используемая напрямую, а не пересчитываемая на лету
        from api.media_pipeline.compositor import scene05_baseplate as sb
        self.assertEqual(sb.APPROVED_TRANSFORM_B.scale, 0.56)
        self.assertEqual(sb.APPROVED_TRANSFORM_B.rotation_deg, -1.0)
        self.assertEqual(sb.APPROVED_TRANSFORM_B.translate, (137.24, 20.48))


class TestNoPaidApiCalls(unittest.TestCase):
    def test_mask_building_makes_no_network_call(self):
        # (10) построение масок и пересборка — полностью локальные операции
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network call!")):
            masks = build_all_layer_masks(DEFAULT_VIEW, APPROVED_TRANSFORM_B,
                                          APPROVED_CANVAS_SIZE)
            self.assertIsNotNone(masks["product_full_mask"])
            result = rebuild_layered_scene(DEFAULT_VIEW)
            self.assertTrue(result["validation"]["passed"])

    def test_no_paid_api_surface_in_new_modules(self):
        modules = ["scene05_baseplate.py", "scene05_layer_masks.py",
                  "scene05_debug_preview.py"]
        base = Path("api/media_pipeline/compositor")
        for name in modules:
            src = (base / name).read_text(encoding="utf-8").lower()
            for token in ("urllib", "api.openai.com", "openai_api_key",
                          "higgsfield", "requests.", "http://", "https://"):
                self.assertNotIn(token, src, f"{name} содержит {token}")


if __name__ == "__main__":
    unittest.main()
