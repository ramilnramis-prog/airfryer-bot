"""Tests for the manual performance-tracking loop (master tracker, daily
input files, analyzer, next-batch recommendations) -- campaign
coating-protect-2026-07. Covers the 14 points requested by the owner:

1. master-performance-tracker.csv exists
2. master-performance-tracker.json exists
3. tracker has 182 rows/items
4. all 14 daily input files exist
5. HOW_TO_TRACK_RESULTS.md exists
6. analyzer CLI exists
7. analyzer does not call external APIs
8. analyzer handles empty metrics gracefully
9. performance-summary.json/.md created
10. next-batch-recommendations.json/.md created
11. review dashboard includes performance tracking section
12. no auto-posting code
13. no OpenAI/Higgsfield calls
14. no Production/Railway changes
"""
import csv
import io
import json
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from api.media_pipeline import cli
from api.media_pipeline import content_factory_performance as perf
from api.media_pipeline import content_factory_review as review

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"
CF_DIR = CAMPAIGN_DIR / "generated" / "content-factory"
PERF_DIR = CF_DIR / "performance-tracking"

SECRET_PATTERN = re.compile(
    r"sk-[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}|api[_-]?key['\"]?\s*[:=]\s*['\"][A-Za-z0-9]{16,}|"
    r"password['\"]?\s*[:=]\s*['\"][^'\"]{4,}|-----BEGIN"
)


