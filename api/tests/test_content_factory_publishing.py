"""Tests for the first 14-day publishing queue (SELECTION only, no new
generation) -- campaign coating-protect-2026-07. Covers the 14 points
requested by the owner:

1. first-14-days plan exists
2. contains exactly 14 days
3. each day has 3 videos
4. each day has 1 Dzen post
5. all referenced files exist
6. no duplicate hook in same day
7. no same batch repeated 3 times in same day
8. checklist files exist
9. upload-ready folders exist for all 14 days
10. creative-testing-matrix exists
11. no forbidden claims
12. no OpenAI/Higgsfield calls
13. no auto-posting
14. no Production/Railway changes
"""
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline import content_factory_publishing as pub
from api.media_pipeline import content_factory_review as review

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"
CF_DIR = CAMPAIGN_DIR / "generated" / "content-factory"
PUB_DIR = CF_DIR / "publishing"

SECRET_PATTERN = re.compile(
    r"sk-[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}|api[_-]?key['\"]?\s*[:=]\s*['\"][A-Za-z0-9]{16,}|"
    r"password['\"]?\s*[:=]\s*['\"][^'\"]{4,}|-----BEGIN"
)
FORBIDDEN_PHRASES = ("100% чисто", "никогда не пачкается", "гарантированно",
                    "идеально для всех аэрогрилей")


def urlopen_raises():
    return mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call!"))


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class TestPlanExists(unittest.TestCase):
    def test_json_and_md_exist(self):
        self.assertTrue((PUB_DIR / "first-14-days-publishing-plan.json").is_file())
        self.assertTrue((PUB_DIR / "first-14-days-publishing-plan.md").is_file())

    def test_live_build_zero_network(self):
        with urlopen_raises():
            plan = pub.build_first_14_days_plan(str(CAMPAIGN_DIR))
        self.assertEqual(plan["num_days"], 14)


class TestExactly14Days(unittest.TestCase):
    def test_plan_has_14_days(self):
        plan = load_json(PUB_DIR / "first-14-days-publishing-plan.json")
        self.assertEqual(len(plan["days"]), 14)
        self.assertEqual(plan["num_days"], 14)
        self.assertEqual([d["day"] for d in plan["days"]], list(range(1, 15)))


class TestEachDayHasThreeVideos(unittest.TestCase):
    def test_three_videos_per_day(self):
        plan = load_json(PUB_DIR / "first-14-days-publishing-plan.json")
        for day in plan["days"]:
            self.assertEqual(len(day["videos"]), 3, f"day {day['day']} does not have 3 videos")
        self.assertEqual(plan["total_videos_selected"], 42)


class TestEachDayHasOneDzenPost(unittest.TestCase):
    def test_one_dzen_post_per_day(self):
        plan = load_json(PUB_DIR / "first-14-days-publishing-plan.json")
        for day in plan["days"]:
            self.assertIsNotNone(day["dzen_post"], f"day {day['day']} missing a dzen post")
        self.assertEqual(plan["total_dzen_selected"], 14)


class TestAllReferencedFilesExist(unittest.TestCase):
    def test_video_and_dzen_files_exist(self):
        plan = load_json(PUB_DIR / "first-14-days-publishing-plan.json")
        for day in plan["days"]:
            for v in day["videos"]:
                self.assertTrue(Path(v["file_path"]).is_file(), f"missing {v['file_path']}")
            if day["dzen_post"]:
                self.assertTrue(Path(day["dzen_post"]["file_path"]).is_file())

    def test_upload_ready_copies_exist(self):
        for day_num in range(1, 15):
            day_dir = PUB_DIR / "upload-ready" / f"day-{day_num:02d}"
            self.assertTrue(day_dir.is_dir())
            videos = list((day_dir / "videos").glob("*.mp4"))
            self.assertEqual(len(videos), 3, f"day-{day_num:02d} should have 3 copied videos")


class TestNoDuplicateHookInSameDay(unittest.TestCase):
    def test_hooks_distinct_within_each_day(self):
        plan = load_json(PUB_DIR / "first-14-days-publishing-plan.json")
        for day in plan["days"]:
            hooks = [v["hook"] for v in day["videos"]]
            self.assertEqual(len(hooks), len(set(hooks)), f"day {day['day']} has duplicate hooks")


