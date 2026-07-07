"""Tests for the B2B Seller Product Traffic Factory MVP skeleton (data
models, storage, reference policy, dry-run contract, delivery kit, web
routes, roadmap doc). Covers the 14 points requested by the owner:

1. b2b storage paths are created correctly
2. product.json schema valid
3. campaign.json schema valid
4. product reference policy rejects zero references
5. product reference policy rejects generated paths
6. product reference policy accepts approved uploaded product refs
7. b2b dry-run creates campaign-dry-run.json
8. dry-run makes 0 OpenAI calls
9. no Higgsfield calls
10. no auto-posting APIs are called
11. demo client/product/campaign seed exists or can be created
12. web routes render basic pages
13. delivery kit README template exists
14. AUTOPOSTING-ROADMAP.md exists
"""
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline import b2b_storage as st
from api.media_pipeline import b2b_reference_policy as pol
from api.media_pipeline import b2b_campaign_contract as contract
from api.media_pipeline import b2b_delivery_kit as dk
from api.media_pipeline import b2b_seed as seed

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_CLIENT = seed.DEMO_CLIENT_ID
DEMO_PRODUCT = seed.DEMO_PRODUCT_ID
DEMO_CAMPAIGN = seed.DEMO_CAMPAIGN_ID

SECRET_PATTERN = re.compile(
    r"sk-[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}|api[_-]?key['\"]?\s*[:=]\s*['\"][A-Za-z0-9]{16,}|"
    r"password['\"]?\s*[:=]\s*['\"][^'\"]{4,}|-----BEGIN"
)


def urlopen_raises():
    return mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call!"))


class TestStoragePathsCreatedCorrectly(unittest.TestCase):
    def test_client_product_campaign_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = st.Client(client_id="acme", name="Acme")
            st.save_client(client, tmp)
            self.assertTrue((st.client_dir("acme", tmp) / "client.json").is_file())

            product = st.Product(product_id="widget", client_id="acme", product_name="Widget")
            st.save_product(product, tmp)
            self.assertTrue((st.product_dir("acme", "widget", tmp) / "product.json").is_file())
            self.assertTrue(st.references_dir("acme", "widget", tmp).is_dir())

            campaign = st.Campaign(campaign_id="camp1", client_id="acme", product_id="widget")
            st.save_campaign(campaign, tmp)
            cdir = st.campaign_dir("acme", "widget", "camp1", tmp)
            self.assertTrue((cdir / "campaign.json").is_file())
            for sub in st.GENERATED_SUBDIRS:
                self.assertTrue((cdir / "generated" / sub).is_dir())

    def test_demo_seed_paths_exist(self):
        self.assertTrue((st.client_dir(DEMO_CLIENT, str(REPO_ROOT)) / "client.json").is_file())
        self.assertTrue((st.product_dir(DEMO_CLIENT, DEMO_PRODUCT, str(REPO_ROOT)) / "product.json").is_file())
        self.assertTrue((st.campaign_dir(DEMO_CLIENT, DEMO_PRODUCT, DEMO_CAMPAIGN, str(REPO_ROOT))
                        / "campaign.json").is_file())


class TestProductJSONSchemaValid(unittest.TestCase):
    def test_demo_product_json_has_required_fields(self):
        path = st.product_dir(DEMO_CLIENT, DEMO_PRODUCT, str(REPO_ROOT)) / "product.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for field in ("product_id", "client_id", "product_name", "marketplace",
                     "marketplace_url", "marketplace_article", "category",
                     "target_audience", "main_pain", "product_description", "created_at"):
            self.assertIn(field, data)

    def test_round_trip_load(self):
        product = st.load_product(DEMO_CLIENT, DEMO_PRODUCT, str(REPO_ROOT))
        self.assertEqual(product.product_id, DEMO_PRODUCT)
        self.assertIn(product.marketplace, st.PRODUCT_MARKETPLACES)


