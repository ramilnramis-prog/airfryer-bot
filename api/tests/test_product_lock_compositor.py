"""Тесты product-locked compositing pipeline.

Покрытие (по заданию):
1. product layer не изменяет handle geometry;
2. non-uniform stretch запрещён;
3. local warp запрещён (ловится validator'ом);
4. perspective transform в пределах допуска разрешён;
5. маска пальцев может перекрывать ручку, но не изменять её;
6. product_lock_validator выявляет подмену ручки;
7. rigid animation сохраняет форму на всех кадрах;
8. generated background не попадает внутрь product mask;
9. pipeline работает без OpenAI и Higgsfield;
10. никакие платные API не вызываются (в compositor нет ни сети, ни ключей).
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw

from api.media_pipeline.compositor.layer_compositor import SceneLayers, compose
from api.media_pipeline.compositor.masks import check_contact_zones
from api.media_pipeline.compositor.perspective import (RigidTransform,
                                                       apply_transform,
                                                       require_uniform_scale)
from api.media_pipeline.compositor.product_lock_validator import (
    ProductLockError, validate_composite)
from api.media_pipeline.compositor.rigid_animation import (RigidAnimationPlan,
                                                           render_preview)

BODY = (70, 70, 75, 255)


def synthetic_product():
    """Мини-товар: корпус + две ручки-язычка со сквозными вырезами."""
    img = Image.new("RGBA", (120, 90), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((20, 15, 100, 80), fill=BODY)
    d.rectangle((4, 38, 20, 62), fill=BODY)          # левая ручка
    d.rectangle((8, 44, 16, 56), fill=(0, 0, 0, 0))  # вырез
    d.rectangle((100, 38, 116, 62), fill=BODY)       # правая ручка
    d.rectangle((104, 44, 112, 56), fill=(0, 0, 0, 0))
    left = Image.new("L", img.size, 0)
    dl = ImageDraw.Draw(left)
    dl.rectangle((4, 38, 20, 62), fill=255)
    right = Image.new("L", img.size, 0)
    dr = ImageDraw.Draw(right)
    dr.rectangle((100, 38, 116, 62), fill=255)
    return img, {"left": left, "right": right}


def noisy_background(size=(220, 200)):
    rng = np.random.default_rng(7)
    arr = rng.integers(0, 255, size=(size[1], size[0], 3), dtype=np.uint8)
    return Image.fromarray(arr, "RGB").convert("RGBA")


def scene(transform=None, front_hand=None):
    product, handles = synthetic_product()
    return SceneLayers(
        background=noisy_background(),
        product=product,
        product_transform=transform or RigidTransform(translate=(50, 55)),
        front_hand=front_hand,
        handle_masks=handles)


class TestProductLock(unittest.TestCase):
    def test_product_layer_preserves_handle_geometry(self):
        # (1) после композиции пиксели обеих ручек идентичны канону
        out = compose(scene())
        self.assertTrue(out["validation"]["passed"])
        hg = out["validation"]["checks"]["handle_geometry"]
        self.assertTrue(hg["left"]["ok"])
        self.assertTrue(hg["right"]["ok"])
        self.assertEqual(hg["left"]["bad_pixel_fraction"], 0.0)
        self.assertEqual(hg["right"]["bad_pixel_fraction"], 0.0)

    def test_non_uniform_stretch_forbidden(self):
        # (2) неравные оси масштаба — немедленный отказ
        with self.assertRaises(ProductLockError):
            require_uniform_scale(1.0, 1.2)
        self.assertEqual(require_uniform_scale(0.8, 0.8), 0.8)
        # RigidTransform структурно не принимает два масштаба
        self.assertNotIn("scale_x", RigidTransform.__dataclass_fields__)

    def test_local_warp_detected(self):
        # (3) локальный варп итогового кадра ловится validator'ом
        out = compose(scene())
        final = out["image"].copy()
        region = final.crop((60, 60, 110, 100))  # кусок товара
        final.paste(region, (63, 60))            # сдвиг подобласти = warp
        report = validate_composite(final, out["expected_product_layer"],
                                    occlusion_mask=out["occlusion_mask"],
                                    handle_masks=out["handle_masks_canvas"])
        self.assertFalse(report["passed"])
        self.assertEqual(report["hard_fail"], "product_lock_violation")

    def test_perspective_within_limits_allowed(self):
        # (4) допустимая перспектива проходит и валидируется
        t = RigidTransform(translate=(50, 55), perspective=0.05,
                           rotation_deg=3.0)
        t.validated()
        out = compose(scene(transform=t))
        self.assertTrue(out["validation"]["passed"])
        with self.assertRaises(ProductLockError):
            RigidTransform(perspective=0.2).validated()
        with self.assertRaises(ProductLockError):
            RigidTransform(rotation_deg=15).validated()

    def test_finger_mask_occludes_but_does_not_modify(self):
        # (5) палец поверх ручки: композиция валидна, ручка различима,
        # пиксели товара под пальцем не изменены
        product, handles = synthetic_product()
        finger = Image.new("RGBA", (220, 200), (0, 0, 0, 0))
        d = ImageDraw.Draw(finger)
        d.rectangle((54, 95, 64, 112), fill=(230, 190, 170, 255))  # над левой ручкой
        out = compose(scene(front_hand=finger))
        self.assertTrue(out["validation"]["passed"])
        zones = check_contact_zones(out["occlusion_mask"],
                                    out["handle_masks_canvas"])
        self.assertTrue(zones["ok"])
        self.assertGreater(zones["left"]["covered_fraction"], 0.0)
        # ожидаемый product layer не зависит от пальца
        base = compose(scene())
        self.assertEqual(out["expected_product_layer"].tobytes(),
                         base["expected_product_layer"].tobytes())

    def test_validator_detects_handle_substitution(self):
        # (6) подмена ручки (перерисованный силуэт) = product_lock_violation
        out = compose(scene())
        final = out["image"].copy()
        d = ImageDraw.Draw(final)
        # «округлая» ручка вместо канонической на том же месте
        d.rectangle((54, 93, 71, 118), fill=(210, 205, 200, 255))
        d.ellipse((54, 93, 71, 118), fill=BODY)
        report = validate_composite(final, out["expected_product_layer"],
                                    occlusion_mask=out["occlusion_mask"],
                                    handle_masks=out["handle_masks_canvas"])
        self.assertFalse(report["passed"])
        self.assertEqual(report["hard_fail"], "product_lock_violation")
        self.assertFalse(report["checks"]["handle_geometry"]["left"]["ok"])

    def test_rigid_animation_keeps_shape_every_frame(self):
        # (7) все кадры rigid-анимации проходят product-lock validation
        product, handles = synthetic_product()
        layers = SceneLayers(background=noisy_background(),
                             product=product,
                             handle_masks=handles)
        plan = RigidAnimationPlan(
            duration_s=0.5, fps=8,
            keyframes=[(0.0, RigidTransform(translate=(50, 70))),
                       (1.0, RigidTransform(scale=0.97, rotation_deg=-1.5,
                                            translate=(53, 45)))])
        with tempfile.TemporaryDirectory() as d:
            report = render_preview(plan, layers, d, size=(90, 160),
                                    watermark=True, write_mp4=False)
        self.assertTrue(report["validations_passed"])
        self.assertGreaterEqual(report["frames"], 4)

    def test_background_never_leaks_inside_product_mask(self):
        # (8) внутри непрозрачного ядра товара — только пиксели товара
        out = compose(scene())
        final = np.asarray(out["image"].convert("RGB"), dtype=np.int16)
        expected = np.asarray(
            out["expected_product_layer"].convert("RGB"), dtype=np.int16)
        alpha = np.asarray(out["expected_product_layer"].getchannel("A"))
        core = alpha >= 250
        diff = np.abs(final - expected).max(axis=2)
        self.assertEqual(int((diff[core] > 0).sum()), 0)
        # а сквозные вырезы ручек остаются фоном (не «затыкаются» товаром)
        self.assertTrue((alpha[100:105, 58:64] < 10).all())

    def test_pipeline_runs_without_openai_and_higgsfield(self):
        # (9) полный цикл композиции и превью — при «мёртвой» сети
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network call!")):
            out = compose(scene())
            self.assertTrue(out["validation"]["passed"])
            product, handles = synthetic_product()
            plan = RigidAnimationPlan(duration_s=0.3, fps=8, keyframes=[
                (0.0, RigidTransform(translate=(50, 60))),
                (1.0, RigidTransform(translate=(50, 50)))])
            with tempfile.TemporaryDirectory() as d:
                report = render_preview(
                    plan, SceneLayers(background=noisy_background(),
                                      product=product, handle_masks=handles),
                    d, size=(90, 160), write_mp4=False)
            self.assertTrue(report["validations_passed"])

    def test_no_paid_api_surface_in_compositor(self):
        # (10) в compositor нет ни сети, ни OpenAI/Higgsfield, ни ключей
        comp_dir = Path("api/media_pipeline/compositor")
        for f in comp_dir.glob("*.py"):
            src = f.read_text(encoding="utf-8").lower()
            for token in ("urllib", "api.openai.com", "openai_api_key",
                          "higgsfield", "requests.", "http://", "https://"):
                self.assertNotIn(token, src, f"{f.name} содержит {token}")


if __name__ == "__main__":
    unittest.main()
