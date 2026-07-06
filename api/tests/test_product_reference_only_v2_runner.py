"""Тесты product-reference-only-v2 runner (scene-05, "product_reference_only_v2")
-- owner clarification после v1 apply: единственные разрешённые reference
assets -- изображения САМОЙ силиконовой формы под product-lock/real-v1
(product/handles/bottom), НИКОГДА airfryer/basket/motion (даже если они тоже
живут под real-v1) и НИКОГДА generated/C1/C2/C3 outputs.

Покрытие (12 пунктов, запрошенных явно):
1. product-reference-only-v2 dry-run exists
2. candidate_label == product_reference_only_v2
3. reference_images length == 4
4. all 4 references are allowed product-only assets
5. no forbidden airfryer/motion/generated references
6. no C1/C2/C3 paths
7. prompt contains no hands/person
8. prompt contains product geometry constraints
9. prompt contains exactly 3 chicken thighs + potato wedges
10. OpenAI calls = 0
11. Higgsfield calls = 0
12. api_spend_usd = 0
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

DRY_RUN_PATH = CAMPAIGN_DIR / "scene-05-product-reference-only-v2-apply-dry-run.json"

C1_C2_C3_PATTERN = re.compile(r"scene-05-c[123][-.]")
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
            report = runner.run_product_reference_only_scene_v2(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["mode"], "dry-run")


class Test2CandidateLabel(unittest.TestCase):
    def test_dry_run_doc_candidate_label(self):
        d = load_json(DRY_RUN_PATH)
        self.assertEqual(d["candidate_label"], "product_reference_only_v2")

    def test_runner_constant(self):
        self.assertEqual(runner.CANDIDATE_LABEL_V2, "product_reference_only_v2")

    def test_scene_variant_and_mode(self):
        d = load_json(DRY_RUN_PATH)
        self.assertEqual(d["scene_variant"], "no_hands_result_shot")
        self.assertEqual(d["product_reference_mode"], "multi_product_reference_only")


class Test3ReferenceImagesLengthFour(unittest.TestCase):
    def test_dry_run_doc_length_four(self):
        d = load_json(DRY_RUN_PATH)
        self.assertEqual(len(d["reference_images"]), 4)
        self.assertEqual(len(d["reference_image_paths"]), 4)

    def test_live_contract_length_four(self):
        req, contract = runner.build_request_contract_v2(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertEqual(len(req.reference_images), 4)
        self.assertEqual(len(contract.reference_images), 4)


class Test4AllReferencesAreAllowedProductOnlyAssets(unittest.TestCase):
    def test_dry_run_doc_references_all_allowed(self):
        d = load_json(DRY_RUN_PATH)
        for asset_id in d["reference_images"]:
            self.assertIn(asset_id, ALLOWED_ASSET_IDS)

    def test_expected_four_assets_exactly(self):
        d = load_json(DRY_RUN_PATH)
        self.assertEqual(d["reference_images"], [
            "real-product-v1:product_45deg_master",
            "real-product-v1:product_top_master",
            "real-product-v1:both_handles_master",
            "real-product-v1:bottom_loop_master",
        ])

    def test_resolved_paths_all_exist_and_are_rgb(self):
        from PIL import Image
        d = load_json(DRY_RUN_PATH)
        for rel_path in d["reference_image_paths"]:
            full = REPO_ROOT / rel_path
            self.assertTrue(full.is_file(), f"missing: {full}")
            with Image.open(full) as im:
                self.assertEqual(im.mode, "RGB", f"{full} should be plain RGB, no alpha")


class Test5NoForbiddenAirfryerMotionGeneratedReferences(unittest.TestCase):
    def test_dry_run_doc_paths_have_no_airfryer_or_motion(self):
        d = load_json(DRY_RUN_PATH)
        for p in d["reference_image_paths"]:
            self.assertIsNone(AIRFRYER_MOTION_PATTERN.search(p.replace("/", "\\") + "\\"),
                             f"forbidden airfryer/motion reference: {p}")

    def test_dry_run_doc_paths_have_no_generated_dir(self):
        d = load_json(DRY_RUN_PATH)
        for p in d["reference_image_paths"]:
            self.assertNotIn("generated", p)

    def test_forbidden_product_lock_assets_declared(self):
        d = load_json(DRY_RUN_PATH)
        forbidden = d["forbidden_product_lock_assets"]
        self.assertIn("real-v1/airfryer/airfryer_front_master.png", forbidden)
        self.assertIn("real-v1/airfryer/clean_basket_master.png", forbidden)
        self.assertIn("real-v1/motion/product_in_basket_master.png", forbidden)
        self.assertIn("real-v1/motion/grip_motion_master.png", forbidden)

    def test_apply_rejects_forbidden_reference_if_injected(self):
        injected_tuple = (*runner.PRODUCT_REFERENCE_IMAGES_V2[:3], "fake:forbidden")
        patched_paths = dict(runner.PRODUCT_REFERENCE_ASSET_PATHS)
        patched_paths["fake:forbidden"] = ("assets/product-lock/airfryer-silicone-form/"
                                           "references/real-v1/airfryer/clean_basket_master.png")
        with mock.patch.object(runner, "PRODUCT_REFERENCE_IMAGES_V2", injected_tuple), \
             mock.patch.object(runner, "PRODUCT_REFERENCE_ASSET_PATHS", patched_paths), \
             mock.patch.dict("os.environ", {"OPENAI_API_KEY": "sk-fake-not-real"}), \
             urlopen_raises():
            with self.assertRaises(runner.ProductReferenceOnlyRunnerError) as ctx:
                runner.run_product_reference_only_scene_v2(str(CAMPAIGN_DIR), SCENE_ID, apply=True)
        self.assertEqual(ctx.exception.code, "FORBIDDEN_REFERENCE_SOURCE")


class Test6NoC1C2C3Paths(unittest.TestCase):
    def test_dry_run_doc_reference_images_clean(self):
        d = load_json(DRY_RUN_PATH)
        for asset_id in d["reference_images"]:
            self.assertIsNone(C1_C2_C3_PATTERN.search(asset_id))
        for p in d["reference_image_paths"]:
            self.assertIsNone(C1_C2_C3_PATTERN.search(p))

    def test_forbidden_reference_sources_names_c1_c2_c3(self):
        d = load_json(DRY_RUN_PATH)
        self.assertIn("C1", d["forbidden_reference_sources"])
        self.assertIn("C2", d["forbidden_reference_sources"])
        self.assertIn("C3", d["forbidden_reference_sources"])


class Test7PromptNoHandsNoPerson(unittest.TestCase):
    def test_model_prompt_v2_no_hands(self):
        self.assertIn("No hands", runner.MODEL_PROMPT_V2)
        self.assertIn("no person", runner.MODEL_PROMPT_V2.lower())

    def test_negative_prompt_v2_forbids_hands_person(self):
        self.assertIn("hands", runner.NEGATIVE_PROMPT_V2)
        self.assertIn("person", runner.NEGATIVE_PROMPT_V2)

    def test_dry_run_doc_prompt_no_hands(self):
        d = load_json(DRY_RUN_PATH)
        self.assertIn("No hands", d["model_prompt"])


class Test8PromptProductGeometryConstraints(unittest.TestCase):
    def test_model_prompt_v2_describes_shape(self):
        for token in ("dark grey matte", "flat corner handle tabs",
                     "short horizontal slots", "ribbed bottom",
                     "faithful to the product references"):
            self.assertIn(token, runner.MODEL_PROMPT_V2)

    def test_negative_prompt_v2_forbids_redesign(self):
        for token in ("redesigned handles", "loop handles", "vertical oval holes"):
            self.assertIn(token, runner.NEGATIVE_PROMPT_V2)

    def test_qa_gates_v2_include_product_match_gate(self):
        names = [g["name"] for g in runner.QA_GATES_PRODUCT_REFERENCE_ONLY_V2]
        self.assertIn("product_visually_matches_references", names)
        self.assertIn("every_reference_under_real_v1_product_only", names)


class Test9PromptExactly3ChickenThighsPotatoWedges(unittest.TestCase):
    def test_model_prompt_v2_food_count(self):
        self.assertIn("exactly 3 roasted golden chicken thighs with potato wedges",
                     runner.MODEL_PROMPT_V2)

    def test_qa_gates_v2_include_food_count_gate(self):
        names = [g["name"] for g in runner.QA_GATES_PRODUCT_REFERENCE_ONLY_V2]
        self.assertIn("food_count_exact", names)


class Test10OpenAICallsZero(unittest.TestCase):
    def test_dry_run_doc_openai_calls_zero(self):
        d = load_json(DRY_RUN_PATH)
        self.assertEqual(d["openai_calls_executed"], 0)
        self.assertEqual(d["openai_calls_planned"], 0)

    def test_live_dry_run_openai_calls_zero(self):
        with urlopen_raises():
            report = runner.run_product_reference_only_scene_v2(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["openai_calls_executed"], 0)

    def test_cli_dry_run_openai_calls_zero(self):
        with urlopen_raises():
            code, out = run_cli(["product-reference-only-scene-v2", "--campaign",
                                 "coating-protect-2026-07", "--scene", SCENE_ID])
        self.assertEqual(code, 0)
        self.assertEqual(out["openai_calls_executed"], 0)


class Test11HiggsfieldCallsZero(unittest.TestCase):
    def test_dry_run_doc_higgsfield_calls_zero(self):
        d = load_json(DRY_RUN_PATH)
        self.assertEqual(d["higgsfield_calls_executed"], 0)
        self.assertEqual(d["higgsfield_calls_planned"], 0)

    def test_live_dry_run_higgsfield_calls_zero(self):
        with urlopen_raises():
            report = runner.run_product_reference_only_scene_v2(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["higgsfield_calls_executed"], 0)


class Test12ApiSpendZero(unittest.TestCase):
    def test_dry_run_doc_api_spend_zero(self):
        d = load_json(DRY_RUN_PATH)
        self.assertEqual(d["api_spend_usd"], 0)

    def test_live_dry_run_api_spend_zero(self):
        with urlopen_raises():
            report = runner.run_product_reference_only_scene_v2(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["api_spend_usd"], 0)


class TestApplyFailClosedContract(unittest.TestCase):
    def test_max_calls_retries_hard_cap_constants(self):
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
                    runner.run_product_reference_only_scene_v2(str(CAMPAIGN_DIR), SCENE_ID, apply=True)
        finally:
            if env_backup is not None:
                os.environ["OPENAI_API_KEY"] = env_backup

    def test_request_mode_is_edit(self):
        req, contract = runner.build_request_contract_v2(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertEqual(req.mode, "edit")
        self.assertEqual(contract.mode, "edit")


class TestGeneratedReportFilesRemainIgnored(unittest.TestCase):
    def test_report_path_is_gitignored(self):
        import subprocess
        with urlopen_raises():
            report = runner.run_product_reference_only_scene_v2(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        report_path = Path(report["report_path"])
        self.assertIn("generated", report_path.parts)
        result = subprocess.run(["git", "check-ignore", "-q", report["report_path"]],
                                cwd=str(REPO_ROOT))
        self.assertEqual(result.returncode, 0, f"{report['report_path']} НЕ в .gitignore!")


class TestV1StillWorksUnchanged(unittest.TestCase):
    """v2 additions must not break the existing v1 path."""

    def test_v1_reference_images_still_length_one(self):
        req, contract = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertEqual(len(req.reference_images), 1)

    def test_v1_candidate_label_unchanged(self):
        self.assertEqual(runner.CANDIDATE_LABEL, "product_reference_only_v1")


if __name__ == "__main__":
    unittest.main()
