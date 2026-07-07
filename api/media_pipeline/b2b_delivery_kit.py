"""B2B delivery kit: what the agency hands the SELLER at the end of a
campaign. Builds the delivery/ folder structure + OWNER-README.md +
DELIVERY-KIT.zip. Pure local file I/O -- no network calls, no auto-posting.

At this MVP-skeleton step no real generation has happened yet (dry-run
only), so most delivery/ subfolders will be empty except OWNER-README.md --
that's expected; this module designs the SHAPE clients receive, the actual
population happens once real generation is wired up in a later step.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from . import b2b_storage as st

DELIVERY_SUBDIRS = ("upload-ready", "videos", "dzen", "images", "metadata",
                    "publishing-plan", "performance-tracking")


def build_owner_readme(product: "st.Product", campaign: "st.Campaign") -> str:
    return f"""# Ваш комплект контента -- {product.product_name}

Это готовый комплект коротких рекламных роликов и статей для продвижения
вашего товара во внешнем трафике. **Публикация -- вручную**, мы не постим
автоматически без вашего согласия.

## 1. Что внутри

- `upload-ready/` -- готовые к загрузке ролики, разложенные по дням публикации
- `videos/` -- все исходные видео-файлы (MP4, вертикальные 9:16)
- `dzen/` -- статьи для Дзена (текст + картинки), готовые к копированию
- `images/` -- изображения к статьям и роликам
- `metadata/` -- заголовки, описания, хэштеги, CTA для каждой площадки
- `publishing-plan/` -- план публикаций по дням и времени
- `performance-tracking/` -- таблицы для внесения результатов после публикации

## 2. Какие ролики куда выкладывать

Смотрите `publishing-plan/` -- там расписан план по дням: время публикации,
на какую площадку (YouTube Shorts / Instagram Reels / TikTok / VK Клипы),
какой ролик выкладывать.

## 3. Где descriptions (заголовки/подписи/хэштеги)

В папке `metadata/` -- для каждого ролика отдельный файл с заголовком,
подписью, хэштегами и CTA под каждую площадку.

## 4. Где статьи

В папке `dzen/` -- готовые статьи для Дзена с картинками, тегами и текстом
закреплённого комментария, готовые для копирования.

## 5. Куда вставить ссылки

После публикации вставляйте ссылку в файл-трекер в `performance-tracking/`
(колонка `published_url`) для соответствующего ролика/статьи.

## 6. Как смотреть performance tracker

Откройте `performance-tracking/master-performance-tracker.csv` в Excel или
Google Таблицах. Через 24 часа после публикации занесите просмотры/лайки/
комментарии/сохранения в тот же файл (или в дневные файлы, если они есть).

---
Кампания: {campaign.campaign_id} | цель: {campaign.campaign_goal} |
статус: {campaign.status} | площадки: {', '.join(campaign.platforms)}

Товар: {product.product_name} ({product.marketplace} / {product.marketplace_article})
"""


def build_delivery_kit_structure(client_id: str, product_id: str, campaign_id: str,
                                 repo_root: str = ".") -> dict:
    product = st.load_product(client_id, product_id, repo_root)
    campaign = st.load_campaign(client_id, product_id, campaign_id, repo_root)
    gen_dir = st.campaign_generated_dir(client_id, product_id, campaign_id, repo_root)
    delivery_dir = gen_dir / "delivery"
    for sub in DELIVERY_SUBDIRS:
        (delivery_dir / sub).mkdir(parents=True, exist_ok=True)

    readme_path = delivery_dir / "OWNER-README.md"
    readme_path.write_text(build_owner_readme(product, campaign), encoding="utf-8")

    return {"delivery_dir": str(delivery_dir), "readme_path": str(readme_path),
           "subdirs": list(DELIVERY_SUBDIRS)}


def build_delivery_kit_zip(client_id: str, product_id: str, campaign_id: str,
                           repo_root: str = ".", out_path=None) -> dict:
    struct = build_delivery_kit_structure(client_id, product_id, campaign_id, repo_root)
    delivery_dir = Path(struct["delivery_dir"])
    out = Path(out_path) if out_path else (delivery_dir / "DELIVERY-KIT.zip")

    added = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(delivery_dir.rglob("*")):
            if f.is_file() and f.resolve() != out.resolve():
                arcname = str(f.relative_to(delivery_dir)).replace("\\", "/")
                zf.write(f, arcname=arcname)
                added.append(arcname)

    return {"zip_path": str(out), "files_added": len(added), "readme_path": struct["readme_path"]}
