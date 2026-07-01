"""Тесты реестра. Только stdlib (unittest, sqlite3, asyncio) — новых зависимостей нет.

Запуск из папки telegram-bot/:
    python -m unittest api.tests.test_registry -v

Каждый тест работает на ВРЕМЕННОЙ копии БД (config.DB_PATH подменяется) — production не трогается.
"""
import os
import sqlite3
import asyncio
import tempfile
import unittest

from api import registry_db, db, auth, config
from api.seed_registry import seed


def _indexes(conn):
    return {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.dbfile = os.path.join(self.tmpdir, "test.db")
        registry_db.DB_PATH = self.dbfile
        db.DB_PATH = self.dbfile
        registry_db.run_migrations()
        db.init_db()

    def tearDown(self):
        for p in (self.dbfile,):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(self.tmpdir)
        except OSError:
            pass

    # ---- миграция ----
    def test_migration_applied_and_idempotent(self):
        self.assertTrue(registry_db.schema_present())
        registry_db.run_migrations()  # повторно — не должно ломать/дублировать
        c = registry_db._connect()
        try:
            vers = [r["version"] for r in c.execute("SELECT version FROM schema_version")]
        finally:
            c.close()
        self.assertEqual(vers, [1])

    def test_expression_and_partial_indexes_exist(self):
        c = registry_db._connect()
        try:
            idx = _indexes(c)
        finally:
            c.close()
        for name in ("ux_products_code", "ux_products_external", "ux_contents_code",
                     "ux_hooks_key", "ux_channels_code", "ux_publications_code",
                     "ux_publications_external", "ux_metric_snapshot",
                     "ux_commerce_pub", "ux_commerce_nopub"):
            self.assertIn(name, idx)

    def test_foreign_keys_pragma_on(self):
        c = registry_db._connect()
        try:
            self.assertEqual(c.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        finally:
            c.close()

    # ---- jobs не сломан ----
    def test_jobs_queue_still_works(self):
        db.create_job("job-1", "generate-pdf")
        self.assertEqual(db.get_job("job-1")["status"], "queued")
        p, _ = registry_db.create_or_get_product("c-x", "X")
        self.assertIsNotNone(p["id"])

    # ---- стабильные коды / идемпотентность ----
    def test_product_code_unique(self):
        a, ca = registry_db.create_or_get_product("airfryer-silicone-form", "Форма")
        b, cb = registry_db.create_or_get_product("airfryer-silicone-form", "Другое имя")
        self.assertTrue(ca); self.assertFalse(cb)
        self.assertEqual(a["id"], b["id"])

    def test_content_code_unique_within_product(self):
        p, _ = registry_db.create_or_get_product("p", "P")
        c1, x1 = registry_db.create_or_get_content(p["id"], "v1", "video", "T")
        c2, x2 = registry_db.create_or_get_content(p["id"], "v1", "video", "T изменён")
        self.assertTrue(x1); self.assertFalse(x2)
        self.assertEqual(c1["id"], c2["id"])

    def test_name_change_no_new_product(self):
        p1, _ = registry_db.create_or_get_product("p", "Имя1")
        registry_db.update_product("p", name="Имя2")
        p2, created = registry_db.create_or_get_product("p", "Имя3")
        self.assertFalse(created)
        self.assertEqual(p1["id"], p2["id"])
        self.assertEqual(registry_db.get_product_by_code("p")["name"], "Имя2")

    def test_add_external_id_updates_same_product(self):
        p1, _ = registry_db.create_or_get_product("p", "P")  # без external_id
        self.assertIsNone(p1["external_id"])
        upd = registry_db.update_product("p", external_id="1931921872")
        self.assertEqual(upd["external_id"], "1931921872")
        self.assertEqual(upd["id"], p1["id"])
        p2, created = registry_db.create_or_get_product("p", "P")
        self.assertFalse(created)
        self.assertEqual(p2["id"], p1["id"])

    def test_title_change_no_new_content(self):
        p, _ = registry_db.create_or_get_product("p", "P")
        c1, _ = registry_db.create_or_get_content(p["id"], "v1", "video", "Заголовок A")
        registry_db.update_content(c1["id"], title="Заголовок B")
        c2, created = registry_db.create_or_get_content(p["id"], "v1", "video", "Заголовок C")
        self.assertFalse(created)
        self.assertEqual(c1["id"], c2["id"])

    def test_hooks_separate(self):
        p, _ = registry_db.create_or_get_product("p", "P")
        c, _ = registry_db.create_or_get_content(p["id"], "v1", "video", "T")
        ha, _ = registry_db.add_hook(c["id"], "A", "текст A")
        hb, _ = registry_db.add_hook(c["id"], "B", "текст B")
        ha2, cr = registry_db.add_hook(c["id"], "A", "другой")
        self.assertNotEqual(ha["id"], hb["id"])
        self.assertFalse(cr); self.assertEqual(ha["id"], ha2["id"])
        self.assertEqual(len(registry_db.get_hooks(c["id"])), 2)

    def test_publication_code_unique(self):
        p, _ = registry_db.create_or_get_product("p", "P")
        c, _ = registry_db.create_or_get_content(p["id"], "v1", "video", "T")
        ch, _ = registry_db.create_or_get_channel("telegram", "TG")
        a, ca = registry_db.create_or_get_publication(c["id"], ch["id"], "pub-1")
        b, cb = registry_db.create_or_get_publication(c["id"], ch["id"], "pub-1")
        self.assertTrue(ca); self.assertFalse(cb)
        self.assertEqual(a["id"], b["id"])

    # ---- foreign keys реально отклоняют orphan ----
    def test_fk_rejects_orphans(self):
        p, _ = registry_db.create_or_get_product("p", "P")
        c, _ = registry_db.create_or_get_content(p["id"], "v1", "video", "T")
        ch, _ = registry_db.create_or_get_channel("telegram", "TG")
        pub, _ = registry_db.create_or_get_publication(c["id"], ch["id"], "pub-1")
        with self.assertRaises(sqlite3.IntegrityError):
            registry_db.create_or_get_content(999999, "v9", "video", "X")        # нет product
        with self.assertRaises(sqlite3.IntegrityError):
            registry_db.add_hook(999999, "A", "x")                                # нет content
        with self.assertRaises(sqlite3.IntegrityError):
            registry_db.create_or_get_publication(c["id"], 999999, "pub-bad")     # нет channel
        with self.assertRaises(sqlite3.IntegrityError):
            registry_db.add_metric_snapshot(999999, "manual", views=1)            # нет publication

    def test_foreign_key_check_clean(self):
        seed()  # наполняем валидный граф
        c = registry_db._connect()
        try:
            self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            c.close()

    # ---- метрики во времени ----
    def test_metric_snapshots_timeseries(self):
        p, _ = registry_db.create_or_get_product("p", "P")
        c, _ = registry_db.create_or_get_content(p["id"], "v1", "video", "T")
        ch, _ = registry_db.create_or_get_channel("youtube_shorts", "YT")
        pub, _ = registry_db.create_or_get_publication(c["id"], ch["id"], "pub-1")
        registry_db.add_metric_snapshot(pub["id"], "manual", captured_at="2026-06-28T10:00:00Z", views=100)
        registry_db.add_metric_snapshot(pub["id"], "manual", captured_at="2026-06-29T10:00:00Z", views=250)
        dup, cr = registry_db.add_metric_snapshot(pub["id"], "manual", captured_at="2026-06-28T10:00:00Z", views=999)
        self.assertFalse(cr)
        self.assertEqual(dup["views"], 100)  # исходный не перезаписан
        self.assertEqual(len(registry_db.get_metric_snapshots(pub["id"])), 2)

    # ---- деньги: целые минорные единицы, без float ----
    def test_money_is_integer_minor(self):
        c = registry_db._connect()
        try:
            cols = {r["name"]: r["type"] for r in c.execute("PRAGMA table_info(commerce_snapshots)")}
        finally:
            c.close()
        self.assertIn("revenue_minor", cols)
        self.assertIn("spend_minor", cols)
        self.assertEqual(cols["revenue_minor"], "INTEGER")
        self.assertEqual(cols["spend_minor"], "INTEGER")
        self.assertNotIn("revenue", cols)
        self.assertNotIn("spend", cols)
        p, _ = registry_db.create_or_get_product("p", "P")
        row, _ = registry_db.add_commerce_snapshot(
            p["id"], "manual", "platform_reported", captured_at="2026-06-29T00:00:00Z",
            orders=2, revenue_minor=129900, spend_minor=0)
        self.assertIsInstance(row["revenue_minor"], int)
        self.assertEqual(row["revenue_minor"], 129900)

    # ---- estimated != confirmed ----
    def test_estimated_not_confirmed(self):
        p, _ = registry_db.create_or_get_product("p", "P")
        c, _ = registry_db.create_or_get_content(p["id"], "v1", "video", "T")
        ch, _ = registry_db.create_or_get_channel("tiktok", "TT")
        pub, _ = registry_db.create_or_get_publication(c["id"], ch["id"], "pub-1")
        registry_db.add_commerce_snapshot(p["id"], "manual", "estimated",
                                          publication_id=pub["id"], orders=5,
                                          captured_at="2026-06-29T00:00:00Z")
        summ = registry_db.publication_summary("pub-1")
        self.assertEqual(len(summ["commerce_confirmed"]), 0)
        self.assertEqual(len(summ["commerce_estimated"]), 1)

    # ---- auth ----
    def test_empty_api_key_denied(self):
        saved = auth.API_KEY
        auth.API_KEY = ""
        try:
            with self.assertRaises(Exception) as ctx:
                asyncio.run(auth.require_api_key(x_api_key=""))
            self.assertEqual(getattr(ctx.exception, "status_code", None), 401)
        finally:
            auth.API_KEY = saved

    def test_valid_api_key_ok(self):
        saved = auth.API_KEY
        auth.API_KEY = "s3cret"
        try:
            self.assertTrue(asyncio.run(auth.require_api_key(x_api_key="s3cret")))
            with self.assertRaises(Exception):
                asyncio.run(auth.require_api_key(x_api_key="wrong"))
        finally:
            auth.API_KEY = saved

    def test_no_secret_leak(self):
        saved = auth.API_KEY
        auth.API_KEY = "TOP_SECRET_VALUE"
        try:
            try:
                asyncio.run(auth.require_api_key(x_api_key="nope"))
            except Exception as e:
                self.assertNotIn("TOP_SECRET_VALUE", str(getattr(e, "detail", "")))
                self.assertNotIn("TOP_SECRET_VALUE", str(e))
        finally:
            auth.API_KEY = saved

    # ---- авто-миграция выключена по умолчанию -> схема не появляется сама ----
    def test_auto_migrate_off_by_default(self):
        self.assertFalse(config.REGISTRY_AUTO_MIGRATE)  # env не задан в тестах
        other = os.path.join(self.tmpdir, "fresh.db")
        prev = registry_db.DB_PATH
        registry_db.DB_PATH = other
        try:
            self.assertFalse(registry_db.schema_present())  # без миграции схемы нет
        finally:
            registry_db.DB_PATH = prev
            try:
                os.remove(other)
            except OSError:
                pass

    # ---- seed дважды без дублей ----
    def test_seed_idempotent(self):
        r1 = seed()
        r2 = seed()
        self.assertEqual(r1["product_id"], r2["product_id"])
        self.assertEqual(r1["content_id"], r2["content_id"])
        self.assertNotIn("product", r2["created"])
        self.assertEqual(len(registry_db.list_channels()), 5)
        self.assertEqual(len(registry_db.get_hooks(r1["content_id"])), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
