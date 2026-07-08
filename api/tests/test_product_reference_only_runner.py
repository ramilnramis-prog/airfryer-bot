"""Тесты product-reference-only runner (scene-05, "product_reference_only_v1")
-- executable path после owner decision PRODUCT ONLY MEANS PRODUCT ONLY (см.
scene-05-generation-attempts-status.json, campaign_visual_policy.json).

TASK 1 finding: api/media_pipeline/openai_images_client.py УЖЕ поддерживает
mode="edit" с reference_images=[<path>] и без mask (files = [("image[]",
ref, Path(ref).read_bytes()) for ref in request.reference_images] --
существующий код, не выдумано заново). Этот модуль (product_reference_only_runner.py)
переиспользует именно этот существующий путь -- единственное новое: fail-
closed single-call runner (тот же MAX_CALLS=1/RETRIES=0/HARD_CAP_USD=0.50
контракт, что и у product_only_scene_runner.py) + новый CLI subcommand
'product-reference-only-scene'.

Покрытие (13 пунктов, запрошенных явно):
1. product-reference-only dry-run exists
2. reference_images length == 1
3. reference_images[0] == real-product-v1
4. no C1/C2/C3 output path appears anywhere in reference_images
5. no generated plate path appears anywhere in reference_images
6. forbidden_global_reference_categories includes generated plates / previous candidate composites
7. prompt contains no hands/person
8. prompt contains product visual constraints from real-product-v1
9. prompt contains exactly 3 chicken thighs + potato wedges
10. model_prompt_clean == true
11. OpenAI calls = 0
12. Higgsfield calls = 0
13. api_spend_usd = 0
"""
import io
import json
import re
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from api.media_pipeline import cli
from api.media_pipeline import product_reference_only_runner as runner

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"
SCENE_ID = "scene-05"

DRY_RUN_PATH = CAMPAIGN_DIR / "scene-05-product-reference-only-apply-dry-run.json"
POLICY_PATH = CAMPAIGN_DIR / "campaign_visual_policy.json"

C1_C2_C3_PNG_PATTERN = re.compile(r"scene-05-c[123][-.]")
GENERATED_PLATE_PATTERN = re.compile(r"generated[\\/]product-only-scene")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_cli(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(argv)
    return code, json.loads(buf.getvalue())


def urlopen_raises():
    return mock.patch("urllib.request.urlopen",
                      side_effect=AssertionError("network call!"))


class Test1DryRunExists(unittest.TestCase):
    def test_apply_dry_run_file_exists(self):
        self.assertTrue(DRY_RUN_PATH.is_file())

    def test_live_dry_run_report_can_be_produced(self):
        with urlopen_raises():
            report = runner.run_product_reference_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["mode"], "dry-run")


class Test2ReferenceImagesLengthOne(unittest.TestCase):
    def test_dry_run_doc_reference_images_length_one(self):
        d = load_json(DRY_RUN_PATH)
        self.assertEqual(len(d["reference_images"]), 1)

    def test_live_contract_reference_images_length_one(self):
        req, contract = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertEqual(len(req.reference_images), 1)
        self.assertEqual(len(contract.reference_images), 1)


class Test3ReferenceImagesIsRealProductV1(unittest.TestCase):
    def test_dry_run_doc_reference_images_value(self):
        d = load_json(DRY_RUN_PATH)
        self.assertEqual(d["reference_images"], ["real-product-v1"])

    def test_resolved_path_points_to_real_product_v1_master_crop(self):
        d = load_json(DRY_RUN_PATH)
        self.assertIn("real-v1/product/product_45deg_master.png",
                     d["reference_image_resolved_path"].replace("\\", "/"))

    def test_resolved_reference_file_actually_exists(self):
        d = load_json(DRY_RUN_PATH)
        self.assertTrue((REPO_ROOT / d["reference_image_resolved_path"]).is_file())


