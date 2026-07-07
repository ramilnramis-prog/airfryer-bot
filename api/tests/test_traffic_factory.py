"""Tests for the public seller entry point (api/traffic_factory.py) --
"Крутая внешняя реклама" for the B2B content factory. Covers the 16 points
requested by the owner:

1. /traffic-factory renders
2. landing contains "Крутая внешняя реклама"
3. /traffic-factory/start renders access gate
4. correct beta code allows wizard/start content
5. wrong beta code blocks wizard
6. /traffic-factory/demo renders
7. /traffic-factory/status/test renders
8. landing explains what to upload
9. landing explains what seller gets
10. landing explains AI product understanding
11. PUBLIC-ENTRY-COPY.md exists
12. TELEGRAM-MINI-APP-ROADMAP.md exists
13. no OpenAI calls
14. no Higgsfield calls
15. no auto-posting APIs
16. no Railway/Production changes (verified manually -- this test tree does
    not touch any Railway/production config)
"""
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline import b2b_seed as seed
from api import traffic_factory as tf

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_PRODUCT = seed.DEMO_PRODUCT_ID


def urlopen_raises():
    return mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call!"))


class TrafficFactoryTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.main import app
        cls.client = TestClient(app)


class TestLandingRenders(TrafficFactoryTestCase):
    def test_landing_status_200(self):
        r = self.client.get("/traffic-factory/")
        self.assertEqual(r.status_code, 200)

    def test_landing_contains_headline(self):
        r = self.client.get("/traffic-factory/")
        self.assertIn("Крутая внешняя реклама", r.text)


class TestStartGateRenders(TrafficFactoryTestCase):
    def test_start_gate_status_200(self):
        r = self.client.get("/traffic-factory/start")
        self.assertEqual(r.status_code, 200)
        self.assertIn("access_code", r.text)


class TestBetaAccessCode(TrafficFactoryTestCase):
    def test_correct_code_redirects_to_wizard(self):
        r = self.client.post("/traffic-factory/start", data={"access_code": "SELLER-BETA"},
                             follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(r.headers["location"], "/b2b/seller/start")
        # follow through and confirm the wizard actually renders
        r2 = self.client.get(r.headers["location"])
        self.assertEqual(r2.status_code, 200)

    def test_correct_code_from_env_override(self):
        with mock.patch.dict("os.environ", {"B2B_BETA_ACCESS_CODE": "CUSTOM-CODE"}):
            r = self.client.post("/traffic-factory/start", data={"access_code": "CUSTOM-CODE"},
                                 follow_redirects=False)
            self.assertEqual(r.status_code, 303)

    def test_wrong_code_blocks_and_shows_soft_message(self):
        r = self.client.post("/traffic-factory/start", data={"access_code": "totally-wrong"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("beta", r.text.lower())
        self.assertNotIn("Шаг 1", r.text)  # never reaches wizard content

    def test_default_access_code_constant(self):
        self.assertEqual(tf.DEFAULT_BETA_ACCESS_CODE, "SELLER-BETA")


class TestDemoPageRenders(TrafficFactoryTestCase):
    def test_demo_status_200(self):
        r = self.client.get("/traffic-factory/demo")
        self.assertEqual(r.status_code, 200)

    def test_demo_shows_core_problem_and_hooks(self):
        r = self.client.get("/traffic-factory/demo")
        self.assertIn("проблему определил AI", r.text)
        self.assertIn("хуки", r.text.lower())
        self.assertIn("DELIVERY-KIT.zip", r.text)


class TestStatusPageRenders(TrafficFactoryTestCase):
    def test_status_unknown_id_renders(self):
        r = self.client.get("/traffic-factory/status/test")
        self.assertEqual(r.status_code, 200)

    def test_status_known_product_renders_checklist(self):
        r = self.client.get(f"/traffic-factory/status/{DEMO_PRODUCT}")
        self.assertEqual(r.status_code, 200)
        for marker in ("draft saved", "product info complete", "references uploaded",
                      "AI analysis ready", "content package plan ready"):
            self.assertIn(marker, r.text)


class TestLandingExplainsUpload(TrafficFactoryTestCase):
    def test_landing_explains_how_it_works(self):
        r = self.client.get("/traffic-factory/")
        self.assertIn("Загружаете товар", r.text)


class TestLandingExplainsWhatSellerGets(TrafficFactoryTestCase):
    def test_landing_lists_deliverables(self):
        r = self.client.get("/traffic-factory/")
        for marker in ("YouTube Shorts", "Статьи для Дзена", "План публикаций",
                      "performance tracker", "delivery ZIP"):
            self.assertIn(marker, r.text)


class TestLandingExplainsAIUnderstanding(TrafficFactoryTestCase):
    def test_landing_explains_ai_promise(self):
        r = self.client.get("/traffic-factory/")
        self.assertIn("не просто генерируем картинки", r.text)


class TestPublicEntryCopyExists(unittest.TestCase):
    def test_file_exists(self):
        path = REPO_ROOT / "content" / "b2b" / "PUBLIC-ENTRY-COPY.md"
        self.assertTrue(path.is_file())

    def test_covers_faq_and_pitch(self):
        text = (REPO_ROOT / "content" / "b2b" / "PUBLIC-ENTRY-COPY.md").read_text(encoding="utf-8")
        for marker in ("FAQ", "Short pitch", "Ozon/WB", "Автопостинг",
                      "B2B_BETA_ACCESS_CODE", "SELLER-BETA"):
            self.assertIn(marker, text)


class TestTelegramMiniAppRoadmapExists(unittest.TestCase):
    def test_file_exists(self):
        path = REPO_ROOT / "content" / "b2b" / "TELEGRAM-MINI-APP-ROADMAP.md"
        self.assertTrue(path.is_file())

    def test_covers_phases_and_what_not_to_do(self):
        text = (REPO_ROOT / "content" / "b2b" /
               "TELEGRAM-MINI-APP-ROADMAP.md").read_text(encoding="utf-8")
        for marker in ("Phase 1", "Phase 2", "Phase 3", "Phase 4",
                      "What NOT to do in the first version", "web_app", "initData"):
            self.assertIn(marker, text)

    def test_no_bot_implemented_claim(self):
        text = (REPO_ROOT / "content" / "b2b" /
               "TELEGRAM-MINI-APP-ROADMAP.md").read_text(encoding="utf-8")
        self.assertIn("No Telegram bot or Mini App is implemented", text)


class TestZeroExternalCallsAndNoAutoPosting(unittest.TestCase):
    def test_no_network_markers_in_module_source(self):
        src = Path(tf.__file__).read_text(encoding="utf-8")
        for marker in ("import requests", "import httpx", "urllib.request.urlopen(",
                      "import openai", "OpenAI(", "higgsfield_client.",
                      "HiggsfieldClient(", "higgsfield.generate",
                      "requests.post", "httpx.post", "youtube.upload",
                      "instagram_api", "tiktok_api", "vk_api.upload",
                      "import telegram", "TeleBot(", "bot.send"):
            self.assertNotIn(marker, src)

    def test_demo_page_zero_network(self):
        with urlopen_raises():
            from fastapi.testclient import TestClient
            from api.main import app
            client = TestClient(app)
            r = client.get("/traffic-factory/demo")
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
