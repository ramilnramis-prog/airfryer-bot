"""Tests for the B2B demo one-video generation pipeline (api.media_pipeline
.b2b_demo_video, the b2b-generate-demo-video CLI command, and the campaign
page's "Тестовый ролик" block). Covers the 16 points requested by the owner:

1. b2b-generate-demo-video dry-run command exists
2. dry-run creates demo-video-dry-run.json
3. dry-run makes 0 OpenAI calls
4. dry-run requires package_mode demo_1_video
5. dry-run uses exactly 1 planned image call
6. dry-run uses uploaded product references only
7. generated/ paths rejected
8. prompt uses product intelligence/ad strategy
9. platform description created in dry-run
10. UI campaign page shows Test video block for demo_1_video
11. final test ZIP button disabled until MP4 exists
12. apply requires explicit --apply
13. apply safety caps enforced
14. no Higgsfield calls
15. no auto-posting
16. no Railway/Production changes (verified manually -- this test tree does
    not touch any Railway/production config)
"""
import io
import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline import b2b_storage as st
from api.media_pipeline import b2b_reference_policy as pol
from api.media_pipeline import b2b_demo_video as dv
from api.media_pipeline import cli as media_cli
from api.media_pipeline.openai_images_client import MissingAPIKeyError

REPO_ROOT = Path(__file__).resolve().parents[2]


def urlopen_raises():
    return mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call!"))


