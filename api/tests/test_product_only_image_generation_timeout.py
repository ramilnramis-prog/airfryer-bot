"""Тесты configurable image-generation timeout (после реального
client_read_timeout на первой scene-05 C3 --apply попытке: запрос был
отправлен, но urllib.request.urlopen не дождался заголовков ответа за
300s -- слишком короткий таймаут для реальной латентности image generation,
не retry-достойная ошибка приложения).

Fix: api.media_pipeline.openai_images_client.resolve_image_generation_timeout_seconds()
+ OpenAIImagesProvider(timeout_seconds=...) + product_only_scene_runner
перехватывает TimeoutError и возвращает структурированный отчёт
(candidate_status: no_candidate_timeout) вместо необработанного traceback.

Покрытие (15 пунктов, запрошенных явно):
1. default image timeout is 900 seconds
2. IMAGE_GENERATION_TIMEOUT_SECONDS overrides timeout
3. invalid env timeout falls back to 900 and records warning
4. timeout below 60 rejected/falls back
5. timeout above 1800 rejected/falls back
6. timeout metadata is written to request metadata
7. timeout error report has error_type == client_read_timeout
8. timeout error report has request_sent == true
9. timeout error report has response_received == false
10. timeout error report has candidate_status == no_candidate_timeout
11. timeout does not trigger retry
12. timeout does not run composite/QA
13. C3 dry-run includes image_generation_timeout_seconds == 900
14. OpenAI calls in dry-run == 0
15. Higgsfield calls == 0
"""
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline import openai_images_client as client
from api.media_pipeline import product_only_scene_runner as runner

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"
SCENE_ID = "scene-05"