class Test4NoC1C2C3OutputInReferenceImages(unittest.TestCase):
    def test_reference_images_field_clean(self):
        d = load_json(DRY_RUN_PATH)
        for ref in d["reference_images"]:
            self.assertIsNone(C1_C2_C3_PNG_PATTERN.search(ref))

    def test_resolved_path_is_not_a_c1_c2_c3_output(self):
        d = load_json(DRY_RUN_PATH)
        self.assertIsNone(C1_C2_C3_PNG_PATTERN.search(d["reference_image_resolved_path"]))

    def test_forbidden_reference_sources_names_c1_c2_c3_explicitly(self):
        d = load_json(DRY_RUN_PATH)
        self.assertIn("C1", d["forbidden_reference_sources"])
        self.assertIn("C2", d["forbidden_reference_sources"])
        self.assertIn("C3", d["forbidden_reference_sources"])


class Test5NoGeneratedPlateInReferenceImages(unittest.TestCase):
    def test_reference_images_field_has_no_generated_plate_path(self):
        d = load_json(DRY_RUN_PATH)
        for ref in d["reference_images"]:
            self.assertIsNone(GENERATED_PLATE_PATTERN.search(ref))

    def test_resolved_path_is_not_under_generated_dir(self):
        d = load_json(DRY_RUN_PATH)
        self.assertNotIn("generated", d["reference_image_resolved_path"])

    def test_resolved_path_is_under_product_lock_assets(self):
        d = load_json(DRY_RUN_PATH)
        self.assertIn("product-lock", d["reference_image_resolved_path"])


class Test6ForbiddenCategoriesIncludeGeneratedPlates(unittest.TestCase):
    def test_policy_forbidden_categories(self):
        policy = load_json(POLICY_PATH)
        forbidden = policy["forbidden_global_reference_categories"]
        self.assertIn("generated_plates", forbidden)
        self.assertIn("previous_candidate_composites", forbidden)

    def test_runner_forbidden_reference_sources_covers_same(self):
        self.assertIn("generated_plates", runner.FORBIDDEN_REFERENCE_SOURCES)
        self.assertIn("previous_candidate_composites", runner.FORBIDDEN_REFERENCE_SOURCES)


class Test7PromptNoHandsNoPerson(unittest.TestCase):
    def test_model_prompt_contains_no_hands(self):
        self.assertIn("No hands", runner.MODEL_PROMPT)
        self.assertIn("no person", runner.MODEL_PROMPT.lower())

    def test_negative_prompt_forbids_hands_and_person(self):
        self.assertIn("hands", runner.NEGATIVE_PROMPT)
        self.assertIn("person", runner.NEGATIVE_PROMPT)

    def test_dry_run_doc_prompt_no_hands(self):
        d = load_json(DRY_RUN_PATH)
        self.assertIn("No hands", d["model_prompt"])


class Test8PromptHasProductVisualConstraints(unittest.TestCase):
    def test_model_prompt_describes_real_product_v1_shape(self):
        for token in ("dark grey matte", "flat corner handle tabs",
                     "short horizontal slots", "ribbed bottom"):
            self.assertIn(token, runner.MODEL_PROMPT)

    def test_negative_prompt_forbids_redesigned_and_loop_handles(self):
        for token in ("redesigned handles", "loop handles", "vertical oval holes",
                     "duplicate tray"):
            self.assertIn(token, runner.NEGATIVE_PROMPT)

    def test_qa_gates_include_product_visual_match_gate(self):
        names = [g["name"] for g in runner.QA_GATES_PRODUCT_REFERENCE_ONLY]
        self.assertIn("product_visually_matches_real_product_v1", names)


class Test9PromptExactly3ChickenThighsPotatoWedges(unittest.TestCase):
    def test_model_prompt_food_count(self):
        self.assertIn("exactly 3 roasted golden chicken thighs with potato wedges",
                     runner.MODEL_PROMPT)

    def test_qa_gates_include_food_count_gate(self):
        names = [g["name"] for g in runner.QA_GATES_PRODUCT_REFERENCE_ONLY]
        self.assertIn("food_count_exact", names)


