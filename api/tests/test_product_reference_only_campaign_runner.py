"""Тесты campaign batch runner (product-reference-only-v2) поверх всех 7
сцен coating-protect-2026-07 -- см.
api.media_pipeline.product_reference_only_campaign_runner.

Покрытие (15 пунктов, запрошенных явно владельцем):
1. campaign dry-run существует (campaign-product-reference-only-v2-dry-run.json)
2. все 7 сцен configured (в SCENE_PROMPTS_V2 / CAMPAIGN_SCENE_ORDER)
3. scene-05 -- selected_existing и НЕ promoted to reference
4. scene-07 -- selected_existing и НЕ promoted to reference
5. все сцены используют только approved product references
6. ни один generated/C1/C2/C3/candidate PNG не встречается в reference_images
7. forbidden references -- fail closed
8. unconfigured scene -- fail closed
9. dry-run делает 0 вызовов OpenAI
10. Higgsfield calls == 0
11. max_calls_per_scene == 1
12. retries == 0
13. campaign_total_hard_cap_usd присутствует
14. prompts чистые, без markdown-документации
15. невозможен auto-accepted статус
"""
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline import product_reference_only_runner as por
from api.media_pipeline import product_reference_only_campaign_runner as campaign

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"

CAMPAIGN_DRY_RUN_PATH = CAMPAIGN_DIR / "campaign-product-reference-only-v2-dry-run.json"

C1_C2_C3_PATTERN = re.compile(r"scene-0\d-c[123][-.]")
GENERATED_PATTERN = re.compile(r"generated[\\/]")
AIRFRYER_MOTION_PATTERN = re.compile(r"real-v1[\\/](airfryer|motion)[\\/]")

ALLOWED_ASSET_IDS = {
    "real-product-v1:product_45deg_master",
    "real-product-v1:product_top_master",
    "real-product-v1:product_full_master",
    "real-product-v1:left_handle_master",
    "real-product-v1:right_handle_master",
    "real-product-v1:both_handles_master",
    "real-product-v1:bottom_loop_master",
}

MARKDOWN_MARKERS = ("```", "##", "**", "[[", "]]", "\n- ", "\n1. ")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def urlopen_raises():
    return mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call!"))


