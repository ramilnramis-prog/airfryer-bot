"""Tests for the seller onboarding wizard simplification (single-block
Step 2 upload, 3-question Step 3, human-readable Step 4 with ad strategy
selection, Russian Step 6 checklist). Covers the 18 points requested by
the owner:

1. Step 2 has one multiple file upload input
2. Step 2 does not render six separate upload inputs
3. Step 3 contains only 3 main required questions
4. Step 3 advanced fields are hidden/collapsible or clearly optional
5. Step 4 does not show "low confidence" raw text
6. Step 4 shows Russian AI summary labels
7. Step 4 shows 3 ad strategy options
8. Step 4 has "Тестировать все варианты"
9. Step 4 has no English action buttons
10. product intelligence output includes ad_strategy_options
11. selected_ad_strategy can be saved
12. Step 6 checklist labels are Russian
13. Step 6 warning about approved references is human-readable
14. backend still stores correct data
15. no OpenAI calls
16. no Higgsfield calls
17. no auto-posting
18. no Railway/Production changes (verified manually -- this test tree does
    not touch any Railway/production config)
"""
import io
import shutil
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline import b2b_storage as st
from api.media_pipeline import product_intelligence as pi
from api.media_pipeline import b2b_seed as seed

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_PRODUCT = seed.DEMO_PRODUCT_ID
DEMO_CAMPAIGN = seed.DEMO_CAMPAIGN_ID


class WizardTestCase(unittest.TestCase):
    CLIENT_ID = "test-simplify-client"

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.main import app
        cls.client = TestClient(app)

    def tearDown(self):
        client_dir = st.client_dir(self.CLIENT_ID, str(REPO_ROOT))
        if client_dir.is_dir():
            shutil.rmtree(client_dir)

    def _step1(self, product_name="Simplify Test Product"):
        data = {
            "client_name": "Test Simplify Client", "contact": "s@example.com",
            "product_name": product_name, "marketplace": "ozon",
            "marketplace_article": "S1", "marketplace_url": "https://ozon.ru/s",
            "price": "500", "category": "test",
            "short_product_description": "test description",
        }
        r = self.client.post("/b2b/seller/start", data=data, follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text)
        return r.headers["location"].rsplit("/", 2)[-2]


class TestStep2SingleUploadBlock(WizardTestCase):
    def test_single_multiple_file_input(self):
        product_id = self._step1()
        r = self.client.get(f"/b2b/seller/{product_id}/step2")
        self.assertEqual(r.status_code, 200)
        self.assertIn('name="photos"', r.text)
        self.assertIn("multiple", r.text)

    def test_no_six_separate_upload_inputs(self):
        product_id = self._step1()
        r = self.client.get(f"/b2b/seller/{product_id}/step2")
        for old_field in ("front_photo", "top_photo", "side_photo", "detail_photo",
                         "packaging_photo", "additional_photos"):
            self.assertNotIn(old_field, r.text)
        # exactly one file input on the page
        self.assertEqual(r.text.count('type="file"'), 1)


class TestStep3ThreeKeyQuestions(WizardTestCase):
    def test_three_main_questions_present(self):
        product_id = self._step1()
        r = self.client.get(f"/b2b/seller/{product_id}/step3")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Кто обычно покупает этот товар?", r.text)
        self.assertIn("Какую главную проблему или желание решает товар?", r.text)
        self.assertIn("Почему человек должен выбрать именно этот товар?", r.text)

    def test_advanced_fields_inside_details(self):
        product_id = self._step1()
        r = self.client.get(f"/b2b/seller/{product_id}/step3")
        self.assertIn("<details>", r.text)
        self.assertIn("Дополнительно, если хотите уточнить", r.text)
        details_start = r.text.index("<details>")
        details_end = r.text.index("</details>")
        details_block = r.text[details_start:details_end]
        for field in ("top_3_benefits", "use_cases", "common_questions",
                     "objections", "what_should_not_be_claimed", "tone_preference"):
            self.assertIn(field, details_block)


class TestStep4NoLowConfidenceRawText(WizardTestCase):
    def test_no_raw_low_confidence_text(self):
        product_id = self._step1()
        r = self.client.get(f"/b2b/seller/{product_id}/step4")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("low confidence", r.text)
        self.assertNotIn("confidence</span>", r.text)


class TestStep4RussianSummaryLabels(WizardTestCase):
    def test_four_cards_russian(self):
        product_id = self._step1()
        r = self.client.get(f"/b2b/seller/{product_id}/step4")
        for label in ("Главная проблема покупателя", "Кому это особенно нужно",
                     "Почему товар могут купить", "Где товар используют"):
            self.assertIn(label, r.text)


