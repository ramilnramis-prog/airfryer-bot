"""Tests for Traffic Factory Landing UX Polish v2 (api/templates/traffic_factory/
landing.html, start_gate.html). Covers the 13 points requested by the owner:

1. /traffic-factory contains improved hero copy
2. landing contains "Что нужно от вас"
3. landing contains "Почему это не просто генератор картинок"
4. landing contains "Кому подойдёт"
5. landing contains beta limitations block
6. what seller gets cards are in Russian
7. start page contains improved beta copy
8. no raw Jinja markers
9. CSS still linked
10. no OpenAI calls
11. no Higgsfield calls
12. no auto-posting
13. no Railway/Production changes (verified manually -- this test tree does
    not touch any Railway/production config)
"""
import unittest
from pathlib import Path
from unittest import mock

from api.media_pipeline import b2b_seed as seed

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_JINJA_MARKERS = ("{%", "{{", "%}", "}}")


class LandingV2TestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.main import app
        cls.client = TestClient(app)


class TestHeroImproved(LandingV2TestCase):
    def test_hero_headline_and_subhead(self):
        r = self.client.get("/traffic-factory/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("AI-контент-завод для селлеров Ozon/WB", r.text)
        self.assertIn("систем", r.text.lower())

    def test_hero_badges_present(self):
        r = self.client.get("/traffic-factory/")
        for badge in ("Для Ozon / WB селлеров", "Без автопостинга в MVP",
                     "ZIP-пакет для ручной публикации", "Product references only"):
            self.assertIn(badge, r.text)

    def test_hero_cta_buttons(self):
        r = self.client.get("/traffic-factory/")
        self.assertIn("Создать контент-пакет", r.text)
        self.assertIn("Посмотреть демо на товаре", r.text)


class TestWhatYouNeedToProvide(LandingV2TestCase):
    def test_block_present(self):
        r = self.client.get("/traffic-factory/")
        self.assertIn("Что нужно от вас", r.text)
        for card in ("Фото товара", "Ссылка и артикул", "Короткое описание", "Ограничения"):
            self.assertIn(card, r.text)


class TestHowItWorksImproved(LandingV2TestCase):
    def test_steps_have_richer_text(self):
        r = self.client.get("/traffic-factory/")
        for text in ("Фото товара + ссылка/артикул + короткое описание.",
                    "Система определяет, какую боль решает товар",
                    "Видео, хуки, описания, статьи Дзена, картинки и план публикаций.",
                    "Готовые файлы, разложенные по дням и площадкам.",
                    "Выкладываете вручную и заносите результаты в трекер."):
            self.assertIn(text, r.text)


class TestWhatSellerGetsRussian(LandingV2TestCase):
    def test_cards_are_russian(self):
        r = self.client.get("/traffic-factory/")
        for card in ("Короткие видео", "Описания и хэштеги", "Статьи для Дзена",
                    "Картинки к статьям", "План публикаций", "Трекер результатов",
                    "ZIP с материалами"):
            self.assertIn(card, r.text)

    def test_no_bare_short_videos_label(self):
        # the old English-only card label ("<p>Short videos</p>" as the sole
        # visible text) must be gone -- Russian title "Короткие видео" instead
        r = self.client.get("/traffic-factory/")
        self.assertNotIn("<b>Short videos</b>", r.text)


class TestWhyThisWorksBlock(LandingV2TestCase):
    def test_heading_and_example(self):
        r = self.client.get("/traffic-factory/")
        self.assertIn("Почему это не просто генератор картинок", r.text)
        self.assertIn("не просто генерируем картинки", r.text)
        self.assertIn("силиконовой формы для аэрогриля", r.text)
        self.assertIn("Да, у меня такая же", r.text)


class TestForWhomBlock(LandingV2TestCase):
    def test_block_present(self):
        r = self.client.get("/traffic-factory/")
        self.assertIn("Кому подойдёт", r.text)
        for card in ("Селлерам Ozon/WB", "Товарам для дома и кухни",
                    "Товарам с понятной бытовой проблемой",
                    "Новым товарам, которым нужен внешний трафик",
                    "Продуктам, которые легко показать в коротком видео"):
            self.assertIn(card, r.text)


class TestBetaLimitationsBlock(LandingV2TestCase):
    def test_block_present(self):
        r = self.client.get("/traffic-factory/")
        self.assertIn("Что сейчас в beta-версии", r.text)
        for item in ("Автопостинг пока не включён.", "Соцсети подключать не нужно.",
                    "Вы получаете ZIP-пакет для ручной публикации.",
                    "Запуск генерации происходит после проверки владельцем.",
                    "AI-гипотезы можно поправить перед созданием контента."):
            self.assertIn(item, r.text)


class TestStartPageImprovedCopy(LandingV2TestCase):
    def test_start_page_copy(self):
        r = self.client.get("/traffic-factory/start")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Создать контент-пакет для товара", r.text)
        self.assertIn("beta-режиме", r.text)
        self.assertIn("После входа вы сможете загрузить фото товара", r.text)


class TestNoRawJinjaMarkers(LandingV2TestCase):
    def test_landing_clean(self):
        r = self.client.get("/traffic-factory/")
        for marker in RAW_JINJA_MARKERS:
            self.assertNotIn(marker, r.text)

    def test_start_clean(self):
        r = self.client.get("/traffic-factory/start")
        for marker in RAW_JINJA_MARKERS:
            self.assertNotIn(marker, r.text)


class TestCSSStillLinked(LandingV2TestCase):
    def test_stylesheet_link_present(self):
        r = self.client.get("/traffic-factory/")
        self.assertIn('href="/static/traffic_factory.css"', r.text)

    def test_css_file_has_new_hero_glow_rules(self):
        css = (REPO_ROOT / "api" / "static" / "traffic_factory.css").read_text(encoding="utf-8")
        self.assertIn("hero-glow", css)
        self.assertIn("sticky-cta", css)


class TestZeroExternalCallsAndNoAutoPosting(unittest.TestCase):
    def test_no_network_markers_in_templates(self):
        for name in ("landing.html", "start_gate.html"):
            src = (REPO_ROOT / "api" / "templates" / "traffic_factory" / name).read_text(encoding="utf-8")
            for marker in ("fetch(", "XMLHttpRequest", "<script", "import openai",
                          "OpenAI(", "HiggsfieldClient(", "requests.post", "httpx.post"):
                self.assertNotIn(marker, src)

    def test_dry_run_still_zero_calls(self):
        from api.media_pipeline import b2b_campaign_contract as contract
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call!")):
            plan = contract.build_campaign_dry_run(seed.DEMO_CLIENT_ID, seed.DEMO_PRODUCT_ID,
                                                    seed.DEMO_CAMPAIGN_ID, str(REPO_ROOT))
        self.assertEqual(plan["openai_calls"], 0)
        self.assertEqual(plan["higgsfield_calls"], 0)
        self.assertFalse(plan["auto_posting_triggered"])


if __name__ == "__main__":
    unittest.main()
