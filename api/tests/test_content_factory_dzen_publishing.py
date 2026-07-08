"""Tests for the Dzen article publishing kits (inventory, selection,
per-article kits, image prompts, generated images, TODAY-PUBLISH, dashboard,
owner zip) -- campaign coating-protect-2026-07. Covers the 18 points
requested by the owner:

1. inventory JSON exists
2. selected articles plan exists
3. selected articles count >= 1
4. every selected article has publishing kit
5. every kit has article-ready-to-copy.md
6. every kit has image-prompts.md/json
7. every article has Ozon article 1931921872
8. every article has Ozon link
9. no forbidden claims
10. image prompts include negative prompt
11. image prompts specify aspect ratio
12. generated images exist for first priority article if image generation succeeded
13. TODAY-PUBLISH folder exists
14. Dzen publishing dashboard exists
15. zip exists and integrity verified
16. no generated image is promoted to reference
17. no auto-posting
18. no Railway/Production changes
"""
import json
import re
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from api.media_pipeline import content_factory_dzen_publishing as dzp

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"
DZEN_PUB_DIR = CAMPAIGN_DIR / "generated" / "content-factory" / "dzen-publishing"

SECRET_PATTERN = re.compile(
    r"sk-[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}|api[_-]?key['\"]?\s*[:=]\s*['\"][A-Za-z0-9]{16,}|"
    r"password['\"]?\s*[:=]\s*['\"][^'\"]{4,}|-----BEGIN"
)


def urlopen_raises():
    return mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call!"))


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class TestInventoryExists(unittest.TestCase):
    def test_json_exists(self):
        self.assertTrue((DZEN_PUB_DIR / "dzen-article-inventory.json").is_file())

    def test_md_exists(self):
        self.assertTrue((DZEN_PUB_DIR / "dzen-article-inventory.md").is_file())

    def test_finds_at_least_40_articles(self):
        d = load_json(DZEN_PUB_DIR / "dzen-article-inventory.json")
        self.assertGreaterEqual(d["total_articles_found"], 40)

    def test_live_scan_zero_network(self):
        with urlopen_raises():
            entries = dzp.scan_all_articles(str(REPO_ROOT))
        self.assertGreaterEqual(len(entries), 40)


class TestSelectedArticlesPlanExists(unittest.TestCase):
    def test_json_and_md_exist(self):
        self.assertTrue((DZEN_PUB_DIR / "selected-dzen-articles-plan.json").is_file())
        self.assertTrue((DZEN_PUB_DIR / "selected-dzen-articles-plan.md").is_file())

    def test_selected_count_at_least_1(self):
        d = load_json(DZEN_PUB_DIR / "selected-dzen-articles-plan.json")
        self.assertGreaterEqual(d["selected_count"], 1)
        self.assertEqual(len(d["selected_articles"]), d["selected_count"])

    def test_canon_article_included(self):
        d = load_json(DZEN_PUB_DIR / "selected-dzen-articles-plan.json")
        ids = [e["article_id"] for e in d["selected_articles"]]
        self.assertIn("canon-chasha-lyseet", ids)


class TestEverySelectedArticleHasKit(unittest.TestCase):
    def _selected_ids(self):
        d = load_json(DZEN_PUB_DIR / "selected-dzen-articles-plan.json")
        return [e["article_id"] for e in d["selected_articles"]]

    def test_kit_dir_exists_for_each(self):
        for article_id in self._selected_ids():
            kit_dir = DZEN_PUB_DIR / "articles" / article_id
            self.assertTrue(kit_dir.is_dir(), f"{article_id} kit dir missing")


class TestKitHasArticleReadyToCopy(unittest.TestCase):
    def test_article_file_exists_for_each_selected(self):
        d = load_json(DZEN_PUB_DIR / "selected-dzen-articles-plan.json")
        for e in d["selected_articles"]:
            path = DZEN_PUB_DIR / "articles" / e["article_id"] / "article-ready-to-copy.md"
            self.assertTrue(path.is_file(), f"{e['article_id']} missing article-ready-to-copy.md")
            self.assertGreater(len(path.read_text(encoding="utf-8")), 500)


class TestKitHasImagePrompts(unittest.TestCase):
    def test_json_and_md_exist_for_each_selected(self):
        d = load_json(DZEN_PUB_DIR / "selected-dzen-articles-plan.json")
        for e in d["selected_articles"]:
            kit_dir = DZEN_PUB_DIR / "articles" / e["article_id"]
            self.assertTrue((kit_dir / "image-prompts.json").is_file())
            self.assertTrue((kit_dir / "image-prompts.md").is_file())

    def test_prompt_count_within_4_to_7(self):
        d = load_json(DZEN_PUB_DIR / "selected-dzen-articles-plan.json")
        for e in d["selected_articles"]:
            doc = load_json(DZEN_PUB_DIR / "articles" / e["article_id"] / "image-prompts.json")
            self.assertGreaterEqual(doc["total_images"], 4)
            self.assertLessEqual(doc["total_images"], 7)


