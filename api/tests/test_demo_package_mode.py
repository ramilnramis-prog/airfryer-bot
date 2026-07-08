"""Tests for the demo/test package mode ("Демо -- 1 тестовый ролик") added to
the B2B seller wizard so a seller can validate the system on a single video
before committing to a 7/14/30-day package. Covers the 13 points requested
by the owner:

1. Step 5 shows "Демо -- 1 тестовый ролик"
2. demo_1_video backend value exists
3. demo_1_video is the first / recommended option
4. demo_1_video dry-run plans exactly 1 video
5. demo_1_video dry-run plans 0 Dzen articles
6. campaign page shows demo mode
7. campaign page does not show the full 40-video package list for demo mode
8. Step 6 button text changes for demo mode
9. campaign-dry-run.json contains package_mode: demo_1_video
10. no OpenAI calls
11. no Higgsfield calls
12. no auto-posting
13. no Railway/Production changes (verified manually -- this test tree does
    not touch any Railway/production config)
"""
import io
import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline import b2b_storage as st
from api.media_pipeline import seller_intake as si
from api.media_pipeline import b2b_campaign_contract as contract

REPO_ROOT = Path(__file__).resolve().parents[2]


def urlopen_raises():
    return mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call!"))


class DemoWizardTestCase(unittest.TestCase):
    """Drives the seller wizard through the FastAPI TestClient far enough to
    run a dry-run in demo mode, and cleans up the created client afterwards."""

    CLIENT_ID = "demo-mode-test-client"

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.main import app
        cls.client = TestClient(app)

    def tearDown(self):
        client_dir = st.client_dir(self.CLIENT_ID, str(REPO_ROOT))
        if client_dir.is_dir():
            shutil.rmtree(client_dir)

    def _step1(self, product_name="Demo Mode Test Product"):
        data = {
            "client_name": "demo-mode-test-client", "contact": "demo@example.com",
            "product_name": product_name, "marketplace": "ozon",
            "marketplace_article": "D1", "marketplace_url": "https://ozon.ru/d",
            "price": "1290", "category": "test category",
            "short_product_description": "test description of the demo product",
        }
        r = self.client.post("/b2b/seller/start", data=data, follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text)
        return r.headers["location"].rsplit("/", 2)[-2]

    def _step2_upload_n(self, product_id, n=1):
        files = [("photos", (f"photo{i}.png", io.BytesIO(b"fake"), "image/png")) for i in range(n)]
        r = self.client.post(f"/b2b/seller/{product_id}/step2", files=files, follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text)

    def _select_demo_package(self, product_id):
        r = self.client.post(f"/b2b/seller/{product_id}/step5",
                             data={"platforms": ["youtube_shorts"],
                                   "package_duration": "demo_1_video"},
                             follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text)

    def _run_dry_run(self, product_id):
        r = self.client.post(f"/b2b/seller/{product_id}/step6/dry-run", follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text)
        return r.headers["location"].rsplit("/", 1)[-1]


class TestStep5ShowsDemoOption(DemoWizardTestCase):
    def test_step5_shows_demo_label(self):
        product_id = self._step1()
        r = self.client.get(f"/b2b/seller/{product_id}/step5")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Демо", r.text)
        self.assertIn("1 тестовый ролик", r.text)


class TestDemoBackendValueExists(unittest.TestCase):
    def test_demo_value_in_package_durations(self):
        self.assertEqual(si.DEMO_PACKAGE_DURATION, "demo_1_video")
        self.assertIn("demo_1_video", si.PACKAGE_DURATIONS)
        self.assertIn("demo_1_video", si.PACKAGE_DURATION_LABELS)

    def test_existing_durations_kept(self):
        for d in ("7_days", "14_days", "30_days"):
            self.assertIn(d, si.PACKAGE_DURATIONS)


class TestDemoIsFirstAndRecommended(DemoWizardTestCase):
    def test_demo_is_first_backend_option(self):
        self.assertEqual(si.PACKAGE_DURATIONS[0], si.DEMO_PACKAGE_DURATION)

    def test_step5_shows_recommended_badge(self):
        product_id = self._step1()
        r = self.client.get(f"/b2b/seller/{product_id}/step5")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Рекомендуется для первого теста", r.text)


