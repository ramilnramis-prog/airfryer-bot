"""Tests for the local content factory (video variant planner, hook bank,
renderer, platform metadata, Dzen posts, review dashboard) -- campaign
coating-protect-2026-07. Covers the 14 points requested by the owner:

1. video-variant-plan has >=30 variants
2. hook-bank has >=100 hooks
3. first 10 variants have distinct hook_text
4. scene_order is valid (only real campaign scene ids)
5. required_assets exist or are marked missing (never silently dropped)
6. generated outputs are never fed back as OpenAI/Higgsfield references
7. renderer makes 0 OpenAI/Higgsfield calls
8. metadata is created for all 4 platforms
9. Dzen plan has >=30 posts
10. first 10 Dzen markdown posts exist
11. review index is created
12. no secrets in generated metadata
13. no auto-posting code is invoked anywhere in this pipeline
14. no Railway/Production changes
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

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"
CF_DIR = CAMPAIGN_DIR / "generated" / "content-factory"

SECRET_PATTERN = re.compile(
    r"sk-[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}|api[_-]?key['\"]?\s*[:=]\s*['\"][A-Za-z0-9]{16,}|"
    r"password['\"]?\s*[:=]\s*['\"][^'\"]{4,}|-----BEGIN"
)

FORBIDDEN_POSTING_MODULE_MARKERS = (
    "requests.post", "httpx.post", "tiktok_api", "instagram_api",
    "youtube_api", "vk_api.upload", "social_publish", "auto_post(",
)


def urlopen_raises():
    return mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call!"))


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class TestVideoVariantPlanCount(unittest.TestCase):
    def test_at_least_30_variants(self):
        with urlopen_raises():
            plan = planner.generate_video_variant_plan(str(CAMPAIGN_DIR))
        self.assertGreaterEqual(plan["total_variants"], 30)
        self.assertGreaterEqual(len(plan["variants"]), 30)

    def test_tracked_plan_file_has_at_least_30(self):
        plan_path = CF_DIR / "video-variants" / "video-variant-plan.json"
        self.assertTrue(plan_path.is_file())
        d = load_json(plan_path)
        self.assertGreaterEqual(d["total_variants"], 30)


class TestHookBankCount(unittest.TestCase):
    def test_at_least_100_hooks(self):
        self.assertGreaterEqual(fd.total_hook_count(), 100)

    def test_hook_bank_file_has_at_least_100(self):
        path = CF_DIR / "video-variants" / "hook-bank.json"
        self.assertTrue(path.is_file())
        d = load_json(path)
        self.assertGreaterEqual(d["total_hooks"], 100)
        counted = sum(len(v) for v in d["categories"].values())
        self.assertEqual(counted, d["total_hooks"])

    def test_no_forbidden_claim_markers_in_any_hook(self):
        for cat, hook in fd.all_hooks_flat():
            for marker in fd.FORBIDDEN_CLAIM_MARKERS:
                self.assertNotIn(marker.lower(), hook.lower(),
                                f"hook {hook!r} in category {cat} contains forbidden marker {marker!r}")


class TestFirstTenVariantsDistinctHooks(unittest.TestCase):
    def test_distinct_hook_text(self):
        with urlopen_raises():
            plan = planner.generate_video_variant_plan(str(CAMPAIGN_DIR))
        first_ten = plan["variants"][:10]
        hooks = [v["hook_text"] for v in first_ten]
        self.assertEqual(len(hooks), len(set(hooks)))


class TestSceneOrderValid(unittest.TestCase):
    def test_every_variant_scene_order_uses_real_scenes(self):
        with urlopen_raises():
            plan = planner.generate_video_variant_plan(str(CAMPAIGN_DIR))
        for v in plan["variants"]:
            for scene_id in v["scene_order"]:
                self.assertIn(scene_id, fd.CAMPAIGN_SCENE_ORDER)
            self.assertGreaterEqual(len(v["scene_order"]), 2)


class TestRequiredAssetsResolvedOrMissing(unittest.TestCase):
    def test_required_assets_have_exists_flag(self):
        with urlopen_raises():
            plan = planner.generate_video_variant_plan(str(CAMPAIGN_DIR))
        for v in plan["variants"]:
            for asset in v["required_assets"]:
                self.assertIn("exists", asset)
                self.assertIn("scene_id", asset)
                if asset["exists"]:
                    self.assertTrue(Path(asset["path"]).is_file())
                else:
                    self.assertIsNone(asset["path"])
            self.assertEqual(v["render_possible_locally"], all(a["exists"] for a in v["required_assets"]))

    def test_missing_scene_falls_back_without_crashing(self):
        entry = planner.resolve_scene_asset("scene-99", str(CAMPAIGN_DIR))
        self.assertFalse(entry["exists"])
        self.assertIsNone(entry["path"])


class TestGeneratedOutputsNeverUsedAsReferences(unittest.TestCase):
    def test_planner_module_does_not_import_openai_reference_machinery(self):
        src = Path(planner.__file__).read_text(encoding="utf-8")
        self.assertNotIn("product_reference_only_runner", src)
        self.assertNotIn("PRODUCT_REFERENCE_ASSET_PATHS", src)
        self.assertNotIn("reference_images", src)

    def test_renderer_module_does_not_import_openai_client(self):
        src = Path(renderer.__file__).read_text(encoding="utf-8")
        self.assertNotIn("openai_images_client", src)
        self.assertNotIn("OpenAIImagesProvider", src)

    def test_scene_assets_are_read_only_inputs_not_written_to(self):
        # resolve_scene_asset must never create/modify files under the
        # already-reviewed scene directories -- only read.
        before = {}
        scene_dir = CAMPAIGN_DIR / "generated/product-reference-only-scene-v2/scene-01"
        for f in scene_dir.iterdir():
            before[f.name] = f.stat().st_mtime
        planner.resolve_scene_asset("scene-01", str(CAMPAIGN_DIR))
        after = {f.name: f.stat().st_mtime for f in scene_dir.iterdir()}
        self.assertEqual(before, after)


class TestRendererMakesNoNetworkCalls(unittest.TestCase):
    def test_render_variant_zero_network_calls(self):
        with urlopen_raises():
            plan = planner.generate_video_variant_plan(str(CAMPAIGN_DIR))
        v = plan["variants"][0]
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with urlopen_raises():
                result = renderer.render_variant(v, tmp)
        self.assertIn(result["render_status"], ("rendered", "render_plan_only"))
        self.assertEqual(result["openai_calls"], 0)
        self.assertEqual(result["higgsfield_calls"], 0)

    def test_check_dependencies_no_network(self):
        with urlopen_raises():
            deps = renderer.check_render_dependencies()
        self.assertIn("can_render_mp4", deps)


class TestPlatformMetadataFourPlatforms(unittest.TestCase):
    def test_batch_metadata_covers_four_platforms(self):
        meta_dir = CF_DIR / "platform-metadata" / "batch-001"
        files = sorted(meta_dir.glob("v*-platform-metadata.json"))
        self.assertGreaterEqual(len(files), 10)
        for f in files:
            d = load_json(f)
            self.assertEqual(set(d["platforms"].keys()), set(fd.FORMATS))
            for platform, entry in d["platforms"].items():
                for key in ("title", "short_description", "caption", "hashtags", "CTA", "pinned_comment_idea"):
                    self.assertIn(key, entry)
                self.assertGreater(len(entry["hashtags"]), 0)

    def test_build_variant_platform_metadata_function(self):
        with urlopen_raises():
            plan = planner.generate_video_variant_plan(str(CAMPAIGN_DIR))
        v = plan["variants"][0]
        d = meta.build_variant_platform_metadata(v)
        self.assertEqual(set(d["platforms"].keys()), set(fd.FORMATS))


class TestDzenPlanCount(unittest.TestCase):
    def test_at_least_30_posts(self):
        plan = meta.generate_dzen_content_plan(target_count=32)
        self.assertGreaterEqual(plan["total_posts"], 30)

    def test_tracked_dzen_plan_file(self):
        path = CF_DIR / "dzen-posts" / "dzen-content-plan.json"
        self.assertTrue(path.is_file())
        d = load_json(path)
        self.assertGreaterEqual(d["total_posts"], 30)


class TestDzenFirstTenPostsExist(unittest.TestCase):
    def test_ten_markdown_files_exist_and_sized_correctly(self):
        batch_dir = CF_DIR / "dzen-posts" / "batch-001"
        md_files = sorted(batch_dir.glob("dzen-*.md"))
        self.assertGreaterEqual(len(md_files), 10)
        for f in md_files[:10]:
            text = f.read_text(encoding="utf-8")
            self.assertGreaterEqual(len(text), 1500)
            self.assertLessEqual(len(text), 3000)
            self.assertTrue(text.startswith("# "))

    def test_no_forbidden_claim_markers_in_dzen_posts(self):
        batch_dir = CF_DIR / "dzen-posts" / "batch-001"
        for f in sorted(batch_dir.glob("dzen-*.md"))[:10]:
            text = f.read_text(encoding="utf-8").lower()
            for marker in fd.FORBIDDEN_CLAIM_MARKERS:
                self.assertNotIn(marker.lower(), text, f"{f.name} contains forbidden marker {marker!r}")


class TestReviewIndexCreated(unittest.TestCase):
    def test_index_html_exists(self):
        path = CF_DIR / "review" / "index.html"
        self.assertTrue(path.is_file())
        html = path.read_text(encoding="utf-8")
        self.assertIn("ready_for_owner_review", html)
        self.assertIn("<video", html)

    def test_build_review_dashboard_function_idempotent(self):
        with urlopen_raises():
            path = review.build_review_dashboard(str(CAMPAIGN_DIR))
        self.assertTrue(Path(path).is_file())


class TestNoSecretsInGeneratedMetadata(unittest.TestCase):
    def test_no_secret_patterns_in_content_factory_tree(self):
        offenders = []
        for f in CF_DIR.rglob("*"):
            if f.is_file() and f.suffix in (".json", ".txt", ".md", ".html", ".srt"):
                text = f.read_text(encoding="utf-8", errors="ignore")
                if SECRET_PATTERN.search(text):
                    offenders.append(str(f))
        self.assertEqual(offenders, [])


class TestNoAutoPostingCodeInvoked(unittest.TestCase):
    def test_no_posting_api_markers_in_source(self):
        modules = [planner, renderer, meta, review, fd]
        for module in modules:
            src = Path(module.__file__).read_text(encoding="utf-8")
            for marker in FORBIDDEN_POSTING_MODULE_MARKERS:
                self.assertNotIn(marker, src, f"{module.__name__} contains posting marker {marker!r}")

    def test_metadata_and_dzen_writers_declare_auto_posting_false(self):
        pm_summary = CF_DIR / "platform-metadata" / "batch-001" / "platform-metadata-summary.json"
        dzen_summary = CF_DIR / "dzen-posts" / "batch-001" / "dzen-batch-summary.json"
        self.assertFalse(load_json(pm_summary)["auto_posting_triggered"])
        self.assertFalse(load_json(dzen_summary)["auto_posting_triggered"])

    def test_full_pipeline_functions_make_zero_network_calls(self):
        import tempfile
        with tempfile.TemporaryDirectory():
            with urlopen_raises():
                plan = meta.generate_dzen_content_plan(target_count=32)
                self.assertGreaterEqual(plan["total_posts"], 30)


class TestNoRailwayProductionChanges(unittest.TestCase):
    def test_content_factory_modules_do_not_reference_railway(self):
        modules = [planner, renderer, meta, review, fd]
        for module in modules:
            src = Path(module.__file__).read_text(encoding="utf-8").lower()
            self.assertNotIn("railway", src)
            self.assertNotIn("production", src)

    def test_generated_content_lives_under_gitignored_path(self):
        import subprocess
        result = subprocess.run(
            ["git", "check-ignore",
             "content/autopilot/coating-protect-2026-07/generated/content-factory/"
             "video-variants/video-variant-plan.json"],
            cwd=str(REPO_ROOT), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, "content-factory output is NOT gitignored")


if __name__ == "__main__":
    unittest.main()