C3_DRY_RUN_PATH = CAMPAIGN_DIR / "scene-05-product-only-apply-dry-run-c3.json"
ACTIVE_DRY_RUN_PATH = CAMPAIGN_DIR / "scene-05-product-only-apply-dry-run.json"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class Test1DefaultTimeoutIs900(unittest.TestCase):
    def test_default_constant_is_900(self):
        self.assertEqual(client.DEFAULT_IMAGE_GENERATION_TIMEOUT_SECONDS, 900)

    def test_resolve_with_no_env_var_returns_900(self):
        value, warnings = client.resolve_image_generation_timeout_seconds({})
        self.assertEqual(value, 900)
        self.assertEqual(warnings, [])

    def test_provider_defaults_to_900_when_no_env_override(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(client.IMAGE_GENERATION_TIMEOUT_ENV_VAR, None)
            provider = client.OpenAIImagesProvider(model="gpt-image-2")
        self.assertEqual(provider.timeout_seconds, 900)


class Test2EnvOverridesTimeout(unittest.TestCase):
    def test_valid_env_value_overrides_default(self):
        value, warnings = client.resolve_image_generation_timeout_seconds(
            {"IMAGE_GENERATION_TIMEOUT_SECONDS": "1200"})
        self.assertEqual(value, 1200)
        self.assertEqual(warnings, [])

    def test_provider_picks_up_env_override(self):
        with mock.patch.dict(os.environ, {client.IMAGE_GENERATION_TIMEOUT_ENV_VAR: "600"}):
            provider = client.OpenAIImagesProvider(model="gpt-image-2")
        self.assertEqual(provider.timeout_seconds, 600)

    def test_explicit_constructor_arg_wins_over_env(self):
        with mock.patch.dict(os.environ, {client.IMAGE_GENERATION_TIMEOUT_ENV_VAR: "600"}):
            provider = client.OpenAIImagesProvider(model="gpt-image-2", timeout_seconds=1234)
        self.assertEqual(provider.timeout_seconds, 1234)


class Test3InvalidEnvFallsBackWithWarning(unittest.TestCase):
    def test_non_integer_falls_back_to_default(self):
        value, warnings = client.resolve_image_generation_timeout_seconds(
            {"IMAGE_GENERATION_TIMEOUT_SECONDS": "not-a-number"})
        self.assertEqual(value, 900)
        self.assertEqual(len(warnings), 1)
        self.assertIn("not an integer", warnings[0])

    def test_empty_string_env_value_uses_default_no_warning(self):
        value, warnings = client.resolve_image_generation_timeout_seconds(
            {"IMAGE_GENERATION_TIMEOUT_SECONDS": "  "})
        self.assertEqual(value, 900)
        self.assertEqual(warnings, [])


class Test4TimeoutBelow60FallsBack(unittest.TestCase):
    def test_below_min_falls_back_to_default_with_warning(self):
        value, warnings = client.resolve_image_generation_timeout_seconds(
            {"IMAGE_GENERATION_TIMEOUT_SECONDS": "10"})
        self.assertEqual(value, 900)
        self.assertEqual(len(warnings), 1)
        self.assertIn("outside allowed range", warnings[0])

    def test_exactly_min_is_accepted(self):
        value, warnings = client.resolve_image_generation_timeout_seconds(
            {"IMAGE_GENERATION_TIMEOUT_SECONDS": "60"})
        self.assertEqual(value, 60)
        self.assertEqual(warnings, [])


class Test5TimeoutAbove1800FallsBack(unittest.TestCase):
    def test_above_max_falls_back_to_default_with_warning(self):
        value, warnings = client.resolve_image_generation_timeout_seconds(
            {"IMAGE_GENERATION_TIMEOUT_SECONDS": "5000"})
        self.assertEqual(value, 900)
        self.assertEqual(len(warnings), 1)
        self.assertIn("outside allowed range", warnings[0])

    def test_exactly_max_is_accepted(self):
        value, warnings = client.resolve_image_generation_timeout_seconds(
            {"IMAGE_GENERATION_TIMEOUT_SECONDS": "1800"})
        self.assertEqual(value, 1800)
        self.assertEqual(warnings, [])


class Test6TimeoutMetadataInRequestMetadata(unittest.TestCase):
    def test_dry_run_planned_request_includes_timeout_seconds(self):
        from api.media_pipeline.models import ImageRequest
        from api.media_pipeline.budget import SpendTracker

        tracker = SpendTracker(cap_usd=0.5)
        provider = client.OpenAIImagesProvider(model="gpt-image-2", tracker=tracker,
                                               timeout_seconds=900)
        req = ImageRequest(scene_id="scene-05", prompt="test prompt", n=1,
                           size="720x1280", mode="generate", reference_images=[])
        results = provider.generate(req, out_dir="/tmp/does-not-matter", apply=False)
        self.assertEqual(results[0].planned_request["timeout_seconds"], 900)


class Test7TimeoutErrorTypeClientReadTimeout(unittest.TestCase):
    def _run_with_timeout(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-fake-not-real"}):
            with mock.patch("urllib.request.urlopen",
                            side_effect=TimeoutError("The read operation timed out")):
                return runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=True)

    def test_error_type_is_client_read_timeout(self):
        report = self._run_with_timeout()
        self.assertEqual(report["error_type"], "client_read_timeout")


class Test8RequestSentTrue(unittest.TestCase):
    def test_request_sent_true(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-fake-not-real"}):
            with mock.patch("urllib.request.urlopen",
                            side_effect=TimeoutError("timed out")):
                report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=True)
        self.assertIs(report["request_sent"], True)
        self.assertIs(report["openai_call_attempted"], True)


class Test9ResponseReceivedFalse(unittest.TestCase):
    def test_response_received_false(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-fake-not-real"}):
            with mock.patch("urllib.request.urlopen",
                            side_effect=TimeoutError("timed out")):
                report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=True)
        self.assertIs(report["response_received"], False)
        self.assertIs(report["actual_cost_known"], False)


class Test10CandidateStatusNoCandidateTimeout(unittest.TestCase):
    def test_candidate_status_no_candidate_timeout(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-fake-not-real"}):
            with mock.patch("urllib.request.urlopen",
                            side_effect=TimeoutError("timed out")):
                report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=True)
        self.assertEqual(report["candidate_status"], "no_candidate_timeout")
        # explicitly NOT "rejected" -- no candidate exists to reject
        self.assertNotEqual(report["candidate_status"], "rejected")


class Test11NoRetryOnTimeout(unittest.TestCase):
    def test_urlopen_called_exactly_once_on_timeout(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-fake-not-real"}):
            with mock.patch("urllib.request.urlopen",
                            side_effect=TimeoutError("timed out")) as mocked:
                report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=True)
        self.assertEqual(mocked.call_count, 1)
        self.assertIs(report["retry_attempted"], False)
        self.assertIs(report["auto_retry_on_timeout"], False)


class Test12NoCompositeOrQaOnTimeout(unittest.TestCase):
    def test_no_compositor_functions_called_on_timeout(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-fake-not-real"}):
            with mock.patch("urllib.request.urlopen",
                            side_effect=TimeoutError("timed out")):
                with mock.patch("api.media_pipeline.compositor.layer_compositor.compose") as mocked_compose:
                    report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=True)
        mocked_compose.assert_not_called()
        self.assertIs(report["composite_and_qa_run"], False)

    def test_report_has_no_qa_results_field_populated(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-fake-not-real"}):
            with mock.patch("urllib.request.urlopen",
                            side_effect=TimeoutError("timed out")):
                report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=True)
        self.assertNotIn("results", report)


class Test13C3DryRunIncludesTimeout900(unittest.TestCase):
    def test_c3_dry_run_timeout_900(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["image_generation_timeout_seconds"], 900)
        self.assertEqual(d["timeout_env_var"], "IMAGE_GENERATION_TIMEOUT_SECONDS")
        self.assertIs(d["auto_retry_on_timeout"], False)

    def test_active_dry_run_timeout_900(self):
        d = load_json(ACTIVE_DRY_RUN_PATH)
        self.assertEqual(d["image_generation_timeout_seconds"], 900)
        self.assertEqual(d["timeout_env_var"], "IMAGE_GENERATION_TIMEOUT_SECONDS")
        self.assertIs(d["auto_retry_on_timeout"], False)

    def test_c3_dry_run_timeout_error_policy(self):
        d = load_json(C3_DRY_RUN_PATH)
        policy = d["timeout_error_policy"]
        self.assertIs(policy["request_sent"], True)
        self.assertIs(policy["response_received"], False)
        self.assertEqual(policy["candidate_status"], "no_candidate_timeout")
        self.assertIs(policy["explicit_owner_authorization_required_for_new_attempt"], True)

    def test_c3_dry_run_still_has_core_c3_fields(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["candidate_label"], "C3")
        self.assertEqual(d["scene_variant"], "no_hands_result_shot")
        self.assertIs(d["no_hands_prompt"], True)
        self.assertIs(d["model_prompt_clean"], True)
        self.assertEqual(d["reference_images"], [])
        self.assertEqual(d["mode"], "generate")
        self.assertEqual(d["model"], "gpt-image-2")
        self.assertEqual(d["size"], "720x1280")
        self.assertEqual(d["n"], 1)
        self.assertEqual(d["retries"], 0)
        self.assertEqual(d["hard_cap_usd"], 0.50)
        self.assertEqual(d["max_calls_future_apply"], 1)


class Test14OpenAICallsZeroInDryRun(unittest.TestCase):
    def test_c3_dry_run_openai_calls_zero(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["openai_calls_executed"], 0)
        self.assertEqual(d["api_spend_usd"], 0)

    def test_dry_run_report_openai_calls_zero(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network call!")):
            report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["openai_calls_executed"], 0)


class Test15HiggsfieldCallsZero(unittest.TestCase):
    def test_c3_dry_run_higgsfield_calls_zero(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["higgsfield_calls_executed"], 0)

    def test_dry_run_report_higgsfield_calls_zero(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network call!")):
            report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["higgsfield_calls_executed"], 0)


class TestTimeoutReportSavedAndGitignored(unittest.TestCase):
    def test_timeout_report_written_to_generated_dir_and_ignored(self):
        import subprocess
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-fake-not-real"}):
            with mock.patch("urllib.request.urlopen",
                            side_effect=TimeoutError("timed out")):
                report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=True)
        report_path = Path(report["report_path"])
        self.assertTrue(report_path.is_file())
        self.assertIn("generated", report_path.parts)
        result = subprocess.run(["git", "check-ignore", "-q", str(report_path)],
                                cwd=str(REPO_ROOT))
        self.assertEqual(result.returncode, 0, f"{report_path} НЕ в .gitignore!")


if __name__ == "__main__":
    unittest.main()