class TestCampaignJSONSchemaValid(unittest.TestCase):
    def test_demo_campaign_json_has_required_fields(self):
        path = st.campaign_dir(DEMO_CLIENT, DEMO_PRODUCT, DEMO_CAMPAIGN, str(REPO_ROOT)) / "campaign.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for field in ("campaign_id", "client_id", "product_id", "campaign_goal",
                     "platforms", "status", "created_at"):
            self.assertIn(field, data)

    def test_campaign_goal_and_status_valid(self):
        campaign = st.load_campaign(DEMO_CLIENT, DEMO_PRODUCT, DEMO_CAMPAIGN, str(REPO_ROOT))
        self.assertIn(campaign.campaign_goal, st.CAMPAIGN_GOALS)
        self.assertIn(campaign.status, st.CAMPAIGN_STATUSES)
        for platform in campaign.platforms:
            self.assertIn(platform, st.CAMPAIGN_PLATFORMS)


class TestReferencePolicyRejectsZeroReferences(unittest.TestCase):
    def test_no_references_at_all_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            st.save_client(st.Client(client_id="acme", name="Acme"), tmp)
            st.save_product(st.Product(product_id="widget", client_id="acme",
                                       product_name="Widget"), tmp)
            with self.assertRaises(pol.B2BReferencePolicyError) as ctx:
                pol.assert_campaign_generation_allowed("acme", "widget", tmp)
            self.assertEqual(ctx.exception.code, "NO_REFERENCES_UPLOADED")

    def test_below_minimum_approved_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            st.save_client(st.Client(client_id="acme", name="Acme"), tmp)
            st.save_product(st.Product(product_id="widget", client_id="acme",
                                       product_name="Widget"), tmp)
            fake_img = Path(tmp) / "fake.png"
            fake_img.write_bytes(b"fake")
            st.add_reference("acme", "widget", str(fake_img), role="front",
                             approved=True, repo_root=tmp)
            with self.assertRaises(pol.B2BReferencePolicyError) as ctx:
                pol.assert_campaign_generation_allowed("acme", "widget", tmp)
            self.assertEqual(ctx.exception.code, "INSUFFICIENT_APPROVED_REFERENCES")


class TestReferencePolicyRejectsGeneratedPaths(unittest.TestCase):
    def test_generated_path_rejected(self):
        bad_ref = st.ProductReference(
            product_id="x", file_path="content/autopilot/coating-protect-2026-07/"
                                     "generated/content-factory/video-renders/foo-c1.png",
            role="front", approved=True)
        with self.assertRaises(pol.B2BReferencePolicyError) as ctx:
            pol.validate_reference_entry(bad_ref, str(REPO_ROOT))
        self.assertEqual(ctx.exception.code, "FORBIDDEN_REFERENCE_PATH")

    def test_candidate_path_rejected(self):
        bad_ref = st.ProductReference(product_id="x", file_path="some/path/scene-05-candidate.png",
                                      role="front", approved=True)
        with self.assertRaises(pol.B2BReferencePolicyError) as ctx:
            pol.validate_reference_entry(bad_ref, str(REPO_ROOT))
        self.assertEqual(ctx.exception.code, "FORBIDDEN_REFERENCE_PATH")

    def test_scan_reference_images_list_flags_forbidden(self):
        result = pol.scan_reference_images_list(
            ["content/autopilot/x/generated/foo.png"], str(REPO_ROOT))
        self.assertTrue(result["forbidden_found"])


class TestReferencePolicyAcceptsApprovedRefs(unittest.TestCase):
    def test_demo_seed_references_accepted(self):
        approved = pol.assert_campaign_generation_allowed(DEMO_CLIENT, DEMO_PRODUCT, str(REPO_ROOT))
        self.assertGreaterEqual(len(approved), pol.MIN_APPROVED_REFERENCES)
        for ref in approved:
            self.assertTrue(ref.approved)
            self.assertIn(ref.role, st.PRODUCT_REFERENCE_ROLES)

    def test_unapproved_reference_excluded_from_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            st.save_client(st.Client(client_id="acme", name="Acme"), tmp)
            st.save_product(st.Product(product_id="widget", client_id="acme",
                                       product_name="Widget"), tmp)
            for i in range(3):
                img = Path(tmp) / f"ref{i}.png"
                img.write_bytes(b"fake")
                st.add_reference("acme", "widget", str(img), role="front",
                                 approved=(i < 2), repo_root=tmp)  # only 2 approved
            with self.assertRaises(pol.B2BReferencePolicyError):
                pol.assert_campaign_generation_allowed("acme", "widget", tmp)


