"""Тесты стратегического пивота: product-only visual reference policy.

После scene-05-hands-experiment-retrospective.md (CALL 1 HANDS V1-V4
rejected) кампания отказывается от reference-based image lock для
рук/персонажа/кухни и переходит на единственный обязательный image lock —
real-product-v1, с continuity рук/персонажа/кухни/одежды/света через
текстовый блок (video-continuity-block.md), общий для всех сцен и хуков
одного видео.

Покрытие (11 пунктов, запрошенных явно):
1. campaign_visual_policy.json существует
2. policy_version == product-only-v1
3. единственный global_visual_reference == real-product-v1
4. hands/person/kitchen/airfryer НЕ image_locked
5. continuity_source == text_prompt_block
6. hooks A/B/C используют один continuity block
7. scene prompts содержат product_lock_instruction
8. scene prompts НЕ ссылаются на старые hands/person image refs как
   обязательные
9. generation dry-run: openai_calls == 0
10. FOOD не запускается на этом этапе
11. product-lock QA rules присутствуют
плюс: никаких платных API-вызовов при выполнении самих тестов.
"""
import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"

POLICY_PATH = CAMPAIGN_DIR / "campaign_visual_policy.json"
SCENE05_PLAN_PATH = CAMPAIGN_DIR / "scene-05-product-only-plan.json"
DRY_RUN_PATH = CAMPAIGN_DIR / "product-only-generation-dry-run.json"
CONTINUITY_PATH = CAMPAIGN_DIR / "video-continuity-block.md"
SCENE_PROMPTS_PATH = CAMPAIGN_DIR / "video-scene-prompts-product-only.md"
RETROSPECTIVE_PATH = CAMPAIGN_DIR / "scene-05-hands-experiment-retrospective.md"
OLD_LOCK_PATH = CAMPAIGN_DIR / "campaign_visual_lock.json"

OLD_HANDS_ASSET_IDS = ["person-b-exhausted-01", "real-grip-motion-01", "v2-hand-hold-01"]

SCENE_IDS = [f"scene-{i:02d}" for i in range(1, 8)]


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_text(path):
    return Path(path).read_text(encoding="utf-8")


class TestPolicyFileExistsAndVersion(unittest.TestCase):
    """1, 2: campaign_visual_policy.json существует, policy_version корректен."""

    def test_policy_file_exists(self):
        self.assertTrue(POLICY_PATH.is_file(), f"не найден {POLICY_PATH}")

    def test_policy_version_is_product_only_v1(self):
        policy = load_json(POLICY_PATH)
        self.assertEqual(policy["policy_version"], "product-only-v1")

    def test_policy_is_valid_json(self):
        load_json(POLICY_PATH)  # не бросает исключение


class TestSingleGlobalVisualReference(unittest.TestCase):
    """3: единственный global_visual_reference — real-product-v1."""

    def test_global_visual_reference_is_real_product_v1(self):
        policy = load_json(POLICY_PATH)
        self.assertEqual(policy["global_visual_reference"]["product_canon"], "real-product-v1")

    def test_global_visual_reference_manifest_matches_active_canon(self):
        policy = load_json(POLICY_PATH)
        manifest = load_json(REPO_ROOT / policy["global_visual_reference"]["product_manifest"])
        self.assertEqual(manifest["canonical_version"], "real-product-v1")
        self.assertEqual(manifest["canonical_status"], "active")

    def test_must_preserve_covers_handle_and_material_geometry(self):
        policy = load_json(POLICY_PATH)
        preserve = policy["global_visual_reference"]["must_preserve"]
        for token in ("flat_corner_handle_tabs", "short_horizontal_handle_slots",
                     "matte_dark_grey_silicone", "ribbed_bottom", "silhouette"):
            self.assertIn(token, preserve)


class TestHandsPersonKitchenAirfryerNotImageLocked(unittest.TestCase):
    """4: hands/person/kitchen/airfryer НЕ являются image_locked."""

    def test_not_image_locked_list_covers_required_categories(self):
        policy = load_json(POLICY_PATH)
        not_locked = policy["not_image_locked"]
        for category in ("hands", "person", "kitchen", "airfryer", "clothing", "lighting"):
            self.assertIn(category, not_locked)

    def test_product_is_not_in_not_image_locked_list(self):
        policy = load_json(POLICY_PATH)
        self.assertNotIn("product", policy["not_image_locked"])
        self.assertNotIn("real-product-v1", policy["not_image_locked"])


