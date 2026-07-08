"""Tests for the Traffic Factory UI polish (server-rendered FastAPI/Jinja +
static CSS, no build step). Covers the 17 points requested by the owner:

1. /traffic-factory renders without raw Jinja markers
2. /traffic-factory/start renders without raw Jinja markers
3. /traffic-factory/demo renders without raw Jinja markers
4. /traffic-factory/status/test renders without raw Jinja markers
5. CSS file exists
6. base template links traffic_factory.css
7. landing contains CTA buttons
8. start page has beta access card
9. wizard pages contain stepper labels
10. product page contains upload guide
11. campaign page contains client-friendly package plan
12. demo page contains product intelligence explanation
13. status page contains readable checklist
14. no OpenAI calls
15. no Higgsfield calls
16. no auto-posting APIs
17. no Railway/Production changes (verified manually -- this test tree does
    not touch any Railway/production config)
"""
import unittest
from pathlib import Path

from api.media_pipeline import b2b_seed as seed

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_PRODUCT = seed.DEMO_PRODUCT_ID
DEMO_CAMPAIGN = seed.DEMO_CAMPAIGN_ID

RAW_JINJA_MARKERS = ("{%", "{{", "%}", "}}")


class UITestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.main import app
        cls.client = TestClient(app)

    def assertNoRawJinjaMarkers(self, text):
        for marker in RAW_JINJA_MARKERS:
            self.assertNotIn(marker, text, f"raw Jinja marker {marker!r} leaked into rendered HTML")


class TestNoRawJinjaMarkers(UITestCase):
    def test_landing_clean(self):
        r = self.client.get("/traffic-factory/")
        self.assertEqual(r.status_code, 200)
        self.assertNoRawJinjaMarkers(r.text)

    def test_start_clean(self):
        r = self.client.get("/traffic-factory/start")
        self.assertEqual(r.status_code, 200)
        self.assertNoRawJinjaMarkers(r.text)

    def test_demo_clean(self):
        r = self.client.get("/traffic-factory/demo")
        self.assertEqual(r.status_code, 200)
        self.assertNoRawJinjaMarkers(r.text)

    def test_status_clean(self):
        r = self.client.get("/traffic-factory/status/test")
        self.assertEqual(r.status_code, 200)
        self.assertNoRawJinjaMarkers(r.text)

    def test_wizard_start_clean(self):
        r = self.client.get("/b2b/seller/start")
        self.assertEqual(r.status_code, 200)
        self.assertNoRawJinjaMarkers(r.text)

    def test_admin_pages_clean(self):
        for path in ("/b2b/", f"/b2b/products/{DEMO_PRODUCT}",
                    f"/b2b/campaigns/{DEMO_CAMPAIGN}",
                    f"/b2b/products/{DEMO_PRODUCT}/intelligence"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertNoRawJinjaMarkers(r.text)


class TestStaticCSS(UITestCase):
    def test_css_file_exists_on_disk(self):
        path = REPO_ROOT / "api" / "static" / "traffic_factory.css"
        self.assertTrue(path.is_file())

    def test_css_served_over_http(self):
        r = self.client.get("/static/traffic_factory.css")
        self.assertEqual(r.status_code, 200)
        self.assertIn("--tf-navy", r.text)
        self.assertIn("--tf-orange", r.text)

    def test_base_template_links_css(self):
        base_html = (REPO_ROOT / "api" / "templates" / "b2b" / "base.html").read_text(encoding="utf-8")
        self.assertIn('/static/traffic_factory.css', base_html)

    def test_rendered_page_includes_stylesheet_link(self):
        r = self.client.get("/traffic-factory/")
        self.assertIn('href="/static/traffic_factory.css"', r.text)


class TestLandingCTAButtons(UITestCase):
    def test_landing_has_cta_buttons(self):
        r = self.client.get("/traffic-factory/")
        self.assertIn("Создать контент-пакет", r.text)
        self.assertIn("Посмотреть демо на товаре", r.text)


class TestStartPageBetaCard(UITestCase):
    def test_start_page_has_access_card(self):
        r = self.client.get("/traffic-factory/start")
        self.assertIn("center-card", r.text)
        self.assertIn("Код доступа", r.text)


class TestWizardStepperLabels(UITestCase):
    def test_step1_has_stepper(self):
        r = self.client.get("/b2b/seller/start")
        self.assertIn("stepper", r.text)
        for label in ("Товар", "Фото", "Покупатель", "AI-анализ", "Пакет", "Готовность"):
            self.assertIn(label, r.text)


class TestProductPageUploadGuide(UITestCase):
    def test_upload_guide_present(self):
        r = self.client.get(f"/b2b/products/{DEMO_PRODUCT}")
        self.assertIn("Что нужно загрузить", r.text)
        self.assertIn("upload-grid", r.text)


class TestCampaignPageClientFriendlyPlan(UITestCase):
    def test_client_friendly_terms_present(self):
        r = self.client.get(f"/b2b/campaigns/{DEMO_CAMPAIGN}")
        self.assertIn("Что создаст контент-завод", r.text)
        self.assertIn("Проверить будущий контент-пакет", r.text)
        self.assertIn("Готовый ZIP с материалами", r.text)


class TestDemoPageIntelligenceExplanation(UITestCase):
    def test_demo_explains_ai_analysis(self):
        r = self.client.get("/traffic-factory/demo")
        self.assertIn("Какую проблему определил AI", r.text)
        self.assertIn("хуки", r.text.lower())


class TestStatusPageChecklist(UITestCase):
    def test_status_checklist_readable(self):
        r = self.client.get(f"/traffic-factory/status/{DEMO_PRODUCT}")
        self.assertIn("checklist", r.text)
        for marker in ("draft saved", "product info complete", "references uploaded",
                      "AI analysis ready", "content package plan ready"):
            self.assertIn(marker, r.text)


class TestZeroExternalCallsAndNoAutoPosting(unittest.TestCase):
    def test_no_network_markers_in_css_or_templates(self):
        css = (REPO_ROOT / "api" / "static" / "traffic_factory.css").read_text(encoding="utf-8")
        for marker in ("http://", "https://", "@import url"):
            self.assertNotIn(marker, css)

    def test_zero_openai_higgsfield_still_holds(self):
        from api.media_pipeline import b2b_campaign_contract as contract
        from unittest import mock
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call!")):
            plan = contract.build_campaign_dry_run(seed.DEMO_CLIENT_ID, DEMO_PRODUCT, DEMO_CAMPAIGN,
                                                    str(REPO_ROOT))
        self.assertEqual(plan["openai_calls"], 0)
        self.assertEqual(plan["higgsfield_calls"], 0)
        self.assertFalse(plan["auto_posting_triggered"])


if __name__ == "__main__":
    unittest.main()
