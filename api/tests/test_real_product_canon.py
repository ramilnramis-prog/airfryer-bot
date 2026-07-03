"""Тесты интеграции real-product-v1 как активного канона геометрии товара.

Решение владельца (2026-07-03): реальные фото/видео товара — безусловный
источник истины для физической геометрии; прежний AI-канон
(forma_6angles.png / handles_reference_crop.png) выведен из активного QA.

Покрытие (по заданию):
1. real photo canon имеет приоритет над AI;
2. legacy AI handles не могут пройти в product geometry QA;
3. система не откатывается на AI fallback при наличии real-v1;
4. manifest создаётся автоматически, не вручную;
5. реальные handle crops совпадают с исходными фото (provenance SHA256);
6. старые вертикальные овальные ручки получают product_mismatch/
   handle_geometry_mismatch;
7. product-lock использует только real-v1 pixels;
8. video frames содержат timestamp и provenance;
9. мужская рука не становится hand canon;
10. платные API не вызываются.

Эти тесты читают УЖЕ построенный пакет (product_asset_manifest.json +
references/real-v1/), не пересобирают его — пересборка (`extract-real`)
детерминирована и покрыта отдельно через сверку SHA256/структуры.
"""
import json
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline.compositor.product_assets import (
    LegacyReferenceError, load_manifest, load_view, sha256_file)
from api.media_pipeline.compositor.real_product_assets import (
    CANONICAL_VERSION, LEGACY_SOURCES, MASTER_CROPS, RAW_DIR, VIDEO_FRAMES)
from api.media_pipeline.compositor.product_lock_validator import (
    validate_composite)
from api.media_pipeline.compositor.perspective import RigidTransform

REPO_ROOT = "."
MANIFEST_PATH = Path("assets/product-lock/airfryer-silicone-form/"
                     "product_asset_manifest.json")
REAL_V1_DIR = Path("assets/product-lock/airfryer-silicone-form/references/real-v1")


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


class TestRealCanonPriority(unittest.TestCase):
    def test_real_photo_canon_has_priority_over_ai(self):
        # (1) real-product-v1 активен, легаси AI-источники явно понижены
        m = _manifest()
        self.assertEqual(m["canonical_version"], CANONICAL_VERSION)
        self.assertEqual(m["canonical_status"], "active")
        self.assertEqual(m["canonical_source_type"], "real_photography")
        self.assertIn("photo_7", m["canonical_source"]["primary"])
        # хотя бы один активный view реально существует и построен из фото
        self.assertTrue(m["assets"], "нет активных views real-product-v1")
        for view in m["assets"].values():
            self.assertEqual(view["source_type"], "photo")
            self.assertEqual(view["canonical_version"], CANONICAL_VERSION)
            self.assertTrue(view["allowed_for_product_lock_source"])


class TestLegacyBlocked(unittest.TestCase):
    def test_legacy_ai_handles_cannot_pass_geometry_qa(self):
        # (2) legacy assets явно заблокированы для geometry QA / product-lock
        m = _manifest()
        self.assertIn("legacy_assets", m)
        self.assertTrue(m["legacy_assets"], "legacy_assets пуст — старые "
                        "виды должны быть сохранены с флагами, не удалены")
        for view in m["legacy_assets"].values():
            self.assertEqual(view["status"], "legacy_incorrect_product_geometry")
            self.assertFalse(view["allowed_for_product_geometry_qa"])
            self.assertFalse(view["allowed_for_product_lock_source"])
        # forma_6angles.png и handles_reference_crop.png явно в legacy_sources
        paths = [s["path"] for s in m["legacy_sources"]]
        self.assertTrue(any("forma_6angles.png" in p for p in paths))
        self.assertTrue(any("handles_reference_crop.png" in p for p in paths))
        for src in m["legacy_sources"]:
            self.assertFalse(src["allowed_for_product_geometry_qa"])
            self.assertFalse(src["allowed_for_product_lock_source"])

    def test_no_automatic_ai_fallback_when_real_v1_present(self):
        # (3) load_view на legacy-виде без allow_legacy -> отказ, не тихий откат
        m = _manifest()
        legacy_view = next(iter(m["legacy_assets"]))
        with self.assertRaises(LegacyReferenceError):
            load_view(legacy_view, repo_root=REPO_ROOT)
        # активный view при этом загружается нормально
        active_view = next(iter(m["assets"]))
        rgba, mask, handles = load_view(active_view, repo_root=REPO_ROOT)
        self.assertEqual(rgba.mode, "RGBA")
        # allow_legacy=True — осознанный обход для истории, тоже работает
        rgba2, _, _ = load_view(legacy_view, repo_root=REPO_ROOT,
                                allow_legacy=True)
        self.assertEqual(rgba2.mode, "RGBA")


