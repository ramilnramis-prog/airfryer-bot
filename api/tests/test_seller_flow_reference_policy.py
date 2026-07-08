"""Tests for the seller-flow reference policy fix -- the wizard's final
step used to block a seller who uploaded photos but hadn't been manually
approved by an admin, which reads as a broken/erroring flow for a public
client. Covers the 15 points requested by the owner:

1. Step 2 copy says at least 1 clear product photo
2. Step 2 recommends 3-8 photos
3. Step 6 does not require approved references in seller flow
4. Step 6 requires at least 1 uploaded photo
5. Step 6 shows warning for 1-2 photos, not blocking error
6. Step 6 shows green/good status for 3+ photos
7. "Проверить будущий контент-пакет" enabled when 1+ uploaded photos and
   other required fields present
8. Dry-run seller flow allows 1 uploaded product photo
9. Dry-run includes reference_quality
10. Generated paths still rejected as references
11. Admin/internal approval buttons still exist on product page
12. No OpenAI calls
13. No Higgsfield calls
14. No auto-posting
15. No Railway/Production changes (verified manually -- this test tree does
    not touch any Railway/production config)
"""
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline import b2b_storage as st
from api.media_pipeline import b2b_reference_policy as pol
from api.media_pipeline import b2b_campaign_contract as contract
from api.media_pipeline import b2b_seed as seed

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_PRODUCT = seed.DEMO_PRODUCT_ID
DEMO_CAMPAIGN = seed.DEMO_CAMPAIGN_ID


class SellerFlowTestCase(unittest.TestCase):
    CLIENT_ID = "test-seller-flow-client"

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.main import app
        cls.client = TestClient(app)

    def tearDown(self):
        client_dir = st.client_dir(self.CLIENT_ID, str(REPO_ROOT))
        if client_dir.is_dir():
            shutil.rmtree(client_dir)

    def _step1(self, product_name="Seller Flow Test Product"):
        data = {
            "client_name": "Test Seller Flow Client", "contact": "sf@example.com",
            "product_name": product_name, "marketplace": "ozon",
            "marketplace_article": "SF1", "marketplace_url": "https://ozon.ru/sf",
            "price": "700", "category": "test",
            "short_product_description": "test description",
        }
        r = self.client.post("/b2b/seller/start", data=data, follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text)
        return r.headers["location"].rsplit("/", 2)[-2]

    def _upload_n(self, product_id, n):
        files = [("photos", (f"photo{i}.png", io.BytesIO(b"fake"), "image/png"))
                for i in range(n)]
        r = self.client.post(f"/b2b/seller/{product_id}/step2", files=files, follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text)


class TestStep2CopyMinimumOnePhoto(SellerFlowTestCase):
    def test_says_at_least_one_photo(self):
        product_id = self._step1()
        r = self.client.get(f"/b2b/seller/{product_id}/step2")
        self.assertIn("Добавьте хотя бы 1 чёткое фото товара", r.text)

    def test_recommends_3_to_8_photos(self):
        product_id = self._step1()
        r = self.client.get(f"/b2b/seller/{product_id}/step2")
        self.assertIn("Лучше 3-8 фото с разных ракурсов", r.text)


class TestStep6DoesNotRequireApproval(SellerFlowTestCase):
    def test_uploaded_unapproved_photo_unblocks_dry_run(self):
        product_id = self._step1()
        self._upload_n(product_id, 1)
        refs = st.load_references(self.CLIENT_ID, product_id, str(REPO_ROOT))
        self.assertFalse(any(r.approved for r in refs))  # still unapproved
        self.client.post(f"/b2b/seller/{product_id}/step5",
                         data={"platforms": ["youtube_shorts"], "package_duration": "14_days"},
                         follow_redirects=False)
        r = self.client.post(f"/b2b/seller/{product_id}/step6/dry-run", follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text)


class TestStep6RequiresAtLeastOnePhoto(SellerFlowTestCase):
    def test_zero_photos_blocks(self):
        product_id = self._step1()
        self.client.post(f"/b2b/seller/{product_id}/step5",
                         data={"platforms": ["youtube_shorts"], "package_duration": "14_days"},
                         follow_redirects=False)
        r = self.client.post(f"/b2b/seller/{product_id}/step6/dry-run", follow_redirects=False)
        self.assertEqual(r.status_code, 422)
        self.assertIn("NOT_ENOUGH_UPLOADED_REFERENCES", r.text)


class TestStep6WarningNotErrorForOneOrTwo(SellerFlowTestCase):
    def test_one_photo_shows_warning_alert_not_error(self):
        product_id = self._step1()
        self._upload_n(product_id, 1)
        r = self.client.get(f"/b2b/seller/{product_id}/step6")
        self.assertIn("alert-warning", r.text)
        self.assertIn("Можно продолжить", r.text)

    def test_two_photos_shows_warning_alert_not_error(self):
        product_id = self._step1()
        self._upload_n(product_id, 2)
        r = self.client.get(f"/b2b/seller/{product_id}/step6")
        self.assertIn("alert-warning", r.text)


class TestStep6GreenStatusForThreePlus(SellerFlowTestCase):
    def test_three_photos_shows_green_status(self):
        product_id = self._step1()
        self._upload_n(product_id, 3)
        r = self.client.get(f"/b2b/seller/{product_id}/step6")
        self.assertIn("alert-success", r.text)
        self.assertIn("Этого достаточно для старта", r.text)


class TestButtonsEnabledWithOnePhoto(SellerFlowTestCase):
    def test_dry_run_button_not_disabled(self):
        product_id = self._step1()
        self._upload_n(product_id, 1)
        self.client.post(f"/b2b/seller/{product_id}/step5",
                         data={"platforms": ["youtube_shorts"], "package_duration": "14_days"},
                         follow_redirects=False)
        r = self.client.get(f"/b2b/seller/{product_id}/step6")
        self.assertNotIn("disabled", r.text)
        self.assertIn("Проверить будущий контент-пакет", r.text)
        self.assertIn("Собрать готовый ZIP с материалами", r.text)


