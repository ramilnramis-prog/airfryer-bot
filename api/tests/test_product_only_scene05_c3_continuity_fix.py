"""Тесты фикса C3 continuity (scene-05 no-hands result shot).

Первый C3 draft отправлял в модель ОБЩИЙ continuity-текст, который
позитивно описывает руки/рукава ("Same woman's natural hands throughout...
Same grey ribbed sweater sleeves visible at the wrists"), а затем
сцено-специфичный текст пытался это "отменить" фразой вида "this shot
contains no hands... this overrides the earlier mention of hands/sleeves
above". Для no-hands сцены это противоречивый prompt: позитивная инструкция
про руки, сразу следом — её отрицание.

Fix: build_model_prompt() (api.media_pipeline.product_only_scene_runner)
теперь подставляет NO_HANDS_CONTINUITY_PROMPT (тот же continuity-текст без
строк про руки/рукава) ВМЕСТО plan['clean_continuity_prompt'], когда
plan['scene_variant'] == 'no_hands_result_shot' -- никакой позитивной
инструкции про руки/рукава в финальном model_prompt больше нет, поэтому
сцено-специфичный текст ничего не "отменяет".

Покрытие (15 пунктов, запрошенных явно):
1. C3 model_prompt does NOT contain "Same woman's natural hands"
2. C3 model_prompt does NOT contain "grey ribbed sweater sleeves"
3. C3 model_prompt does NOT contain "wrists"
4. C3 model_prompt does NOT contain "thumbs"
5. C3 model_prompt does NOT contain "lifting"
6. C3 model_prompt does NOT contain "overrides"
7. C3 model_prompt contains "No hands"
8. C3 model_prompt contains "no arms"
9. C3 model_prompt contains "no fingers"
10. C3 model_prompt contains "no person"
11. C3 dry-run has no_hands_prompt == true
12. C3 dry-run has front_hand_extraction == not_needed
13. C3 dry-run has hands_grip_qa == not_applicable
14. OpenAI calls = 0
15. Higgsfield calls = 0
"""
import json
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline import product_only_scene_runner as runner

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = REPO_ROOT / "content" / "autopilot" / "coating-protect-2026-07"
SCENE_ID = "scene-05"

C3_DRY_RUN_PATH = CAMPAIGN_DIR / "scene-05-product-only-apply-dry-run-c3.json"
ACTIVE_DRY_RUN_PATH = CAMPAIGN_DIR / "scene-05-product-only-apply-dry-run.json"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def urlopen_raises():
    return mock.patch("urllib.request.urlopen",
                      side_effect=AssertionError("network call!"))


def live_model_prompt():
    _req, contract, _plan = runner.build_request_contract(str(CAMPAIGN_DIR), SCENE_ID)
    return contract.model_prompt


class Test1NoSameWomanNaturalHands(unittest.TestCase):
    def test_model_prompt_does_not_contain_same_womans_natural_hands(self):
        self.assertNotIn("Same woman's natural hands", live_model_prompt())

    def test_no_hands_continuity_constant_does_not_contain_it_either(self):
        self.assertNotIn("Same woman's natural hands", runner.NO_HANDS_CONTINUITY_PROMPT)


class Test2NoGreyRibbedSweaterSleeves(unittest.TestCase):
    def test_model_prompt_does_not_contain_grey_ribbed_sweater_sleeves(self):
        self.assertNotIn("grey ribbed sweater sleeves", live_model_prompt())

    def test_no_hands_continuity_constant_does_not_contain_it_either(self):
        self.assertNotIn("grey ribbed sweater sleeves", runner.NO_HANDS_CONTINUITY_PROMPT)


class Test3NoWrists(unittest.TestCase):
    def test_model_prompt_does_not_contain_wrists(self):
        self.assertNotIn("wrists", live_model_prompt())


class Test4NoThumbs(unittest.TestCase):
    def test_model_prompt_does_not_contain_thumbs(self):
        self.assertNotIn("thumbs", live_model_prompt())


class Test5NoLifting(unittest.TestCase):
    def test_model_prompt_does_not_contain_lifting(self):
        self.assertNotIn("lifting", live_model_prompt())


