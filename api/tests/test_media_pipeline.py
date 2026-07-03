"""Тесты визуального конвейера (api/media_pipeline) на mock-провайдере.

Проверяемые сценарии (по заданию):
- создание трёх кандидатов;
- отклонение кандидата с четырьмя ручками;
- отклонение другого аэрогриля;
- отклонение мужских рук;
- выбор единственного подходящего кандидата;
- отказ выбрать победителя, если все три плохие;
- формирование regeneration brief;
- sequence rejection для скачка между сценами;
- запрет Higgsfield до sequence approval (и без владельца);
- запрет реального API-вызова без --apply (сети нет вообще);
- бюджет и отсутствие секретов в выводе.
"""
import json
import os
import unittest
from unittest import mock

from api.media_pipeline.models import (CandidateObservation, ImageRequest,
                                       SceneSpec)
from api.media_pipeline.mock_provider import MockImageProvider
from api.media_pipeline.openai_images_client import (BudgetExceededError,
                                                     MissingAPIKeyError,
                                                     OpenAIImagesProvider)
from api.media_pipeline.pipeline import (PipelineGateError, higgsfield_gate,
                                         produce_scene)
from api.media_pipeline.visual_qa import (DIMENSIONS, evaluate_candidate,
                                          select_winner)
from api.media_pipeline.sequence_qa import check_sequence


def good_scores(value=90):
    return {d: value for d in DIMENSIONS}


def obs(cid, **overrides):
    base = dict(candidate_id=cid, scores=good_scores())
    base.update(overrides)
    return CandidateObservation.from_dict(base)


SPEC = SceneSpec(
    scene_id="scene-05", title="Доставание формы",
    prompt_action="woman lifts the liner by its two oval handles",
    required_references=[],
    exact_food_count={"item": "chicken thigh", "count": 3},
    animation_intent="подъём формы + пар",
)


class TestVisualQA(unittest.TestCase):
    def test_reject_four_handles(self):
        v = evaluate_candidate(obs("c1", handle_count=4), SPEC)
        self.assertFalse(v.passed)
        self.assertIn("handle_count", v.hard_fails)

    def test_reject_different_airfryer(self):
        v = evaluate_candidate(obs("c1", airfryer_matches_reference=False), SPEC)
        self.assertFalse(v.passed)
        self.assertIn("airfryer_mismatch", v.hard_fails)

    def test_reject_male_hands(self):
        v = evaluate_candidate(obs("c1", hands_gender="male"), SPEC)
        self.assertFalse(v.passed)
        self.assertIn("hands_male", v.hard_fails)

    def test_reject_wrong_food_count(self):
        v = evaluate_candidate(obs("c1", food_count_actual=4), SPEC)
        self.assertIn("food_count_changed", v.hard_fails)

    def test_reject_text_watermark_and_cgi(self):
        v = evaluate_candidate(
            obs("c1", has_text_or_watermark=True, looks_cgi=True), SPEC)
        self.assertIn("text_watermark", v.hard_fails)
        self.assertIn("cgi_look", v.hard_fails)

    def test_reject_below_threshold_scores(self):
        scores = good_scores()
        scores["hand_anatomy"] = 60  # ниже минимума 70
        v = evaluate_candidate(obs("c1", scores=scores,
                                   food_count_actual=3), SPEC)
        self.assertFalse(v.passed)
        self.assertFalse(v.hard_fails)

    def test_select_single_passing_candidate(self):
        cands = [
            obs("c1", handle_count=4),
            obs("c2", food_count_actual=3),          # единственный проходящий
            obs("c3", hands_gender="male"),
        ]
        d = select_winner("scene-05", cands, SPEC)
        self.assertEqual(d.winner_id, "c2")
        self.assertEqual(set(d.rejection_reasons), {"c1", "c3"})

    def test_exactly_one_winner_among_two_passing(self):
        s_low, s_high = good_scores(85), good_scores(95)
        cands = [obs("c1", scores=s_low, food_count_actual=3),
                 obs("c2", scores=s_high, food_count_actual=3)]
        d = select_winner("scene-05", cands, SPEC)
        self.assertEqual(d.winner_id, "c2")
        self.assertIn("c1", d.rejection_reasons)

    def test_no_winner_when_all_bad_and_brief_built(self):
        cands = [obs("c1", handle_count=4),
                 obs("c2", airfryer_matches_reference=False),
                 obs("c3", hands_gender="male", hand_anatomy_ok=False)]
        d = select_winner("scene-05", cands, SPEC)
        self.assertIsNone(d.winner_id)
        self.assertIsNotNone(d.regeneration_brief)
        # бриф конкретный: содержит и причины, и инструкции исправления
        self.assertIn("handle_count", d.regeneration_brief)
        self.assertIn("TWO oval cut-out handles", d.regeneration_brief)
        self.assertIn("woman's hands", d.regeneration_brief)


