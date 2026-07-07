"""Tests for the B2B Seller Product Traffic Factory admin-first MVP (data
models, storage, reference policy, dry-run contract, delivery kit, web
routes, CLI commands, roadmap/readme docs). Covers the 19 points requested
by the owner:

1. preflight command reports branch/status
2. product creation saves product.json
3. uploaded references saved under product folder
4. references default approved=false
5. approval changes reference status
6. dry-run rejects product with <3 approved refs
7. dry-run passes with >=3 approved refs
8. campaign-dry-run.json created
9. campaign-dry-run.md created
10. delivery kit zip created
11. OWNER-README.md exists
12. B2B-MVP-README.md exists
13. web dashboard renders
14. product form renders
15. campaign page renders
16. no OpenAI calls
17. no Higgsfield calls
18. no auto-posting APIs are called
19. no Railway/Production changes (verified manually -- this test tree does
    not touch any Railway/production config)
"""
import io
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
from api.media_pipeline import cli as media_cli

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


class TestB2BPreflightCommand(unittest.TestCase):
    def _run_preflight(self, expected_branch):
        import argparse
        import contextlib

        args = argparse.Namespace(expected_branch=expected_branch)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = media_cli.cmd_b2b_preflight(args)
        return code, json.loads(buf.getvalue())

    def test_reports_current_branch_and_status(self):
        code, report = self._run_preflight("__definitely-not-a-real-branch__")
        self.assertIn("current_branch", report)
        self.assertIn("git_status_short", report)
        self.assertIn("last_commit", report)
        self.assertFalse(report["branch_matches"])
        self.assertEqual(code, 2)
        self.assertIn("error", report)

    def test_matching_branch_reports_ok(self):
        import subprocess

        current = subprocess.run(["git", "branch", "--show-current"], cwd=str(REPO_ROOT),
                                 capture_output=True, text=True).stdout.strip()
        code, report = self._run_preflight(current)
        self.assertTrue(report["branch_matches"])
        self.assertEqual(code, 0)


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