class Test10ModelPromptCleanTrue(unittest.TestCase):
    def test_dry_run_doc_model_prompt_clean(self):
        d = load_json(DRY_RUN_PATH)
        self.assertIs(d["model_prompt_clean"], True)

    def test_prompt_has_no_markdown_or_russian(self):
        self.assertNotIn("##", runner.MODEL_PROMPT)
        self.assertNotIn("```", runner.MODEL_PROMPT)
        cyrillic = [ch for ch in runner.FULL_MODEL_PROMPT if "Ѐ" <= ch <= "ӿ"]
        self.assertEqual(cyrillic, [])


class Test11OpenAICallsZero(unittest.TestCase):
    def test_dry_run_doc_openai_calls_zero(self):
        d = load_json(DRY_RUN_PATH)
        self.assertEqual(d["openai_calls_executed"], 0)
        self.assertEqual(d["openai_calls_planned"], 0)

    def test_live_dry_run_openai_calls_zero(self):
        with urlopen_raises():
            report = runner.run_product_reference_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["openai_calls_executed"], 0)

    def test_cli_dry_run_openai_calls_zero(self):
        with urlopen_raises():
            code, out = run_cli(["product-reference-only-scene", "--campaign", "coating-protect-2026-07",
                                 "--scene", SCENE_ID])
        self.assertEqual(code, 0)
        self.assertEqual(out["openai_calls_executed"], 0)


class Test12HiggsfieldCallsZero(unittest.TestCase):
    def test_dry_run_doc_higgsfield_calls_zero(self):
        d = load_json(DRY_RUN_PATH)
        self.assertEqual(d["higgsfield_calls_executed"], 0)
        self.assertEqual(d["higgsfield_calls_planned"], 0)

    def test_live_dry_run_higgsfield_calls_zero(self):
        with urlopen_raises():
            report = runner.run_product_reference_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["higgsfield_calls_executed"], 0)

    def test_no_paid_api_surface_in_runner_module(self):
        src = (REPO_ROOT / "api" / "media_pipeline" / "product_reference_only_runner.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("api.higgsfield", src)


class Test13ApiSpendZero(unittest.TestCase):
    def test_dry_run_doc_api_spend_zero(self):
        d = load_json(DRY_RUN_PATH)
        self.assertEqual(d["api_spend_usd"], 0)

    def test_live_dry_run_api_spend_zero(self):
        with urlopen_raises():
            report = runner.run_product_reference_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["api_spend_usd"], 0)


class TestApplyRequiresKeyAndSingleCall(unittest.TestCase):
    """Same fail-closed guarantees as product_only_scene_runner.py: apply
    without OPENAI_API_KEY fails before network; max_calls/retries are
    structurally 1/0."""

    def test_max_calls_and_retries_constants(self):
        self.assertEqual(runner.MAX_CALLS, 1)
        self.assertEqual(runner.RETRIES, 0)
        self.assertEqual(runner.HARD_CAP_USD, 0.50)

    def test_apply_without_key_raises_before_network(self):
        import os
        from api.media_pipeline.openai_images_client import MissingAPIKeyError
        env_backup = os.environ.pop("OPENAI_API_KEY", None)
        try:
            with urlopen_raises():
                with self.assertRaises(MissingAPIKeyError):
                    runner.run_product_reference_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=True)
        finally:
            if env_backup is not None:
                os.environ["OPENAI_API_KEY"] = env_backup

    def test_request_mode_is_edit(self):
        req, contract = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertEqual(req.mode, "edit")
        self.assertEqual(contract.mode, "edit")

    def test_endpoint_is_images_edits(self):
        _req, contract = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertEqual(contract.endpoint, "/images/edits")


class TestGeneratedReportFilesRemainIgnored(unittest.TestCase):
    def test_report_path_is_gitignored(self):
        import subprocess
        with urlopen_raises():
            report = runner.run_product_reference_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        report_path = Path(report["report_path"])
        self.assertIn("generated", report_path.parts)
        result = subprocess.run(["git", "check-ignore", "-q", report["report_path"]],
                                cwd=str(REPO_ROOT))
        self.assertEqual(result.returncode, 0, f"{report['report_path']} НЕ в .gitignore!")


if __name__ == "__main__":
    unittest.main()