class TestPipelineRounds(unittest.TestCase):
    def _observer(self):
        def observe(result):
            return result.planned_request["mock_observation"]
        return observe

    def test_three_candidates_created(self):
        provider = MockImageProvider(scenario={"scene-05": [[
            dict(food_count_actual=3, scores=good_scores()),
            dict(food_count_actual=3, scores=good_scores(85)),
            dict(food_count_actual=3, scores=good_scores(82)),
        ]]})
        out = produce_scene(provider, SPEC, self._observer(), out_dir=".")
        self.assertEqual(provider.calls[0]["n"], 3)
        self.assertEqual(len(out["records"]), 3)
        self.assertEqual(out["rounds"], 1)
        self.assertIsNotNone(out["decision"]["winner_id"])

    def test_regeneration_loop_then_winner(self):
        provider = MockImageProvider(scenario={"scene-05": [
            [dict(handle_count=4), dict(handle_count=4), dict(looks_cgi=True)],
            [dict(food_count_actual=3, scores=good_scores()),
             dict(handle_count=1), dict(hands_gender="male")],
        ]})
        out = produce_scene(provider, SPEC, self._observer(), out_dir=".")
        self.assertEqual(out["rounds"], 2)
        self.assertIsNotNone(out["decision"]["winner_id"])
        # второй раунд получил regeneration brief в промпт
        self.assertIn("REGENERATION BRIEF", provider.calls[1]["prompt"])

    def test_max_rounds_escalates_to_owner(self):
        bad_round = [dict(handle_count=4)] * 3
        provider = MockImageProvider(
            scenario={"scene-05": [bad_round, bad_round, bad_round]})
        out = produce_scene(provider, SPEC, self._observer(), out_dir=".")
        self.assertEqual(out["rounds"], 3)
        self.assertIsNone(out["decision"]["winner_id"])
        self.assertTrue(out["decision"]["needs_owner"])
        self.assertEqual(len(provider.calls), 3)  # не больше max_rounds


class TestSequenceQA(unittest.TestCase):
    def test_sequence_rejects_jump(self):
        report = check_sequence([
            {"pair": ["scene-04", "scene-05"],
             "jumps": {"food_jump": True},
             "details": {"food_jump": "в кадре 4 три бёдрышка, в кадре 5 четыре"}},
            {"pair": ["scene-05", "scene-06"], "jumps": {}},
        ])
        self.assertFalse(report["approved"])
        ids = [s["scene_id"] for s in report["scenes_to_regenerate"]]
        self.assertEqual(ids, ["scene-05"])
        self.assertIn("бёдрышка", report["scenes_to_regenerate"][0]["reason"])

    def test_sequence_approves_clean(self):
        report = check_sequence([
            {"pair": ["scene-01", "scene-02"], "jumps": {}},
            {"pair": ["scene-02", "scene-03"], "jumps": {"light_jump": False}},
        ])
        self.assertTrue(report["approved"])
        self.assertEqual(report["scenes_to_regenerate"], [])

    def test_unknown_jump_type_rejected(self):
        with self.assertRaises(ValueError):
            check_sequence([{"pair": ["a", "b"], "jumps": {"vibes_jump": True}}])


class TestHiggsfieldGate(unittest.TestCase):
    DECISIONS_OK = [{"scene_id": f"scene-0{i}", "winner_id": f"scene-0{i}-c1"}
                    for i in range(1, 8)]

    def test_blocked_without_sequence_approval(self):
        bad_seq = {"approved": False,
                   "scenes_to_regenerate": [{"scene_id": "scene-05"}]}
        with self.assertRaises(PipelineGateError):
            higgsfield_gate(self.DECISIONS_OK, bad_seq, owner_approved=True)

    def test_blocked_without_sequence_report(self):
        with self.assertRaises(PipelineGateError):
            higgsfield_gate(self.DECISIONS_OK, None, owner_approved=True)

    def test_blocked_without_owner_approval(self):
        ok_seq = {"approved": True, "scenes_to_regenerate": []}
        with self.assertRaises(PipelineGateError):
            higgsfield_gate(self.DECISIONS_OK, ok_seq, owner_approved=False)

    def test_blocked_when_scene_has_no_winner(self):
        decisions = list(self.DECISIONS_OK)
        decisions[2] = {"scene_id": "scene-03", "winner_id": None}
        ok_seq = {"approved": True, "scenes_to_regenerate": []}
        with self.assertRaises(PipelineGateError):
            higgsfield_gate(decisions, ok_seq, owner_approved=True)

    def test_opens_only_with_all_conditions(self):
        ok_seq = {"approved": True, "scenes_to_regenerate": []}
        self.assertTrue(higgsfield_gate(self.DECISIONS_OK, ok_seq,
                                        owner_approved=True))


class TestOpenAIProviderSafety(unittest.TestCase):
    REQ = ImageRequest(scene_id="scene-01", prompt="test prompt", n=3)

    def test_dry_run_makes_no_network_call_and_reads_no_key(self):
        provider = OpenAIImagesProvider()
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network call in dry-run!")):
            with mock.patch.dict(os.environ, {}, clear=True):
                results = provider.generate(self.REQ, out_dir=".", apply=False)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(r.dry_run for r in results))
        self.assertIsNotNone(results[0].planned_request)

    def test_apply_without_env_key_fails_before_network(self):
        provider = OpenAIImagesProvider()
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network before key check!")):
            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(MissingAPIKeyError):
                    provider.generate(self.REQ, out_dir=".", apply=True)

    def test_budget_guard(self):
        provider = OpenAIImagesProvider(budget_usd=0.5)  # 3 x 0.30 > 0.5
        with self.assertRaises(BudgetExceededError):
            provider.generate(self.REQ, out_dir=".", apply=False)

    def test_candidate_limit(self):
        provider = OpenAIImagesProvider()
        big = ImageRequest(scene_id="s", prompt="p", n=10)
        from api.media_pipeline.openai_images_client import MediaPipelineError
        with self.assertRaises(MediaPipelineError):
            provider.generate(big, out_dir=".", apply=False)

    def test_no_secret_in_serialized_output(self):
        fake_key = "sk-test-FAKE-NOT-A-REAL-KEY"
        provider = OpenAIImagesProvider()
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": fake_key}):
            results = provider.generate(self.REQ, out_dir=".", apply=False)
        dumped = json.dumps([r.to_dict() for r in results])
        self.assertNotIn(fake_key, dumped)
        self.assertNotIn(fake_key, repr(provider.__dict__))


if __name__ == "__main__":
    unittest.main()