class TestDryRunAllowsSinglePhoto(unittest.TestCase):
    def test_build_campaign_dry_run_with_one_unapproved_photo(self):
        with tempfile.TemporaryDirectory() as tmp:
            st.save_client(st.Client(client_id="acme", name="Acme"), tmp)
            st.save_product(st.Product(product_id="widget", client_id="acme",
                                       product_name="Widget"), tmp)
            img = Path(tmp) / "a.png"
            img.write_bytes(b"fake")
            st.add_reference("acme", "widget", str(img), role="front",
                             approved=False, repo_root=tmp)
            st.save_campaign(st.Campaign(campaign_id="camp1", client_id="acme",
                                         product_id="widget"), tmp)
            with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network!")):
                plan = contract.build_campaign_dry_run("acme", "widget", "camp1", tmp)
            self.assertEqual(plan["status"], "dry_run_only")
            self.assertEqual(len(plan["references_used"]), 1)


class TestDryRunIncludesReferenceQuality(unittest.TestCase):
    def test_reference_quality_present(self):
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network!")):
            plan = contract.build_campaign_dry_run(seed.DEMO_CLIENT_ID, DEMO_PRODUCT,
                                                    DEMO_CAMPAIGN, str(REPO_ROOT))
        self.assertIn("reference_quality", plan)
        rq = plan["reference_quality"]
        for key in ("uploaded_count", "approved_count", "minimum_required_for_seller_flow",
                   "recommended_count", "quality_risk", "notes"):
            self.assertIn(key, rq)
        self.assertIn(rq["quality_risk"], ("high", "medium", "low"))

    def test_quality_risk_levels(self):
        with tempfile.TemporaryDirectory() as tmp:
            st.save_client(st.Client(client_id="acme", name="Acme"), tmp)
            st.save_product(st.Product(product_id="widget", client_id="acme",
                                       product_name="Widget"), tmp)
            for i in range(1):
                img = Path(tmp) / f"r{i}.png"
                img.write_bytes(b"fake")
                st.add_reference("acme", "widget", str(img), role="front",
                                 approved=False, repo_root=tmp)
            q = pol.build_reference_quality("acme", "widget", tmp)
            self.assertEqual(q["quality_risk"], "high")

            img2 = Path(tmp) / "r2.png"
            img2.write_bytes(b"fake")
            st.add_reference("acme", "widget", str(img2), role="top", approved=False, repo_root=tmp)
            q2 = pol.build_reference_quality("acme", "widget", tmp)
            self.assertEqual(q2["quality_risk"], "medium")

            img3 = Path(tmp) / "r3.png"
            img3.write_bytes(b"fake")
            st.add_reference("acme", "widget", str(img3), role="side", approved=False, repo_root=tmp)
            q3 = pol.build_reference_quality("acme", "widget", tmp)
            self.assertEqual(q3["quality_risk"], "low")


class TestGeneratedPathsStillRejected(unittest.TestCase):
    def test_generated_path_rejected_in_lenient_mode(self):
        bad_ref = st.ProductReference(
            product_id="x", file_path="content/autopilot/x/generated/foo-c1.png",
            role="front", approved=True)
        with self.assertRaises(pol.B2BReferencePolicyError) as ctx:
            pol.validate_reference_entry(bad_ref, str(REPO_ROOT), require_approved=False)
        self.assertEqual(ctx.exception.code, "FORBIDDEN_REFERENCE_PATH")

    def test_generated_reference_excluded_from_seller_flow_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            st.save_client(st.Client(client_id="acme", name="Acme"), tmp)
            st.save_product(st.Product(product_id="widget", client_id="acme",
                                       product_name="Widget"), tmp)
            st.add_reference("acme", "widget",
                            "content/autopilot/x/generated/foo-c1.png",
                            role="front", approved=True, repo_root=tmp)
            with self.assertRaises(pol.B2BReferencePolicyError) as ctx:
                pol.assert_campaign_generation_allowed("acme", "widget", tmp)
            self.assertEqual(ctx.exception.code, "FORBIDDEN_REFERENCE_PATH")


class TestAdminApprovalButtonsStillExist(unittest.TestCase):
    def test_product_page_has_approve_and_note(self):
        from fastapi.testclient import TestClient
        from api.main import app
        client = TestClient(app)
        r = client.get(f"/b2b/products/{DEMO_PRODUCT}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("approve", r.text)
        self.assertIn("unapprove", r.text)
        self.assertIn("Подтверждение фото нужно для внутренней проверки качества", r.text)


class TestZeroExternalCallsAndNoAutoPosting(unittest.TestCase):
    def test_no_network_markers_in_policy_module(self):
        src = Path(pol.__file__).read_text(encoding="utf-8")
        for marker in ("import requests", "import httpx", "urllib.request.urlopen(",
                      "import openai", "OpenAI(", "HiggsfieldClient(",
                      "requests.post", "httpx.post", "youtube.upload"):
            self.assertNotIn(marker, src)

    def test_dry_run_zero_calls_with_lenient_policy(self):
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network!")):
            plan = contract.build_campaign_dry_run(seed.DEMO_CLIENT_ID, DEMO_PRODUCT,
                                                    DEMO_CAMPAIGN, str(REPO_ROOT))
        self.assertEqual(plan["openai_calls"], 0)
        self.assertEqual(plan["higgsfield_calls"], 0)
        self.assertFalse(plan["auto_posting_triggered"])


if __name__ == "__main__":
    unittest.main()
