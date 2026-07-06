"""Tests for the content-factory batch scale-up (batch-002..005, angle-based
generation, aggregated review dashboard, content-queue.json) -- campaign
coating-protect-2026-07. Covers the 14 points requested by the owner:

1. batch angle parameter works
2. batch-002/003/004/005 render plans valid
3. at least 80 total video variants exist across batches
4. 80 MP4 or render-plan outputs exist
5. no duplicate hook_text inside each batch
6. metadata exists for all videos and 4 platforms
7. Dzen batch-002/003/004 posts exist
8. review dashboard references all batches
9. content-queue.json exists and has all produced assets
10. no OpenAI/Higgsfield calls
11. no auto-posting
12. no generated outputs are used as references
13. no forbidden claims ("100% чисто", "никогда не пачкается", "гарантированно")
14. secret scan clean
"""
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline import content_factory_data as fd
from api.media_pipeline import content_factory_planner as planner
from api.media_pipeline import content_factory_renderer as renderer
from api.media_pipeline import content_factory_metadata as meta
from api.media_pipeline import content_factory_review as review
from api.media_pipeline import content_factory_queue as queue

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"
CF_DIR = CAMPAIGN_DIR / "generated" / "content-factory"

NEW_BATCHES = ("batch-002", "batch-003", "batch-004", "batch-005")
ANGLE_BY_BATCH = {
    "batch-002": "pain_problem",
    "batch-003": "recipe",
    "batch-004": "meme_conversational",
    "batch-005": "fast_hype",
}

SECRET_PATTERN = re.compile(
    r"sk-[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}|api[_-]?key['\"]?\s*[:=]\s*['\"][A-Za-z0-9]{16,}|"
    r"password['\"]?\s*[:=]\s*['\"][^'\"]{4,}|-----BEGIN"
)

EXPLICIT_FORBIDDEN_PHRASES = ("100% чисто", "никогда не пачкается", "гарантированно")


def urlopen_raises():
    return mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call!"))


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class TestAngleParameterWorks(unittest.TestCase):
    def test_generate_angle_batch_variants_for_each_angle(self):
        with urlopen_raises():
            for angle in fd.CREATIVE_ANGLES:
                variants = planner.generate_angle_batch_variants(
                    angle, str(CAMPAIGN_DIR), f"batch-angle-test-{angle}", count=20)
                self.assertEqual(len(variants), 20)
                for v in variants:
                    self.assertEqual(v["creative_angle"], angle)

    def test_unknown_angle_raises(self):
        with self.assertRaises(ValueError):
            planner.generate_angle_batch_variants(
                "not_a_real_angle", str(CAMPAIGN_DIR), "batch-x", count=5)

    def test_fast_hype_duration_bounds(self):
        with urlopen_raises():
            variants = planner.generate_angle_batch_variants(
                "fast_hype", str(CAMPAIGN_DIR), "batch-hype-test", count=20)
        for v in variants:
            self.assertGreaterEqual(v["duration_target_seconds"], 12.0)
            self.assertLessEqual(v["duration_target_seconds"], 15.0)


class TestBatchRenderPlansValid(unittest.TestCase):
    def test_per_batch_variant_plan_files_exist_and_valid(self):
        for batch in NEW_BATCHES:
            path = CF_DIR / "video-variants" / f"video-variant-plan-{batch}.json"
            self.assertTrue(path.is_file(), f"{path} missing")
            d = load_json(path)
            self.assertEqual(d["total_variants"], 20)
            self.assertEqual(d["creative_angle"], ANGLE_BY_BATCH[batch])
            self.assertEqual(d["openai_calls"], 0)
            self.assertEqual(d["higgsfield_calls"], 0)
            self.assertFalse(d["generated_outputs_used_as_references"])


class TestAtLeast80VariantsAcrossBatches(unittest.TestCase):
    def test_total_variants_in_new_batches(self):
        total = 0
        for batch in NEW_BATCHES:
            d = load_json(CF_DIR / "video-variants" / f"video-variant-plan-{batch}.json")
            total += d["total_variants"]
        self.assertGreaterEqual(total, 80)


class Test80MP4OrRenderPlanOutputsExist(unittest.TestCase):
    def test_each_new_batch_has_20_outputs(self):
        for batch in NEW_BATCHES:
            batch_dir = CF_DIR / "video-renders" / batch
            self.assertTrue(batch_dir.is_dir())
            summary = load_json(batch_dir / "batch-summary.json")
            self.assertEqual(summary["variants_processed"], 20)
            self.assertEqual(
                summary["rendered_mp4_count"] + summary["render_plan_only_count"], 20)

    def test_total_outputs_at_least_80(self):
        total = 0
        for batch in NEW_BATCHES:
            summary = load_json(CF_DIR / "video-renders" / batch / "batch-summary.json")
            total += summary["variants_processed"]
        self.assertGreaterEqual(total, 80)


