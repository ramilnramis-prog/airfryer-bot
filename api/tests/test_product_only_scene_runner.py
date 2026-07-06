"""Тесты product-only scene runner (background-first CLI path, замена
отклонённого CALL 1 HANDS masked-edit подхода).

Покрытие (12 пунктов, запрошенных явно):
1. product-only-scene dry-run executes with network_calls=0
2. --apply is required for network call
3. --apply без OPENAI_API_KEY падает ДО сети
4. --apply требует max_calls=1
5. retries принудительно 0
6. campaign_visual_lock.json не читается
7. appearance refs не резолвятся
8. scene-05 final prompt содержит product lock instruction
9. scene-05 dry-run содержит real-product-v1
10. старые refs заблокированы
11. generated-файлы остаются gitignored
12. никаких платных OpenAI-вызовов в тестах
"""
import io
import json
import subprocess
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from api.media_pipeline import cli
from api.media_pipeline import product_only_scene_runner as runner
from api.media_pipeline.openai_images_client import MissingAPIKeyError
from api.media_pipeline.product_only_policy import FORBIDDEN_APPEARANCE_ASSET_IDS

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"
SCENE_ID = "scene-05"

FINAL_PROMPT_PATH = CAMPAIGN_DIR / "scene-05-final-product-only-prompt.md"
APPLY_DRY_RUN_PATH = CAMPAIGN_DIR / "scene-05-product-only-apply-dry-run.json"
SCENE05_DRY_RUN_PATH = CAMPAIGN_DIR / "scene-05-product-only-generation-dry-run.json"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_text(path):
    return Path(path).read_text(encoding="utf-8")


def run_cli(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(argv)
    return code, json.loads(buf.getvalue())


def urlopen_raises():
    return mock.patch("urllib.request.urlopen",
                      side_effect=AssertionError("network call!"))


class TestDryRunZeroNetworkCalls(unittest.TestCase):
    """1: dry-run исполняется с network_calls=0."""

    def test_run_product_only_scene_dry_run_makes_no_network_call(self):
        with urlopen_raises():
            report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["mode"], "dry-run")
        self.assertEqual(report["openai_calls_executed"], 0)
        self.assertEqual(report["api_spend_usd"], 0)

    def test_cli_product_only_scene_dry_run_makes_no_network_call(self):
        with urlopen_raises():
            code, out = run_cli(["product-only-scene", "--campaign", "coating-protect-2026-07",
                                 "--scene", SCENE_ID, "--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(out["openai_calls_executed"], 0)

    def test_dry_run_is_default_without_apply_flag(self):
        with urlopen_raises():
            code, out = run_cli(["product-only-scene", "--campaign", "coating-protect-2026-07",
                                 "--scene", SCENE_ID])
        self.assertEqual(code, 0)
        self.assertEqual(out["mode"], "dry-run")


class TestApplyRequiredForNetworkCall(unittest.TestCase):
    """2: --apply обязателен для сетевого вызова (без него сети не будет
    никогда, см. также TestDryRunZeroNetworkCalls)."""

    def test_apply_false_never_reaches_urlopen_even_with_valid_key(self):
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": "sk-fake-not-real"}):
            with urlopen_raises():
                report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["openai_calls_executed"], 0)


class TestApplyWithoutKeyFailsBeforeNetwork(unittest.TestCase):
    """3: --apply без OPENAI_API_KEY падает ДО сети."""

    def test_apply_without_key_raises_missing_api_key_before_network(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("OPENAI_API_KEY", None)
            with urlopen_raises():
                with self.assertRaises(MissingAPIKeyError):
                    runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=True)

    def test_cli_apply_without_key_exits_1_no_network(self):
        import os
        env_backup = os.environ.pop("OPENAI_API_KEY", None)
        try:
            with urlopen_raises():
                code, out = run_cli(["product-only-scene", "--campaign", "coating-protect-2026-07",
                                     "--scene", SCENE_ID, "--apply"])
            self.assertEqual(code, 1)
            self.assertIn("OPENAI_API_KEY", out["error"])
        finally:
            if env_backup is not None:
                os.environ["OPENAI_API_KEY"] = env_backup


class TestApplyRequiresMaxCallsOne(unittest.TestCase):
    """4: --apply требует max_calls == 1."""

    def test_max_calls_constant_is_one(self):
        self.assertEqual(runner.MAX_CALLS, 1)

    def test_apply_raises_if_max_calls_misconfigured(self):
        with mock.patch.object(runner, "MAX_CALLS", 2):
            with urlopen_raises():
                with self.assertRaises(runner.ProductOnlyRunnerError) as ctx:
                    runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=True)
        self.assertEqual(ctx.exception.code, "MAX_CALLS_VIOLATION")

    def test_request_contract_reports_max_calls_one(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertEqual(contract.max_calls, 1)


class TestRetriesForcedToZero(unittest.TestCase):
    """5: retries принудительно 0."""

    def test_retries_constant_is_zero(self):
        self.assertEqual(runner.RETRIES, 0)

    def test_apply_raises_if_retries_misconfigured(self):
        with mock.patch.object(runner, "RETRIES", 1):
            with urlopen_raises():
                with self.assertRaises(runner.ProductOnlyRunnerError) as ctx:
                    runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=True)
        self.assertEqual(ctx.exception.code, "RETRIES_VIOLATION")

    def test_request_contract_reports_retries_zero(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertEqual(contract.retries, 0)

    def test_image_request_object_has_no_retry_mechanism(self):
        req, _contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertFalse(hasattr(req, "max_retries"))
        self.assertFalse(hasattr(req, "retries"))


class TestCampaignVisualLockNotRead(unittest.TestCase):
    """6: runner никогда не читает campaign_visual_lock.json."""

    def test_runner_module_does_not_import_reference_library(self):
        # "campaign_visual_lock"/"reference_library" legitimately appear in
        # docstrings/report-field-names (documenting that they're NOT used,
        # e.g. "uses_campaign_visual_lock": False) -- what actually matters
        # is that the module never IMPORTS the resolver or opens that file.
        src = (REPO_ROOT / "api" / "media_pipeline" / "product_only_scene_runner.py").read_text(encoding="utf-8")
        self.assertNotIn("import reference_library", src)
        self.assertNotIn("from .reference_library", src)
        self.assertNotIn("from api.media_pipeline.reference_library", src)
        self.assertNotIn("campaign_visual_lock.json'", src)
        self.assertNotIn('campaign_visual_lock.json"', src)

    def test_building_request_contract_never_opens_old_lock_file(self):
        old_lock_path = CAMPAIGN_DIR / "campaign_visual_lock.json"
        real_read_text = Path.read_text

        def guarded_read_text(self, *args, **kwargs):
            if self == old_lock_path:
                raise AssertionError("campaign_visual_lock.json was read!")
            return real_read_text(self, *args, **kwargs)

        with mock.patch.object(Path, "read_text", guarded_read_text):
            runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)