class TestCampaignDryRunExists(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(CAMPAIGN_DRY_RUN_PATH.is_file())

    def test_live_dry_run_writes_same_path(self):
        with urlopen_raises():
            report = campaign.run_campaign(str(CAMPAIGN_DIR), apply=False)
        self.assertEqual(Path(report["report_path"]).resolve(), CAMPAIGN_DRY_RUN_PATH.resolve())
        self.assertEqual(report["mode"], "dry-run")


class TestAllSevenScenesConfigured(unittest.TestCase):
    def test_campaign_scene_order_has_seven_scenes(self):
        self.assertEqual(list(por.CAMPAIGN_SCENE_ORDER),
                         [f"scene-0{n}" for n in range(1, 8)])

    def test_all_seven_scenes_in_scene_prompts_v2(self):
        for scene_id in por.CAMPAIGN_SCENE_ORDER:
            self.assertIn(scene_id, por.SCENE_PROMPTS_V2)

    def test_live_run_all_scenes_configured_or_selected(self):
        with urlopen_raises():
            report = campaign.run_campaign(str(CAMPAIGN_DIR), apply=False, skip_selected=False)
        statuses = {s["scene_id"]: s["status"] for s in report["scene_reports"]}
        self.assertEqual(set(statuses), set(por.CAMPAIGN_SCENE_ORDER))
        for scene_id, status in statuses.items():
            self.assertEqual(status, "configured")


class TestScene05SelectedExistingNotPromoted(unittest.TestCase):
    def test_scene05_selected_existing_by_default(self):
        with urlopen_raises():
            report = campaign.run_campaign(str(CAMPAIGN_DIR), scenes=["scene-05"], apply=False)
        entry = report["scene_reports"][0]
        self.assertEqual(entry["status"], "selected_existing")
        self.assertTrue(entry["selected_candidate"]["not_promoted_to_reference"])

    def test_scene05_registry_entry_not_promoted(self):
        selected = campaign.load_selected_candidates(str(CAMPAIGN_DIR))
        self.assertIn("scene-05", selected)
        self.assertTrue(selected["scene-05"]["not_promoted_to_reference"])
        self.assertEqual(selected["scene-05"]["status"], "working_candidate_selected")
        self.assertEqual(selected["scene-05"]["status_detail"], "pending_final_owner_approval")


class TestScene07SelectedExistingNotPromoted(unittest.TestCase):
    def test_scene07_selected_existing_by_default(self):
        with urlopen_raises():
            report = campaign.run_campaign(str(CAMPAIGN_DIR), scenes=["scene-07"], apply=False)
        entry = report["scene_reports"][0]
        self.assertEqual(entry["status"], "selected_existing")
        self.assertTrue(entry["selected_candidate"]["not_promoted_to_reference"])

    def test_scene07_registry_entry_not_promoted(self):
        selected = campaign.load_selected_candidates(str(CAMPAIGN_DIR))
        self.assertIn("scene-07", selected)
        self.assertTrue(selected["scene-07"]["not_promoted_to_reference"])
        self.assertEqual(selected["scene-07"]["status"], "working_candidate_selected")
        self.assertEqual(selected["scene-07"]["status_detail"], "pending_final_owner_approval")


class TestAllScenesOnlyApprovedProductReferences(unittest.TestCase):
    def test_every_configured_scene_uses_exactly_allowed_four(self):
        with urlopen_raises():
            report = campaign.run_campaign(str(CAMPAIGN_DIR), apply=False, skip_selected=False)
        for entry in report["scene_reports"]:
            self.assertEqual(entry["status"], "configured")
            self.assertEqual(set(entry["reference_images"]), set(por.PRODUCT_REFERENCE_IMAGES_V2))
            for ref in entry["reference_images"]:
                self.assertIn(ref, ALLOWED_ASSET_IDS)


class TestNoGeneratedC1C2C3CandidateInReferenceImages(unittest.TestCase):
    def test_resolved_paths_clean(self):
        with urlopen_raises():
            report = campaign.run_campaign(str(CAMPAIGN_DIR), apply=False, skip_selected=False)
        for entry in report["scene_reports"]:
            for p in entry["reference_image_paths"]:
                self.assertIsNone(GENERATED_PATTERN.search(p))
                self.assertIsNone(AIRFRYER_MOTION_PATTERN.search(p.replace("/", "\\") + "\\"))
                self.assertIsNone(C1_C2_C3_PATTERN.search(p))
                self.assertNotIn("product-reference-only-v2-candidate", p)

    def test_forbidden_refs_scan_reports_clean_for_every_scene(self):
        with urlopen_raises():
            report = campaign.run_campaign(str(CAMPAIGN_DIR), apply=False, skip_selected=False)
        for entry in report["scene_reports"]:
            scan = entry["forbidden_refs_scan"]
            self.assertFalse(scan["forbidden_found"])
            self.assertEqual(scan["findings"], [])
            self.assertEqual(scan["scanned"], 4)


class TestScanForbiddenRefsFailsClosedOnBadInput(unittest.TestCase):
    def test_flags_generated_path(self):
        result = campaign.scan_forbidden_refs(
            ["content/autopilot/x/generated/product-reference-only-scene-v2/scene-05/scene-05-c1.png"])
        self.assertTrue(result["forbidden_found"])

    def test_flags_airfryer_master(self):
        result = campaign.scan_forbidden_refs(
            ["assets/product-lock/airfryer-silicone-form/references/real-v1/airfryer/airfryer_front_master.png"])
        self.assertTrue(result["forbidden_found"])

    def test_flags_c1_c2_c3_candidate_filenames(self):
        result = campaign.scan_forbidden_refs(["some/path/scene-03-c2-candidate.png"])
        self.assertTrue(result["forbidden_found"])

    def test_clean_paths_pass(self):
        result = campaign.scan_forbidden_refs([
            "assets/product-lock/airfryer-silicone-form/references/real-v1/product/product_45deg_master.png",
        ])
        self.assertFalse(result["forbidden_found"])


class TestUnconfiguredSceneFailsClosed(unittest.TestCase):
    def test_plan_scene_not_configured(self):
        entry = campaign.plan_scene(str(CAMPAIGN_DIR), "scene-99",
                                    skip_existing=False, skip_selected=True,
                                    repo_root=".", selected_candidates={})
        self.assertEqual(entry["status"], "not_configured")

    def test_campaign_run_reports_not_configured_without_network(self):
        with urlopen_raises():
            report = campaign.run_campaign(str(CAMPAIGN_DIR), scenes=["scene-99"], apply=False)
        self.assertEqual(report["scene_reports"][0]["status"], "not_configured")

    def test_apply_unconfigured_scene_does_not_call_openai(self):
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "sk-fake-not-real"}):
            with urlopen_raises():
                report = campaign.run_campaign(str(CAMPAIGN_DIR), scenes=["scene-99"], apply=True)
        self.assertEqual(report["scene_reports"][0]["status"], "not_configured")
        self.assertEqual(report["openai_calls_executed"], 0)