class TestWebProductCreationFlow(unittest.TestCase):
    """Covers points 2 (product.json saved), 3 (references saved under
    product folder), 4 (approved=false by default), 5 (approve/unapprove
    change reference status) -- via the actual /b2b web routes, not the
    storage layer directly."""

    CLIENT_ID = "test-web-flow-client"

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.main import app
        cls.client = TestClient(app)

    def tearDown(self):
        client_dir = st.client_dir(self.CLIENT_ID, str(REPO_ROOT))
        if client_dir.is_dir():
            shutil.rmtree(client_dir)

    def _create_product_with_refs(self, n=3):
        files = [("reference_images", (f"ref{i}.png", io.BytesIO(b"fakepngbytes"), "image/png"))
                for i in range(n)]
        data = {
            "client_name": "Test Web Flow Client", "contact": "test@example.com",
            "product_name": "Test Web Flow Product", "marketplace": "ozon",
            "marketplace_article": "T1", "marketplace_url": "https://ozon.ru/t",
            "category": "test", "target_audience": "testers", "main_pain": "bugs",
            "product_description": "desc",
        }
        r = self.client.post("/b2b/products/new", data=data, files=files, follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text)
        product_id = r.headers["location"].rsplit("/", 1)[-1]
        return product_id

    def test_product_json_saved(self):
        product_id = self._create_product_with_refs()
        path = st.product_dir(self.CLIENT_ID, product_id, str(REPO_ROOT)) / "product.json"
        self.assertTrue(path.is_file())

    def test_references_saved_under_uploaded_subfolder(self):
        product_id = self._create_product_with_refs()
        refs = st.load_references(self.CLIENT_ID, product_id, str(REPO_ROOT))
        self.assertEqual(len(refs), 3)
        for r in refs:
            self.assertIn("references/uploaded/", r.file_path.replace("\\", "/"))
            self.assertTrue((Path(REPO_ROOT) / r.file_path).is_file())

    def test_references_default_approved_false(self):
        product_id = self._create_product_with_refs()
        refs = st.load_references(self.CLIENT_ID, product_id, str(REPO_ROOT))
        for r in refs:
            self.assertFalse(r.approved)

    def test_approve_then_unapprove_changes_status(self):
        product_id = self._create_product_with_refs()
        refs = st.load_references(self.CLIENT_ID, product_id, str(REPO_ROOT))
        file_path = refs[0].file_path

        r = self.client.post(f"/b2b/products/{product_id}/references/approve",
                             data={"file_path": file_path}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        refs = st.load_references(self.CLIENT_ID, product_id, str(REPO_ROOT))
        self.assertTrue(next(r for r in refs if r.file_path == file_path).approved)

        r = self.client.post(f"/b2b/products/{product_id}/references/unapprove",
                             data={"file_path": file_path}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        refs = st.load_references(self.CLIENT_ID, product_id, str(REPO_ROOT))
        self.assertFalse(next(r for r in refs if r.file_path == file_path).approved)

    def test_role_change_route(self):
        product_id = self._create_product_with_refs()
        refs = st.load_references(self.CLIENT_ID, product_id, str(REPO_ROOT))
        file_path = refs[0].file_path
        r = self.client.post(f"/b2b/products/{product_id}/references/role",
                             data={"file_path": file_path, "role": "top"},
                             follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        refs = st.load_references(self.CLIENT_ID, product_id, str(REPO_ROOT))
        self.assertEqual(next(r for r in refs if r.file_path == file_path).role, "top")

    def test_campaign_creation_gated_on_three_approved(self):
        product_id = self._create_product_with_refs()
        r = self.client.post(f"/b2b/products/{product_id}/campaigns/new",
                             data={"campaign_goal": "external_traffic"}, follow_redirects=False)
        # route itself doesn't gate creation (UI hides the button); the real
        # gate is the dry-run/delivery-kit fail-closed policy check
        self.assertEqual(r.status_code, 303)
        campaign_id = r.headers["location"].rsplit("/", 1)[-1]
        r = self.client.post(f"/b2b/campaigns/{campaign_id}/dry-run", follow_redirects=False)
        self.assertEqual(r.status_code, 422)

    def test_dry_run_succeeds_after_three_approvals(self):
        product_id = self._create_product_with_refs()
        refs = st.load_references(self.CLIENT_ID, product_id, str(REPO_ROOT))
        for r in refs:
            self.client.post(f"/b2b/products/{product_id}/references/approve",
                             data={"file_path": r.file_path}, follow_redirects=False)
        r = self.client.post(f"/b2b/products/{product_id}/campaigns/new",
                             data={"campaign_goal": "external_traffic"}, follow_redirects=False)
        campaign_id = r.headers["location"].rsplit("/", 1)[-1]
        r = self.client.post(f"/b2b/campaigns/{campaign_id}/dry-run", follow_redirects=False)
        self.assertEqual(r.status_code, 303)


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
        for name in ("OWNER-README.md", "PRODUCT-SUMMARY.md", "CAMPAIGN-PLAN.md",
                    "REFERENCE-POLICY.md", "NEXT-STEPS.md"):
            self.assertIn(name, z.namelist())

    def test_delivery_kit_fails_closed_below_minimum_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            st.save_client(st.Client(client_id="acme", name="Acme"), tmp)
            st.save_product(st.Product(product_id="widget", client_id="acme",
                                       product_name="Widget"), tmp)
            st.save_campaign(st.Campaign(campaign_id="camp1", client_id="acme",
                                         product_id="widget"), tmp)
            with self.assertRaises(pol.B2BReferencePolicyError):
                dk.build_delivery_kit_zip("acme", "widget", "camp1", tmp)


class TestDryRunMarkdownCreated(unittest.TestCase):
    def test_campaign_dry_run_md_created(self):
        with urlopen_raises():
            plan = contract.write_campaign_dry_run(DEMO_CLIENT, DEMO_PRODUCT, DEMO_CAMPAIGN, str(REPO_ROOT))
        self.assertTrue(Path(plan["report_md_path"]).is_file())
        text = Path(plan["report_md_path"]).read_text(encoding="utf-8")
        for marker in ("Campaign dry-run", "## Client", "## Product",
                      "Approved references used", "Rejected / unapproved references",
                      "Content package plan", "Estimated cost", "Safety policy summary",
                      "Forbidden refs scan", "dry_run_only"):
            self.assertIn(marker, text)

    def test_dry_run_json_includes_rejected_refs_and_safety_summary(self):
        d = json.loads((st.campaign_generated_dir(DEMO_CLIENT, DEMO_PRODUCT, DEMO_CAMPAIGN, str(REPO_ROOT))
                       / "campaign-dry-run.json").read_text(encoding="utf-8"))
        self.assertIn("references_rejected", d)
        self.assertIn("safety_policy_summary", d)
        self.assertIn("min_approved_references", d["safety_policy_summary"])


class TestB2BMVPReadmeExists(unittest.TestCase):
    def test_file_exists(self):
        path = REPO_ROOT / "content" / "b2b" / "B2B-MVP-README.md"
        self.assertTrue(path.is_file())

    def test_covers_required_sections(self):
        text = (REPO_ROOT / "content" / "b2b" / "B2B-MVP-README.md").read_text(encoding="utf-8")
        for marker in ("b2b-seed-demo", "b2b-campaign-dry-run", "b2b-build-delivery-kit",
                      "What is NOT yet implemented", "Payments", "Auto-posting",
                      "OAuth", "Login"):
            self.assertIn(marker, text)


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