class TestNoDuplicateHooksPerBatch(unittest.TestCase):
    def test_hooks_distinct_within_each_new_batch(self):
        for batch in NEW_BATCHES:
            batch_dir = CF_DIR / "video-renders" / batch
            hooks = []
            for f in sorted(batch_dir.glob(f"{batch}-v*.json")):
                d = load_json(f)
                hooks.append(d["hook_text"])
            self.assertEqual(len(hooks), 20, f"{batch} should have 20 render-metadata files")
            self.assertEqual(len(hooks), len(set(hooks)), f"{batch} has duplicate hook_text")


class TestMetadataForAllVideosAndFourPlatforms(unittest.TestCase):
    def test_platform_metadata_exists_for_every_new_batch_video(self):
        for batch in NEW_BATCHES:
            meta_dir = CF_DIR / "platform-metadata" / batch
            files = [f for f in meta_dir.glob("*.json") if f.name != "platform-metadata-summary.json"]
            self.assertEqual(len(files), 20, f"{batch} should have 20 platform-metadata files")
            for f in files:
                d = load_json(f)
                self.assertEqual(set(d["platforms"].keys()), set(fd.FORMATS))
                for platform, entry in d["platforms"].items():
                    for key in ("title", "short_description", "caption", "hashtags", "CTA", "pinned_comment_idea"):
                        self.assertIn(key, entry)


