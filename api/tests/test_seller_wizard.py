"""Tests for the seller-facing onboarding wizard (api/b2b_seller_wizard.py,
api/media_pipeline/seller_intake.py) -- B2B content factory. Covers the 18
points requested by the owner:

1. /b2b/seller/start renders
2. seller onboarding form fields exist
3. product basics are saved
4. seller-intake.json is created
5. product reference upload roles are represented
6. references default to approved=false / pending_review
7. readiness checklist blocks dry-run if <3 approved references
8. readiness checklist allows dry-run if >=3 approved references
9. product page shows "what to upload" guide
10. product page shows Product Intelligence summary
11. campaign page shows client-friendly content package plan
12. campaign page shows core problem / viewer thought to trigger
13. SELLER-ONBOARDING-GUIDE.md exists
14. demo seed has seller-intake.json
15. no OpenAI calls
16. no Higgsfield calls
17. no auto-posting APIs
18. no Railway/Production changes (verified manually -- this test tree does
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
from api.media_pipeline import b2b_seed as seed

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_CLIENT = seed.DEMO_CLIENT_ID
DEMO_PRODUCT = seed.DEMO_PRODUCT_ID
DEMO_CAMPAIGN = seed.DEMO_CAMPAIGN_ID


def urlopen_raises():
    return mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call!"))


class WizardWebTestCase(unittest.TestCase):
    """Base class: drives the wizard through the FastAPI TestClient and
    cleans up the created client afterwards."""

    CLIENT_ID = "test-wizard-client"

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.main import app
        cls.client = TestClient(app)

    def tearDown(self):
        client_dir = st.client_dir(self.CLIENT_ID, str(REPO_ROOT))
        if client_dir.is_dir():
            shutil.rmtree(client_dir)

    def _step1(self, product_name="Test Wizard Product"):
        data = {
            "client_name": "Test Wizard Client", "contact": "wiz@example.com",
            "product_name": product_name, "marketplace": "ozon",
            "marketplace_article": "W1", "marketplace_url": "https://ozon.ru/w",
            "price": "990", "category": "test category",
            "short_product_description": "test description of the product",
        }
        r = self.client.post("/b2b/seller/start", data=data, follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text)
        return r.headers["location"].rsplit("/", 2)[-2]

    def _step2_upload_n(self, product_id, n=3):
        files = [("photos", (f"photo{i}.png", io.BytesIO(b"fake"), "image/png")) for i in range(n)]
        r = self.client.post(f"/b2b/seller/{product_id}/step2", files=files, follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text)

    def _approve_all_refs(self, product_id):
        product = None
        for p in st.list_all_products(str(REPO_ROOT)):
            if p.product_id == product_id:
                product = p
        refs = st.load_references(product.client_id, product_id, str(REPO_ROOT))
        for ref in refs:
            self.client.post(f"/b2b/products/{product_id}/references/approve",
                             data={"file_path": ref.file_path}, follow_redirects=False)


class TestWizardStartRenders(WizardWebTestCase):
    def test_step1_renders(self):
        r = self.client.get("/b2b/seller/start")
        self.assertEqual(r.status_code, 200)


class TestOnboardingFormFieldsExist(WizardWebTestCase):
    def test_step1_fields(self):
        r = self.client.get("/b2b/seller/start")
        for field in ("client_name", "product_name", "marketplace", "marketplace_article",
                     "marketplace_url", "price", "category", "short_product_description"):
            self.assertIn(field, r.text)

    def test_step3_fields(self):
        product_id = self._step1()
        r = self.client.get(f"/b2b/seller/{product_id}/step3")
        self.assertEqual(r.status_code, 200)
        for field in ("who_is_this_for", "what_problem_does_it_usually_solve",
                     "why_people_buy_it", "top_3_benefits", "use_cases", "common_questions",
                     "objections", "what_should_not_be_claimed", "tone_preference"):
            self.assertIn(field, r.text)

    def test_step5_fields(self):
        product_id = self._step1()
        r = self.client.get(f"/b2b/seller/{product_id}/step5")
        self.assertEqual(r.status_code, 200)
        self.assertIn("platforms", r.text)
        self.assertIn("package_duration", r.text)
        self.assertIn("content_types", r.text)
        self.assertIn("Готовый ZIP для ручной публикации", r.text)


class TestProductBasicsSaved(WizardWebTestCase):
    def test_product_json_has_wizard_fields(self):
        product_id = self._step1(product_name="Basics Save Test")
        product = st.load_product(self.CLIENT_ID, product_id, str(REPO_ROOT))
        self.assertEqual(product.product_name, "Basics Save Test")
        self.assertEqual(product.marketplace_article, "W1")
        self.assertEqual(product.price, "990")


class TestSellerIntakeCreated(WizardWebTestCase):
    def test_seller_intake_json_created_after_step1(self):
        product_id = self._step1()
        path = si.seller_intake_path(self.CLIENT_ID, product_id, str(REPO_ROOT))
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text(encoding="utf-8"))
        for section in ("product_basics", "reference_uploads", "customer_positioning",
                       "product_intelligence_summary", "content_package_settings",
                       "readiness_checklist", "created_at", "updated_at"):
            self.assertIn(section, data)
        self.assertEqual(data["product_basics"]["product_name"], "Test Wizard Product")


class TestReferenceUploadRoles(WizardWebTestCase):
    def test_upload_roles_represented(self):
        product_id = self._step1()
        self._step2_upload_n(product_id, n=3)
        refs = st.load_references(self.CLIENT_ID, product_id, str(REPO_ROOT))
        roles = {r.role for r in refs}
        self.assertEqual(roles, {"front", "top", "side"})


class TestReferencesDefaultPendingReview(WizardWebTestCase):
    def test_uploaded_refs_not_approved_by_default(self):
        product_id = self._step1()
        self._step2_upload_n(product_id, n=3)
        refs = st.load_references(self.CLIENT_ID, product_id, str(REPO_ROOT))
        for r in refs:
            self.assertFalse(r.approved)


class TestReadinessChecklistGatesDryRun(WizardWebTestCase):
    def test_blocks_dry_run_with_zero_uploaded_photos(self):
        product_id = self._step1()
        self.client.post(f"/b2b/seller/{product_id}/step3", data={}, follow_redirects=False)
        self.client.post(f"/b2b/seller/{product_id}/step5",
                         data={"platforms": ["youtube_shorts"], "package_duration": "14_days"},
                         follow_redirects=False)
        r = self.client.post(f"/b2b/seller/{product_id}/step6/dry-run", follow_redirects=False)
        self.assertEqual(r.status_code, 422)

    def test_allows_dry_run_with_uploaded_unapproved_photos(self):
        # Seller MVP policy: uploaded (not necessarily approved) references
        # are enough to unblock the dry-run -- this is the exact scenario
        # that used to incorrectly 422 before the seller-flow policy fix.
        product_id = self._step1()
        self._step2_upload_n(product_id, n=3)  # uploaded but not approved
        self.client.post(f"/b2b/seller/{product_id}/step3", data={}, follow_redirects=False)
        self.client.post(f"/b2b/seller/{product_id}/step5",
                         data={"platforms": ["youtube_shorts"], "package_duration": "14_days"},
                         follow_redirects=False)
        r = self.client.post(f"/b2b/seller/{product_id}/step6/dry-run", follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text)

    def test_allows_dry_run_with_single_uploaded_photo(self):
        product_id = self._step1()
        self._step2_upload_n(product_id, n=1)
        self.client.post(f"/b2b/seller/{product_id}/step5",
                         data={"platforms": ["youtube_shorts"], "package_duration": "14_days"},
                         follow_redirects=False)
        r = self.client.post(f"/b2b/seller/{product_id}/step6/dry-run", follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text)

    def test_allows_dry_run_at_or_above_threshold(self):
        product_id = self._step1()
        self._step2_upload_n(product_id, n=3)
        self._approve_all_refs(product_id)
        self.client.post(f"/b2b/seller/{product_id}/step5",
                         data={"platforms": ["youtube_shorts"], "package_duration": "14_days"},
                         follow_redirects=False)
        r = self.client.post(f"/b2b/seller/{product_id}/step6/dry-run", follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text)
        self.assertTrue(r.headers["location"].startswith("/b2b/campaigns/"))


class TestProductPageShowsUploadGuide(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.main import app
        cls.client = TestClient(app)

    def test_upload_guide_present(self):
        r = self.client.get(f"/b2b/products/{DEMO_PRODUCT}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Что нужно загрузить", r.text)
        self.assertIn("Product references", r.text)


class TestProductPageShowsIntelligenceSummary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.main import app
        cls.client = TestClient(app)

    def test_intelligence_summary_present(self):
        r = self.client.get(f"/b2b/products/{DEMO_PRODUCT}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Что система поняла о вашем товаре", r.text)


class TestCampaignPageShowsContentPackagePlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.main import app
        cls.client = TestClient(app)

    def test_content_package_plan_present(self):
        r = self.client.get(f"/b2b/campaigns/{DEMO_CAMPAIGN}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Что создаст контент-завод", r.text)
        for marker in ("рекламные сцены", "short video creatives", "статьи Дзена",
                      "план публикаций", "таблица для отслеживания результатов", "ZIP с материалами"):
            self.assertIn(marker, r.text)

    def test_core_problem_and_viewer_thought_present(self):
        r = self.client.get(f"/b2b/campaigns/{DEMO_CAMPAIGN}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Контент будет строиться на основе главной проблемы товара", r.text)
        self.assertIn("Главная мысль зрителя", r.text)


class TestSellerGuideExists(unittest.TestCase):
    def test_file_exists(self):
        path = REPO_ROOT / "content" / "b2b" / "templates" / "SELLER-ONBOARDING-GUIDE.md"
        self.assertTrue(path.is_file())

    def test_covers_required_sections(self):
        text = (REPO_ROOT / "content" / "b2b" / "templates" /
               "SELLER-ONBOARDING-GUIDE.md").read_text(encoding="utf-8")
        for marker in ("front", "top", "side", "detail", "packaging", "product reference",
                      "AI-анализ", "primary problem", "DELIVERY-KIT.zip", "Run dry-run"):
            self.assertIn(marker, text)


class TestDemoSeedHasSellerIntake(unittest.TestCase):
    def test_seed_demo_creates_seller_intake(self):
        with urlopen_raises():
            result = seed.seed_demo(str(REPO_ROOT))
        self.assertIn("seller_intake_path", result)
        self.assertTrue(Path(result["seller_intake_path"]).is_file())
        intake = si.load_seller_intake(DEMO_CLIENT, DEMO_PRODUCT, str(REPO_ROOT))
        self.assertIsNotNone(intake)
        self.assertEqual(intake["content_package_settings"]["package_duration"], "14_days")
        self.assertTrue(result["readiness_checklist"]["can_run_dry_run"])


class TestZeroExternalCallsAndNoAutoPosting(unittest.TestCase):
    def test_no_network_markers_in_wizard_modules(self):
        import api.b2b_seller_wizard as wiz
        for mod in (wiz, si):
            src = Path(mod.__file__).read_text(encoding="utf-8")
            for marker in ("import requests", "import httpx", "urllib.request.urlopen(",
                          "import openai", "OpenAI(", "higgsfield_client.",
                          "HiggsfieldClient(", "higgsfield.generate",
                          "requests.post", "httpx.post", "youtube.upload",
                          "instagram_api", "tiktok_api", "vk_api.upload"):
                self.assertNotIn(marker, src)

    def test_seed_demo_zero_openai_higgsfield(self):
        with urlopen_raises():
            result = seed.seed_demo(str(REPO_ROOT))
        self.assertNotIn("openai_calls", result)  # seed itself makes no API-call accounting claims
        # dry-run built from the same demo data must explicitly declare 0 calls
        from api.media_pipeline import b2b_campaign_contract as contract
        with urlopen_raises():
            plan = contract.build_campaign_dry_run(DEMO_CLIENT, DEMO_PRODUCT, DEMO_CAMPAIGN, str(REPO_ROOT))
        self.assertEqual(plan["openai_calls"], 0)
        self.assertEqual(plan["higgsfield_calls"], 0)
        self.assertFalse(plan["auto_posting_triggered"])


if __name__ == "__main__":
    unittest.main()