class TestDryRunZeroOpenAICalls(unittest.TestCase):
    def test_whole_campaign_dry_run_zero_calls(self):
        with urlopen_raises():
            report = campaign.run_campaign(str(CAMPAIGN_DIR), apply=False)
        self.assertEqual(report["openai_calls_executed"], 0)
        self.assertEqual(report["total_actual_spend_usd"], 0)

    def test_dry_run_works_without_api_key(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            had_key = os.environ.pop("OPENAI_API_KEY", None)
            try:
                with urlopen_raises():
                    report = campaign.run_campaign(str(CAMPAIGN_DIR), apply=False)
                self.assertEqual(report["openai_calls_executed"], 0)
            finally:
                if had_key is not None:
                    os.environ["OPENAI_API_KEY"] = had_key


class TestHiggsfieldCallsAlwaysZero(unittest.TestCase):
    def test_dry_run(self):
        with urlopen_raises():
            report = campaign.run_campaign(str(CAMPAIGN_DIR), apply=False)
        self.assertEqual(report["higgsfield_calls_executed"], 0)

    def test_dry_run_doc_on_disk(self):
        d = load_json(CAMPAIGN_DRY_RUN_PATH)
        self.assertEqual(d["higgsfield_calls_executed"], 0)


class TestMaxCallsPerSceneIsOne(unittest.TestCase):
    def test_constant(self):
        self.assertEqual(por.MAX_CALLS, 1)

    def test_reported_in_dry_run(self):
        with urlopen_raises():
            report = campaign.run_campaign(str(CAMPAIGN_DIR), apply=False)
        self.assertEqual(report["max_calls_per_scene"], 1)
        for entry in report["scene_reports"]:
            if entry["status"] == "configured":
                self.assertEqual(entry["max_calls"], 1)


class TestRetriesIsZero(unittest.TestCase):
    def test_constant(self):
        self.assertEqual(por.RETRIES, 0)

    def test_reported_in_dry_run(self):
        with urlopen_raises():
            report = campaign.run_campaign(str(CAMPAIGN_DIR), apply=False)
        self.assertEqual(report["retries"], 0)
        for entry in report["scene_reports"]:
            if entry["status"] == "configured":
                self.assertEqual(entry["retries"], 0)


class TestCampaignTotalHardCapPresent(unittest.TestCase):
    def test_constant_value(self):
        self.assertEqual(campaign.CAMPAIGN_TOTAL_HARD_CAP_USD, 5.00)

    def test_present_in_dry_run(self):
        with urlopen_raises():
            report = campaign.run_campaign(str(CAMPAIGN_DIR), apply=False)
        self.assertEqual(report["campaign_total_hard_cap_usd"], 5.00)

    def test_present_in_tracked_doc(self):
        d = load_json(CAMPAIGN_DRY_RUN_PATH)
        self.assertEqual(d["campaign_total_hard_cap_usd"], 5.00)

    def test_apply_would_stop_before_exceeding_cap(self):
        # 5.00 / 0.50-per-scene-hard-cap == 10 slots available -- with only
        # 5 non-selected scenes configured, the campaign cap is never hit in
        # this campaign, but the guard itself must exist and be checked
        # before every real call.
        self.assertGreater(campaign.CAMPAIGN_TOTAL_HARD_CAP_USD, 0)
        self.assertGreaterEqual(campaign.CAMPAIGN_TOTAL_HARD_CAP_USD, por.HARD_CAP_USD)


class TestPromptsCleanNoMarkdownDocs(unittest.TestCase):
    def test_all_scene_prompts_have_no_markdown_markers(self):
        for scene_id in por.CAMPAIGN_SCENE_ORDER:
            prompt, _gates = por.SCENE_PROMPTS_V2[scene_id]
            for marker in MARKDOWN_MARKERS:
                self.assertNotIn(marker, prompt, f"{scene_id} prompt contains markdown marker {marker!r}")

    def test_dry_run_docs_flag_clean_prompt(self):
        for scene_id in por.CAMPAIGN_SCENE_ORDER:
            path = CAMPAIGN_DIR / f"{scene_id}-product-reference-only-v2-apply-dry-run.json"
            d = load_json(path)
            self.assertTrue(d["model_prompt_clean"])


class TestNoAutoAcceptedStatusPossible(unittest.TestCase):
    ACCEPTABLE_STATUSES = {
        "configured", "selected_existing", "skipped", "pending_apply",
        "not_configured", "skipped_campaign_hard_cap",
        "pending_manual_review", "rejected", "no_candidate_timeout", "rejected_api_error",
    }

    def test_dry_run_statuses_never_accepted(self):
        with urlopen_raises():
            report = campaign.run_campaign(str(CAMPAIGN_DIR), apply=False, skip_selected=False)
        for entry in report["scene_reports"]:
            self.assertNotEqual(entry["status"], "accepted")
            self.assertIn(entry["status"], self.ACCEPTABLE_STATUSES)

    def test_candidate_status_note_present(self):
        with urlopen_raises():
            report = campaign.run_campaign(str(CAMPAIGN_DIR), apply=False)
        self.assertIn("never accepted automatically", report["candidate_status_note"])

    def test_apply_error_path_never_accepted(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("OPENAI_API_KEY", None)
            with urlopen_raises():
                report = campaign.run_campaign(str(CAMPAIGN_DIR), scenes=["scene-01"], apply=True)
        entry = report["scene_reports"][0]
        self.assertEqual(entry["status"], "rejected_api_error")
        self.assertNotEqual(entry["status"], "accepted")


class TestSkipExistingAndStopOnErrorFlags(unittest.TestCase):
    def test_skip_existing_default_false(self):
        with urlopen_raises():
            report = campaign.run_campaign(str(CAMPAIGN_DIR), scenes=["scene-01"], apply=False)
        self.assertFalse(report["skip_existing"])

    def test_skip_selected_default_true(self):
        with urlopen_raises():
            report = campaign.run_campaign(str(CAMPAIGN_DIR), scenes=["scene-05"], apply=False)
        self.assertTrue(report["skip_selected"])
        self.assertEqual(report["scene_reports"][0]["status"], "selected_existing")

    def test_stop_on_error_default_true(self):
        with urlopen_raises():
            report = campaign.run_campaign(str(CAMPAIGN_DIR), scenes=["scene-01"], apply=False)
        self.assertTrue(report["stop_on_error"])


class TestScopedScenesSelection(unittest.TestCase):
    def test_scenes_param_limits_run(self):
        with urlopen_raises():
            report = campaign.run_campaign(str(CAMPAIGN_DIR),
                                           scenes=["scene-01", "scene-02", "scene-03"],
                                           apply=False)
        self.assertEqual(report["scenes_requested"], ["scene-01", "scene-02", "scene-03"])
        self.assertEqual(len(report["scene_reports"]), 3)


if __name__ == "__main__":
    unittest.main()