class TestDzenBatchesExist(unittest.TestCase):
    def test_batch_002_003_004_have_10_posts_each(self):
        for batch in ("batch-002", "batch-003", "batch-004"):
            batch_dir = CF_DIR / "dzen-posts" / batch
            md_files = sorted(batch_dir.glob(f"{batch}-dzen-*.md"))
            self.assertEqual(len(md_files), 10, f"{batch} should have 10 dzen markdown posts")
            for f in md_files:
                text = f.read_text(encoding="utf-8")
                self.assertGreaterEqual(len(text), 1500)
                self.assertLessEqual(len(text), 3000)

    def test_no_duplicate_titles_within_each_dzen_batch(self):
        for batch in ("batch-002", "batch-003", "batch-004"):
            batch_dir = CF_DIR / "dzen-posts" / batch
            titles = []
            for f in sorted(batch_dir.glob(f"{batch}-dzen-*.md")):
                titles.append(f.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(len(titles), len(set(titles)), f"{batch} has duplicate post titles")


class TestReviewDashboardReferencesAllBatches(unittest.TestCase):
    def test_index_references_all_five_batches(self):
        html = (CF_DIR / "review" / "index.html").read_text(encoding="utf-8")
        for batch in ("batch-001",) + NEW_BATCHES:
            self.assertIn(batch, html)

    def test_per_batch_pages_exist(self):
        for batch in ("batch-001",) + NEW_BATCHES:
            self.assertTrue((CF_DIR / "review" / f"{batch}.html").is_file())

    def test_filters_present_in_index(self):
        html = (CF_DIR / "review" / "index.html").read_text(encoding="utf-8")
        for filter_id in ("f-batch", "f-angle", "f-platform", "f-status"):
            self.assertIn(filter_id, html)

    def test_discover_batches_finds_all_five(self):
        with urlopen_raises():
            batches = review.discover_batches(str(CAMPAIGN_DIR))
        self.assertEqual(set(batches), {"batch-001"} | set(NEW_BATCHES))


class TestContentQueueComplete(unittest.TestCase):
    def test_content_queue_exists_and_covers_all_assets(self):
        path = CF_DIR / "content-queue.json"
        self.assertTrue(path.is_file())
        d = load_json(path)
        self.assertGreaterEqual(d["total_video_assets"], 90)
        self.assertGreaterEqual(d["total_dzen_assets"], 40)
        self.assertEqual(d["total_assets"], d["total_video_assets"] + d["total_dzen_assets"])
        self.assertEqual(len(d["recommended_posting_order"]), d["total_assets"])

    def test_all_queue_entries_ready_and_unpublished(self):
        d = load_json(CF_DIR / "content-queue.json")
        for item in d["video_assets"] + d["dzen_assets"]:
            self.assertIn(item["status"], ("ready_for_owner_review", "needs_edit"))
            self.assertEqual(item["publish_status"], "not_published")
            self.assertEqual(item["owner_notes"], "")

    def test_no_auto_posting_flag(self):
        d = load_json(CF_DIR / "content-queue.json")
        self.assertFalse(d["auto_posting_triggered"])
        self.assertEqual(d["openai_calls"], 0)
        self.assertEqual(d["higgsfield_calls"], 0)


class TestNoOpenAIHiggsfieldCallsInBatchGeneration(unittest.TestCase):
    def test_write_angle_variant_plan_zero_network(self):
        with urlopen_raises():
            plan = planner.write_angle_variant_plan(
                str(CAMPAIGN_DIR), angle="recipe", batch_name="batch-network-test", count=5)
        self.assertEqual(plan["openai_calls"], 0)
        self.assertEqual(plan["higgsfield_calls"], 0)
        Path(plan["report_path"]).unlink()

    def test_render_batch_zero_network(self):
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "plan.json"
            with urlopen_raises():
                planner.write_angle_variant_plan(
                    str(CAMPAIGN_DIR), angle="pain_problem", batch_name="batch-net-test-2",
                    count=2, out_path=str(plan_path))
                summary = renderer.render_batch(
                    str(CAMPAIGN_DIR), limit=2, batch_name="batch-net-test-2-out",
                    variant_plan_path=str(plan_path))
        self.assertEqual(summary["openai_calls"], 0)
        self.assertEqual(summary["higgsfield_calls"], 0)
        shutil.rmtree(Path(summary["out_dir"]), ignore_errors=True)

    def test_content_queue_build_zero_network(self):
        with urlopen_raises():
            q = queue.build_content_queue(str(CAMPAIGN_DIR))
        self.assertEqual(q["openai_calls"], 0)
        self.assertEqual(q["higgsfield_calls"], 0)


class TestNoAutoPostingInBatchModules(unittest.TestCase):
    def test_no_posting_markers_in_queue_module(self):
        src = Path(queue.__file__).read_text(encoding="utf-8")
        for marker in ("requests.post", "httpx.post", "auto_post(", "social_publish"):
            self.assertNotIn(marker, src)

    def test_content_queue_declares_auto_posting_false(self):
        d = load_json(CF_DIR / "content-queue.json")
        self.assertFalse(d["auto_posting_triggered"])


class TestGeneratedOutputsNeverUsedAsReferencesInBatches(unittest.TestCase):
    def test_queue_module_does_not_import_openai_reference_machinery(self):
        src = Path(queue.__file__).read_text(encoding="utf-8")
        self.assertNotIn("product_reference_only_runner", src)
        self.assertNotIn("PRODUCT_REFERENCE_ASSET_PATHS", src)

    def test_angle_variants_reuse_only_already_reviewed_scene_pngs(self):
        with urlopen_raises():
            variants = planner.generate_angle_batch_variants(
                "recipe", str(CAMPAIGN_DIR), "batch-ref-check", count=5)
        for v in variants:
            for asset in v["required_assets"]:
                if asset["exists"]:
                    self.assertIn("product-reference-only-scene-v2", asset["path"])
                    self.assertNotIn("generated/content-factory", asset["path"])


class TestNoForbiddenClaimsInBatchOutputs(unittest.TestCase):
    def test_no_forbidden_phrases_in_new_batch_video_metadata(self):
        # Scoped to actual customer-facing copy only -- risk_notes/tone
        # documentation legitimately QUOTES the forbidden phrase as a
        # caution against using it, which would otherwise false-positive.
        for batch in NEW_BATCHES:
            batch_dir = CF_DIR / "video-renders" / batch
            for f in batch_dir.glob(f"{batch}-v*.json"):
                d = load_json(f)
                customer_facing = [d["hook_text"], d["CTA"], d["voiceover_text"]]
                customer_facing.extend(d["on_screen_text"])
                customer_facing.extend(seg["text"] for seg in d["caption_timeline"])
                text = " ".join(customer_facing).lower()
                for phrase in EXPLICIT_FORBIDDEN_PHRASES:
                    self.assertNotIn(phrase.lower(), text, f"{f} contains forbidden phrase {phrase!r}")

    def test_no_forbidden_phrases_in_new_dzen_batches(self):
        for batch in ("batch-002", "batch-003", "batch-004"):
            batch_dir = CF_DIR / "dzen-posts" / batch
            for f in batch_dir.glob(f"{batch}-dzen-*.md"):
                text = f.read_text(encoding="utf-8").lower()
                for phrase in EXPLICIT_FORBIDDEN_PHRASES:
                    self.assertNotIn(phrase.lower(), text, f"{f} contains forbidden phrase {phrase!r}")

    def test_no_forbidden_markers_in_new_angle_hooks(self):
        for angle in fd.CREATIVE_ANGLES:
            category = fd.ANGLE_HOOK_CATEGORY[angle]
            for hook in fd.HOOK_BANK[category]:
                for marker in fd.FORBIDDEN_CLAIM_MARKERS:
                    self.assertNotIn(marker.lower(), hook.lower())


class TestSecretScanCleanInBatchOutputs(unittest.TestCase):
    def test_no_secret_patterns_in_new_batches(self):
        offenders = []
        for batch in NEW_BATCHES:
            for base_dir in (CF_DIR / "video-renders" / batch, CF_DIR / "platform-metadata" / batch):
                if not base_dir.is_dir():
                    continue
                for f in base_dir.rglob("*"):
                    if f.is_file() and f.suffix in (".json", ".txt", ".md", ".html", ".srt"):
                        text = f.read_text(encoding="utf-8", errors="ignore")
                        if SECRET_PATTERN.search(text):
                            offenders.append(str(f))
        self.assertEqual(offenders, [])

    def test_no_secret_patterns_in_content_queue_and_review(self):
        offenders = []
        for f in [CF_DIR / "content-queue.json", CF_DIR / "review" / "index.html"]:
            text = f.read_text(encoding="utf-8", errors="ignore")
            if SECRET_PATTERN.search(text):
                offenders.append(str(f))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