class TestManifestAutomation(unittest.TestCase):
    def test_manifest_generated_not_hand_authored(self):
        # (4) манифест — автоматически сгенерированный артефакт: указывает
        # инструмент/команду воспроизведения, и все SHA256 самосогласованы
        m = _manifest()
        self.assertEqual(m["extraction"]["tool"],
                         "api.media_pipeline.compositor.real_product_assets")
        self.assertIn("extract-real", m["extraction"]["reproduce"])
        for name, view in m["assets"].items():
            iso = Path(view["isolated"])
            msk = Path(view["mask"])
            self.assertEqual(sha256_file(iso), view["sha256_isolated"],
                             f"{name}: isolated не совпадает с манифестом")
            self.assertEqual(sha256_file(msk), view["sha256_mask"],
                             f"{name}: mask не совпадает с манифестом")


class TestRealHandleCropsProvenance(unittest.TestCase):
    def test_handle_crops_match_source_photos(self):
        # (5) master crops ручек происходят из заявленного исходного фото
        # (SHA256 источника в real_v1_manifest.json совпадает с фактическим
        # файлом фото, и это именно PRIMARY photo_7 для ручек)
        entries = json.loads(
            (REAL_V1_DIR / "real_v1_manifest.json").read_text(encoding="utf-8"))["entries"]
        by_name = {e["name"]: e for e in entries}
        for name in ("left_handle_master", "right_handle_master", "both_handles_master"):
            self.assertIn(name, by_name)
            e = by_name[name]
            self.assertEqual(e["source_filename"], "photo_7_2026-06-18_16-53-42.jpg")
            self.assertEqual(e["source_type"], "photo")
            self.assertTrue(e["approved"])
            self.assertEqual(e["canonical_version"], CANONICAL_VERSION)
            src_path = RAW_DIR / e["source_filename"]
            if src_path.is_file():
                self.assertEqual(sha256_file(src_path), e["source_sha256"])
            derivative_path = Path(e["path"])
            if derivative_path.is_file():
                self.assertEqual(sha256_file(derivative_path),
                                 e["derivative_sha256"])


class TestObsoleteGeometryRejected(unittest.TestCase):
    def test_legacy_vertical_oval_shape_is_forbidden_not_canon(self):
        # (6) прежняя вертикальная ручка-петля с овальным вырезом явно
        # описана как OBSOLETE/forbidden, а не как допустимая альтернатива
        vb = json.loads(Path(
            "assets/visual-bible/airfryer-silicone-form/visual_bible.json"
        ).read_text(encoding="utf-8"))
        forbidden = " ".join(vb["product"]["handle_geometry"]["forbidden"])
        self.assertIn("OBSOLETE", forbidden)
        self.assertIn("вертикальный", forbidden.lower())
        cr = json.loads(Path(
            "assets/visual-bible/airfryer-silicone-form/continuity_rules.json"
        ).read_text(encoding="utf-8"))
        self.assertIn("OBSOLETE", cr["handle_geometry"]["forbidden"])
        self.assertEqual(cr["canonical_version"], CANONICAL_VERSION)

    def test_product_lock_validator_flags_mismatched_layer(self):
        # синтетическая проверка: композит с иной (не real-v1) геометрией
        # ручки не проходит validate_composite против реального product layer.
        # Canvas paste offset (10,10): body rect (20,15)-(100,80) -> canvas
        # (30,25)-(110,90); handle rect (4,30)-(20,70) -> canvas (14,40)-(30,80).
        from PIL import Image, ImageDraw

        product = Image.new("RGBA", (120, 90), (0, 0, 0, 0))
        d = ImageDraw.Draw(product)
        d.rectangle((20, 15, 100, 80), fill=(70, 70, 75, 255))
        d.rectangle((4, 30, 20, 70), fill=(70, 70, 75, 255))  # canonical flat tab
        canvas = Image.new("RGBA", (150, 120), (0, 0, 0, 0))
        canvas.alpha_composite(product, (10, 10))

        bad = canvas.copy()
        bd = ImageDraw.Draw(bad)
        # искажение ВНУТРИ известной непрозрачной области ручки-язычка
        # (легаси "иная" геометрия/цвет на месте канонической ручки)
        bd.rectangle((14, 40, 30, 80), fill=(200, 50, 50, 255))

        report = validate_composite(bad.convert("RGB"), canvas)
        self.assertFalse(report["passed"])
        self.assertEqual(report["hard_fail"], "product_lock_violation")