class TestAppearanceRefsNotResolved(unittest.TestCase):
    """7: appearance refs не резолвятся вообще."""

    def test_request_contract_has_empty_reference_images(self):
        req, _contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertEqual(req.reference_images, [])

    def test_request_mode_is_generate_not_edit(self):
        req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertEqual(req.mode, "generate")
        self.assertEqual(contract.mode, "generate")

    def test_dry_run_report_reference_images_empty(self):
        with urlopen_raises():
            report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["request_contract"]["reference_images"], [])
        self.assertFalse(report["uses_reference_library_for_appearance"])
        self.assertFalse(report["uses_campaign_visual_lock"])


class TestScene05FinalPromptHasProductLockInstruction(unittest.TestCase):
    """8: scene-05 final prompt содержит product lock instruction."""

    def test_final_prompt_file_exists(self):
        self.assertTrue(FINAL_PROMPT_PATH.is_file())

    def test_final_prompt_has_product_lock_section_and_pixel_faithful_line(self):
        text = load_text(FINAL_PROMPT_PATH)
        self.assertIn("Product lock instruction", text)
        self.assertIn("pixel-faithful", text)
        self.assertIn("real-product-v1", text)

    def test_final_prompt_matches_current_runner_prompt_sha256(self):
        _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        text = load_text(FINAL_PROMPT_PATH)
        self.assertIn(contract.prompt_sha256, text)