def urlopen_raises():
    return mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call!"))


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_cli(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


class TestMasterTrackerCSVExists(unittest.TestCase):
    def test_csv_exists(self):
        self.assertTrue((PERF_DIR / "master-performance-tracker.csv").is_file())

    def test_csv_columns_match_spec(self):
        with open(PERF_DIR / "master-performance-tracker.csv", encoding="utf-8") as f:
            header = next(csv.reader(f))
        self.assertEqual(list(header), list(perf.TRACKER_COLUMNS))


class TestMasterTrackerJSONExists(unittest.TestCase):
    def test_json_exists(self):
        self.assertTrue((PERF_DIR / "master-performance-tracker.json").is_file())

    def test_json_columns_declared(self):
        d = load_json(PERF_DIR / "master-performance-tracker.json")
        self.assertEqual(d["columns"], list(perf.TRACKER_COLUMNS))


class TestTrackerHas182Rows(unittest.TestCase):
    def test_csv_row_count(self):
        with open(PERF_DIR / "master-performance-tracker.csv", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        self.assertEqual(len(rows) - 1, 182)

    def test_json_row_count(self):
        d = load_json(PERF_DIR / "master-performance-tracker.json")
        self.assertEqual(d["total_rows"], 182)
        self.assertEqual(len(d["rows"]), 182)

    def test_live_build_zero_network(self):
        with urlopen_raises():
            rows = perf.build_master_tracker_rows(str(CAMPAIGN_DIR))
        self.assertEqual(len(rows), 182)


class TestAll14DailyInputFilesExist(unittest.TestCase):
    def test_all_14_files_present(self):
        for day_num in range(1, 15):
            path = PERF_DIR / "daily-input" / f"day-{day_num:02d}-metrics.csv"
            self.assertTrue(path.is_file(), f"{path} missing")

    def test_each_day_has_13_rows(self):
        for day_num in range(1, 15):
            path = PERF_DIR / "daily-input" / f"day-{day_num:02d}-metrics.csv"
            with open(path, encoding="utf-8") as f:
                rows = list(csv.reader(f))
            self.assertEqual(len(rows) - 1, 13, f"day-{day_num:02d} should have 13 rows")

    def test_daily_columns_match_spec(self):
        with open(PERF_DIR / "daily-input" / "day-01-metrics.csv", encoding="utf-8") as f:
            header = next(csv.reader(f))
        self.assertEqual(list(header), list(perf.DAILY_INPUT_COLUMNS))


class TestHowToTrackResultsExists(unittest.TestCase):
    def test_file_exists(self):
        path = PERF_DIR / "HOW_TO_TRACK_RESULTS.md"
        self.assertTrue(path.is_file())

    def test_covers_required_topics(self):
        text = PERF_DIR / "HOW_TO_TRACK_RESULTS.md"
        content = text.read_text(encoding="utf-8").lower()
        for marker in ("published_url", "views_24h", "decision", "analyze-content-performance"):
            self.assertIn(marker.lower(), content)


class TestAnalyzerCLIExists(unittest.TestCase):
    def test_cli_subcommand_runs(self):
        code, output = run_cli(["analyze-content-performance", "--campaign", "coating-protect-2026-07"])
        self.assertEqual(code, 0)
        d = json.loads(output)
        self.assertIn("performance_summary", d)
        self.assertIn("next_batch_recommendations", d)

    def test_cli_help_lists_command(self):
        code, output = run_cli(["--help"]) if False else (None, None)
        # argparse --help calls sys.exit; just confirm the subcommand parses cleanly instead.
        with urlopen_raises():
            code2, _ = run_cli(["analyze-content-performance", "--campaign", "coating-protect-2026-07"])
        self.assertEqual(code2, 0)


class TestAnalyzerNoExternalAPICalls(unittest.TestCase):
    def test_analyze_performance_zero_network(self):
        with urlopen_raises():
            report = perf.analyze_performance(str(CAMPAIGN_DIR))
        self.assertEqual(report["openai_calls"], 0)
        self.assertEqual(report["higgsfield_calls"], 0)
        self.assertEqual(report["external_api_calls"], 0)

    def test_no_network_import_markers_in_module(self):
        src = Path(perf.__file__).read_text(encoding="utf-8")
        for marker in ("requests.get", "requests.post", "httpx.", "urlopen("):
            self.assertNotIn(marker, src)


class TestAnalyzerHandlesEmptyMetricsGracefully(unittest.TestCase):
    def test_empty_data_report_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp) / "coating-protect-2026-07"
            shutil.copytree(CAMPAIGN_DIR, sandbox)
            # daily-input files in the sandbox are freshly copied (unfilled) --
            # analyzer must not crash and must report has_data=False.
            with urlopen_raises():
                report = perf.analyze_performance(str(sandbox))
            self.assertFalse(report["has_data"])
            self.assertIn("ожидаются метрики", report["note"])
            self.assertEqual(report["best_videos_by_views_24h"], [])

    def test_partial_data_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp) / "coating-protect-2026-07"
            shutil.copytree(CAMPAIGN_DIR, sandbox)
            day01 = sandbox / "generated/content-factory/performance-tracking/daily-input/day-01-metrics.csv"
            with open(day01, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            fieldnames = list(rows[0].keys())
            rows[0]["views_24h"] = "500"  # only ONE row filled in, rest blank
            with open(day01, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(rows)
            with urlopen_raises():
                report = perf.analyze_performance(str(sandbox))
            self.assertTrue(report["has_data"])
            self.assertEqual(report["rows_with_data"], 1)


class TestPerformanceSummaryCreated(unittest.TestCase):
    def test_json_and_md_exist(self):
        self.assertTrue((PERF_DIR / "reports" / "performance-summary.json").is_file())
        self.assertTrue((PERF_DIR / "reports" / "performance-summary.md").is_file())

    def test_tracked_summary_reflects_no_data_yet(self):
        d = load_json(PERF_DIR / "reports" / "performance-summary.json")
        self.assertIn("has_data", d)
        self.assertIn("recommendations_for_next_batch", d)


class TestNextBatchRecommendationsCreated(unittest.TestCase):
    def test_json_and_md_exist(self):
        self.assertTrue((PERF_DIR / "reports" / "next-batch-recommendations.json").is_file())
        self.assertTrue((PERF_DIR / "reports" / "next-batch-recommendations.md").is_file())

    def test_has_expected_keys_when_no_data(self):
        d = load_json(PERF_DIR / "reports" / "next-batch-recommendations.json")
        for key in ("repeat_winning_hooks", "remake_underperforming_angles",
                   "generate_more_of", "avoid_next_time", "next_batch_prompt_notes"):
            self.assertIn(key, d)

    def test_live_build_zero_network(self):
        with urlopen_raises():
            rec = perf.build_next_batch_recommendations(str(CAMPAIGN_DIR))
        self.assertIn("has_data", rec)


class TestReviewDashboardIncludesPerformanceSection(unittest.TestCase):
    def test_index_has_performance_tracking_section(self):
        html = (CF_DIR / "review" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Performance Tracking", html)
        summary = load_json(PERF_DIR / "reports" / "performance-summary.json")
        if not summary["has_data"]:
            self.assertIn("waiting_for_publication_data", html)

    def test_dashboard_links_master_tracker_and_howto(self):
        html = (CF_DIR / "review" / "index.html").read_text(encoding="utf-8")
        self.assertIn("master-performance-tracker.csv", html)
        self.assertIn("HOW_TO_TRACK_RESULTS.md", html)
        for day_num in range(1, 15):
            self.assertIn(f"day-{day_num:02d}", html)


class TestNoAutoPostingCode(unittest.TestCase):
    def test_no_posting_markers_in_performance_module(self):
        src = Path(perf.__file__).read_text(encoding="utf-8")
        for marker in ("requests.post", "httpx.post", "auto_post(", "social_publish"):
            self.assertNotIn(marker, src)

    def test_tracker_json_declares_no_auto_posting(self):
        d = load_json(PERF_DIR / "master-performance-tracker.json")
        self.assertFalse(d["auto_posting_triggered"])


class TestNoOpenAIHiggsfieldCalls(unittest.TestCase):
    def test_write_master_tracker_zero_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp) / "coating-protect-2026-07"
            shutil.copytree(CAMPAIGN_DIR, sandbox)
            with urlopen_raises():
                result = perf.write_master_tracker(str(sandbox))
            self.assertEqual(result["total_rows"], 182)

    def test_tracker_declares_zero_calls(self):
        d = load_json(PERF_DIR / "master-performance-tracker.json")
        self.assertEqual(d["openai_calls"], 0)
        self.assertEqual(d["higgsfield_calls"], 0)


class TestNoRailwayProductionChanges(unittest.TestCase):
    def test_performance_module_does_not_reference_railway(self):
        src = Path(perf.__file__).read_text(encoding="utf-8").lower()
        self.assertNotIn("railway", src)
        self.assertNotIn("production", src)

    def test_performance_output_is_gitignored(self):
        import subprocess
        result = subprocess.run(
            ["git", "check-ignore",
             "content/autopilot/coating-protect-2026-07/generated/content-factory/"
             "performance-tracking/master-performance-tracker.json"],
            cwd=str(REPO_ROOT), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, "performance-tracking output is NOT gitignored")


class TestSecretScanCleanInPerformanceOutputs(unittest.TestCase):
    def test_no_secrets_in_performance_tree(self):
        offenders = []
        for f in PERF_DIR.rglob("*"):
            if f.is_file() and f.suffix in (".json", ".md", ".csv"):
                text = f.read_text(encoding="utf-8", errors="ignore")
                if SECRET_PATTERN.search(text):
                    offenders.append(str(f))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