class TestContinuitySourceIsText(unittest.TestCase):
    """5: continuity_source == text_prompt_block."""

    def test_continuity_source_is_text_prompt_block(self):
        policy = load_json(POLICY_PATH)
        self.assertEqual(policy["continuity_source"], "text_prompt_block")

    def test_continuity_block_file_exists(self):
        policy = load_json(POLICY_PATH)
        self.assertTrue((REPO_ROOT / policy["continuity_block_file"]).is_file())

    def test_continuity_block_describes_hands_kitchen_lighting_camera(self):
        text = load_text(CONTINUITY_PATH)
        for token in ("kitchen", "hands", "daylight", "9:16", "sweater"):
            self.assertIn(token, text)


class TestHooksShareOneContinuityBlock(unittest.TestCase):
    """6: hooks A/B/C используют один и тот же continuity block."""

    def test_policy_marks_shared_across_hooks(self):
        policy = load_json(POLICY_PATH)
        self.assertTrue(policy["shared_across_hooks"])
        self.assertTrue(policy["shared_across_scenes_in_this_video"])

    def test_hook_openers_section_lists_exactly_three_variants(self):
        text = load_text(SCENE_PROMPTS_PATH)
        section = text.split("## hook_openers", 1)[1]
        for code in ("**A**", "**B**", "**C**"):
            self.assertIn(code, section)

    def test_hook_openers_do_not_redefine_continuity_per_variant(self):
        text = load_text(SCENE_PROMPTS_PATH)
        section = text.split("## hook_openers", 1)[1]
        self.assertIn("общие для всех трёх", section)

    def test_every_scene_references_the_same_continuity_block_file(self):
        text = load_text(SCENE_PROMPTS_PATH)
        occurrences = text.count("continuity_block_ref**: video-continuity-block.md")
        self.assertEqual(occurrences, len(SCENE_IDS))


class TestScenePromptsHaveProductLockInstruction(unittest.TestCase):
    """7: scene prompts содержат product_lock_instruction (для каждой из 7 сцен)."""

    def test_all_seven_scenes_present(self):
        text = load_text(SCENE_PROMPTS_PATH)
        for scene_id in SCENE_IDS:
            self.assertIn(f"## {scene_id}", text)

    def test_all_seven_scenes_have_product_lock_instruction_field(self):
        text = load_text(SCENE_PROMPTS_PATH)
        sections = re.split(r"\n## (scene-\d\d)\n", text)[1:]
        scene_bodies = dict(zip(sections[0::2], sections[1::2]))
        self.assertEqual(set(scene_bodies), set(SCENE_IDS))
        for scene_id, body in scene_bodies.items():
            self.assertIn("product_lock_instruction", body, f"{scene_id} missing product_lock_instruction")

    def test_product_bearing_scenes_require_real_product_v1_in_instruction(self):
        text = load_text(SCENE_PROMPTS_PATH)
        sections = re.split(r"\n## (scene-\d\d)\n", text)[1:]
        scene_bodies = dict(zip(sections[0::2], sections[1::2]))
        for scene_id in ("scene-03", "scene-04", "scene-05", "scene-07"):
            self.assertIn("real-product-v1", scene_bodies[scene_id])


class TestOldHandsReferencesNotRequired(unittest.TestCase):
    """8: scene prompts НЕ ссылаются на старые hands/person image refs как
    обязательные."""

    def test_scene_prompts_file_does_not_mention_old_hands_asset_ids(self):
        text = load_text(SCENE_PROMPTS_PATH)
        for asset_id in OLD_HANDS_ASSET_IDS:
            self.assertNotIn(asset_id, text)

    def test_scene05_plan_explicitly_excludes_old_hands_asset_ids(self):
        plan = load_json(SCENE05_PLAN_PATH)
        excluded = plan["not_used"]["excluded_asset_ids"]
        for asset_id in OLD_HANDS_ASSET_IDS:
            self.assertIn(asset_id, excluded)

    def test_scene05_plan_does_not_list_old_refs_as_inputs(self):
        plan = load_json(SCENE05_PLAN_PATH)
        inputs_str = json.dumps(plan["inputs"])
        for asset_id in OLD_HANDS_ASSET_IDS:
            self.assertNotIn(asset_id, inputs_str)


class TestGenerationDryRunZeroApiCalls(unittest.TestCase):
    """9: generation dry-run имеет openai_calls == 0."""

    def test_dry_run_file_exists_and_is_dry_run_status(self):
        plan = load_json(DRY_RUN_PATH)
        self.assertEqual(plan["status"], "dry_run_only")

    def test_openai_calls_executed_is_zero(self):
        plan = load_json(DRY_RUN_PATH)
        self.assertEqual(plan["execution_summary"]["openai_images_api_calls_executed"], 0)
        self.assertEqual(plan["openai_calls"], 0)

    def test_higgsfield_calls_executed_is_zero(self):
        plan = load_json(DRY_RUN_PATH)
        self.assertEqual(plan["execution_summary"]["higgsfield_api_calls_executed"], 0)
        self.assertEqual(plan["higgsfield_calls"], 0)

    def test_api_spend_is_zero(self):
        plan = load_json(DRY_RUN_PATH)
        self.assertEqual(plan["execution_summary"]["api_spend_usd_executed"], 0)
        self.assertEqual(plan["api_spend_usd"], 0)


