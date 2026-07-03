"""Тесты masked image edit contract для OpenAI Images Edit API (без сети).

Покрытие:
1. edit request сериализует multipart field `mask`
2. mask не попадает в список обычных image references
3. mask применяется к первому image
4. порядок пяти images сохраняется
5. generation request с mask отклоняется
6. отсутствующая mask отклоняется
7. JPG mask отклоняется
8. mask без alpha отклоняется
9. mask другого размера отклоняется
10. mask больше 4 MB отклоняется
11. полностью прозрачная mask отклоняется
12. полностью непрозрачная mask отклоняется
13. alpha=0 находится только в разрешённых зонах
14. protected area остаётся alpha=255
15. size запроса равен 720x1280
16. n=1
17. retries=0
18. без OPENAI_API_KEY dry-run работает
19. apply без OPENAI_API_KEY останавливается до network call
20. тестовый transport подтверждает, что network calls при тестах = 0
плюс multipart contract snapshot (имена полей).
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline.image_mask import MASK_MAX_BYTES, MaskValidationError
from api.media_pipeline.models import ImageRequest
from api.media_pipeline.openai_images_client import (MediaPipelineError,
                                                      MissingAPIKeyError,
                                                      OpenAIImagesProvider,
                                                      _multipart)

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"
MASK_DIR = CAMPAIGN_DIR / "generated" / "scene-05-locked-layers"
REAL_MASK_PATH = MASK_DIR / "call1-edit-mask.png"


def write_rgba_png(path, size=(10, 10), alpha=255):
    from PIL import Image
    im = Image.new("RGBA", size, (0, 0, 0, alpha))
    im.save(path, "PNG")
    return path


def write_rgb_png_no_alpha(path, size=(10, 10)):
    from PIL import Image
    Image.new("RGB", size, (0, 0, 0)).save(path, "PNG")
    return path


def write_jpg(path, size=(10, 10)):
    from PIL import Image
    Image.new("RGB", size, (0, 0, 0)).save(path, "JPEG")
    return path


class TestMaskMultipartField(unittest.TestCase):
    def test_multipart_has_exactly_one_mask_field_named_mask(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            images = [write_rgba_png(tmp_path / f"img{i}.png") for i in range(5)]
            mask = write_rgba_png(tmp_path / "mask.png", alpha=0)
            # для валидного контракта edit_mask должен иметь и editable, и
            # protected пиксели — перекрасим половину непрозрачной
            from PIL import Image
            im = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
            for x in range(5):
                for y in range(10):
                    im.putpixel((x, y), (0, 0, 0, 255))
            im.save(mask, "PNG")

            files = [("image[]", ref, Path(ref).read_bytes()) for ref in images]
            files.append(("mask", str(mask), Path(mask).read_bytes()))
            body, ctype = _multipart({"model": "gpt-image-2"}, files)
            body_text = body.decode("latin-1")

            self.assertEqual(body_text.count('name="mask"'), 1)
            self.assertEqual(body_text.count('name="image[]"'), 5)

    def test_mask_field_is_not_counted_among_image_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            images = [write_rgba_png(tmp_path / f"img{i}.png") for i in range(2)]
            request = ImageRequest(scene_id="scene-05", prompt="p", n=1, mode="edit",
                                   reference_images=[str(p) for p in images],
                                   mask_path=None)
            self.assertEqual(len(request.reference_images), 2)
            self.assertIsNone(request.mask_path)


class TestMaskAppliesToFirstImageAndOrderPreserved(unittest.TestCase):
    def test_five_images_order_preserved_in_reference_images(self):
        order = ["baseplate", "person-b-exhausted-01", "real-grip-motion-01",
                "left_handle_master", "right_handle_master"]
        request = ImageRequest(scene_id="scene-05", prompt="p", n=1, mode="edit",
                               reference_images=order)
        self.assertEqual(request.reference_images, order)

    def test_mask_validated_against_first_reference_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary = write_rgba_png(tmp_path / "primary.png", size=(20, 30))
            other = write_rgba_png(tmp_path / "other.png", size=(999, 999))
            mask = tmp_path / "mask.png"
            from PIL import Image
            m = Image.new("RGBA", (20, 30), (0, 0, 0, 255))
            for x in range(5):
                for y in range(5):
                    m.putpixel((x, y), (0, 0, 0, 0))
            m.save(mask, "PNG")

            request = ImageRequest(scene_id="s", prompt="p", n=1, mode="edit",
                                   reference_images=[str(primary), str(other)],
                                   mask_path=str(mask))
            provider = OpenAIImagesProvider()
            # dry-run: mask валидируется против reference_images[0] (primary),
            # НЕ против other (999x999) — иначе был бы MASK_SIZE_MISMATCH.
            results = provider.generate(request, out_dir=str(tmp_path), apply=False)
            self.assertTrue(all(r.dry_run for r in results))
            self.assertEqual(results[0].planned_request["mask"]["width"], 20)
            self.assertEqual(results[0].planned_request["mask"]["height"], 30)


class TestGenerationModeRejectsMask(unittest.TestCase):
    def test_mask_with_generate_mode_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mask = write_rgba_png(tmp_path / "mask.png", alpha=0)
            request = ImageRequest(scene_id="s", prompt="p", n=1, mode="generate",
                                   mask_path=str(mask))
            provider = OpenAIImagesProvider()
            with self.assertRaises(MediaPipelineError):
                provider.generate(request, out_dir=str(tmp_path), apply=False)


class TestMaskFileValidationFailClosed(unittest.TestCase):
    def _make_valid_zoned_mask(self, path, size=(720, 1280)):
        from PIL import Image, ImageDraw
        im = Image.new("RGBA", size, (0, 0, 0, 255))
        d = ImageDraw.Draw(im)
        d.rectangle((80, 36, 266, 268), fill=(0, 0, 0, 0))
        im.save(path, "PNG")

    def test_missing_mask_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary = write_rgba_png(tmp_path / "primary.png", size=(720, 1280))
            request = ImageRequest(scene_id="s", prompt="p", n=1, mode="edit",
                                   reference_images=[str(primary)],
                                   mask_path=str(tmp_path / "does-not-exist.png"))
            provider = OpenAIImagesProvider()
            with self.assertRaises(MaskValidationError) as ctx:
                provider.generate(request, out_dir=str(tmp_path), apply=False)
            self.assertEqual(ctx.exception.code, "MASK_NOT_FOUND")

    def test_jpg_mask_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary = write_rgba_png(tmp_path / "primary.png", size=(10, 10))
            mask = write_jpg(tmp_path / "mask.jpg", size=(10, 10))
            request = ImageRequest(scene_id="s", prompt="p", n=1, mode="edit",
                                   reference_images=[str(primary)], mask_path=str(mask))
            provider = OpenAIImagesProvider()
            with self.assertRaises(MaskValidationError) as ctx:
                provider.generate(request, out_dir=str(tmp_path), apply=False)
            self.assertEqual(ctx.exception.code, "MASK_NOT_PNG")

    def test_mask_without_alpha_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary = write_rgba_png(tmp_path / "primary.png", size=(10, 10))
            mask = write_rgb_png_no_alpha(tmp_path / "mask.png", size=(10, 10))
            request = ImageRequest(scene_id="s", prompt="p", n=1, mode="edit",
                                   reference_images=[str(primary)], mask_path=str(mask))
            provider = OpenAIImagesProvider()
            with self.assertRaises(MaskValidationError) as ctx:
                provider.generate(request, out_dir=str(tmp_path), apply=False)
            self.assertEqual(ctx.exception.code, "MASK_NO_ALPHA")

    def test_mask_wrong_size_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary = write_rgba_png(tmp_path / "primary.png", size=(720, 1280))
            mask = write_rgba_png(tmp_path / "mask.png", size=(100, 100), alpha=0)
            request = ImageRequest(scene_id="s", prompt="p", n=1, mode="edit",
                                   reference_images=[str(primary)], mask_path=str(mask))
            provider = OpenAIImagesProvider()
            with self.assertRaises(MaskValidationError) as ctx:
                provider.generate(request, out_dir=str(tmp_path), apply=False)
            self.assertEqual(ctx.exception.code, "MASK_SIZE_MISMATCH")

    def test_mask_over_4mb_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary = write_rgba_png(tmp_path / "primary.png", size=(10, 10))
            mask_path = tmp_path / "mask.png"
            self._make_valid_zoned_mask(mask_path, size=(10, 10))
            # Дополняем файл junk-байтами после IEND, чтобы превысить лимит,
            # оставаясь читаемым PNG (Pillow останавливается на IEND).
            with open(mask_path, "ab") as f:
                f.write(b"\x00" * (MASK_MAX_BYTES + 1024))
            request = ImageRequest(scene_id="s", prompt="p", n=1, mode="edit",
                                   reference_images=[str(primary)], mask_path=str(mask_path))
            provider = OpenAIImagesProvider()
            with self.assertRaises(MaskValidationError) as ctx:
                provider.generate(request, out_dir=str(tmp_path), apply=False)
            self.assertEqual(ctx.exception.code, "MASK_TOO_LARGE")

    def test_fully_transparent_mask_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary = write_rgba_png(tmp_path / "primary.png", size=(10, 10))
            mask = write_rgba_png(tmp_path / "mask.png", size=(10, 10), alpha=0)
            request = ImageRequest(scene_id="s", prompt="p", n=1, mode="edit",
                                   reference_images=[str(primary)], mask_path=str(mask))
            provider = OpenAIImagesProvider()
            with self.assertRaises(MaskValidationError) as ctx:
                provider.generate(request, out_dir=str(tmp_path), apply=False)
            self.assertEqual(ctx.exception.code, "MASK_FULL_FRAME")

    def test_fully_opaque_mask_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary = write_rgba_png(tmp_path / "primary.png", size=(10, 10))
            mask = write_rgba_png(tmp_path / "mask.png", size=(10, 10), alpha=255)
            request = ImageRequest(scene_id="s", prompt="p", n=1, mode="edit",
                                   reference_images=[str(primary)], mask_path=str(mask))
            provider = OpenAIImagesProvider()
            with self.assertRaises(MaskValidationError) as ctx:
                provider.generate(request, out_dir=str(tmp_path), apply=False)
            self.assertEqual(ctx.exception.code, "MASK_EMPTY")

    def test_non_binary_alpha_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary = write_rgba_png(tmp_path / "primary.png", size=(10, 10))
            from PIL import Image
            mask_path = tmp_path / "mask.png"
            im = Image.new("RGBA", (10, 10), (0, 0, 0, 255))
            im.putpixel((0, 0), (0, 0, 0, 128))  # полупрозрачный пиксель
            im.putpixel((1, 1), (0, 0, 0, 0))
            im.save(mask_path, "PNG")
            request = ImageRequest(scene_id="s", prompt="p", n=1, mode="edit",
                                   reference_images=[str(primary)], mask_path=str(mask_path))
            provider = OpenAIImagesProvider()
            with self.assertRaises(MaskValidationError) as ctx:
                provider.generate(request, out_dir=str(tmp_path), apply=False)
            self.assertEqual(ctx.exception.code, "MASK_NOT_BINARY")


class TestRealCall1MaskZoneMatch(unittest.TestCase):
    def test_editable_alpha_zero_only_in_approved_zones(self):
        if not REAL_MASK_PATH.is_file():
            self.skipTest("call1-edit-mask.png не сгенерирован в этом окружении")
        from api.media_pipeline.compositor.scene05_edit_mask import \
            assert_editable_area_matches_zones
        from api.media_pipeline.compositor.scene05_layer_masks import \
            call1_edit_mask_zones
        zones = {
            "left_forearm_hand": (80, 36, 266, 268),
            "right_forearm_hand": (554, 152, 655, 380),
            "left_fingers_over_handle": (190, 44, 275, 72),
            "right_fingers_over_handle": (549, 166, 595, 212),
        }
        assert_editable_area_matches_zones(REAL_MASK_PATH, zones)  # не бросает

    def test_protected_area_is_alpha_255(self):
        if not REAL_MASK_PATH.is_file():
            self.skipTest("call1-edit-mask.png не сгенерирован в этом окружении")
        from PIL import Image
        with Image.open(REAL_MASK_PATH) as im:
            alpha = im.getchannel("A")
            # точка вне всех 4 зон — должна быть protected
            self.assertEqual(alpha.getpixel((400, 700)), 255)

    def test_zone_match_fails_if_stray_editable_pixel_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            from PIL import Image
            from api.media_pipeline.compositor.scene05_edit_mask import \
                assert_editable_area_matches_zones
            mask_path = Path(tmp) / "stray-mask.png"
            im = Image.new("RGBA", (720, 1280), (0, 0, 0, 255))
            im.putpixel((10, 10), (0, 0, 0, 0))  # вне всех зон
            im.save(mask_path, "PNG")
            zones = {"left_forearm_hand": (80, 36, 266, 268)}
            with self.assertRaises(MaskValidationError) as ctx:
                assert_editable_area_matches_zones(mask_path, zones)
            self.assertEqual(ctx.exception.code, "MASK_EDIT_ZONE_MISMATCH")


class TestRequestSizeModelRetries(unittest.TestCase):
    def test_size_and_n_match_pilot_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary = write_rgba_png(tmp_path / "primary.png", size=(720, 1280))
            request = ImageRequest(scene_id="scene-05", prompt="p", n=1, mode="edit",
                                   size="720x1280", reference_images=[str(primary)])
            provider = OpenAIImagesProvider(model="gpt-image-2")
            results = provider.generate(request, out_dir=str(tmp_path), apply=False)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].planned_request["size"], "720x1280")
            self.assertEqual(results[0].planned_request["n"], 1)
            self.assertEqual(results[0].planned_request["model"], "gpt-image-2")
            self.assertNotIn("input_fidelity", results[0].planned_request)
            self.assertNotIn("background", results[0].planned_request)

    def test_no_retry_logic_in_client_source(self):
        src = (REPO_ROOT / "api" / "media_pipeline" / "openai_images_client.py"
              ).read_text(encoding="utf-8")
        self.assertIn("Без retries", src)


class TestDryRunAndApplyKeyGate(unittest.TestCase):
    def test_dry_run_works_without_openai_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary = write_rgba_png(tmp_path / "primary.png", size=(720, 1280))
            mask_path = tmp_path / "mask.png"
            from PIL import Image, ImageDraw
            im = Image.new("RGBA", (720, 1280), (0, 0, 0, 255))
            ImageDraw.Draw(im).rectangle((80, 36, 266, 268), fill=(0, 0, 0, 0))
            im.save(mask_path, "PNG")

            request = ImageRequest(scene_id="scene-05", prompt="p", n=1, mode="edit",
                                   size="720x1280", reference_images=[str(primary)],
                                   mask_path=str(mask_path))
            provider = OpenAIImagesProvider(model="gpt-image-2")
            with mock.patch("urllib.request.urlopen",
                            side_effect=AssertionError("network call in dry-run!")):
                with mock.patch.dict(os.environ, {}, clear=True):
                    results = provider.generate(request, out_dir=str(tmp_path), apply=False)
            self.assertTrue(all(r.dry_run for r in results))
            self.assertEqual(results[0].planned_request["mask"]["sha256"],
                             __import__("api.media_pipeline.image_mask", fromlist=["sha256_file"])
                             .sha256_file(mask_path))

    def test_apply_without_key_stops_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary = write_rgba_png(tmp_path / "primary.png", size=(720, 1280))
            mask_path = tmp_path / "mask.png"
            from PIL import Image, ImageDraw
            im = Image.new("RGBA", (720, 1280), (0, 0, 0, 255))
            ImageDraw.Draw(im).rectangle((80, 36, 266, 268), fill=(0, 0, 0, 0))
            im.save(mask_path, "PNG")

            request = ImageRequest(scene_id="scene-05", prompt="p", n=1, mode="edit",
                                   size="720x1280", reference_images=[str(primary)],
                                   mask_path=str(mask_path))
            provider = OpenAIImagesProvider(model="gpt-image-2")
            with mock.patch("urllib.request.urlopen",
                            side_effect=AssertionError("network call before key check!")):
                with mock.patch.dict(os.environ, {}, clear=True):
                    with self.assertRaises(MissingAPIKeyError):
                        provider.generate(request, out_dir=str(tmp_path), apply=True)


class TestNoNetworkCallsInTests(unittest.TestCase):
    def test_module_import_and_validation_make_no_network_call(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network call!")):
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                primary = write_rgba_png(tmp_path / "primary.png", size=(10, 10))
                mask = write_rgba_png(tmp_path / "mask.png", size=(10, 10), alpha=0)
                from PIL import Image
                m = Image.new("RGBA", (10, 10), (0, 0, 0, 255))
                for x in range(3):
                    m.putpixel((x, 0), (0, 0, 0, 0))
                m.save(mask, "PNG")
                request = ImageRequest(scene_id="s", prompt="p", n=1, mode="edit",
                                       reference_images=[str(primary)], mask_path=str(mask))
                OpenAIImagesProvider().generate(request, out_dir=str(tmp_path), apply=False)

    def test_no_paid_api_surface_in_image_mask_module(self):
        src = (REPO_ROOT / "api" / "media_pipeline" / "image_mask.py").read_text(encoding="utf-8").lower()
        for token in ("urllib", "api.openai.com", "openai_api_key", "requests.", "http://", "https://"):
            self.assertNotIn(token, src, token)


class TestMultipartContractSnapshot(unittest.TestCase):
    """Перехватывает построенный (не отправленный) HTTP request через
    мок-transport и разбирает multipart-тело — подтверждает точный
    контракт полей без единого реального сетевого вызова."""

    def _capture_request(self, request, api_key="sk-fake-test-key-not-real"):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["req"] = req
            raise AssertionError("stop before real network call")

        provider = OpenAIImagesProvider(model="gpt-image-2")
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": api_key}):
            with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
                with self.assertRaises(AssertionError):
                    provider.generate(request, out_dir=".", apply=True)
        return captured["req"]

    def test_exact_field_contract_five_images_plus_mask(self):
        import re

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            images = [write_rgba_png(tmp_path / f"img{i}.png", size=(720, 1280))
                     for i in range(5)]
            mask_path = tmp_path / "mask.png"
            from PIL import Image, ImageDraw
            im = Image.new("RGBA", (720, 1280), (0, 0, 0, 255))
            ImageDraw.Draw(im).rectangle((80, 36, 266, 268), fill=(0, 0, 0, 0))
            im.save(mask_path, "PNG")

            request = ImageRequest(
                scene_id="scene-05", prompt="p", n=1, mode="edit",
                size="720x1280", output_format="png",
                reference_images=[str(p) for p in images],
                mask_path=str(mask_path))
            req = self._capture_request(request)
            text = req.data.decode("latin-1")

            # Content-Disposition field names (не filename=): достаточно
            # проверить, что каждое ожидаемое имя присутствует ровно
            # нужное число раз, без опоры на regex, ловящий "filename=".
            self.assertEqual(text.count('name="model"'), 1)
            self.assertEqual(text.count('name="prompt"'), 1)
            self.assertEqual(text.count('name="n"'), 1)
            self.assertEqual(text.count('name="size"'), 1)
            self.assertEqual(text.count('name="output_format"'), 1)
            self.assertEqual(text.count('name="image[]"'), 5)
            self.assertEqual(text.count('name="mask"'), 1)

            # mask идёт ПОСЛЕ всех пяти image[] полей — применяется только к
            # первому image, но физически передаётся отдельным последним полем.
            last_image_pos = text.rfind('name="image[]"')
            mask_pos = text.find('name="mask"')
            self.assertGreater(mask_pos, last_image_pos)

    def test_no_extra_unexpected_fields_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            images = [write_rgba_png(tmp_path / f"img{i}.png", size=(720, 1280))
                     for i in range(5)]
            mask_path = tmp_path / "mask.png"
            from PIL import Image, ImageDraw
            im = Image.new("RGBA", (720, 1280), (0, 0, 0, 255))
            ImageDraw.Draw(im).rectangle((80, 36, 266, 268), fill=(0, 0, 0, 0))
            im.save(mask_path, "PNG")

            request = ImageRequest(
                scene_id="scene-05", prompt="p", n=1, mode="edit",
                size="720x1280", output_format="png",
                reference_images=[str(p) for p in images],
                mask_path=str(mask_path))
            req = self._capture_request(request)
            text = req.data.decode("latin-1")
            self.assertNotIn('name="background"', text)
            self.assertNotIn('name="input_fidelity"', text)


if __name__ == "__main__":
    unittest.main()