class TestDemoDryRunPlansOneVideo(DemoWizardTestCase):
    def test_dry_run_plans_exactly_one_video(self):
        product_id = self._step1()
        self._step2_upload_n(product_id, n=1)
        self._select_demo_package(product_id)
        with urlopen_raises():
            campaign_id = self._run_dry_run(product_id)
        product = None
        for p in st.list_all_products(str(REPO_ROOT)):
            if p.product_id == product_id:
                product = p
        plan = json.loads((st.campaign_generated_dir(product.client_id, product_id, campaign_id,
                                                      str(REPO_ROOT)) / "campaign-dry-run.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual(plan["content_package_plan"]["planned_scenes_count"], 1)
        self.assertEqual(plan["content_package_plan"]["planned_short_videos_count"], 1)
        self.assertTrue(plan["content_package_plan"]["demo_mode"])
        self.assertEqual(plan["content_package_plan"]["planned_publishing_days"], 1)


class TestDemoDryRunZeroDzenArticles(DemoWizardTestCase):
    def test_dry_run_plans_zero_dzen_articles(self):
        product_id = self._step1()
        self._step2_upload_n(product_id, n=1)
        self._select_demo_package(product_id)
        with urlopen_raises():
            campaign_id = self._run_dry_run(product_id)
        product = None
        for p in st.list_all_products(str(REPO_ROOT)):
            if p.product_id == product_id:
                product = p
        plan = json.loads((st.campaign_generated_dir(product.client_id, product_id, campaign_id,
                                                      str(REPO_ROOT)) / "campaign-dry-run.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual(plan["content_package_plan"]["planned_dzen_articles_count"], 0)
        self.assertEqual(plan["content_package_plan"]["planned_article_images_count"], 0)


class TestCampaignPageShowsDemoMode(DemoWizardTestCase):
    def test_campaign_page_shows_demo_badge_and_reduced_list(self):
        product_id = self._step1()
        self._step2_upload_n(product_id, n=1)
        self._select_demo_package(product_id)
        with urlopen_raises():
            campaign_id = self._run_dry_run(product_id)
        r = self.client.get(f"/b2b/campaigns/{campaign_id}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Режим: демо -- 1 тестовый ролик", r.text)
        self.assertIn("1 рекламный сценарий", r.text)
        self.assertIn("1 short video creative", r.text)
        self.assertIn("тестовый ZIP после генерации", r.text)

    def test_campaign_page_hides_full_package_items_for_demo(self):
        product_id = self._step1()
        self._step2_upload_n(product_id, n=1)
        self._select_demo_package(product_id)
        with urlopen_raises():
            campaign_id = self._run_dry_run(product_id)
        r = self.client.get(f"/b2b/campaigns/{campaign_id}")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("статьи Дзена", r.text)
        self.assertNotIn("картинки к статьям", r.text)
        self.assertNotIn("таблица для отслеживания результатов", r.text)


class TestStep6ButtonTextChangesForDemo(DemoWizardTestCase):
    def test_step6_shows_demo_button_text(self):
        product_id = self._step1()
        self._select_demo_package(product_id)
        r = self.client.get(f"/b2b/seller/{product_id}/step6")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Проверить будущий тестовый ролик", r.text)
        self.assertIn("Будет создан тестовый план на 1 ролик.", r.text)

    def test_step6_shows_normal_button_text_for_full_package(self):
        product_id = self._step1()
        r = self.client.post(f"/b2b/seller/{product_id}/step5",
                             data={"platforms": ["youtube_shorts"], "package_duration": "14_days"},
                             follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text)
        r = self.client.get(f"/b2b/seller/{product_id}/step6")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Проверить будущий контент-пакет", r.text)
        self.assertNotIn("Будет создан тестовый план на 1 ролик.", r.text)


class TestDryRunJsonHasPackageMode(DemoWizardTestCase):
    def test_dry_run_json_contains_demo_package_mode(self):
        product_id = self._step1()
        self._step2_upload_n(product_id, n=1)
        self._select_demo_package(product_id)
        with urlopen_raises():
            campaign_id = self._run_dry_run(product_id)
        product = None
        for p in st.list_all_products(str(REPO_ROOT)):
            if p.product_id == product_id:
                product = p
        plan = json.loads((st.campaign_generated_dir(product.client_id, product_id, campaign_id,
                                                      str(REPO_ROOT)) / "campaign-dry-run.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual(plan["package_mode"], "demo_1_video")

    def test_dry_run_md_explains_demo_plan(self):
        product_id = self._step1()
        self._step2_upload_n(product_id, n=1)
        self._select_demo_package(product_id)
        with urlopen_raises():
            campaign_id = self._run_dry_run(product_id)
        product = None
        for p in st.list_all_products(str(REPO_ROOT)):
            if p.product_id == product_id:
                product = p
        md = (st.campaign_generated_dir(product.client_id, product_id, campaign_id, str(REPO_ROOT))
             / "campaign-dry-run.md").read_text(encoding="utf-8")
        self.assertIn("Это демо-план. Он нужен, чтобы проверить один ролик перед запуском "
                      "большого контент-пакета.", md)


class TestDemoModeZeroExternalCallsAndNoAutoPosting(DemoWizardTestCase):
    def test_demo_dry_run_declares_zero_calls_and_no_posting(self):
        product_id = self._step1()
        self._step2_upload_n(product_id, n=1)
        self._select_demo_package(product_id)
        with urlopen_raises():
            campaign_id = self._run_dry_run(product_id)
        product = None
        for p in st.list_all_products(str(REPO_ROOT)):
            if p.product_id == product_id:
                product = p
        plan = json.loads((st.campaign_generated_dir(product.client_id, product_id, campaign_id,
                                                      str(REPO_ROOT)) / "campaign-dry-run.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual(plan["openai_calls"], 0)
        self.assertEqual(plan["higgsfield_calls"], 0)
        self.assertEqual(plan["external_api_calls"], 0)
        self.assertFalse(plan["auto_posting_triggered"])

    def test_no_network_markers_in_contract_module(self):
        src = Path(contract.__file__).read_text(encoding="utf-8")
        for marker in ("import requests", "import httpx", "urllib.request.urlopen(",
                      "import openai", "OpenAI(", "higgsfield_client.",
                      "HiggsfieldClient(", "higgsfield.generate",
                      "requests.post", "httpx.post", "youtube.upload",
                      "instagram_api", "tiktok_api", "vk_api.upload"):
            self.assertNotIn(marker, src)


if __name__ == "__main__":
    unittest.main()