class TestScene05DryRunContainsRealProductV1(unittest.TestCase):
    """9: scene-05 dry-run содержит real-product-v1."""

    def test_scene05_generation_dry_run_has_product_canon(self):
        d = load_json(SCENE05_DRY_RUN_PATH)
        self.assertEqual(d["product_canon"], "real-product-v1")

    def test_scene05_apply_dry_run_exists_and_has_product_canon(self):
        self.assertTrue(APPLY_DRY_RUN_PATH.is_file())
        d = load_json(APPLY_DRY_RUN_PATH)
        self.assertEqual(d["product_canon"], "real-product-v1")
        self.assertEqual(d["generation_mode"], "product_only")
        self.assertEqual(d["composite_approach"], "background_first")

    def test_apply_dry_run_has_qa_gates_and_zero_calls(self):
        d = load_json(APPLY_DRY_RUN_PATH)
        self.assertEqual(len(d["qa_gates"]), 10)
        self.assertEqual(d["openai_calls_executed"], 0)
        self.assertEqual(d["higgsfield_calls_executed"], 0)
        self.assertEqual(d["api_spend_usd"], 0)
        self.assertEqual(d["hard_cap_usd"], 0.50)
        self.assertEqual(d["max_calls_future_apply"], 1)
        self.assertEqual(d["retries"], 0)


class TestOldRefsBlocked(unittest.TestCase):
    """10: старые refs заблокированы."""

    def test_no_forbidden_asset_ids_in_apply_dry_run_doc_runtime_data(self):
        # forbidden asset_id's МОГУТ упоминаться в прозе как "что запрещено"
        # (документация) -- проверяем, что они не встречаются как ЗНАЧЕНИЯ в
        # фактических runtime-полях контракта/QA, а не строку целиком.
        d = load_json(APPLY_DRY_RUN_PATH)
        flat_values = json.dumps(d, ensure_ascii=False)
        # единственное легитимное место -- нет, apply-dry-run вообще не должен
        # упоминать их ни в каком виде (это чистый request-контракт, не проза).
        for asset_id in FORBIDDEN_APPEARANCE_ASSET_IDS:
            self.assertNotIn(asset_id, flat_values)

    def test_forbidden_asset_ids_in_final_prompt_only_appear_as_prohibited(self):
        text = load_text(FINAL_PROMPT_PATH)
        for asset_id in FORBIDDEN_APPEARANCE_ASSET_IDS:
            if asset_id in text:
                # допустимо ТОЛЬКО в предложении, явно перечисляющем их как
                # запрещённые (рядом должно быть слово "запрещ").
                idx = text.index(asset_id)
                window = text[max(0, idx - 300):idx + 300]
                self.assertIn("запрещ", window,
                             f"{asset_id} упомянут не в контексте запрета")

    def test_runner_never_puts_forbidden_ids_into_actual_request_contract(self):
        with urlopen_raises():
            report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        flat = json.dumps(report, ensure_ascii=False)
        for asset_id in FORBIDDEN_APPEARANCE_ASSET_IDS:
            self.assertNotIn(asset_id, flat)

    def test_legacy_pilot_generate_still_blocked(self):
        code, out = run_cli(["pilot", str(CAMPAIGN_DIR), "--scene", "scene-05"])
        self.assertEqual(code, 2)
        self.assertEqual(out["code"], "BLOCKED_BY_PRODUCT_ONLY_POLICY")


class TestGeneratedFilesRemainIgnored(unittest.TestCase):
    """11: generated-файлы (отчёты runner'а) остаются gitignored."""

    def test_report_path_is_under_gitignored_generated_dir(self):
        with urlopen_raises():
            report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        report_path = Path(report["report_path"])
        self.assertIn("generated", report_path.parts)

    def test_git_check_ignore_confirms_report_path_ignored(self):
        with urlopen_raises():
            report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        result = subprocess.run(
            ["git", "check-ignore", "-q", report["report_path"]],
            cwd=str(REPO_ROOT))
        self.assertEqual(result.returncode, 0,
                         f"{report['report_path']} НЕ в .gitignore!")


class TestNoPaidApiCallsDuringTests(unittest.TestCase):
    """12: ни одного платного OpenAI-вызова во время тестов."""

    def test_full_dry_run_suite_makes_no_network_call(self):
        with urlopen_raises():
            runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
            runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)

    def test_no_paid_api_surface_in_runner_module(self):
        src = (REPO_ROOT / "api" / "media_pipeline" / "product_only_scene_runner.py").read_text(encoding="utf-8").lower()
        for token in ("api.higgsfield",):
            self.assertNotIn(token, src, token)


if __name__ == "__main__":
    unittest.main()