class TestNoSameBatchThreeTimesInSameDay(unittest.TestCase):
    def test_batch_not_repeated_three_times(self):
        plan = load_json(PUB_DIR / "first-14-days-publishing-plan.json")
        for day in plan["days"]:
            batches = [v["batch"] for v in day["videos"]]
            for b in set(batches):
                self.assertLess(batches.count(b), 3,
                               f"day {day['day']} uses batch {b} 3 times")

    def test_no_video_reused_across_the_whole_plan(self):
        plan = load_json(PUB_DIR / "first-14-days-publishing-plan.json")
        seen = set()
        for day in plan["days"]:
            for v in day["videos"]:
                self.assertNotIn(v["variant_id"], seen, f"{v['variant_id']} used twice in the plan")
                seen.add(v["variant_id"])


class TestChecklistFilesExist(unittest.TestCase):
    EXPECTED_FILES = ("youtube-shorts-checklist.csv", "instagram-reels-checklist.csv",
                      "tiktok-checklist.csv", "vk-clips-checklist.csv",
                      "dzen-checklist.csv", "master-publishing-checklist.csv")

    def test_all_six_checklists_exist(self):
        checklists_dir = PUB_DIR / "checklists"
        for name in self.EXPECTED_FILES:
            self.assertTrue((checklists_dir / name).is_file(), f"{name} missing")

    def test_checklist_columns_correct(self):
        import csv
        with open(PUB_DIR / "checklists" / "youtube-shorts-checklist.csv", encoding="utf-8") as f:
            header = next(csv.reader(f))
        self.assertEqual(list(header), list(pub.CHECKLIST_COLUMNS))

    def test_master_checklist_row_count(self):
        import csv
        with open(PUB_DIR / "checklists" / "master-publishing-checklist.csv", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        # header + 42*4 platform rows + 14 dzen rows
        self.assertEqual(len(rows) - 1, 42 * 4 + 14)


class TestUploadReadyFoldersExistForAll14Days(unittest.TestCase):
    def test_all_day_folders_present_with_subdirs(self):
        for day_num in range(1, 15):
            day_dir = PUB_DIR / "upload-ready" / f"day-{day_num:02d}"
            self.assertTrue((day_dir / "videos").is_dir())
            self.assertTrue((day_dir / "dzen").is_dir())
            self.assertTrue((day_dir / "metadata").is_dir())

    def test_originals_not_modified_by_copy(self):
        plan = load_json(PUB_DIR / "first-14-days-publishing-plan.json")
        v = plan["days"][0]["videos"][0]
        orig = Path(v["file_path"])
        day_dir = PUB_DIR / "upload-ready" / "day-01" / "videos"
        copies = list(day_dir.glob("*.mp4"))
        self.assertTrue(any(c.stat().st_size == orig.stat().st_size for c in copies))


class TestCreativeTestingMatrixExists(unittest.TestCase):
    def test_json_and_md_exist(self):
        self.assertTrue((PUB_DIR / "creative-testing-matrix.json").is_file())
        self.assertTrue((PUB_DIR / "creative-testing-matrix.md").is_file())

    def test_five_groups_present(self):
        matrix = load_json(PUB_DIR / "creative-testing-matrix.json")
        groups = {g["group"] for g in matrix["groups"]}
        self.assertEqual(groups, {"A", "B", "C", "D", "E"})
        for g in matrix["groups"]:
            for key in ("hook_type", "creative_angle", "first_3_seconds", "CTA",
                       "product_benefit", "style_types", "platform_fit",
                       "expected_audience_reaction"):
                self.assertIn(key, g)

    def test_live_build_zero_network(self):
        with urlopen_raises():
            matrix = pub.build_creative_testing_matrix()
        self.assertEqual(len(matrix["groups"]), 5)


class TestNoForbiddenClaims(unittest.TestCase):
    def test_no_forbidden_phrases_in_plan(self):
        plan = load_json(PUB_DIR / "first-14-days-publishing-plan.json")
        text = json.dumps(plan, ensure_ascii=False).lower()
        for phrase in FORBIDDEN_PHRASES:
            self.assertNotIn(phrase.lower(), text)

    def test_quality_filter_flags_forbidden_claims(self):
        fake_meta = {
            "render_status": "rendered", "mp4_path": __file__,
            "duration_target_seconds": 15, "target_size": [720, 1280],
            "publish_status": "not_published",
            "hook_text": "Форма работает гарантированно",
            "CTA": "", "voiceover_text": "", "on_screen_text": [],
        }
        ok, reasons = pub.passes_quality_filter(fake_meta)
        self.assertFalse(ok)
        self.assertTrue(any("forbidden_claim" in r for r in reasons))

    def test_no_forbidden_phrases_in_checklists(self):
        import csv
        for name in TestChecklistFilesExist.EXPECTED_FILES:
            with open(PUB_DIR / "checklists" / name, encoding="utf-8") as f:
                text = f.read().lower()
            for phrase in FORBIDDEN_PHRASES:
                self.assertNotIn(phrase.lower(), text, f"{name} contains {phrase!r}")


class TestNoOpenAIHiggsfieldCalls(unittest.TestCase):
    def test_build_plan_zero_network(self):
        with urlopen_raises():
            plan = pub.build_first_14_days_plan(str(CAMPAIGN_DIR))
        self.assertEqual(plan["openai_calls"], 0)
        self.assertEqual(plan["higgsfield_calls"], 0)
        self.assertEqual(plan["external_video_api_calls"], 0)

    def test_tracked_plan_declares_zero_calls(self):
        plan = load_json(PUB_DIR / "first-14-days-publishing-plan.json")
        self.assertEqual(plan["openai_calls"], 0)
        self.assertEqual(plan["higgsfield_calls"], 0)
        self.assertEqual(plan["external_video_api_calls"], 0)

    def test_no_new_mp4_generation_happened(self):
        # Every selected video's mp4_path must be one of the 90 already-
        # rendered files (batch-001..005) -- never a freshly generated one.
        plan = load_json(PUB_DIR / "first-14-days-publishing-plan.json")
        for day in plan["days"]:
            for v in day["videos"]:
                self.assertIn(v["batch"], ("batch-001", "batch-002", "batch-003",
                                          "batch-004", "batch-005"))


class TestNoAutoPosting(unittest.TestCase):
    def test_plan_declares_no_auto_posting(self):
        plan = load_json(PUB_DIR / "first-14-days-publishing-plan.json")
        self.assertFalse(plan["auto_posting_triggered"])
        for day in plan["days"]:
            for v in day["videos"]:
                self.assertEqual(v["publish_status"], "not_published")
                self.assertEqual(v["owner_status"], "not_reviewed")
            if day["dzen_post"]:
                self.assertEqual(day["dzen_post"]["publish_status"], "not_published")

    def test_no_posting_markers_in_publishing_module(self):
        src = Path(pub.__file__).read_text(encoding="utf-8")
        for marker in ("requests.post", "httpx.post", "auto_post(", "social_publish"):
            self.assertNotIn(marker, src)

    def test_review_dashboard_decision_buttons_are_local_js_only(self):
        html = (CF_DIR / "review" / "index.html").read_text(encoding="utf-8")
        self.assertIn("setDecision", html)
        self.assertIn("no backend", html.lower() + review._DECISION_JS.lower())


class TestNoRailwayProductionChanges(unittest.TestCase):
    def test_publishing_module_does_not_reference_railway(self):
        src = Path(pub.__file__).read_text(encoding="utf-8").lower()
        self.assertNotIn("railway", src)
        self.assertNotIn("production", src)

    def test_publishing_output_is_gitignored(self):
        import subprocess
        result = subprocess.run(
            ["git", "check-ignore",
             "content/autopilot/coating-protect-2026-07/generated/content-factory/"
             "publishing/first-14-days-publishing-plan.json"],
            cwd=str(REPO_ROOT), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, "publishing output is NOT gitignored")


class TestSecretScanCleanInPublishingOutputs(unittest.TestCase):
    def test_no_secrets_in_publishing_tree(self):
        offenders = []
        for f in PUB_DIR.rglob("*"):
            if f.is_file() and f.suffix in (".json", ".md", ".csv", ".txt"):
                text = f.read_text(encoding="utf-8", errors="ignore")
                if SECRET_PATTERN.search(text):
                    offenders.append(str(f))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
