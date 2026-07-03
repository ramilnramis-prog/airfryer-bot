"""Тесты статичного real base plate scene-05 (compositor.cli baseplate).

Покрытие: три варианта положения (A/B/C) используют один и тот же
real-product-v1 product layer, только RigidTransform различается; каждый
проходит product-lock validation; фон — реальный кадр (не placeholder);
никаких платных API-вызовов.
"""
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline.compositor.cli import (
    BASEPLATE_VARIANTS, REAL_BACKGROUND, _load_real_image, _shadow_overlay,
    _variant_transform)
from api.media_pipeline.compositor.layer_compositor import SceneLayers, compose
from api.media_pipeline.compositor.product_assets import DEFAULT_VIEW, load_view


class TestBaseplateVariants(unittest.TestCase):
    def test_three_named_variants_ABC(self):
        self.assertEqual(set(BASEPLATE_VARIANTS), {"A", "B", "C"})

    def test_variant_transforms_within_product_lock_limits(self):
        product, _mask, _handles = load_view(DEFAULT_VIEW)
        for key, spec in BASEPLATE_VARIANTS.items():
            t = _variant_transform(spec, product.size)
            t.validated()  # бросит ProductLockError при нарушении лимитов
            self.assertGreaterEqual(t.translate[0], 0)
            self.assertGreaterEqual(t.translate[1], 0,
                                    f"variant {key}: translate.y < 0 — "
                                    "форма уйдёт за верхний край холста")

    def test_variants_differ_only_by_position_not_by_product_source(self):
        product, _, _ = load_view(DEFAULT_VIEW)
        transforms = {k: _variant_transform(s, product.size)
                     for k, s in BASEPLATE_VARIANTS.items()}
        # A -> C: форма поднимается (translate.y уменьшается) и немного
        # отдаляется (scale уменьшается) — монотонный тренд подъёма
        self.assertGreater(transforms["A"].translate[1], transforms["B"].translate[1])
        self.assertGreater(transforms["B"].translate[1], transforms["C"].translate[1])
        self.assertGreaterEqual(transforms["A"].scale, transforms["B"].scale)
        self.assertGreaterEqual(transforms["B"].scale, transforms["C"].scale)


class TestBaseplateComposition(unittest.TestCase):
    def test_real_background_is_not_placeholder(self):
        bg = _load_real_image(REAL_BACKGROUND)
        self.assertEqual(bg.mode, "RGBA")
        self.assertTrue(Path(REAL_BACKGROUND).is_file())
        self.assertIn("real-v1", REAL_BACKGROUND)

    def test_each_variant_passes_product_lock_validation(self):
        product, _mask, handles = load_view(DEFAULT_VIEW)
        background = _load_real_image(REAL_BACKGROUND)
        for key, spec in BASEPLATE_VARIANTS.items():
            transform = _variant_transform(spec, product.size)
            shadow = _shadow_overlay(background.size, 360, spec["bottom_y"] + 6)
            layers = SceneLayers(background=background, product=product,
                                 product_transform=transform,
                                 effects=[shadow], handle_masks=handles)
            result = compose(layers, validate=True)
            self.assertTrue(result["validation"]["passed"],
                            f"variant {key} failed: {result['validation']}")
            for side, hm in result["handle_masks_canvas"].items():
                self.assertIsNotNone(hm.getbbox(),
                                     f"variant {key}: ручка {side} не видна в кадре")

    def test_no_hands_food_steam_layers_present(self):
        # на этом этапе SceneLayers не получает back_hand/front_hand —
        # только background + product + shadow effect
        product, _mask, handles = load_view(DEFAULT_VIEW)
        background = _load_real_image(REAL_BACKGROUND)
        spec = BASEPLATE_VARIANTS["B"]
        transform = _variant_transform(spec, product.size)
        layers = SceneLayers(background=background, product=product,
                             product_transform=transform,
                             effects=[_shadow_overlay(background.size, 360, 386)],
                             handle_masks=handles)
        self.assertIsNone(layers.back_hand)
        self.assertIsNone(layers.front_hand)
        self.assertEqual(len(layers.effects), 1)  # только тень


class TestNoPaidCalls(unittest.TestCase):
    def test_baseplate_helpers_make_no_network_call(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network call!")):
            product, _mask, handles = load_view(DEFAULT_VIEW)
            background = _load_real_image(REAL_BACKGROUND)
            transform = _variant_transform(BASEPLATE_VARIANTS["A"], product.size)
            layers = SceneLayers(background=background, product=product,
                                 product_transform=transform, handle_masks=handles)
            result = compose(layers, validate=True)
            self.assertTrue(result["validation"]["passed"])


if __name__ == "__main__":
    unittest.main()