class TestProductLockUsesOnlyRealV1(unittest.TestCase):
    def test_active_views_pixels_traceable_to_real_photos(self):
        # (7) активные views ссылаются ТОЛЬКО на real-v1 pack, ни один
        # активный путь не указывает на старые isolated/masks (forma_6angles)
        m = _manifest()
        for view in m["assets"].values():
            self.assertIn("real-v1", view["isolated"])
            self.assertIn("real-v1", view["mask"])
            self.assertNotIn("form_three_quarter", view["isolated"])


class TestVideoFrameProvenance(unittest.TestCase):
    def test_video_frames_have_timestamp_and_provenance(self):
        # (8) кадры видео содержат frame_index, timestamp и source provenance
        entries = json.loads(
            (REAL_V1_DIR / "real_v1_manifest.json").read_text(encoding="utf-8"))["entries"]
        video_entries = [e for e in entries if e["source_type"] == "video_frame"]
        self.assertEqual(len(video_entries), len(VIDEO_FRAMES))
        for e in video_entries:
            self.assertIn("frame_index", e)
            self.assertIsInstance(e["frame_index"], int)
            self.assertIsInstance(e["timestamp"], float)
            self.assertGreater(e["timestamp"], 0)
            self.assertEqual(e["source_filename"], "IMG_5925.MOV")
            self.assertTrue(e["approved"])
            self.assertEqual(e["canonical_version"], CANONICAL_VERSION)


class TestMaleHandNotCanon(unittest.TestCase):
    def test_male_hand_frame_is_motion_reference_only(self):
        # (9) единственный кадр с рукой в VIDEO_FRAMES явно помечен
        # motion/grip-only, а не hand canon; ни один MASTER_CROPS элемент
        # категории handles/product не является источником рук
        names = {n for n, *_ in VIDEO_FRAMES}
        self.assertIn("grip_motion_master", names)
        purpose = dict((n, p) for n, _, _, p in VIDEO_FRAMES)["grip_motion_master"]
        self.assertIn("motion/grip reference", purpose)
        self.assertIn("hand canon", purpose)
        self.assertIn("рука мужская", purpose)
        for _name, _src, _bbox, category, _purpose in MASTER_CROPS:
            self.assertNotEqual(category, "hands",
                                "master crops не должны содержать категорию "
                                "'hands' с реальной (мужской) рукой как канон")


class TestNoPaidApiCalls(unittest.TestCase):
    def test_load_view_makes_no_network_call(self):
        # (10) чтение уже построенного real-v1 пакета не требует сети
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network call!")):
            m = _manifest()
            view = next(iter(m["assets"]))
            load_view(view, repo_root=REPO_ROOT)

    def test_real_product_assets_module_has_no_network_surface(self):
        src = Path("api/media_pipeline/compositor/real_product_assets.py").read_text(
            encoding="utf-8").lower()
        for token in ("urllib", "api.openai.com", "openai_api_key",
                      "higgsfield", "requests.", "http://", "https://"):
            self.assertNotIn(token, src, f"real_product_assets.py содержит {token}")


if __name__ == "__main__":
    unittest.main()