class TestDryRunCreatesFile(unittest.TestCase):
    def test_campaign_dry_run_json_created(self):
        with urlopen_raises():
            plan = contract.write_campaign_dry_run(DEMO_CLIENT, DEMO_PRODUCT, DEMO_CAMPAIGN, str(REPO_ROOT))
        self.assertEqual(plan["status"], "dry_run_only")
        self.assertTrue(Path(plan["report_path"]).is_file())

    def test_dry_run_contains_required_sections(self):
        d = json.loads((st.campaign_generated_dir(DEMO_CLIENT, DEMO_PRODUCT, DEMO_CAMPAIGN, str(REPO_ROOT))
                       / "campaign-dry-run.json").read_text(encoding="utf-8"))
        for key in ("client", "product", "campaign", "references_used", "platforms",
                   "planned_scenes", "planned_video_variants", "planned_dzen_articles",
                   "planned_publishing_queue", "estimated_image_calls",
                   "estimated_video_renders", "estimated_cost_usd", "forbidden_refs_scan"):
            self.assertIn(key, d)


class TestDryRunZeroOpenAICalls(unittest.TestCase):
    def test_zero_network(self):
        with urlopen_raises():
            plan = contract.build_campaign_dry_run(DEMO_CLIENT, DEMO_PRODUCT, DEMO_CAMPAIGN, str(REPO_ROOT))
        self.assertEqual(plan["openai_calls"], 0)


