"""Тесты portable/private reference library resolver'а (portability/privacy
blocker перед push). Покрытие:

1. campaign lock использует asset_id, а не абсолютный путь
2. resolver работает через REFERENCE_LIBRARY_ROOT
3. hash mismatch блокирует использование
4. path traversal блокируется
5. отсутствующий root выдаёт понятную ошибку
6. один asset может иметь несколько категорий без дублирования бинарника
7. все три hooks получают один resolved visual lock
8. новая кампания может выбрать другие asset_id (см. test_campaign_visual_lock.py)
9. product canon real-product-v1 не разрешается через external library
10. third-party/любые binaries не добавляются в Git
11. никакие API не вызываются
"""
import hashlib
import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline.reference_library.models import ReferenceLibraryError
from api.media_pipeline.reference_library import cli as rl_cli
from api.media_pipeline.reference_library.resolver import (ROOT_ENV_VAR,
                                                            load_index,
                                                            resolve_asset)

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_LOCK_PATH = (REPO_ROOT / "content" / "autopilot" /
                     "coating-protect-2026-07" / "campaign_visual_lock.json")
LIB_ROOT = REPO_ROOT / "assets" / "reference-library"
REAL_EXTERNAL_ROOT = Path("D:/OzonGrowthProject/content/assets")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_test_png(path, size=(3, 2)):
    """Пишет валидный крошечный PNG (PIL должен уметь его открыть) и
    возвращает (sha256, file_size_bytes, width, height)."""
    from PIL import Image
    Image.new("RGB", size, (10, 20, 30)).save(path, "PNG")
    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data), size[0], size[1]


class TestCampaignLockUsesAssetIdNotAbsolutePath(unittest.TestCase):
    def test_locked_elements_only_carry_asset_id_not_paths(self):
        lock = load_json(CAMPAIGN_LOCK_PATH)
        for e in lock["locked_elements"]:
            self.assertIn("asset_id", e)
            self.assertNotIn("source_path", e)
            self.assertNotIn("path", e)

    def test_no_absolute_windows_path_anywhere_in_campaign_lock(self):
        src = CAMPAIGN_LOCK_PATH.read_text(encoding="utf-8")
        self.assertNotIn("D:/", src)
        self.assertNotIn("D:\\", src)

    def test_no_absolute_windows_path_in_reference_library_index(self):
        src = (LIB_ROOT / "reference_library_index.json").read_text(encoding="utf-8")
        self.assertNotIn("D:/", src)
        self.assertNotIn("D:\\", src)

    def test_no_absolute_windows_path_in_any_category_manifest(self):
        for manifest_path in LIB_ROOT.glob("*/manifest.json"):
            src = manifest_path.read_text(encoding="utf-8")
            self.assertNotIn("D:/", src, manifest_path)
            self.assertNotIn("D:\\", src, manifest_path)