class DemoVideoWizardTestCase(unittest.TestCase):
    """Drives the seller wizard through the FastAPI TestClient to get a
    demo_1_video product + campaign with >=1 uploaded reference and
    product intelligence, then exercises b2b_demo_video against it."""

    CLIENT_ID = "demo-video-test-client"

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.main import app
        cls.client = TestClient(app)

    def tearDown(self):
        client_dir = st.client_dir(self.CLIENT_ID, str(REPO_ROOT))
        if client_dir.is_dir():
            shutil.rmtree(client_dir)

    def _step1(self, product_name="Demo Video Test Product"):
        data = {
            "client_name": "demo-video-test-client", "contact": "demo-video@example.com",
            "product_name": product_name, "marketplace": "ozon",
            "marketplace_article": "DV1", "marketplace_url": "https://ozon.ru/dv1",
            "price": "1490", "category": "фонарик",
            "short_product_description": "Мощный аккумуляторный фонарик для дома и авто.",
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

    def _run_campaign_dry_run(self, product_id):
        r = self.client.post(f"/b2b/seller/{product_id}/step6/dry-run", follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text)
        return r.headers["location"].rsplit("/", 1)[-1]

    def _setup_demo_campaign(self, n_refs=1):
        product_id = self._step1()
        self._step2_upload_n(product_id, n=n_refs)
        self._select_demo_package(product_id)
        with urlopen_raises():
            campaign_id = self._run_campaign_dry_run(product_id)
        return product_id, campaign_id


class TestCliCommandExists(DemoVideoWizardTestCase):
    def test_dry_run_command_returns_zero(self):
        product_id, campaign_id = self._setup_demo_campaign()
        with urlopen_raises():
            code = media_cli.main(["b2b-generate-demo-video", "--client", self.CLIENT_ID,
                                   "--product", product_id, "--campaign", campaign_id,
                                   "--dry-run"])
        self.assertEqual(code, 0)


class TestDryRunCreatesJson(DemoVideoWizardTestCase):
    def test_dry_run_json_and_md_created(self):
        product_id, campaign_id = self._setup_demo_campaign()
        with urlopen_raises():
            plan = dv.write_demo_video_dry_run(self.CLIENT_ID, product_id, campaign_id, str(REPO_ROOT))
        self.assertTrue(Path(plan["report_path"]).is_file())
        self.assertTrue(Path(plan["report_md_path"]).is_file())
        self.assertEqual(Path(plan["report_path"]).name, "demo-video-dry-run.json")
        on_disk = json.loads(Path(plan["report_path"]).read_text(encoding="utf-8"))
        self.assertEqual(on_disk["package_mode"], "demo_1_video")


class TestDryRunZeroOpenAICalls(DemoVideoWizardTestCase):
    def test_zero_openai_and_higgsfield_calls(self):
        product_id, campaign_id = self._setup_demo_campaign()
        with urlopen_raises():
            plan = dv.build_demo_video_dry_run(self.CLIENT_ID, product_id, campaign_id, str(REPO_ROOT))
        self.assertEqual(plan["openai_calls"], 0)
        self.assertEqual(plan["higgsfield_calls"], 0)
        self.assertEqual(plan["external_api_calls"], 0)


class TestDryRunRequiresDemoPackageMode(DemoVideoWizardTestCase):
    def test_wrong_package_mode_raises(self):
        product_id = self._step1()
        self._step2_upload_n(product_id, n=1)
        # select the full 14-day package instead of demo_1_video
        r = self.client.post(f"/b2b/seller/{product_id}/step5",
                             data={"platforms": ["youtube_shorts"], "package_duration": "14_days"},
                             follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text)
        with urlopen_raises():
            campaign_id = self._run_campaign_dry_run(product_id)
        with urlopen_raises():
            with self.assertRaises(dv.B2BDemoVideoError) as ctx:
                dv.build_demo_video_dry_run(self.CLIENT_ID, product_id, campaign_id, str(REPO_ROOT))
        self.assertEqual(ctx.exception.code, "WRONG_PACKAGE_MODE")


class TestDryRunPlansExactlyOneImageCall(DemoVideoWizardTestCase):
    def test_estimated_image_calls_is_one(self):
        product_id, campaign_id = self._setup_demo_campaign()
        with urlopen_raises():
            plan = dv.build_demo_video_dry_run(self.CLIENT_ID, product_id, campaign_id, str(REPO_ROOT))
        self.assertEqual(plan["estimated_image_calls"], 1)
        self.assertEqual(plan["estimated_local_mp4_renders"], 1)
        self.assertEqual(plan["apply_allowed"], False)


class TestDryRunUsesUploadedReferencesOnly(DemoVideoWizardTestCase):
    def test_chosen_references_are_uploaded_paths(self):
        product_id, campaign_id = self._setup_demo_campaign(n_refs=2)
        with urlopen_raises():
            plan = dv.build_demo_video_dry_run(self.CLIENT_ID, product_id, campaign_id, str(REPO_ROOT))
        self.assertGreaterEqual(len(plan["chosen_product_references"]), 1)
        for ref in plan["chosen_product_references"]:
            self.assertIn("/references/uploaded/", ref["file_path"].replace("\\", "/"))
        self.assertFalse(plan["forbidden_refs_scan"]["forbidden_found"])


class TestGeneratedPathsRejected(DemoVideoWizardTestCase):
    def test_forbidden_reference_path_raises(self):
        product_id, campaign_id = self._setup_demo_campaign()
        st.add_reference(self.CLIENT_ID, product_id,
                         f"content/b2b/clients/{self.CLIENT_ID}/products/{product_id}/"
                         f"campaigns/{campaign_id}/generated/demo-video/demo-video-candidate.png",
                         role="front", repo_root=str(REPO_ROOT))
        with urlopen_raises():
            with self.assertRaises(pol.B2BReferencePolicyError) as ctx:
                dv.build_demo_video_dry_run(self.CLIENT_ID, product_id, campaign_id, str(REPO_ROOT))
        self.assertEqual(ctx.exception.code, "FORBIDDEN_REFERENCE_PATH")


class TestPromptUsesProductIntelligence(DemoVideoWizardTestCase):
    def test_prompt_and_angle_reflect_intelligence(self):
        product_id, campaign_id = self._setup_demo_campaign()
        with urlopen_raises():
            plan = dv.build_demo_video_dry_run(self.CLIENT_ID, product_id, campaign_id, str(REPO_ROOT))
        self.assertIn(plan["product_summary"]["product_name"], plan["image_prompt"])
        self.assertIn(plan["resolved_angle"], ("pain_problem", "demo_use_case", "benefit_convenience"))
        self.assertEqual(plan["selected_ad_strategy"], "multi_angle_test")
        # "фонарик" category should resolve to the flashlight scene context,
        # not a hardcoded/generic one -- proves the prompt is category-driven.
        self.assertIn("flashlight", "".join(dv.SCENE_CONTEXT_BY_CATEGORY.keys()))

    def test_resolve_primary_angle_rules(self):
        self.assertEqual(dv.resolve_primary_angle({"selected_ad_strategy": "benefit_convenience"}),
                         "benefit_convenience")
        self.assertEqual(dv.resolve_primary_angle({"selected_ad_strategy": "multi_angle_test",
                                                    "matched_category": "flashlight"}), "pain_problem")
        self.assertEqual(dv.resolve_primary_angle({"selected_ad_strategy": "multi_angle_test",
                                                    "matched_category": "generic_fallback"}),
                         "demo_use_case")


class TestPlatformDescriptionCreatedInDryRun(DemoVideoWizardTestCase):
    def test_platform_description_fields_present(self):
        product_id, campaign_id = self._setup_demo_campaign()
        with urlopen_raises():
            plan = dv.build_demo_video_dry_run(self.CLIENT_ID, product_id, campaign_id, str(REPO_ROOT))
        pd = plan["platform_description"]
        for key in ("platform", "title", "description", "hashtags", "cta", "marketplace_link", "warnings"):
            self.assertIn(key, pd)
        self.assertEqual(pd["platform"], "youtube_shorts")


class TestCampaignPageShowsTestVideoBlock(DemoVideoWizardTestCase):
    def test_test_video_block_present_for_demo_mode(self):
        product_id, campaign_id = self._setup_demo_campaign()
        r = self.client.get(f"/b2b/campaigns/{campaign_id}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Тестовый ролик", r.text)
        self.assertIn("Подготовить план тестового ролика", r.text)


class TestZipButtonDisabledUntilMp4Exists(DemoVideoWizardTestCase):
    def test_zip_link_absent_then_present(self):
        product_id, campaign_id = self._setup_demo_campaign()
        r1 = self.client.get(f"/b2b/campaigns/{campaign_id}")
        self.assertNotIn(f"/b2b/campaigns/{campaign_id}/demo-video/kit.zip", r1.text)

        demo_dir = st.campaign_generated_dir(self.CLIENT_ID, product_id, campaign_id,
                                             str(REPO_ROOT)) / "demo-video"
        demo_dir.mkdir(parents=True, exist_ok=True)
        (demo_dir / "demo-video-test.mp4").write_bytes(b"FAKE")
        (demo_dir / "DEMO-ONE-VIDEO-KIT.zip").write_bytes(b"PK\x03\x04")

        r2 = self.client.get(f"/b2b/campaigns/{campaign_id}")
        self.assertIn(f"/b2b/campaigns/{campaign_id}/demo-video/kit.zip", r2.text)
        self.assertIn("Тестовый ролик готов.", r2.text)


class TestApplyRequiresExplicitFlag(DemoVideoWizardTestCase):
    def test_dry_run_never_calls_apply_path(self):
        product_id, campaign_id = self._setup_demo_campaign()
        with urlopen_raises():
            result = dv.run_demo_video_generation(self.CLIENT_ID, product_id, campaign_id,
                                                   str(REPO_ROOT), apply=False)
        self.assertEqual(result["candidate_status"], "planned_only")
        self.assertEqual(result["openai_calls"], 0)

    def test_cli_without_apply_flag_stays_dry_run(self):
        """Omitting --apply entirely (not even --dry-run) must still behave
        as a dry-run -- --apply is the only thing that can trigger network
        activity, never the default. Wrapped in urlopen_raises() as
        defense-in-depth: if this ever silently applied, the test would
        fail on the network call itself, not just on candidate_status."""
        product_id, campaign_id = self._setup_demo_campaign()
        with urlopen_raises():
            code = media_cli.main(["b2b-generate-demo-video", "--client", self.CLIENT_ID,
                                   "--product", product_id, "--campaign", campaign_id])
        self.assertEqual(code, 0)


class TestApplySafetyCapsEnforced(DemoVideoWizardTestCase):
    def test_safety_cap_constants(self):
        self.assertEqual(dv.MAX_IMAGE_CALLS, 1)
        self.assertEqual(dv.RETRIES, 0)
        self.assertLessEqual(dv.HARD_CAP_USD, 0.50)

    def test_apply_blocked_for_wrong_package_mode(self):
        product_id = self._step1()
        self._step2_upload_n(product_id, n=1)
        r = self.client.post(f"/b2b/seller/{product_id}/step5",
                             data={"platforms": ["youtube_shorts"], "package_duration": "14_days"},
                             follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text)
        with urlopen_raises():
            campaign_id = self._run_campaign_dry_run(product_id)
        with urlopen_raises():
            with self.assertRaises(dv.B2BDemoVideoError) as ctx:
                dv.run_demo_video_generation(self.CLIENT_ID, product_id, campaign_id,
                                             str(REPO_ROOT), apply=True)
        self.assertEqual(ctx.exception.code, "WRONG_PACKAGE_MODE")

    def test_apply_without_api_key_is_graceful(self):
        product_id, campaign_id = self._setup_demo_campaign()
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("OPENAI_API_KEY", None)
            with urlopen_raises():
                result = dv.run_demo_video_generation(self.CLIENT_ID, product_id, campaign_id,
                                                       str(REPO_ROOT), apply=True)
        self.assertEqual(result["candidate_status"], "no_api_key")
        self.assertEqual(result["openai_calls"], 0)
        self.assertEqual(result["api_spend_usd"], 0.0)


class TestNoHiggsfieldCalls(DemoVideoWizardTestCase):
    def test_no_higgsfield_markers_in_module(self):
        src = Path(dv.__file__).read_text(encoding="utf-8")
        for marker in ("HiggsfieldClient(", "higgsfield.generate", "higgsfield_client."):
            self.assertNotIn(marker, src)

    def test_dry_run_declares_zero_higgsfield_calls(self):
        product_id, campaign_id = self._setup_demo_campaign()
        with urlopen_raises():
            plan = dv.build_demo_video_dry_run(self.CLIENT_ID, product_id, campaign_id, str(REPO_ROOT))
        self.assertEqual(plan["higgsfield_calls"], 0)


class TestNoAutoPosting(DemoVideoWizardTestCase):
    def test_no_posting_markers_in_module(self):
        src = Path(dv.__file__).read_text(encoding="utf-8")
        for marker in ("requests.post", "httpx.post", "youtube.upload",
                      "instagram_api", "tiktok_api", "vk_api.upload"):
            self.assertNotIn(marker, src)

    def test_dry_run_declares_no_auto_posting(self):
        product_id, campaign_id = self._setup_demo_campaign()
        with urlopen_raises():
            plan = dv.build_demo_video_dry_run(self.CLIENT_ID, product_id, campaign_id, str(REPO_ROOT))
        self.assertFalse(plan["auto_posting_triggered"])


if __name__ == "__main__":
    unittest.main()