class TestNoHiggsfieldCalls(unittest.TestCase):
    def test_higgsfield_zero(self):
        plan = json.loads((st.campaign_generated_dir(DEMO_CLIENT, DEMO_PRODUCT, DEMO_CAMPAIGN, str(REPO_ROOT))
                          / "campaign-dry-run.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["higgsfield_calls"], 0)

    def test_no_higgsfield_markers_in_b2b_modules(self):
        # Docstrings legitimately MENTION "Higgsfield" as documentation of
        # what's never called (e.g. "no OpenAI/Higgsfield call") -- that's
        # not a usage. Check for actual import/call patterns instead.
        for mod in (contract, pol, st, dk, seed):
            src = Path(mod.__file__).read_text(encoding="utf-8")
            for marker in ("import higgsfield", "from .higgsfield", "HiggsfieldClient(",
                          "higgsfield_client.", "higgsfield.generate"):
                self.assertNotIn(marker, src)


class TestNoAutoPostingAPIsCalled(unittest.TestCase):
    def test_no_posting_markers_in_b2b_modules(self):
        for mod in (contract, pol, st, dk, seed):
            src = Path(mod.__file__).read_text(encoding="utf-8")
            for marker in ("requests.post", "httpx.post", "youtube.upload",
                          "instagram_api", "tiktok_api", "vk_api.upload"):
                self.assertNotIn(marker, src)

    def test_dry_run_declares_no_auto_posting(self):
        plan = json.loads((st.campaign_generated_dir(DEMO_CLIENT, DEMO_PRODUCT, DEMO_CAMPAIGN, str(REPO_ROOT))
                          / "campaign-dry-run.json").read_text(encoding="utf-8"))
        self.assertFalse(plan["auto_posting_triggered"])
        self.assertEqual(plan["external_api_calls"], 0)


class TestDemoSeedExists(unittest.TestCase):
    def test_seed_is_idempotent_and_returns_expected_ids(self):
        result = seed.seed_demo(str(REPO_ROOT))
        self.assertEqual(result["client_id"], DEMO_CLIENT)
        self.assertEqual(result["product_id"], DEMO_PRODUCT)
        self.assertEqual(result["campaign_id"], DEMO_CAMPAIGN)
        self.assertGreaterEqual(result["references_count"], pol.MIN_APPROVED_REFERENCES)

    def test_legacy_adapter_manifest_exists(self):
        path = (st.campaign_generated_dir(DEMO_CLIENT, DEMO_PRODUCT, DEMO_CAMPAIGN, str(REPO_ROOT))
               / "legacy-campaign-adapter.json")
        self.assertTrue(path.is_file())
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("pointers", manifest)
        self.assertIn("scenes", manifest["pointers"])


class TestWebRoutesRenderBasicPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.main import app
        cls.client = TestClient(app)

    def test_dashboard_renders(self):
        r = self.client.get("/b2b/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(DEMO_CLIENT, r.text)

    def test_product_new_form_renders(self):
        r = self.client.get("/b2b/products/new")
        self.assertEqual(r.status_code, 200)
        self.assertIn("product_name", r.text)

    def test_product_detail_renders(self):
        r = self.client.get(f"/b2b/products/{DEMO_PRODUCT}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("approved", r.text)

    def test_campaign_detail_renders(self):
        r = self.client.get(f"/b2b/campaigns/{DEMO_CAMPAIGN}")
        self.assertEqual(r.status_code, 200)
        self.assertIn(DEMO_CAMPAIGN, r.text)

    def test_unknown_product_404s(self):
        r = self.client.get("/b2b/products/does-not-exist")
        self.assertEqual(r.status_code, 404)


class TestDeliveryKitReadmeExists(unittest.TestCase):
    def test_readme_generated_for_demo_campaign(self):
        result = dk.build_delivery_kit_structure(DEMO_CLIENT, DEMO_PRODUCT, DEMO_CAMPAIGN, str(REPO_ROOT))
        readme = Path(result["readme_path"])
        self.assertTrue(readme.is_file())
        text = readme.read_text(encoding="utf-8")
        for marker in ("upload-ready", "publishing-plan", "performance-tracking",
                      "published_url", "master-performance-tracker.csv"):
            self.assertIn(marker, text)

    def test_delivery_zip_valid(self):
        import zipfile
        result = dk.build_delivery_kit_zip(DEMO_CLIENT, DEMO_PRODUCT, DEMO_CAMPAIGN, str(REPO_ROOT))
        z = zipfile.ZipFile(result["zip_path"])
        self.assertIsNone(z.testzip())
        self.assertIn("OWNER-README.md", z.namelist())


class TestAutopostingRoadmapExists(unittest.TestCase):
    def test_file_exists(self):
        path = REPO_ROOT / "content" / "b2b" / "AUTOPOSTING-ROADMAP.md"
        self.assertTrue(path.is_file())

    def test_covers_all_four_phases(self):
        text = (REPO_ROOT / "content" / "b2b" / "AUTOPOSTING-ROADMAP.md").read_text(encoding="utf-8")
        for marker in ("Phase 1", "Phase 2", "Phase 3", "Phase 4", "OAuth",
                      "YouTube Data API", "Content Publishing API",
                      "Content Posting API", "Dzen"):
            self.assertIn(marker, text)

    def test_no_real_api_calls_implied_as_done(self):
        text = REPO_ROOT.joinpath("content/b2b/AUTOPOSTING-ROADMAP.md").read_text(encoding="utf-8")
        self.assertIn("No real autoposting is implemented", text)


class TestSecretScanCleanInB2BOutputs(unittest.TestCase):
    def test_no_secrets_in_b2b_tree(self):
        b2b_dir = REPO_ROOT / "content" / "b2b"
        offenders = []
        for f in b2b_dir.rglob("*"):
            if f.is_file() and f.suffix in (".json", ".md"):
                text = f.read_text(encoding="utf-8", errors="ignore")
                if SECRET_PATTERN.search(text):
                    offenders.append(str(f))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