class TestFoodNotRunAtThisStage(unittest.TestCase):
    """10: FOOD не запускается на этом этапе."""

    def test_food_calls_executed_is_zero(self):
        plan = load_json(DRY_RUN_PATH)
        self.assertEqual(plan["execution_summary"]["food_calls_executed"], 0)
        self.assertEqual(plan["food_calls"], 0)

    def test_food_status_is_blocked(self):
        plan = load_json(DRY_RUN_PATH)
        self.assertIn("BLOCKED", plan["food_status"])


class TestProductLockQaRulesPresent(unittest.TestCase):
    """11: product-lock QA rules присутствуют."""

    def test_dry_run_lists_product_lock_validator_checks(self):
        plan = load_json(DRY_RUN_PATH)
        checks = plan["product_lock_qa"]["checks"]
        for check in ("silhouette", "handle_geometry", "aspect_ratio",
                     "pixel_similarity", "no_local_warp"):
            self.assertIn(check, checks)

    def test_dry_run_reject_conditions_cover_geometry_and_colour(self):
        plan = load_json(DRY_RUN_PATH)
        joined = " ".join(plan["product_lock_qa"]["reject_if"])
        self.assertIn("handle_geometry_mismatch", joined)
        self.assertIn("warp", joined.lower())

    def test_scene05_plan_has_matching_qa_reject_conditions(self):
        plan = load_json(SCENE05_PLAN_PATH)
        self.assertGreater(len(plan["qa_reject_conditions"]), 0)
        joined = " ".join(plan["qa_reject_conditions"])
        self.assertIn("3", joined)  # ровно 3 бёдрышка


class TestOldLockMarkedSupersededButNotDeleted(unittest.TestCase):
    """Явное требование ТЗ: не удалять старые файлы, пометить superseded."""

    def test_old_campaign_visual_lock_still_exists(self):
        self.assertTrue(OLD_LOCK_PATH.is_file())

    def test_old_lock_marked_superseded(self):
        lock = load_json(OLD_LOCK_PATH)
        self.assertIn("superseded_by_product_only_policy", lock)
        self.assertEqual(lock["superseded_by_product_only_policy"],
                         "content/autopilot/coating-protect-2026-07/campaign_visual_policy.json")

    def test_old_lock_status_field_untouched_for_backward_compatibility(self):
        # существующие тесты (test_visual_lock_set_a_activation) ожидают
        # status == "active" -- пивот не должен его менять.
        lock = load_json(OLD_LOCK_PATH)
        self.assertEqual(lock["status"], "active")

    def test_old_lock_still_resolves_product_canon_repository_only(self):
        lock = load_json(OLD_LOCK_PATH)
        self.assertEqual(lock["product_canon_resolution"], "repository_only")


class TestRetrospectiveDocumentsRejection(unittest.TestCase):
    def test_retrospective_file_exists(self):
        self.assertTrue(RETROSPECTIVE_PATH.is_file())

    def test_retrospective_mentions_all_four_versions(self):
        text = load_text(RETROSPECTIVE_PATH)
        for v in ("V1", "V2", "V3", "V4"):
            self.assertIn(v, text)

    def test_retrospective_confirms_food_and_higgsfield_never_ran(self):
        text = load_text(RETROSPECTIVE_PATH)
        self.assertIn("FOOD", text)
        self.assertIn("Higgsfield", text)
        self.assertIn("не запускался", text)


class TestNoPaidApiCalls(unittest.TestCase):
    def test_loading_all_new_policy_files_makes_no_network_call(self):
        with mock_urlopen_raises():
            load_json(POLICY_PATH)
            load_json(SCENE05_PLAN_PATH)
            load_json(DRY_RUN_PATH)
            load_text(CONTINUITY_PATH)
            load_text(SCENE_PROMPTS_PATH)

    def test_no_paid_api_tokens_in_new_json_files(self):
        # словосочетание "higgsfield" ожидаемо встречается в полях вида
        # higgsfield_status/higgsfield_calls (документируют, что НЕ
        # запускалось) -- проверяем отсутствие настоящих секретов/хостов,
        # а не самого слова.
        for path in (POLICY_PATH, SCENE05_PLAN_PATH, DRY_RUN_PATH):
            src = load_text(path).lower()
            for token in ("openai_api_key", "api.openai.com", "api.higgsfield",
                         "sk-proj-", "sk-"):
                self.assertNotIn(token, src)


def mock_urlopen_raises():
    from unittest import mock
    return mock.patch("urllib.request.urlopen",
                      side_effect=AssertionError("network call!"))


if __name__ == "__main__":
    unittest.main()