class TestStep4AdStrategyOptions(WizardTestCase):
    def test_three_strategy_cards_shown(self):
        product_id = self._step1()
        r = self.client.get(f"/b2b/seller/{product_id}/step4")
        self.assertIn("Как будем рекламировать товар?", r.text)
        self.assertIn("Через боль", r.text)
        self.assertIn("Через демонстрацию", r.text)
        self.assertIn("Через выгоду", r.text)

    def test_test_all_variants_option(self):
        product_id = self._step1()
        r = self.client.get(f"/b2b/seller/{product_id}/step4")
        self.assertIn("Тестировать все варианты", r.text)


class TestStep4NoEnglishActionButtons(WizardTestCase):
    def test_no_english_buttons(self):
        product_id = self._step1()
        r = self.client.get(f"/b2b/seller/{product_id}/step4")
        for english in ("Approve AI analysis", "Regenerate from product info",
                       "Edit primary problem", "Save primary problem",
                       "Mark product as", "Disable irrelevant hook"):
            self.assertNotIn(english, r.text)
        for russian in ("Подтвердить AI-анализ", "Пересобрать анализ",
                       "Поправить главную проблему", "Сохранить проблему",
                       "Тип продвижения"):
            self.assertIn(russian, r.text)


class TestProductIntelligenceAdStrategyOptions(unittest.TestCase):
    def test_output_includes_ad_strategy_options(self):
        report = pi.analyze_product_intelligence({"product_name": "Тестовый товар для теста"})
        self.assertIn("ad_strategy_options", report)
        self.assertEqual(len(report["ad_strategy_options"]), 3)
        ids = [o["strategy_id"] for o in report["ad_strategy_options"]]
        self.assertEqual(ids, ["pain_problem", "demo_use_case", "benefit_convenience"])
        for opt in report["ad_strategy_options"]:
            for key in ("strategy_id", "title", "main_message", "viewer_thought",
                       "example_hook", "recommended_for"):
                self.assertIn(key, opt)

    def test_default_selected_ad_strategy_is_multi_angle_test(self):
        report = pi.analyze_product_intelligence({"product_name": "Тестовый товар"})
        self.assertEqual(report["selected_ad_strategy"], "multi_angle_test")