class Test6NoOverrides(unittest.TestCase):
    def test_model_prompt_does_not_contain_overrides(self):
        self.assertNotIn("overrides", live_model_prompt())
        self.assertNotIn("override", live_model_prompt())


class Test7ContainsNoHands(unittest.TestCase):
    def test_model_prompt_contains_no_hands(self):
        self.assertIn("No hands", live_model_prompt())


class Test8ContainsNoArms(unittest.TestCase):
    def test_model_prompt_contains_no_arms(self):
        self.assertIn("no arms", live_model_prompt())


class Test9ContainsNoFingers(unittest.TestCase):
    def test_model_prompt_contains_no_fingers(self):
        self.assertIn("no fingers", live_model_prompt())


class Test10ContainsNoPerson(unittest.TestCase):
    def test_model_prompt_contains_no_person(self):
        self.assertIn("no person", live_model_prompt())


class Test11NoHandsPromptFlagTrue(unittest.TestCase):
    def test_c3_dry_run_no_hands_prompt_true(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertIs(d["no_hands_prompt"], True)

    def test_active_dry_run_no_hands_prompt_true(self):
        d = load_json(ACTIVE_DRY_RUN_PATH)
        self.assertIs(d["no_hands_prompt"], True)


class Test12FrontHandExtractionNotNeeded(unittest.TestCase):
    def test_c3_dry_run_front_hand_extraction(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["front_hand_extraction"], "not_needed")

    def test_active_dry_run_front_hand_extraction(self):
        d = load_json(ACTIVE_DRY_RUN_PATH)
        self.assertEqual(d["front_hand_extraction"], "not_needed")


class Test13HandsGripQaNotApplicable(unittest.TestCase):
    def test_c3_dry_run_hands_grip_qa(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["hands_grip_qa"], "not_applicable")

    def test_active_dry_run_hands_grip_qa(self):
        d = load_json(ACTIVE_DRY_RUN_PATH)
        self.assertEqual(d["hands_grip_qa"], "not_applicable")


class Test14OpenAICallsZero(unittest.TestCase):
    def test_dry_run_report_openai_calls_zero(self):
        with urlopen_raises():
            report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["openai_calls_executed"], 0)

    def test_c3_dry_run_doc_openai_calls_zero(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["openai_calls_executed"], 0)
        self.assertEqual(d["api_spend_usd"], 0)


class Test15HiggsfieldCallsZero(unittest.TestCase):
    def test_dry_run_report_higgsfield_calls_zero(self):
        with urlopen_raises():
            report = runner.run_product_only_scene(str(CAMPAIGN_DIR), SCENE_ID, apply=False)
        self.assertEqual(report["higgsfield_calls_executed"], 0)

    def test_c3_dry_run_doc_higgsfield_calls_zero(self):
        d = load_json(C3_DRY_RUN_PATH)
        self.assertEqual(d["higgsfield_calls_executed"], 0)


class TestContradictionFullyRemoved(unittest.TestCase):
    """End-to-end: the exact contradiction reported by the owner no longer
    exists anywhere in the live model_prompt sent to the API."""

    def test_prompt_has_no_positive_hand_person_sleeve_instruction_at_all(self):
        prompt = live_model_prompt()
        banned = ("Same woman's natural hands", "grey ribbed sweater sleeves",
                 "wrists", "thumbs", "lifting", "overrides", "override")
        for term in banned:
            self.assertNotIn(term, prompt, f"found banned term: {term!r}")

    def test_prompt_still_has_required_no_hands_language(self):
        prompt = live_model_prompt()
        for term in ("No hands", "no arms", "no fingers", "no person"):
            self.assertIn(term, prompt)

    def test_scene_variant_drives_continuity_selection(self):
        from api.media_pipeline import product_only_policy
        plan = product_only_policy.plan_scene_request(str(CAMPAIGN_DIR), SCENE_ID)
        self.assertEqual(plan["scene_variant"], "no_hands_result_shot")


if __name__ == "__main__":
    unittest.main()