class TestEveryArticleHasOzonArtikul(unittest.TestCase):
    def test_ozon_artikul_present(self):
        d = load_json(DZEN_PUB_DIR / "selected-dzen-articles-plan.json")
        for e in d["selected_articles"]:
            text = (DZEN_PUB_DIR / "articles" / e["article_id"] / "article-ready-to-copy.md").read_text(encoding="utf-8")
            self.assertIn(dzp.OZON_ARTIKUL, text)
            self.assertNotIn("{{OZON_ARTIKUL}}", text)


class TestEveryArticleHasOzonLink(unittest.TestCase):
    def test_ozon_link_present(self):
        d = load_json(DZEN_PUB_DIR / "selected-dzen-articles-plan.json")
        for e in d["selected_articles"]:
            text = (DZEN_PUB_DIR / "articles" / e["article_id"] / "article-ready-to-copy.md").read_text(encoding="utf-8")
            self.assertIn(dzp.OZON_LINK, text)
            self.assertNotIn("{{OZON_LINK}}", text)

    def test_pinned_comment_has_link_and_artikul(self):
        d = load_json(DZEN_PUB_DIR / "selected-dzen-articles-plan.json")
        for e in d["selected_articles"]:
            text = (DZEN_PUB_DIR / "articles" / e["article_id"] / "PINNED-COMMENT.txt").read_text(encoding="utf-8")
            self.assertIn(dzp.OZON_LINK, text)
            self.assertIn(dzp.OZON_ARTIKUL, text)


class TestNoForbiddenClaims(unittest.TestCase):
    def test_no_forbidden_phrases_in_any_selected_article(self):
        d = load_json(DZEN_PUB_DIR / "selected-dzen-articles-plan.json")
        for e in d["selected_articles"]:
            text = (DZEN_PUB_DIR / "articles" / e["article_id"] / "article-ready-to-copy.md").read_text(encoding="utf-8")
            hits = dzp._has_forbidden_claim(text)
            self.assertEqual(hits, [], f"{e['article_id']} contains forbidden claim(s): {hits}")

    def test_canon_softening_rule_applied(self):
        text = (DZEN_PUB_DIR / "articles" / "canon-chasha-lyseet" / "article-ready-to-copy.md").read_text(encoding="utf-8")
        self.assertNotIn("вообще не пачкалась", text)
        self.assertIn("вообще не соприкасалась", text)


class TestImagePromptsHaveNegativePrompt(unittest.TestCase):
    def test_every_prompt_has_negative_prompt(self):
        d = load_json(DZEN_PUB_DIR / "selected-dzen-articles-plan.json")
        for e in d["selected_articles"]:
            doc = load_json(DZEN_PUB_DIR / "articles" / e["article_id"] / "image-prompts.json")
            for p in doc["prompts"]:
                self.assertTrue(p["negative_prompt"])
                for banned in ("loop handles", "vertical oval holes", "duplicate tray",
                              "text", "watermark", "logo", "CGI"):
                    self.assertIn(banned, p["negative_prompt"])


class TestImagePromptsSpecifyAspectRatio(unittest.TestCase):
    def test_every_prompt_has_aspect_ratio(self):
        d = load_json(DZEN_PUB_DIR / "selected-dzen-articles-plan.json")
        for e in d["selected_articles"]:
            doc = load_json(DZEN_PUB_DIR / "articles" / e["article_id"] / "image-prompts.json")
            for p in doc["prompts"]:
                self.assertIn("aspect_ratio", p)
                self.assertTrue(p["aspect_ratio"])


class TestGeneratedImagesForFirstPriorityArticle(unittest.TestCase):
    def test_canon_article_images_exist(self):
        images_dir = DZEN_PUB_DIR / "articles" / "canon-chasha-lyseet" / "images"
        pngs = list(images_dir.glob("*.png")) if images_dir.is_dir() else []
        report_path = DZEN_PUB_DIR / "articles" / "canon-chasha-lyseet" / "image-generation-report.json"
        if report_path.is_file():
            report = load_json(report_path)
            if report["images_generated"] > 0:
                self.assertGreater(len(pngs), 0)


class TestTodayPublishFolderExists(unittest.TestCase):
    def test_folder_and_files_exist(self):
        today_dir = DZEN_PUB_DIR / "TODAY-PUBLISH"
        self.assertTrue(today_dir.is_dir())
        for name in ("ARTICLE-TO-COPY.md", "PINNED-COMMENT.txt", "TAGS.txt",
                    "IMAGE-PROMPTS-TO-GENERATE.md", "CHECKLIST.txt"):
            self.assertTrue((today_dir / name).is_file(), f"{name} missing from TODAY-PUBLISH")

    def test_today_publish_is_canon_article(self):
        text = (DZEN_PUB_DIR / "TODAY-PUBLISH" / "ARTICLE-TO-COPY.md").read_text(encoding="utf-8")
        self.assertIn("лысеет", text)

    def test_live_build_zero_network(self):
        with urlopen_raises():
            result = dzp.build_today_publish(str(CAMPAIGN_DIR))
        self.assertEqual(result["article_id"], "canon-chasha-lyseet")


