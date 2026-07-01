"""Тесты content-package моста (валидация + транзакционный импорт + CLI).

Только stdlib (unittest, sqlite3, tempfile) — новых зависимостей нет. Каждый тест — на
ВРЕМЕННОЙ SQLite (config.DB_PATH подменяется), production не трогается.

Запуск:
    python -m unittest api.tests.test_content_package -v
"""
import io
import os
import copy
import json
import tempfile
import unittest
import contextlib

from api import registry_db as R
from api import content_package as CP
from api import import_content_package as CLI

PRODUCT_CODE = "airfryer-silicone-form"


def _base_package():
    return {
        "schema_version": 1,
        "product": {"product_code": PRODUCT_CODE},
        "content": {
            "content_code": "video3-recipes-teaser",
            "content_type": "short_video",
            "title": "Ролик 3",
            "core_idea": "идея",
            "audience_segment": "аудитория",
            "pain_or_desire": "боль",
            "hypothesis": "гипотеза",
            "source_path": "content/video3.md",
            "status": "draft",
        },
        "hooks": [
            {"hook_code": "A", "hook_text": "текст A", "version": 1, "status": "draft"},
            {"hook_code": "B", "hook_text": "текст B", "version": 1, "status": "draft"},
        ],
        "publication_drafts": [
            {
                "publication_code": "video3-recipes-teaser-tiktok",
                "hook_code": "A",
                "channel_code": "tiktok",
                "status": "draft",
                "utm_source": "tiktok",
                "utm_medium": "organic",
                "utm_campaign": "video3",
                "utm_content": "hookA",
            },
            {
                "publication_code": "video3-recipes-teaser-youtube",
                "hook_code": "B",
                "channel_code": "youtube_shorts",
                "status": "draft",
                "utm_source": "youtube_shorts",
                "utm_medium": "organic",
                "utm_campaign": "video3",
                "utm_content": "hookB",
            },
        ],
    }


class ContentPackageTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.dbfile = os.path.join(self.tmpdir, "test.db")
        R.DB_PATH = self.dbfile
        R.run_migrations()
        R.create_or_get_product(PRODUCT_CODE, "Силиконовая форма для аэрогриля")
        for code, name in (("telegram", "Telegram"), ("tiktok", "TikTok"),
                           ("youtube_shorts", "YouTube Shorts")):
            R.create_or_get_channel(code, name)

    def tearDown(self):
        try:
            os.remove(self.dbfile)
        except OSError:
            pass
        try:
            os.rmdir(self.tmpdir)
        except OSError:
            pass

    def _conn(self):
        return R._connect()

    def _counts(self):
        c = self._conn()
        try:
            return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("contents", "hooks", "publications")}
        finally:
            c.close()

    # 1. валидный пакет создаёт content, hooks и draft publications
    def test_valid_package_creates_everything(self):
        result = CP.import_package(_base_package())
        self.assertTrue(result["created"]["content"])
        self.assertEqual(sorted(result["created"]["hooks"]), ["A", "B"])
        self.assertEqual(sorted(result["created"]["publications"]),
                          sorted(["video3-recipes-teaser-tiktok", "video3-recipes-teaser-youtube"]))
        self.assertEqual(self._counts(), {"contents": 1, "hooks": 2, "publications": 2})

    # 2. повторный импорт не создаёт дублей
    def test_repeat_import_no_duplicates(self):
        CP.import_package(_base_package())
        result2 = CP.import_package(_base_package())
        self.assertFalse(result2["created"]["content"])
        self.assertTrue(result2["existing"]["content"])
        self.assertEqual(sorted(result2["existing"]["hooks"]), ["A", "B"])
        self.assertEqual(sorted(result2["existing"]["publications"]),
                          sorted(["video3-recipes-teaser-tiktok", "video3-recipes-teaser-youtube"]))
        self.assertEqual(self._counts(), {"contents": 1, "hooks": 2, "publications": 2})

    # 3. неизвестный channel_code отклоняет весь пакет
    def test_unknown_channel_rejects_whole_package(self):
        pkg = _base_package()
        pkg["publication_drafts"][1]["channel_code"] = "vk_reels_unknown"
        with self.assertRaises(CP.PackageError):
            CP.import_package(pkg)
        self.assertEqual(self._counts(), {"contents": 0, "hooks": 0, "publications": 0})

    # 4. ошибка в одном hook откатывает весь пакет
    def test_bad_hook_rolls_back_whole_package(self):
        pkg = _base_package()
        del pkg["hooks"][1]["hook_code"]
        with self.assertRaises(CP.PackageError):
            CP.import_package(pkg)
        self.assertEqual(self._counts(), {"contents": 0, "hooks": 0, "publications": 0})

    # 5. ошибка в одной publication откатывает весь пакет
    def test_bad_publication_rolls_back_whole_package(self):
        pkg = _base_package()
        pkg["publication_drafts"][1]["hook_code"] = "does-not-exist"
        with self.assertRaises(CP.PackageError):
            CP.import_package(pkg)
        self.assertEqual(self._counts(), {"contents": 0, "hooks": 0, "publications": 0})

    # 6. несуществующий product_code даёт контролируемую ошибку
    def test_missing_product_controlled_error(self):
        pkg = _base_package()
        pkg["product"]["product_code"] = "does-not-exist"
        with self.assertRaises(CP.ProductNotFoundError):
            CP.import_package(pkg)
        self.assertEqual(self._counts(), {"contents": 0, "hooks": 0, "publications": 0})

    # 7. конфликт content_code -> PackageConflict (маппится в HTTP 409 в registry.py)
    def test_content_code_conflict(self):
        CP.import_package(_base_package())
        other_product, _ = R.create_or_get_product("other-product", "Другой товар")
        pkg = _base_package()
        pkg["product"]["product_code"] = "other-product"
        with self.assertRaises(CP.PackageConflict) as ctx:
            CP.import_package(pkg)
        self.assertEqual(ctx.exception.field, "content.content_code")

        # content_type conflict под тем же продуктом
        pkg2 = _base_package()
        pkg2["content"]["content_type"] = "article"
        with self.assertRaises(CP.PackageConflict) as ctx2:
            CP.import_package(pkg2)
        self.assertEqual(ctx2.exception.field, "content.content_type")

    # 8. публикации нельзя создать в статусе published
    def test_published_status_rejected(self):
        pkg = _base_package()
        pkg["publication_drafts"][0]["status"] = "published"
        with self.assertRaises(CP.PackageError):
            CP.import_package(pkg)
        self.assertEqual(self._counts(), {"contents": 0, "hooks": 0, "publications": 0})

    # 9. все публикации после импорта имеют draft
    def test_all_publications_are_draft(self):
        CP.import_package(_base_package())
        c = self._conn()
        try:
            statuses = {r["status"] for r in c.execute("SELECT status FROM publications")}
        finally:
            c.close()
        self.assertEqual(statuses, {"draft"})

    # 10. данные разных hooks сохраняются отдельно
    def test_hooks_saved_separately(self):
        result = CP.import_package(_base_package())
        c = self._conn()
        try:
            rows = {r["hook_code"]: r["hook_text"] for r in c.execute(
                "SELECT hook_code, hook_text FROM hooks WHERE content_id=?", (result["content_id"],))}
        finally:
            c.close()
        self.assertEqual(rows, {"A": "текст A", "B": "текст B"})

    # 11. UTM-поля сохраняются
    def test_utm_fields_saved(self):
        result = CP.import_package(_base_package())
        c = self._conn()
        try:
            row = c.execute(
                "SELECT utm_source, utm_medium, utm_campaign, utm_content FROM publications "
                "WHERE id=?", (result["publication_ids"]["video3-recipes-teaser-tiktok"],)).fetchone()
        finally:
            c.close()
        self.assertEqual(row["utm_source"], "tiktok")
        self.assertEqual(row["utm_medium"], "organic")
        self.assertEqual(row["utm_campaign"], "video3")
        self.assertEqual(row["utm_content"], "hookA")

    # 17. секреты отклоняются до записи и не попадают в исключение молча
    def test_secret_like_field_rejected(self):
        pkg = _base_package()
        pkg["content"]["api_key"] = "sk-should-not-be-here"
        with self.assertRaises(CP.PackageError) as ctx:
            CP.import_package(pkg)
        self.assertIn("secret", str(ctx.exception).lower())
        self.assertEqual(self._counts(), {"contents": 0, "hooks": 0, "publications": 0})

    # существующие редактируемые поля не перезаписываются молча -> warning
    def test_editable_field_diff_gives_warning_not_overwrite(self):
        CP.import_package(_base_package())
        pkg = _base_package()
        pkg["content"]["title"] = "Другой заголовок"
        result = CP.import_package(pkg)
        self.assertTrue(any("title" in w for w in result["warnings"]))
        content = R.get_content(result["content_id"])
        self.assertEqual(content["title"], "Ролик 3")  # не перезаписан


