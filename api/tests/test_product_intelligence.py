"""Tests for the Product Need / Problem-Solution Intelligence Engine
(api/media_pipeline/product_intelligence.py) -- B2B seller traffic factory.
Covers the 16 points requested by the owner:

1. product intelligence file created
2. engine works without external APIs
3. engine fail-closed on missing/invalid product data
4. airfryer silicone form demo produces relevant pain/problem hypotheses
5. flashlight-like product produces relevant utility hypotheses
6. intelligence report contains required keys
7. confidence / needs_owner_review present
8. manual override path works
9. B2B product page shows intelligence block
10. B2B campaign page shows recommended hook/video angles
11. onboarding includes new positioning fields
12. content factory / campaign dry-run can read intelligence
13. no OpenAI calls
14. no Higgsfield calls
15. no auto-posting
16. no Railway/Production changes (verified manually -- this test tree does
    not touch any Railway/production config)
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline import b2b_storage as st
from api.media_pipeline import product_intelligence as pi
from api.media_pipeline import b2b_campaign_contract as contract
from api.media_pipeline import b2b_seed as seed

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_CLIENT = seed.DEMO_CLIENT_ID
DEMO_PRODUCT = seed.DEMO_PRODUCT_ID
DEMO_CAMPAIGN = seed.DEMO_CAMPAIGN_ID

REQUIRED_REPORT_KEYS = (
    "core_problem_solved", "secondary_problems_solved", "ideal_customer_segments",
    "jobs_to_be_done", "pain_points", "desired_outcomes", "product_benefits",
    "likely_objections", "use_cases", "hook_angles", "video_message_angles",
    "recommended_content_mix", "confidence_notes", "needs_owner_review",
    "matched_category", "match_confidence", "positioning_mode",
)


def urlopen_raises():
    return mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call!"))


class TestIntelligenceFileCreated(unittest.TestCase):
    def test_write_product_intelligence_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            st.save_client(st.Client(client_id="acme", name="Acme"), tmp)
            st.save_product(st.Product(product_id="widget", client_id="acme",
                                       product_name="Widget"), tmp)
            with urlopen_raises():
                envelope = pi.write_product_intelligence("acme", "widget", tmp)
            path = pi.intelligence_path("acme", "widget", tmp)
            self.assertTrue(path.is_file())
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["report"]["matched_category"], envelope["report"]["matched_category"])

    def test_demo_product_intelligence_generates_via_dry_run(self):
        with urlopen_raises():
            plan = contract.build_campaign_dry_run(DEMO_CLIENT, DEMO_PRODUCT, DEMO_CAMPAIGN, str(REPO_ROOT))
        self.assertTrue(pi.intelligence_path(DEMO_CLIENT, DEMO_PRODUCT, str(REPO_ROOT)).is_file())
        self.assertIn("product_intelligence", plan)


class TestEngineNoExternalAPIs(unittest.TestCase):
    def test_analyze_is_pure_local(self):
        with urlopen_raises():
            report = pi.analyze_product_intelligence({"product_name": "Тестовый товар"})
        self.assertIsInstance(report, dict)

    def test_no_network_markers_in_module_source(self):
        # Docstrings legitimately MENTION "OpenAI"/"Higgsfield" as documentation
        # of what's never called -- check for actual import/call patterns
        # instead of bare word presence (see test_b2b.py for the same pattern).
        src = Path(pi.__file__).read_text(encoding="utf-8")
        for marker in ("import requests", "import httpx", "urllib.request.urlopen(",
                      "import openai", "OpenAI(", "higgsfield_client.",
                      "HiggsfieldClient(", "higgsfield.generate"):
            self.assertNotIn(marker, src)


class TestEngineFailClosed(unittest.TestCase):
    def test_missing_product_name_raises(self):
        with self.assertRaises(pi.ProductIntelligenceError) as ctx:
            pi.analyze_product_intelligence({"category": "x"})
        self.assertEqual(ctx.exception.code, "MISSING_PRODUCT_NAME")

    def test_empty_product_name_raises(self):
        with self.assertRaises(pi.ProductIntelligenceError) as ctx:
            pi.analyze_product_intelligence({"product_name": "   "})
        self.assertEqual(ctx.exception.code, "MISSING_PRODUCT_NAME")

    def test_invalid_type_raises(self):
        with self.assertRaises(pi.ProductIntelligenceError) as ctx:
            pi.analyze_product_intelligence(["not", "a", "dict"])
        self.assertEqual(ctx.exception.code, "INVALID_PRODUCT_DATA")

    def test_regenerate_without_existing_file_still_works_but_toggle_requires_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(pi.ProductIntelligenceError) as ctx:
                pi.approve_product_intelligence("acme", "widget", tmp)
            self.assertEqual(ctx.exception.code, "INTELLIGENCE_NOT_FOUND")


class TestAirfryerHeuristics(unittest.TestCase):
    def test_airfryer_produces_relevant_pain_hypotheses(self):
        report = pi.analyze_product_intelligence({
            "product_name": "Силиконовая форма для аэрогриля",
            "category": "Кухонные принадлежности",
            "product_description": "Антипригарная форма-вкладыш для аэрогриля",
        })
        self.assertEqual(report["matched_category"], "airfryer_silicone_form")
        self.assertEqual(report["match_confidence"], "high")
        combined_pains = " ".join(p["pain"] for p in report["pain_points"]).lower()
        self.assertIn("жир", combined_pains)
        combined_use_cases = " ".join(u["scenario"].lower() for u in report["use_cases"])
        self.assertTrue(any(kw in combined_use_cases for kw in
                           ("куриц", "картоф", "выпечк", "запеканк", "рыб")))


class TestFlashlightHeuristics(unittest.TestCase):
    def test_flashlight_produces_relevant_utility_hypotheses(self):
        report = pi.analyze_product_intelligence({
            "product_name": "Аккумуляторный LED фонарик",
            "category": "Освещение",
        })
        self.assertEqual(report["matched_category"], "flashlight")
        combined_pains = " ".join(p["pain"] for p in report["pain_points"]).lower()
        self.assertTrue(any(kw in combined_pains for kw in ("свет", "батаре", "заряд")))


class TestRequiredKeysPresent(unittest.TestCase):
    def test_all_required_keys_present(self):
        report = pi.analyze_product_intelligence({"product_name": "Любой товар для теста"})
        for key in REQUIRED_REPORT_KEYS:
            self.assertIn(key, report)

    def test_recommended_content_mix_keys(self):
        report = pi.analyze_product_intelligence({"product_name": "Любой товар для теста"})
        for key in ("pain_problem", "problem_solution", "demo", "recipe_or_use_case",
                   "ugc_style", "meme_style"):
            self.assertIn(key, report["recommended_content_mix"])


class TestConfidenceAndNeedsOwnerReview(unittest.TestCase):
    def test_confidence_fields_present(self):
        report = pi.analyze_product_intelligence({"product_name": "Совершенно неизвестный товар xyz123"})
        self.assertIn(report["match_confidence"], ("high", "medium", "low"))
        self.assertIsInstance(report["match_confidence_score"], float)
        self.assertTrue(report["confidence_notes"])
        self.assertIs(report["needs_owner_review"], True)

    def test_unmatched_product_is_low_confidence_hypothesis_not_fact(self):
        report = pi.analyze_product_intelligence({"product_name": "Zzyzx Unmatched Widget Q9"})
        self.assertEqual(report["matched_category"], "generic_fallback")
        self.assertEqual(report["match_confidence"], "low")
        self.assertIn("гипотеза", report["confidence_notes"].lower())


class TestManualOverridePath(unittest.TestCase):
    def test_manual_positioning_fields_override_heuristic(self):
        report = pi.analyze_product_intelligence({
            "product_name": "Товар",
            "who_is_this_for": "Кастомная аудитория",
            "what_problem_does_it_usually_solve": "Кастомная проблема продавца",
            "top_3_benefits": "Выгода 1, Выгода 2, Выгода 3",
            "common_questions": "Вопрос 1; Вопрос 2",
            "what_should_not_be_claimed": "Не заявлять медицинский эффект",
            "tone_preference": "дружелюбный",
        })
        self.assertEqual(report["core_problem_solved"], "Кастомная проблема продавца")
        self.assertEqual(report["ideal_customer_segments"][0]["segment"], "Кастомная аудитория")
        self.assertIn("Выгода 1", [b["benefit"] for b in report["product_benefits"]])
        self.assertTrue(any(o["objection"] == "Вопрос 1" for o in report["likely_objections"]))
        self.assertEqual(report["claims_to_avoid"], ["Не заявлять медицинский эффект"])
        self.assertEqual(report["tone_preference"], "дружелюбный")
        self.assertTrue(report["manual_override_present"])

    def test_storage_level_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            st.save_client(st.Client(client_id="acme", name="Acme"), tmp)
            st.save_product(st.Product(product_id="widget", client_id="acme",
                                       product_name="Фонарик"), tmp)
            pi.write_product_intelligence("acme", "widget", tmp)

            approved = pi.approve_product_intelligence("acme", "widget", tmp, "looks good")
            self.assertTrue(approved["approved_by_owner"])

            updated = pi.set_primary_problem("acme", "widget", tmp, "New primary problem")
            self.assertEqual(updated["report"]["core_problem_solved"], "New primary problem")
            self.assertTrue(updated["approved_by_owner"])  # unaffected by primary-problem edit

            moded = pi.set_positioning_mode("acme", "widget", tmp, "status")
            self.assertEqual(moded["report"]["positioning_mode"], "status")

            with self.assertRaises(pi.ProductIntelligenceError):
                pi.set_positioning_mode("acme", "widget", tmp, "not_a_real_mode")

            toggled = pi.toggle_hook_angle("acme", "widget", tmp, index=0, enabled=False)
            self.assertFalse(toggled["report"]["hook_angles"][0]["enabled"])

            with self.assertRaises(pi.ProductIntelligenceError):
                pi.toggle_hook_angle("acme", "widget", tmp, index=999, enabled=True)

            regenerated = pi.regenerate_product_intelligence("acme", "widget", tmp)
            self.assertFalse(regenerated["approved_by_owner"])


class TestB2BProductPageShowsIntelligence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.main import app
        cls.client = TestClient(app)

    def test_product_detail_shows_intelligence_block(self):
        r = self.client.get(f"/b2b/products/{DEMO_PRODUCT}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("систем", r.text.lower())

    def test_intelligence_preview_page_renders(self):
        r = self.client.get(f"/b2b/products/{DEMO_PRODUCT}/intelligence")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Hook", r.text)

    def test_regenerate_and_approve_routes(self):
        r = self.client.post(f"/b2b/products/{DEMO_PRODUCT}/intelligence/regenerate",
                             follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        r = self.client.post(f"/b2b/products/{DEMO_PRODUCT}/intelligence/approve",
                             data={"approval_notes": "ok"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)


class TestB2BCampaignPageShowsHookAngles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.main import app
        cls.client = TestClient(app)

    def test_campaign_detail_shows_hook_and_video_angles(self):
        r = self.client.get(f"/b2b/campaigns/{DEMO_CAMPAIGN}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Suggested hook angles", r.text)
        self.assertIn("Suggested video angles", r.text)


class TestOnboardingPositioningFields(unittest.TestCase):
    def test_product_new_form_includes_positioning_fields(self):
        from fastapi.testclient import TestClient
        from api.main import app
        client = TestClient(app)
        r = client.get("/b2b/products/new")
        self.assertEqual(r.status_code, 200)
        for field in ("who_is_this_for", "what_problem_does_it_usually_solve",
                     "why_people_buy_it", "top_3_benefits", "common_questions",
                     "what_should_not_be_claimed", "tone_preference"):
            self.assertIn(field, r.text)

    def test_product_dataclass_has_positioning_fields(self):
        product = st.Product(product_id="x", client_id="y", product_name="z")
        for field in ("who_is_this_for", "what_problem_does_it_usually_solve",
                     "why_people_buy_it", "top_3_benefits", "common_questions",
                     "what_should_not_be_claimed", "tone_preference"):
            self.assertTrue(hasattr(product, field))


class TestContentFactoryReadsIntelligence(unittest.TestCase):
    def test_dry_run_json_includes_product_intelligence(self):
        with urlopen_raises():
            plan = contract.build_campaign_dry_run(DEMO_CLIENT, DEMO_PRODUCT, DEMO_CAMPAIGN, str(REPO_ROOT))
        self.assertIn("product_intelligence", plan)
        pi_summary = plan["product_intelligence"]
        for key in ("core_problem_solved", "matched_category", "match_confidence",
                   "top_pain_points", "top_benefits", "hook_angles",
                   "video_message_angles", "recommended_content_mix"):
            self.assertIn(key, pi_summary)

    def test_dry_run_md_includes_product_intelligence_section(self):
        with urlopen_raises():
            plan = contract.write_campaign_dry_run(DEMO_CLIENT, DEMO_PRODUCT, DEMO_CAMPAIGN, str(REPO_ROOT))
        text = Path(plan["report_md_path"]).read_text(encoding="utf-8")
        self.assertIn("Product intelligence", text)


class TestZeroExternalCallsAndNoAutoPosting(unittest.TestCase):
    def test_zero_openai_higgsfield_in_dry_run(self):
        with urlopen_raises():
            plan = contract.build_campaign_dry_run(DEMO_CLIENT, DEMO_PRODUCT, DEMO_CAMPAIGN, str(REPO_ROOT))
        self.assertEqual(plan["openai_calls"], 0)
        self.assertEqual(plan["higgsfield_calls"], 0)
        self.assertFalse(plan["auto_posting_triggered"])

    def test_no_posting_markers_in_intelligence_module(self):
        src = Path(pi.__file__).read_text(encoding="utf-8")
        for marker in ("requests.post", "httpx.post", "youtube.upload",
                      "instagram_api", "tiktok_api", "vk_api.upload"):
            self.assertNotIn(marker, src)


if __name__ == "__main__":
    unittest.main()
