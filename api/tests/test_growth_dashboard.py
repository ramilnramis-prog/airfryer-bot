"""Tests for api/growth_dashboard.py: aggregation math, «сегодняшний день»
derivation, approvals extraction and graceful degradation when data files
are missing. Pure tempdir fixtures -- no network, no real campaign data."""
import json
import tempfile
import unittest
from pathlib import Path

from api import growth_dashboard as gd


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


MANIFEST = {
    "campaign_code": "test-campaign",
    "status": "awaiting_asset_generation",
    "approval_required_for": "платная генерация кадров",
    "unresolved_questions": ["Бустить ли победителя?"],
    "scene_status": {
        "scene-05": {
            "animation_status": "rejected_by_owner_needs_regeneration",
            "animation_reject_reason": "handle_geometry_mismatch",
        }
    },
}

PLAN = {
    "campaign_code": "test-campaign",
    "days": [
        {"day": 1, "videos": [
            {"slot": 1, "posting_time": "12:30", "hook": "Хук 1",
             "native_platform": "youtube_shorts", "publish_status": "published"},
            {"slot": 2, "posting_time": "16:30", "hook": "Хук 2",
             "native_platform": "youtube_shorts", "publish_status": "published"},
        ]},
        {"day": 2, "videos": [
            {"slot": 1, "posting_time": "12:30", "hook": "Хук 3",
             "native_platform": "tiktok", "publish_status": "not_published"},
        ]},
    ],
}

TRACKER = {
    "campaign_code": "test-campaign",
    "rows": [
        {"platform": "youtube_shorts", "publish_status": "published",
         "views_24h": "120", "likes_24h": "10", "clicks_24h": "4"},
        {"platform": "youtube_shorts", "publish_status": "published",
         "views_24h": "80", "likes_24h": "", "clicks_24h": ""},
        {"platform": "tiktok", "publish_status": "not_published",
         "views_24h": "", "likes_24h": "", "clicks_24h": ""},
    ],
}


class GrowthDashboardTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.campaign = "content/autopilot/test-campaign"
        base = self.root / self.campaign
        _write_json(base / "campaign_manifest.json", MANIFEST)
        _write_json(base / gd.PLAN_RELPATH, PLAN)
        _write_json(base / gd.TRACKER_RELPATH, TRACKER)

    def test_summarize_tracker_totals_and_platform_split(self):
        summary = gd.summarize_tracker(TRACKER)
        self.assertEqual(summary["total_slots"], 3)
        self.assertEqual(summary["published"], 2)
        self.assertEqual(summary["views_24h"], 200)
        self.assertEqual(summary["likes_24h"], 10)
        self.assertEqual(summary["clicks_24h"], 4)
        self.assertEqual(summary["by_platform"]["youtube_shorts"]["published"], 2)
        self.assertEqual(summary["by_platform"]["youtube_shorts"]["views_24h"], 200)
        self.assertEqual(summary["by_platform"]["tiktok"]["published"], 0)

    def test_summarize_tracker_handles_missing(self):
        summary = gd.summarize_tracker(None)
        self.assertEqual(summary["total_slots"], 0)
        self.assertEqual(summary["by_platform"], {})

    def test_current_plan_day_is_first_unpublished(self):
        self.assertEqual(gd.current_plan_day(PLAN), 2)

    def test_current_plan_day_all_published_returns_last_day(self):
        plan = {"days": [{"day": 1, "videos": [
            {"publish_status": "published"}]}]}
        self.assertEqual(gd.current_plan_day(plan), 1)
        self.assertIsNone(gd.current_plan_day(None))
        self.assertIsNone(gd.current_plan_day({"days": []}))

    def test_collect_approvals(self):
        approvals = gd.collect_approvals(MANIFEST)
        joined = "\n".join(approvals)
        self.assertIn("awaiting_asset_generation", joined)
        self.assertIn("платная генерация кадров", joined)
        self.assertIn("handle_geometry_mismatch", joined)
        self.assertIn("Бустить ли победителя?", joined)
        self.assertEqual(gd.collect_approvals(None), [])

    def test_write_dashboard_full_data(self):
        out = gd.write_dashboard(self.campaign, repo_root=str(self.root))
        html_text = Path(out).read_text(encoding="utf-8")
        self.assertIn("test-campaign", html_text)
        self.assertIn("Хук 3", html_text)          # задачи дня 2 (не дня 1)
        self.assertNotIn("Хук 1", html_text.split("План публикаций")[0].split("Задачи на сегодня")[-1])
        self.assertIn("2 / 3", html_text)          # published / total
        self.assertIn("youtube_shorts", html_text)
        self.assertIn("Ждёт твоего подтверждения", html_text)
        self.assertIn(gd.OZON_SKU, html_text)

    def test_write_dashboard_without_any_data_files(self):
        empty_campaign = "content/autopilot/empty-campaign"
        (self.root / empty_campaign).mkdir(parents=True)
        out = gd.write_dashboard(empty_campaign, repo_root=str(self.root),
                                 out_path=str(self.root / "dash2.html"))
        html_text = Path(out).read_text(encoding="utf-8")
        self.assertIn("манифест не найден", html_text)
        self.assertIn("Нет плана публикаций", html_text)
        self.assertIn("Трекер пуст", html_text)

    def test_html_escapes_user_text(self):
        manifest = dict(MANIFEST, approval_required_for="<script>alert(1)</script>")
        base = self.root / self.campaign
        _write_json(base / "campaign_manifest.json", manifest)
        out = gd.write_dashboard(self.campaign, repo_root=str(self.root),
                                 out_path=str(self.root / "dash3.html"))
        html_text = Path(out).read_text(encoding="utf-8")
        self.assertNotIn("<script>alert(1)</script>", html_text)
        self.assertIn("&lt;script&gt;", html_text)

    def test_cli_main(self):
        out_file = self.root / "cli-dash.html"
        code = gd.main(["--campaign", self.campaign,
                        "--repo-root", str(self.root),
                        "--out", str(out_file)])
        self.assertEqual(code, 0)
        self.assertTrue(out_file.is_file())


if __name__ == "__main__":
    unittest.main()
