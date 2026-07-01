"""Тесты backfill'а публикаций video2-forma-ad (хуки A/B/C) —
api/backfill_video2_publications.py + published_date (миграция 0002).

Запуск из папки telegram-bot-registry-integration/:
    python -m unittest api.tests.test_backfill_video2_publications -v

Каждый тест работает на ВРЕМЕННОЙ SQLite (config.DB_PATH подменяется) — production не трогается.
Никакие внешние API не вызываются, ничего реально не публикуется.
"""
import os
import tempfile
import unittest

from api import registry_db, db
from api.seed_registry import seed
from api import backfill_video2_publications as BF


class BackfillVideo2Tests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.dbfile = os.path.join(self.tmpdir, "test.db")
        registry_db.DB_PATH = self.dbfile
        db.DB_PATH = self.dbfile
        registry_db.run_migrations()
        db.init_db()
        seed()  # product + content + hooks A/B/C — backfill предполагает, что это уже есть

    def tearDown(self):
        try:
            os.remove(self.dbfile)
        except OSError:
            pass
        try:
            os.rmdir(self.tmpdir)
        except OSError:
            pass

    # ---- миграция 0002 ----
    def test_migration_adds_published_date_column(self):
        c = registry_db._connect()
        try:
            cols = {r["name"] for r in c.execute("PRAGMA table_info(publications)")}
        finally:
            c.close()
        self.assertIn("published_date", cols)

    def test_invalid_published_date_rejected(self):
        p, _ = registry_db.create_or_get_product("p-x", "X")
        c, _ = registry_db.create_or_get_content(p["id"], "v1", "video", "T")
        ch, _ = registry_db.create_or_get_channel("telegram", "TG")
        with self.assertRaises(ValueError):
            registry_db.create_or_get_publication(
                c["id"], ch["id"], "pub-bad-date", published_date="2026-02-30")  # нет 30 февраля
        with self.assertRaises(ValueError):
            registry_db.create_or_get_publication(
                c["id"], ch["id"], "pub-bad-format", published_date="30-06-2026")  # не ISO

    def test_valid_published_date_accepted(self):
        p, _ = registry_db.create_or_get_product("p-y", "Y")
        c, _ = registry_db.create_or_get_content(p["id"], "v1", "video", "T")
        ch, _ = registry_db.create_or_get_channel("telegram", "TG")
        row, created = registry_db.create_or_get_publication(
            c["id"], ch["id"], "pub-good-date", status="published", published_date="2026-06-30")
        self.assertTrue(created)
        self.assertEqual(row["published_date"], "2026-06-30")

    # ---- dry-run ----
    def test_dry_run_writes_nothing(self):
        rc = BF.main(["--db-path", self.dbfile])
        self.assertEqual(rc, 0)
        pubs = [p for p in registry_db.list_publications()
                if p["publication_code"].startswith("video2-forma-ad-")]
        self.assertEqual(len(pubs), 0)
        self.assertIsNone(registry_db.get_channel_by_code("vk_video"))

    # ---- apply ----
    def test_apply_creates_exactly_12_publications(self):
        rc = BF.main(["--db-path", self.dbfile, "--apply"])
        self.assertEqual(rc, 0)
        pubs = [p for p in registry_db.list_publications()
                if p["publication_code"].startswith("video2-forma-ad-")]
        self.assertEqual(len(pubs), 12)

    def test_apply_twice_no_duplicates(self):
        BF.main(["--db-path", self.dbfile, "--apply"])
        BF.main(["--db-path", self.dbfile, "--apply"])
        pubs = [p for p in registry_db.list_publications()
                if p["publication_code"].startswith("video2-forma-ad-")]
        self.assertEqual(len(pubs), 12)
        codes = [p["publication_code"] for p in pubs]
        self.assertEqual(len(codes), len(set(codes)))

    def test_hook_a_published_date(self):
        BF.main(["--db-path", self.dbfile, "--apply"])
        for channel in BF.CHANNELS:
            row = registry_db.get_publication_by_code(f"video2-forma-ad-{channel}-A-v1")
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "published")
            self.assertEqual(row["published_date"], "2026-06-30")
            self.assertIsNone(row["published_at"])
            self.assertIsNone(row["scheduled_at"])

    def test_hook_b_published_date(self):
        BF.main(["--db-path", self.dbfile, "--apply"])
        for channel in BF.CHANNELS:
            row = registry_db.get_publication_by_code(f"video2-forma-ad-{channel}-B-v1")
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "published")
            self.assertEqual(row["published_date"], "2026-07-01")
            self.assertIsNone(row["published_at"])
            self.assertIsNone(row["scheduled_at"])

    def test_hook_c_scheduled(self):
        BF.main(["--db-path", self.dbfile, "--apply"])
        for channel in BF.CHANNELS:
            row = registry_db.get_publication_by_code(f"video2-forma-ad-{channel}-C-v1")
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "scheduled")
            self.assertEqual(row["scheduled_at"], "2026-07-01T18:30:00Z")
            self.assertIsNone(row["published_at"])
            self.assertIsNone(row["published_date"])

    def test_ab_published_at_stays_null(self):
        BF.main(["--db-path", self.dbfile, "--apply"])
        for hook in ("A", "B"):
            for channel in BF.CHANNELS:
                row = registry_db.get_publication_by_code(f"video2-forma-ad-{channel}-{hook}-v1")
                self.assertIsNone(row["published_at"])

    def test_vk_video_channel_created_once(self):
        self.assertIsNone(registry_db.get_channel_by_code("vk_video"))
        BF.main(["--db-path", self.dbfile, "--apply"])
        first = registry_db.get_channel_by_code("vk_video")
        self.assertIsNotNone(first)
        BF.main(["--db-path", self.dbfile, "--apply"])
        second = registry_db.get_channel_by_code("vk_video")
        self.assertEqual(first["id"], second["id"])
        c = registry_db._connect()
        try:
            n = c.execute(
                "SELECT COUNT(*) AS n FROM channels WHERE code='vk_video'").fetchone()["n"]
        finally:
            c.close()
        self.assertEqual(n, 1)

    # ---- запись без явной цели запрещена (никогда не пишет в config.DB_PATH молча) ----
    def test_apply_without_db_path_or_confirmation_refused(self):
        rc = BF.main(["--apply"])
        self.assertNotEqual(rc, 0)

    def test_apply_without_yes_refused_even_with_allow_config_db(self):
        rc = BF.main(["--apply", "--allow-config-db"])
        self.assertNotEqual(rc, 0)

    # ---- backfill без seed (product/content/hooks отсутствуют) отказывает, не пишет ----
    def test_backfill_without_seed_fails_closed(self):
        fresh = os.path.join(self.tmpdir, "fresh.db")
        registry_db.DB_PATH = fresh
        registry_db.run_migrations()
        try:
            rc = BF.main(["--db-path", fresh, "--apply"])
            self.assertNotEqual(rc, 0)
            pubs = registry_db.list_publications()
            self.assertEqual(len(pubs), 0)
        finally:
            registry_db.DB_PATH = self.dbfile
            try:
                os.remove(fresh)
            except OSError:
                pass

    # ---- jobs не сломан ----
    def test_jobs_queue_still_works_after_backfill(self):
        BF.main(["--db-path", self.dbfile, "--apply"])
        db.create_job("job-bf-1", "generate-pdf")
        self.assertEqual(db.get_job("job-bf-1")["status"], "queued")


if __name__ == "__main__":
    unittest.main(verbosity=2)