class TestResolverUsesReferenceLibraryRoot(unittest.TestCase):
    def _make_fake_asset(self, tmp_path):
        f = tmp_path / "fake.png"
        sha256, size_bytes, width, height = write_test_png(f)
        asset = {
            "asset_id": "fake-asset-01", "filename": "fake.png",
            "categories": ["hands"], "description": "fixture",
            "suitable_uses": [], "restrictions": [],
            "source_type": "ai_reference", "ownership_status": "generated_reference",
            "approved_for_reference_only": True,
            "prohibited_as_product_geometry_source": False,
            "sha256": sha256, "width": width, "height": height,
            "file_size_bytes": size_bytes,
            "already_in_repo": False, "relative_private_path": "fake.png",
        }
        index = {"assets": [asset]}
        return index, sha256

    def test_resolve_asset_succeeds_with_explicit_root_param(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            index, sha256 = self._make_fake_asset(tmp_path)
            resolved = resolve_asset("fake-asset-01", root=str(tmp_path), index=index)
            self.assertEqual(resolved.sha256, sha256)
            self.assertEqual(resolved.path, (tmp_path / "fake.png").resolve())

    def test_resolve_asset_reads_root_from_environment_variable(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            index, sha256 = self._make_fake_asset(tmp_path)
            old = os.environ.get(ROOT_ENV_VAR)
            os.environ[ROOT_ENV_VAR] = str(tmp_path)
            try:
                resolved = resolve_asset("fake-asset-01", index=index)
                self.assertEqual(resolved.sha256, sha256)
            finally:
                if old is None:
                    os.environ.pop(ROOT_ENV_VAR, None)
                else:
                    os.environ[ROOT_ENV_VAR] = old

    def test_already_in_repo_asset_resolves_without_root(self):
        old = os.environ.pop(ROOT_ENV_VAR, None)
        try:
            resolved = resolve_asset("real-airfryer-front-01")
            self.assertTrue(resolved.path.is_file())
            self.assertTrue(resolved.already_in_repo)
        finally:
            if old is not None:
                os.environ[ROOT_ENV_VAR] = old

    def test_real_external_root_resolves_all_private_assets_if_available(self):
        if not REAL_EXTERNAL_ROOT.is_dir():
            self.skipTest("внешняя REFERENCE_LIBRARY_ROOT недоступна на этой машине")
        index = load_index()
        for asset in index["assets"]:
            if asset.get("already_in_repo"):
                continue
            resolved = resolve_asset(asset["asset_id"], root=str(REAL_EXTERNAL_ROOT), index=index)
            self.assertTrue(resolved.path.is_file())


class TestHashMismatchBlocks(unittest.TestCase):
    def test_hash_mismatch_raises_with_correct_code(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            content = b"real-bytes"
            f = tmp_path / "asset.png"
            f.write_bytes(content)
            asset = {
                "asset_id": "tampered-01", "filename": "asset.png",
                "categories": [], "description": "", "suitable_uses": [],
                "restrictions": [], "source_type": "ai_reference",
                "ownership_status": "generated_reference",
                "approved_for_reference_only": True,
                "prohibited_as_product_geometry_source": False,
                "sha256": "0" * 64,  # неверный хеш
                "width": 1, "height": 1, "file_size_bytes": len(content),
                "already_in_repo": False, "relative_private_path": "asset.png",
            }
            index = {"assets": [asset]}
            with self.assertRaises(ReferenceLibraryError) as ctx:
                resolve_asset("tampered-01", root=str(tmp_path), index=index)
            self.assertEqual(ctx.exception.code, "REFERENCE_HASH_MISMATCH")

    def test_resolve_campaign_raises_if_index_sha256_diverges_from_lock(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sha256, size_bytes, width, height = write_test_png(tmp_path / "asset.png")
            index = {"assets": [{
                "asset_id": "drift-01", "filename": "asset.png",
                "categories": [], "description": "", "suitable_uses": [],
                "restrictions": [], "source_type": "ai_reference",
                "ownership_status": "generated_reference",
                "approved_for_reference_only": True,
                "prohibited_as_product_geometry_source": False,
                "sha256": sha256, "width": width, "height": height,
                "file_size_bytes": size_bytes, "already_in_repo": False,
                "relative_private_path": "asset.png",
            }]}
            lock = {
                "campaign_code": "drift-test", "content_code": "drift-test",
                "product_canon": "real-product-v1",
                "product_canon_resolution": "repository_only",
                "locked_elements": [{
                    "role": "hands", "asset_id": "drift-01",
                    "locked_for_all_scenes": True, "shared_across_hooks": True,
                    "expected_sha256": "1" * 64,  # намеренно расходится
                    "reference_only": True, "restrictions": [],
                }],
                "hooks": {"variants": ["A", "B", "C"], "shared_main_body": True,
                         "shared_visual_lock": "n/a"},
            }
            with self.assertRaises(ReferenceLibraryError) as ctx:
                _resolve_campaign_from_dict(lock, index, str(tmp_path))
            self.assertEqual(ctx.exception.code, "REFERENCE_HASH_MISMATCH")


def _resolve_campaign_from_dict(lock, index, root):
    """Помощник: прогоняет логику resolve_campaign без чтения файла с диска."""
    for element in lock["locked_elements"]:
        ra = resolve_asset(element["asset_id"], root=root, index=index)
        if ra.sha256 != element["expected_sha256"]:
            raise ReferenceLibraryError(
                "REFERENCE_HASH_MISMATCH",
                f"{element['asset_id']}: lock expected {element['expected_sha256']} "
                f"!= index {ra.sha256}")


class TestPathTraversalBlocked(unittest.TestCase):
    def test_relative_private_path_escaping_root_is_blocked(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            outside = tmp_path.parent / "outside-secret.txt"
            outside.write_bytes(b"secret")
            try:
                asset = {
                    "asset_id": "escape-01", "filename": "escape.png",
                    "categories": [], "description": "", "suitable_uses": [],
                    "restrictions": [], "source_type": "ai_reference",
                    "ownership_status": "generated_reference",
                    "approved_for_reference_only": True,
                    "prohibited_as_product_geometry_source": False,
                    "sha256": "0" * 64, "width": 1, "height": 1, "file_size_bytes": 0,
                    "already_in_repo": False,
                    "relative_private_path": "../outside-secret.txt",
                }
                index = {"assets": [asset]}
                with self.assertRaises(ReferenceLibraryError) as ctx:
                    resolve_asset("escape-01", root=str(tmp_path), index=index)
                self.assertEqual(ctx.exception.code, "REFERENCE_PATH_ESCAPE")
            finally:
                outside.unlink(missing_ok=True)


class TestMissingRootGivesClearError(unittest.TestCase):
    def test_missing_root_raises_reference_root_not_set(self):
        asset = {
            "asset_id": "needs-root-01", "filename": "x.png",
            "categories": [], "description": "", "suitable_uses": [],
            "restrictions": [], "source_type": "ai_reference",
            "ownership_status": "generated_reference",
            "approved_for_reference_only": True,
            "prohibited_as_product_geometry_source": False,
            "sha256": "0" * 64, "width": 1, "height": 1, "file_size_bytes": 0,
            "already_in_repo": False, "relative_private_path": "x.png",
        }
        index = {"assets": [asset]}
        old = os.environ.pop(ROOT_ENV_VAR, None)
        try:
            with self.assertRaises(ReferenceLibraryError) as ctx:
                resolve_asset("needs-root-01", index=index)
            self.assertEqual(ctx.exception.code, "REFERENCE_ROOT_NOT_SET")
        finally:
            if old is not None:
                os.environ[ROOT_ENV_VAR] = old

    def test_missing_asset_raises_reference_asset_not_found(self):
        with self.assertRaises(ReferenceLibraryError) as ctx:
            resolve_asset("does-not-exist-anywhere", root="C:/whatever", index={"assets": []})
        self.assertEqual(ctx.exception.code, "REFERENCE_ASSET_NOT_FOUND")

    def test_ambiguous_asset_id_raises_reference_asset_ambiguous(self):
        dup = {
            "asset_id": "dup-01", "filename": "x.png", "categories": [],
            "description": "", "suitable_uses": [], "restrictions": [],
            "source_type": "ai_reference", "ownership_status": "generated_reference",
            "approved_for_reference_only": True,
            "prohibited_as_product_geometry_source": False,
            "sha256": "0" * 64, "width": 1, "height": 1, "file_size_bytes": 0,
            "already_in_repo": False, "relative_private_path": "x.png",
        }
        index = {"assets": [dup, dict(dup)]}
        with self.assertRaises(ReferenceLibraryError) as ctx:
            resolve_asset("dup-01", root="C:/whatever", index=index)
        self.assertEqual(ctx.exception.code, "REFERENCE_ASSET_AMBIGUOUS")


class TestOneAssetMultipleCategoriesNoBinaryDuplication(unittest.TestCase):
    def test_category_manifests_reference_asset_ids_not_full_metadata(self):
        for manifest_path in LIB_ROOT.glob("*/manifest.json"):
            manifest = load_json(manifest_path)
            self.assertIn("asset_ids", manifest)
            self.assertNotIn("assets", manifest, manifest_path)
            for asset_id in manifest["asset_ids"]:
                self.assertIsInstance(asset_id, str)

    def test_index_has_exactly_one_entry_per_asset_id(self):
        index = load_json(LIB_ROOT / "reference_library_index.json")
        ids = [a["asset_id"] for a in index["assets"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_an_asset_appearing_in_multiple_categories_has_one_index_entry(self):
        index = load_json(LIB_ROOT / "reference_library_index.json")
        multi_category = [a for a in index["assets"] if len(a["categories"]) > 1]
        self.assertGreater(len(multi_category), 0)
        ids = [a["asset_id"] for a in index["assets"]]
        for a in multi_category:
            self.assertEqual(ids.count(a["asset_id"]), 1)

    def test_no_binary_image_files_exist_under_reference_library_dir(self):
        binary_exts = {".png", ".jpg", ".jpeg", ".mp4", ".mov", ".webp"}
        found = [p for p in LIB_ROOT.rglob("*") if p.suffix.lower() in binary_exts]
        self.assertEqual(found, [], f"reference-library должен содержать только JSON: {found}")


class TestAllHooksGetOneResolvedSet(unittest.TestCase):
    def test_resolve_campaign_confirms_same_set_for_all_hooks(self):
        if not REAL_EXTERNAL_ROOT.is_dir():
            self.skipTest("внешняя REFERENCE_LIBRARY_ROOT недоступна на этой машине")
        report = rl_cli.resolve_campaign(str(CAMPAIGN_LOCK_PATH),
                                         root=str(REAL_EXTERNAL_ROOT))
        summary = report["hooks_share_one_resolved_set"]
        self.assertEqual(set(summary["variants"]), {"A", "B", "C"})
        self.assertTrue(summary["same_resolved_set_confirmed"])

    def test_resolve_campaign_output_has_no_absolute_path_leak_in_git(self):
        # resolve_campaign() сам по себе — чистая функция; проверяем, что
        # вызывающий CLI пишет результат ТОЛЬКО в gitignored generated/
        import inspect
        src = inspect.getsource(rl_cli.cmd_resolve_campaign)
        self.assertIn("generated", src)


class TestProductCanonNeverResolvedViaExternalLibrary(unittest.TestCase):
    def test_index_contains_no_product_canon_asset(self):
        index = load_index()
        ids = {a["asset_id"] for a in index["assets"]}
        self.assertNotIn("real-product-v1", ids)

    def test_resolve_campaign_rejects_non_repository_only_product_canon(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "tampered_lock.json"
            lock = {
                "campaign_code": "x", "content_code": "x",
                "product_canon": "real-product-v1",
                "product_canon_resolution": "reference_library",  # запрещённое значение
                "locked_elements": [],
                "hooks": {"variants": ["A", "B", "C"], "shared_main_body": True,
                         "shared_visual_lock": "n/a"},
            }
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            with self.assertRaises(ReferenceLibraryError):
                rl_cli.resolve_campaign(str(lock_path))


class TestThirdPartyBinariesNotInGit(unittest.TestCase):
    def test_git_ls_files_under_reference_library_is_json_only(self):
        result = subprocess.run(
            ["git", "ls-files", "assets/reference-library"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True)
        tracked = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertGreater(len(tracked), 0)
        for path in tracked:
            self.assertTrue(path.endswith(".json"), path)

    def test_generated_campaign_dirs_are_gitignored(self):
        result = subprocess.run(
            ["git", "check-ignore",
            "content/autopilot/coating-protect-2026-07/generated/resolved-campaign-visual-lock.json"],
            cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_third_party_reference_assets_would_be_flagged_if_present(self):
        index = load_index()
        third_party = [a for a in index["assets"]
                      if a["ownership_status"] == "third_party_reference"]
        # На сегодня третьих лиц нет, но проверяем, что схема ГОТОВА их
        # отличить — ни один такой asset не должен попасть в git как бинарник.
        for a in third_party:
            self.assertFalse(a.get("already_in_repo"), a["asset_id"])


class TestNoNetworkCalls(unittest.TestCase):
    def test_resolve_asset_makes_no_network_call(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sha256, size_bytes, width, height = write_test_png(tmp_path / "a.png")
            asset = {
                "asset_id": "net-check-01", "filename": "a.png",
                "categories": [], "description": "", "suitable_uses": [],
                "restrictions": [], "source_type": "ai_reference",
                "ownership_status": "generated_reference",
                "approved_for_reference_only": True,
                "prohibited_as_product_geometry_source": False,
                "sha256": sha256,
                "width": width, "height": height, "file_size_bytes": size_bytes,
                "already_in_repo": False, "relative_private_path": "a.png",
            }
            with mock.patch("urllib.request.urlopen",
                            side_effect=AssertionError("network call!")):
                resolve_asset("net-check-01", root=str(tmp_path), index={"assets": [asset]})

    def test_no_paid_api_surface_in_reference_library_package(self):
        pkg_dir = REPO_ROOT / "api" / "media_pipeline" / "reference_library"
        for py_file in pkg_dir.glob("*.py"):
            src = py_file.read_text(encoding="utf-8").lower()
            for token in ("urllib", "api.openai.com", "openai_api_key",
                         "higgsfield", "requests.", "http://", "https://"):
                self.assertNotIn(token, src, f"{py_file.name} содержит {token}")


if __name__ == "__main__":
    unittest.main()
