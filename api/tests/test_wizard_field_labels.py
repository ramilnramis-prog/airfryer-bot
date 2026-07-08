"""Tests for seller wizard Step 1 UX field-label polish (api/templates/b2b/
wizard/step1.html and related label dictionaries in b2b_storage.py,
seller_intake.py, product_intelligence.py, b2b_seller_wizard.py). Covers the
12 points requested by the owner:

1. seller start page does not show "client_name" as a visible hint
2. seller start page does not show snake_case field hints
3. marketplace select contains "OZON"
4. marketplace select contains "Wildberries"
5. marketplace select contains "Яндекс Маркет"
6. marketplace select contains "Свой сайт"
7. marketplace select contains "Другое"
8. backend marketplace values remain ozon/wildberries/yandex_market/own_site/other
9. no OpenAI calls
10. no Higgsfield calls
11. no auto-posting
12. no Railway/Production changes (verified manually -- this test tree does
    not touch any Railway/production config)
"""
import re
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline import b2b_storage as st

REPO_ROOT = Path(__file__).resolve().parents[2]

OPTION_RE = re.compile(r'<option value="([a-z_]+)">([^<]*)</option>')


class WizardLabelTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.main import app
        cls.client = TestClient(app)


class TestNoClientNameHint(WizardLabelTestCase):
    def test_client_name_hint_paragraph_gone(self):
        r = self.client.get("/b2b/seller/start")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('<p class="hint">client_name</p>', r.text)

    def test_client_name_attribute_still_wired(self):
        # the input's name="client_name" attribute must remain -- only the
        # VISIBLE hint text was removed, backend wiring is untouched
        r = self.client.get("/b2b/seller/start")
        self.assertIn('name="client_name"', r.text)


class TestNoSnakeCaseHints(WizardLabelTestCase):
    def test_no_visible_snake_case_option_labels(self):
        r = self.client.get("/b2b/seller/start")
        for value, label in OPTION_RE.findall(r.text):
            self.assertNotEqual(label.strip(), value,
                               f"option {value!r} shown with raw backend value as its label")

    def test_no_bare_hint_paragraphs_for_known_fields(self):
        r = self.client.get("/b2b/seller/start")
        for field in ("contact", "product_name", "marketplace", "marketplace_article",
                     "marketplace_url", "short_product_description"):
            self.assertNotIn(f'<p class="hint">{field}</p>', r.text)


class TestMarketplaceSelectLabels(WizardLabelTestCase):
    def test_contains_ozon_label(self):
        r = self.client.get("/b2b/seller/start")
        self.assertIn(">OZON<", r.text)

    def test_contains_wildberries_label(self):
        r = self.client.get("/b2b/seller/start")
        self.assertIn(">Wildberries<", r.text)

    def test_contains_yandex_market_label(self):
        r = self.client.get("/b2b/seller/start")
        self.assertIn(">Яндекс Маркет<", r.text)

    def test_contains_own_site_label(self):
        r = self.client.get("/b2b/seller/start")
        self.assertIn(">Свой сайт<", r.text)

    def test_contains_other_label(self):
        r = self.client.get("/b2b/seller/start")
        self.assertIn(">Другое<", r.text)


class TestBackendMarketplaceValuesUnchanged(WizardLabelTestCase):
    def test_constant_values_unchanged(self):
        self.assertEqual(st.PRODUCT_MARKETPLACES,
                         ("ozon", "wildberries", "yandex_market", "own_site", "other"))

    def test_option_value_attributes_unchanged(self):
        r = self.client.get("/b2b/seller/start")
        for expected in ("ozon", "wildberries", "yandex_market", "own_site", "other"):
            self.assertIn(f'value="{expected}"', r.text)

    def test_label_dict_maps_every_backend_value(self):
        for value in st.PRODUCT_MARKETPLACES:
            self.assertIn(value, st.PRODUCT_MARKETPLACE_LABELS)


class TestOtherSelectLabelsHumanReadable(WizardLabelTestCase):
    def test_platform_labels(self):
        r = self.client.post("/b2b/seller/start",
                             data={"client_name": "Label Test Client",
                                  "product_name": "Label Test Product"},
                             follow_redirects=False)
        product_id = r.headers["location"].rsplit("/", 2)[-2]
        try:
            r5 = self.client.get(f"/b2b/seller/{product_id}/step5")
            for label in ("YouTube Shorts", "Instagram Reels", "TikTok", "VK Клипы", "Дзен",
                        "7 дней", "14 дней", "30 дней", "Готовый ZIP для ручной публикации"):
                self.assertIn(label, r5.text)
            r3 = self.client.get(f"/b2b/seller/{product_id}/step3")
            self.assertIn("Спокойный", r3.text)
            r4 = self.client.get(f"/b2b/seller/{product_id}/step4")
            self.assertIn("Решение боли", r4.text)
        finally:
            import shutil
            client_dir = st.client_dir("label-test-client", str(REPO_ROOT))
            if client_dir.is_dir():
                shutil.rmtree(client_dir)


class TestZeroExternalCallsAndNoAutoPosting(unittest.TestCase):
    def test_no_network_markers_in_wizard_module(self):
        import api.b2b_seller_wizard as wiz
        src = Path(wiz.__file__).read_text(encoding="utf-8")
        for marker in ("import requests", "import httpx", "urllib.request.urlopen(",
                      "import openai", "OpenAI(", "HiggsfieldClient(",
                      "requests.post", "httpx.post", "youtube.upload"):
            self.assertNotIn(marker, src)

    def test_dry_run_still_zero_calls(self):
        from api.media_pipeline import b2b_campaign_contract as contract
        from api.media_pipeline import b2b_seed as seed
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call!")):
            plan = contract.build_campaign_dry_run(seed.DEMO_CLIENT_ID, seed.DEMO_PRODUCT_ID,
                                                    seed.DEMO_CAMPAIGN_ID, str(REPO_ROOT))
        self.assertEqual(plan["openai_calls"], 0)
        self.assertEqual(plan["higgsfield_calls"], 0)
        self.assertFalse(plan["auto_posting_triggered"])


if __name__ == "__main__":
    unittest.main()