class TestSelectedAdStrategyCanBeSaved(unittest.TestCase):
    def test_set_ad_strategy_persists(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            st.save_client(st.Client(client_id="acme", name="Acme"), tmp)
            st.save_product(st.Product(product_id="widget", client_id="acme",
                                       product_name="Widget"), tmp)
            pi.write_product_intelligence("acme", "widget", tmp)
            env = pi.set_ad_strategy("acme", "widget", tmp, "demo_use_case")
            self.assertEqual(env["report"]["selected_ad_strategy"], "demo_use_case")
            reloaded = pi.load_product_intelligence("acme", "widget", tmp)
            self.assertEqual(reloaded["report"]["selected_ad_strategy"], "demo_use_case")

    def test_set_ad_strategy_rejects_unknown_id(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            st.save_client(st.Client(client_id="acme", name="Acme"), tmp)
            st.save_product(st.Product(product_id="widget", client_id="acme",
                                       product_name="Widget"), tmp)
            pi.write_product_intelligence("acme", "widget", tmp)
            with self.assertRaises(pi.ProductIntelligenceError) as ctx:
                pi.set_ad_strategy("acme", "widget", tmp, "not_a_real_strategy")
            self.assertEqual(ctx.exception.code, "UNKNOWN_AD_STRATEGY")

    def test_web_route_saves_selection(self):
        from fastapi.testclient import TestClient
        from api.main import app
        client = TestClient(app)
        r = client.post(f"/b2b/seller/{DEMO_PRODUCT}/step4/ad-strategy",
                        data={"strategy_id": "benefit_convenience"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        envelope = pi.load_product_intelligence(seed.DEMO_CLIENT_ID, DEMO_PRODUCT, str(REPO_ROOT))
        self.assertEqual(envelope["report"]["selected_ad_strategy"], "benefit_convenience")
        # restore default for other tests relying on demo state
        pi.set_ad_strategy(seed.DEMO_CLIENT_ID, DEMO_PRODUCT, str(REPO_ROOT), "multi_angle_test")


class TestStep6ChecklistRussian(WizardTestCase):
    def test_checklist_labels_russian(self):
        product_id = self._step1()
        r = self.client.get(f"/b2b/seller/{product_id}/step6")
        self.assertEqual(r.status_code, 200)
        for label in ("Информация о товаре заполнена", "Артикул или ссылка добавлены",
                     "Загружено минимум 3 фото товара", "Фото товара загружены",
                     "Покупатель и проблема описаны", "AI-анализ товара готов",
                     "Главная проблема подтверждена", "Площадки выбраны",
                     "Период пакета выбран"):
            self.assertIn(label, r.text)
        for old_label in ("product info complete", "marketplace article/link present",
                         "at least 3 uploaded product references",
                         "at least 3 approved product references", "Фото товара проверены"):
            self.assertNotIn(old_label, r.text)


class TestStep6HumanReadableWarning(WizardTestCase):
    def test_warning_is_human_readable(self):
        product_id = self._step1()
        r = self.client.get(f"/b2b/seller/{product_id}/step6")
        self.assertIn("Нужно загрузить хотя бы 1 фото товара, чтобы продолжить", r.text)
        self.assertIn("Загрузить фото товара", r.text)
        self.assertNotIn("Одобрить фото можно на странице товара:", r.text)
        self.assertNotIn("Фото уже загружены, но их нужно подтвердить", r.text)

    def test_quality_note_for_one_or_two_uploaded_not_blocking(self):
        product_id = self._step1()
        files = [("photos", ("p1.png", io.BytesIO(b"fake"), "image/png"))]
        self.client.post(f"/b2b/seller/{product_id}/step2", files=files, follow_redirects=False)
        r = self.client.get(f"/b2b/seller/{product_id}/step6")
        self.assertIn("Фото товара загружены. Можно продолжить", r.text)
        self.assertIn("рекомендуем добавить", r.text)
        self.assertNotIn("disabled", r.text)

    def test_green_status_for_three_or_more_uploaded(self):
        product_id = self._step1()
        files = [("photos", (f"p{i}.png", io.BytesIO(b"fake"), "image/png")) for i in range(3)]
        self.client.post(f"/b2b/seller/{product_id}/step2", files=files, follow_redirects=False)
        r = self.client.get(f"/b2b/seller/{product_id}/step6")
        self.assertIn("Фото товара загружены. Этого достаточно для старта.", r.text)


class TestBackendStillStoresCorrectData(WizardTestCase):
    def test_full_flow_persists_backend_data(self):
        product_id = self._step1(product_name="Backend Check Product")
        files = [("photos", (f"p{i}.png", io.BytesIO(b"fake"), "image/png")) for i in range(3)]
        self.client.post(f"/b2b/seller/{product_id}/step2", files=files, follow_redirects=False)

        product = st.load_product(self.CLIENT_ID, product_id, str(REPO_ROOT))
        refs = st.load_references(self.CLIENT_ID, product_id, str(REPO_ROOT))
        self.assertEqual(len(refs), 3)
        self.assertEqual([r.role for r in refs], ["front", "top", "side"])
        for r in refs:
            self.assertFalse(r.approved)

        self.client.post(f"/b2b/seller/{product_id}/step3", data={
            "who_is_this_for": "Test audience",
            "what_problem_does_it_usually_solve": "Test problem",
            "why_people_buy_it": "Test reason",
        }, follow_redirects=False)
        product = st.load_product(self.CLIENT_ID, product_id, str(REPO_ROOT))
        self.assertEqual(product.who_is_this_for, "Test audience")
        self.assertEqual(product.what_problem_does_it_usually_solve, "Test problem")


class TestZeroExternalCallsAndNoAutoPosting(unittest.TestCase):
    def test_no_network_markers_in_modules(self):
        import api.b2b_seller_wizard as wiz
        for mod in (wiz, pi):
            src = Path(mod.__file__).read_text(encoding="utf-8")
            for marker in ("import requests", "import httpx", "urllib.request.urlopen(",
                          "import openai", "OpenAI(", "HiggsfieldClient(",
                          "requests.post", "httpx.post", "youtube.upload"):
                self.assertNotIn(marker, src)

    def test_dry_run_still_zero_calls(self):
        from api.media_pipeline import b2b_campaign_contract as contract
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call!")):
            plan = contract.build_campaign_dry_run(seed.DEMO_CLIENT_ID, DEMO_PRODUCT,
                                                    DEMO_CAMPAIGN, str(REPO_ROOT))
        self.assertEqual(plan["openai_calls"], 0)
        self.assertEqual(plan["higgsfield_calls"], 0)
        self.assertFalse(plan["auto_posting_triggered"])


if __name__ == "__main__":
    unittest.main()
