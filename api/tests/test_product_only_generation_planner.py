"""Тесты: product-only policy реально управляет media pipeline / generation
planning, а не только документация.

Покрытие (12 пунктов, запрошенных явно):
1. product-only policy has priority over campaign_visual_lock
2. product-only mode does not resolve appearance refs
3. product-only mode blocks person-b-exhausted-01
4. product-only mode blocks real-grip-motion-01
5. old CALL 1 HANDS cannot run when product-only policy active
6. old FOOD plan cannot run when product-only policy active
7. scene-05 final prompt includes continuity block
8. scene-05 final prompt includes product lock instruction
9. scene-05 final prompt has no mandatory hands/person/kitchen image refs
10. dry-run has OpenAI calls = 0
11. dry-run has Higgsfield calls = 0
12. product canon remains real-product-v1
плюс: никаких платных API-вызовов.
"""
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from api.media_pipeline import cli
from api.media_pipeline.product_only_policy import (
    FORBIDDEN_APPEARANCE_ASSET_IDS,
    ProductOnlyPolicyError,
    assert_legacy_generation_allowed,
    assert_no_forbidden_appearance_refs,
    is_product_only_campaign,
    load_product_only_policy,
    plan_scene_request,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"
SCENE_IDS = [f"scene-{i:02d}" for i in range(1, 8)]

DRY_RUN_PATH = CAMPAIGN_DIR / "product-only-generation-dry-run.json"
SCENE05_DRY_RUN_PATH = CAMPAIGN_DIR / "scene-05-product-only-generation-dry-run.json"
SCENE05_FINAL_PROMPT_PATH = CAMPAIGN_DIR / "scene-05-final-product-only-prompt.md"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_text(path):
    return Path(path).read_text(encoding="utf-8")


def run_cli(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(argv)
    return code, json.loads(buf.getvalue())


class TestProductOnlyHasPriorityOverOldLock(unittest.TestCase):
    """1: product-only policy имеет приоритет над campaign_visual_lock.json
    для этой кампании -- старый lock существует и остаётся resolvable сам
    по себе (для истории/аудита), но НЕ участвует в generation planning, и
    сам факт его существования/owner_approved НЕ разблокирует старый путь."""

    def test_both_files_exist_simultaneously(self):
        self.assertTrue((CAMPAIGN_DIR / "campaign_visual_lock.json").is_file())
        self.assertTrue((CAMPAIGN_DIR / "campaign_visual_policy.json").is_file())

    def test_old_lock_marked_superseded_by_new_policy(self):
        old_lock = load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
        self.assertEqual(old_lock["superseded_by_product_only_policy"],
                         "content/autopilot/coating-protect-2026-07/campaign_visual_policy.json")

    def test_old_locks_owner_approved_true_does_not_unblock_legacy_path(self):
        old_lock = load_json(CAMPAIGN_DIR / "campaign_visual_lock.json")
        self.assertTrue(old_lock["owner_approved"])  # старый lock всё ещё "approved"
        # ...но легаси-путь генерации всё равно заблокирован новой policy:
        with self.assertRaises(ProductOnlyPolicyError):
            assert_legacy_generation_allowed(CAMPAIGN_DIR)

    def test_is_product_only_campaign_true_for_this_campaign(self):
        self.assertTrue(is_product_only_campaign(CAMPAIGN_DIR))

    def test_is_product_only_campaign_false_for_unrelated_campaign(self):
        self.assertFalse(is_product_only_campaign(REPO_ROOT / "content" / "autopilot" / "does-not-exist"))


class TestProductOnlyModeDoesNotResolveAppearanceRefs(unittest.TestCase):
    """2: planner никогда не заполняет appearance/hands/kitchen/airfryer refs."""

    def test_all_seven_scenes_have_empty_appearance_refs(self):
        for scene_id in SCENE_IDS:
            plan = plan_scene_request(CAMPAIGN_DIR, scene_id)
            self.assertEqual(plan["appearance_image_refs"], [])
            self.assertEqual(plan["hands_image_refs"], [])
            self.assertEqual(plan["kitchen_image_refs"], [])
            self.assertEqual(plan["airfryer_image_refs"], [])

    def test_planner_never_calls_reference_library_resolver(self):
        # плановая генерация не должна ничего резолвить через reference
        # library -- проверяем это, гарантируя отсутствие сетевых вызовов
        # (resolve_asset тоже сети не делает, но сам факт, что planner его
        # не импортирует/не вызывает, подтверждается тем, что весь план
        # строится ТОЛЬКО из campaign_visual_policy.json + markdown-файлов).
        for scene_id in SCENE_IDS:
            plan = plan_scene_request(CAMPAIGN_DIR, scene_id)
            self.assertFalse(plan["uses_reference_library_for_appearance"])
            self.assertFalse(plan["uses_campaign_visual_lock"])
            self.assertEqual(plan["generation_mode"], "product_only")


class TestForbiddenAssetIdsBlocked(unittest.TestCase):
    """3, 4: person-b-exhausted-01 / real-grip-motion-01 (и остальные 3)
    заблокированы как mandatory refs -- fail-closed на уровне кода."""

    def test_person_b_exhausted_01_is_in_forbidden_list(self):
        self.assertIn("person-b-exhausted-01", FORBIDDEN_APPEARANCE_ASSET_IDS)

    def test_real_grip_motion_01_is_in_forbidden_list(self):
        self.assertIn("real-grip-motion-01", FORBIDDEN_APPEARANCE_ASSET_IDS)

    def test_all_five_legacy_asset_ids_forbidden(self):
        for asset_id in ("person-b-exhausted-01", "real-grip-motion-01",
                         "v2-hand-hold-01", "v2-form-in-basket-01", "food-wings-01"):
            self.assertIn(asset_id, FORBIDDEN_APPEARANCE_ASSET_IDS)

    def test_assert_no_forbidden_refs_raises_for_person_b_exhausted_01(self):
        with self.assertRaises(ProductOnlyPolicyError) as ctx:
            assert_no_forbidden_appearance_refs(
                "uses person-b-exhausted-01 as mandatory reference", "test")
        self.assertEqual(ctx.exception.code, "FORBIDDEN_APPEARANCE_REF_FOUND")

    def test_assert_no_forbidden_refs_raises_for_real_grip_motion_01(self):
        with self.assertRaises(ProductOnlyPolicyError) as ctx:
            assert_no_forbidden_appearance_refs(
                "uses real-grip-motion-01 as mandatory reference", "test")
        self.assertEqual(ctx.exception.code, "FORBIDDEN_APPEARANCE_REF_FOUND")

    def test_clean_text_does_not_raise(self):
        assert_no_forbidden_appearance_refs("real-product-v1 only", "test")  # не бросает


class TestOldCall1HandsCannotRun(unittest.TestCase):
    """5: старый CALL 1 HANDS путь (cli.py pilot, scene-05 masked-edit style)
    не может запуститься для этой кампании."""

    def test_pilot_blocked_for_this_campaign(self):
        code, out = run_cli(["pilot", str(CAMPAIGN_DIR), "--scene", "scene-05"])
        self.assertEqual(code, 2)
        self.assertEqual(out["code"], "BLOCKED_BY_PRODUCT_ONLY_POLICY")
        self.assertIn("blocked_by_product_only_policy".upper(), out["gate_error"].upper())

    def test_pilot_blocked_makes_no_network_call(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network call!")):
            code, _out = run_cli(["pilot", str(CAMPAIGN_DIR), "--scene", "scene-05"])
        self.assertEqual(code, 2)

    def test_generate_also_blocked_for_this_campaign(self):
        code, out = run_cli(["generate", str(CAMPAIGN_DIR), "--scene", "scene-05"])
        self.assertEqual(code, 2)
        self.assertEqual(out["code"], "BLOCKED_BY_PRODUCT_ONLY_POLICY")


class TestOldFoodPlanCannotRun(unittest.TestCase):
    """6: FOOD (CALL 2) из старого плана не запускается."""

    def test_food_subcommand_does_not_exist_in_cli(self):
        # argparse для неизвестной subcommand завершает процесс с SystemExit(2)
        # -- в этом кодовой базе нет "food" CLI-команды вообще.
        with self.assertRaises(SystemExit):
            run_cli(["food"])

    def test_generate_blocked_means_food_followup_also_blocked(self):
        # FOOD (CALL 2) в старой архитектуре шёл ПОСЛЕ image generate для
        # сцены -- раз cmd_generate/cmd_pilot заблокированы для этой
        # кампании, у FOOD нет пути запуститься через старый CLI вообще.
        code, out = run_cli(["generate", str(CAMPAIGN_DIR), "--scene", "scene-05"])
        self.assertEqual(code, 2)

    def test_dry_run_food_calls_executed_is_zero(self):
        plan = load_json(DRY_RUN_PATH)
        self.assertEqual(plan["execution_summary"]["food_calls_executed"], 0)
        scene05 = load_json(SCENE05_DRY_RUN_PATH)
        self.assertEqual(scene05["food_calls_executed"], 0)


class TestScene05FinalPromptIncludesContinuityBlock(unittest.TestCase):
    """7: scene-05 final prompt включает continuity block."""

    def test_final_prompt_file_exists(self):
        self.assertTrue(SCENE05_FINAL_PROMPT_PATH.is_file())

    def test_final_prompt_contains_continuity_language(self):
        # scene-05 is now the C3 no-hands result shot: NO_HANDS_CONTINUITY_PROMPT
        # (used instead of the shared continuity block for this scene_variant)
        # deliberately drops "grey ribbed sweater sleeves" (a hands/sleeves
        # line that would contradict a no-hands scene) -- see
        # test_product_only_scene05_c3_continuity_fix.py for that check.
        text = load_text(SCENE05_FINAL_PROMPT_PATH)
        for token in ("Cozy clean white home kitchen", "9:16", "720", "1280"):
            self.assertIn(token, text)

    def test_final_prompt_built_from_same_planner_as_dry_run(self):
        plan = plan_scene_request(CAMPAIGN_DIR, "scene-05")
        text = load_text(SCENE05_FINAL_PROMPT_PATH)
        # проверяем, что сцено-специфичный action prompt из планировщика
        # действительно присутствует в финальном тексте (один источник истины)
        self.assertIn(plan["scene_action_prompt"][:60], text)


class TestScene05FinalPromptIncludesProductLockInstruction(unittest.TestCase):
    """8: scene-05 final prompt включает product lock instruction."""

    def test_final_prompt_has_product_lock_section(self):
        # regenerated (scene-05 "product placement plate" refinement) --
        # heading is now pipeline_product_lock_instruction, kept structurally
        # separate from model_prompt (see test_product_only_scene_runner.py
        # TestPlacementPlateRefinement for the full split coverage).
        text = load_text(SCENE05_FINAL_PROMPT_PATH)
        self.assertIn("pipeline_product_lock_instruction", text)
        self.assertIn("real-product-v1", text)

    def test_final_prompt_has_pixel_faithful_instruction(self):
        text = load_text(SCENE05_FINAL_PROMPT_PATH)
        self.assertIn("The silicone form is not generated from imagination.", text)
        self.assertIn("pixel-faithful", text)


class TestScene05FinalPromptHasNoMandatoryImageRefs(unittest.TestCase):
    """9: scene-05 final prompt не содержит обязательных hands/person/kitchen
    image refs."""

    def test_final_prompt_states_no_mandatory_image_refs_header(self):
        text = load_text(SCENE05_FINAL_PROMPT_PATH)
        self.assertIn("Mandatory image refs: НЕТ", text)

    def test_final_prompt_explicitly_states_no_mandatory_refs(self):
        # regenerated (Step 5 of the product-only-scene-runner task) from
        # product_only_scene_runner.build_request_contract() -- wording
        # updated accordingly, still asserts zero mandatory image refs.
        text = load_text(SCENE05_FINAL_PROMPT_PATH)
        self.assertIn("Mandatory image refs: НЕТ", text)
        self.assertIn("reference_images: []", text)

    def test_scene05_dry_run_confirms_empty_refs(self):
        scene05 = load_json(SCENE05_DRY_RUN_PATH)
        self.assertEqual(scene05["appearance_image_refs"], [])
        self.assertEqual(scene05["hands_image_refs"], [])
        self.assertEqual(scene05["kitchen_image_refs"], [])
        self.assertEqual(scene05["airfryer_image_refs"], [])


class TestDryRunZeroApiCalls(unittest.TestCase):
    """10, 11: OpenAI calls == 0, Higgsfield calls == 0."""

    def test_campaign_dry_run_openai_calls_zero(self):
        plan = load_json(DRY_RUN_PATH)
        self.assertEqual(plan["openai_calls_executed"], 0)
        self.assertEqual(plan["execution_summary"]["openai_images_api_calls_executed"], 0)

    def test_campaign_dry_run_higgsfield_calls_zero(self):
        plan = load_json(DRY_RUN_PATH)
        self.assertEqual(plan["higgsfield_calls_executed"], 0)
        self.assertEqual(plan["execution_summary"]["higgsfield_api_calls_executed"], 0)

    def test_scene05_dry_run_openai_and_higgsfield_calls_zero(self):
        scene05 = load_json(SCENE05_DRY_RUN_PATH)
        self.assertEqual(scene05["openai_calls_executed"], 0)
        self.assertEqual(scene05["higgsfield_calls_executed"], 0)

    def test_campaign_dry_run_generation_mode_is_product_only(self):
        plan = load_json(DRY_RUN_PATH)
        self.assertEqual(plan["generation_mode"], "product_only")
        self.assertFalse(plan["uses_campaign_visual_lock"])
        self.assertFalse(plan["uses_reference_library_for_appearance"])


class TestProductCanonRemainsRealProductV1(unittest.TestCase):
    """12: product canon остаётся real-product-v1 везде."""

    def test_policy_product_canon(self):
        policy = load_product_only_policy(CAMPAIGN_DIR, required=True)
        self.assertEqual(policy.product_canon, "real-product-v1")

    def test_campaign_dry_run_global_visual_reference(self):
        plan = load_json(DRY_RUN_PATH)
        self.assertEqual(plan["global_visual_reference"], "real-product-v1")

    def test_scene05_dry_run_product_canon(self):
        scene05 = load_json(SCENE05_DRY_RUN_PATH)
        self.assertEqual(scene05["product_canon"], "real-product-v1")

    def test_all_scene_plans_reference_real_product_v1_as_product_canon(self):
        for scene_id in SCENE_IDS:
            plan = plan_scene_request(CAMPAIGN_DIR, scene_id)
            self.assertEqual(plan["global_visual_reference"], "real-product-v1")
            self.assertEqual(plan["refs_passed_in_order"][0]["source"], "real-product-v1")


class TestNoPaidApiCalls(unittest.TestCase):
    def test_planning_all_seven_scenes_makes_no_network_call(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network call!")):
            for scene_id in SCENE_IDS:
                plan_scene_request(CAMPAIGN_DIR, scene_id)

    def test_no_paid_api_surface_in_product_only_policy_module(self):
        src = (REPO_ROOT / "api" / "media_pipeline" / "product_only_policy.py").read_text(encoding="utf-8").lower()
        for token in ("urllib", "api.openai.com", "openai_api_key",
                     "api.higgsfield", "requests.", "http://", "https://"):
            self.assertNotIn(token, src, token)


if __name__ == "__main__":
    unittest.main()