class ImportContentPackageCLITests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.dbfile = os.path.join(self.tmpdir, "test.db")
        self.pkgfile = os.path.join(self.tmpdir, "pkg.json")
        R.DB_PATH = self.dbfile
        R.run_migrations()
        R.create_or_get_product(PRODUCT_CODE, "Силиконовая форма для аэрогриля")
        for code, name in (("tiktok", "TikTok"), ("youtube_shorts", "YouTube Shorts")):
            R.create_or_get_channel(code, name)
        with open(self.pkgfile, "w", encoding="utf-8") as f:
            json.dump(_base_package(), f, ensure_ascii=False)

    def tearDown(self):
        for p in (self.dbfile, self.pkgfile):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(self.tmpdir)
        except OSError:
            pass

    def _counts(self):
        c = R._connect()
        try:
            return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("contents", "hooks", "publications")}
        finally:
            c.close()

    def _run_cli(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = CLI.main([self.pkgfile, "--db-path", self.dbfile, *args])
        return code, buf.getvalue()

    # 12. CLI dry-run не изменяет базу
    def test_cli_dry_run_no_writes(self):
        code, out = self._run_cli()
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["mode"], "dry-run")
        self.assertEqual(payload["conflicts"], [])
        self.assertEqual(self._counts(), {"contents": 0, "hooks": 0, "publications": 0})

    # 13. CLI --apply изменяет только временную базу
    def test_cli_apply_writes_to_given_db(self):
        code, out = self._run_cli("--apply")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["mode"], "apply")
        self.assertEqual(self._counts(), {"contents": 1, "hooks": 2, "publications": 2})

    # 14. повторный CLI --apply не создаёт дублей
    def test_cli_apply_twice_no_duplicates(self):
        self._run_cli("--apply")
        code, out = self._run_cli("--apply")
        self.assertEqual(code, 0)
        self.assertEqual(self._counts(), {"contents": 1, "hooks": 2, "publications": 2})

    def test_cli_dry_run_reports_conflicts_nonzero_exit(self):
        pkg = _base_package()
        pkg["product"]["product_code"] = "does-not-exist"
        with open(self.pkgfile, "w", encoding="utf-8") as f:
            json.dump(pkg, f, ensure_ascii=False)
        code, out = self._run_cli()
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertTrue(payload["conflicts"])
        self.assertEqual(self._counts(), {"contents": 0, "hooks": 0, "publications": 0})


if __name__ == "__main__":
    unittest.main(verbosity=2)