class TestDzenPublishingDashboardExists(unittest.TestCase):
    def test_index_html_exists(self):
        path = DZEN_PUB_DIR / "index.html"
        self.assertTrue(path.is_file())
        html = path.read_text(encoding="utf-8")
        self.assertIn("canon-chasha-lyseet", html)
        self.assertIn("images_generated", html)


class TestZipExistsAndIntegrityVerified(unittest.TestCase):
    def test_zip_exists(self):
        self.assertTrue((DZEN_PUB_DIR / "DZEN-PUBLISHING-KIT.zip").is_file())

    def test_zip_integrity(self):
        z = zipfile.ZipFile(DZEN_PUB_DIR / "DZEN-PUBLISHING-KIT.zip")
        self.assertIsNone(z.testzip())
        self.assertGreater(len(z.namelist()), 0)

    def test_zip_contains_today_publish_and_articles(self):
        z = zipfile.ZipFile(DZEN_PUB_DIR / "DZEN-PUBLISHING-KIT.zip")
        names = z.namelist()
        self.assertTrue(any("TODAY-PUBLISH" in n for n in names))
        self.assertTrue(any("articles/canon-chasha-lyseet/article-ready-to-copy.md" in n.replace("\\", "/")
                           for n in names))


class TestNoGeneratedImagePromotedToReference(unittest.TestCase):
    def test_module_does_not_write_to_product_lock(self):
        # The module DOES read PRODUCT_REFERENCE_ASSET_PATHS (to resolve the
        # 4 allowed real-v1 reference images) -- that's expected. What must
        # NEVER happen is writing generated output back into product-lock/,
        # or assigning into that dict (as opposed to reading from it).
        src = Path(dzp.__file__).read_text(encoding="utf-8")
        self.assertNotIn("assets/product-lock", src)
        self.assertNotIn("PRODUCT_REFERENCE_ASSET_PATHS[", src.replace(
            "por.PRODUCT_REFERENCE_ASSET_PATHS[ref_id]", ""))

    def test_reference_images_only_come_from_allowlist(self):
        d = load_json(DZEN_PUB_DIR / "selected-dzen-articles-plan.json")
        for e in d["selected_articles"]:
            doc = load_json(DZEN_PUB_DIR / "articles" / e["article_id"] / "image-prompts.json")
            for p in doc["prompts"]:
                if p["use_product_reference"]:
                    for ref in p["reference_images"]:
                        self.assertIn(ref, dzp.PRODUCT_REFERENCE_IMAGES)

    def test_generated_images_never_listed_as_reference_source(self):
        d = load_json(DZEN_PUB_DIR / "selected-dzen-articles-plan.json")
        for e in d["selected_articles"]:
            doc = load_json(DZEN_PUB_DIR / "articles" / e["article_id"] / "image-prompts.json")
            for p in doc["prompts"]:
                for ref in p.get("reference_images", []):
                    self.assertNotIn("generated", ref)
                    self.assertNotIn("dzen-publishing", ref)


class TestNoAutoPosting(unittest.TestCase):
    def test_no_posting_markers_in_module(self):
        src = Path(dzp.__file__).read_text(encoding="utf-8")
        for marker in ("requests.post", "httpx.post", "auto_post(", "social_publish"):
            self.assertNotIn(marker, src)

    def test_generation_summary_never_auto_accepts(self):
        d = load_json(DZEN_PUB_DIR / "selected-dzen-articles-plan.json")
        for e in d["selected_articles"]:
            report_path = DZEN_PUB_DIR / "articles" / e["article_id"] / "image-generation-report.json"
            if report_path.is_file():
                report = load_json(report_path)
                for r in report["results"]:
                    self.assertNotEqual(r["candidate_status"], "accepted")
                    self.assertIn(r["candidate_status"],
                                 ("pending_manual_review", "rejected_api_error",
                                  "no_candidate_timeout", "skipped_hard_limit"))


class TestNoRailwayProductionChanges(unittest.TestCase):
    def test_module_does_not_reference_railway(self):
        src = Path(dzp.__file__).read_text(encoding="utf-8").lower()
        self.assertNotIn("railway", src)
        self.assertNotIn("production", src)

    def test_dzen_publishing_output_is_gitignored(self):
        import subprocess
        result = subprocess.run(
            ["git", "check-ignore",
             "content/autopilot/coating-protect-2026-07/generated/content-factory/"
             "dzen-publishing/dzen-article-inventory.json"],
            cwd=str(REPO_ROOT), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, "dzen-publishing output is NOT gitignored")


class TestSecretScanCleanInDzenPublishingOutputs(unittest.TestCase):
    def test_no_secrets_in_text_outputs(self):
        offenders = []
        for f in DZEN_PUB_DIR.rglob("*"):
            if f.is_file() and f.suffix in (".json", ".md", ".txt", ".html"):
                text = f.read_text(encoding="utf-8", errors="ignore")
                if SECRET_PATTERN.search(text):
                    offenders.append(str(f))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
