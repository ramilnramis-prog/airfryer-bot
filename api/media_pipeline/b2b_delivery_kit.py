"""B2B delivery kit: what the agency hands the SELLER at the end of a
campaign. Builds the delivery/ folder structure + explanatory markdown docs
+ DELIVERY-KIT.zip. Pure local file I/O -- no network calls, no auto-posting.

At this MVP-skeleton step no real generation has happened yet, so this is a
MOCK/TEMPLATE kit: it always recomputes a fresh campaign-dry-run plan (same
fail-closed B2B_PRODUCT_REFERENCE_ONLY_POLICY gate as
b2b_campaign_contract.build_campaign_dry_run) and describes, in plain
language, what WILL be produced -- it does not copy or generate any real
video/image content. For the demo campaign specifically, the legacy
adapter manifest (if present) is referenced by path only, never copied --
this kit stays small regardless of how much legacy content exists.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from . import b2b_storage as st
from . import b2b_reference_policy as pol
from .b2b_campaign_contract import build_campaign_dry_run

DELIVERY_SUBDIRS = ("upload-ready", "publishing-plan", "performance-tracking")


def build_owner_readme(product: "st.Product", campaign: "st.Campaign") -> str:
    return f"""# Ваш комплект контента -- {product.product_name}

## 1. Что мы получили от вас

Название товара, ссылку на карточку маркетплейса ({product.marketplace} /
{product.marketplace_article}), описание, портрет аудитории, основную боль
клиента и загруженные вами фотографии товара ("product references").

## 2. Что будет создано

По плану кампании (см. `CAMPAIGN-PLAN.md`): короткие вертикальные ролики
для нескольких площадок, статьи для Дзена с картинками, план публикаций по
дням. **Публикация -- вручную**, мы не постим автоматически без вашего
согласия (см. `content/b2b/AUTOPOSTING-ROADMAP.md` в репозитории агентства
для деталей будущей авто-публикации).

## 3. Что такое "product references"

Это одобренные вами фотографии товара (front/top/side/detail/packaging),
которые агентство использует как единственный источник внешнего вида
товара при генерации кадров. Никакие другие изображения товара не
используются.

## 4. Почему сгенерированные материалы никогда не становятся референсами

Каждый сгенерированный кадр/видео -- это ВЫХОД пайплайна, не вход. Если
разрешить сгенерированным изображениям становиться новыми референсами,
ошибки/искажения будут накапливаться от кампании к кампании. Поэтому
референсом может быть только то, что вы сами загрузили и одобрили --
это правило соблюдается автоматически (см. `REFERENCE-POLICY.md`).

## 5. Как выглядит публикация вручную

Вы (или ваш SMM) открываете `upload-ready/`, берёте готовый ролик/статью
по расписанию из `publishing-plan/`, вручную загружаете его на нужную
площадку (YouTube Shorts / Instagram Reels / TikTok / VK Клипы / Дзен) и
вставляете получившуюся ссылку в файл-трекер `performance-tracking/`
(колонка `published_url`) -- туда же через 24-48 часов вносятся
просмотры/лайки/комментарии для последующего анализа. Файл
`performance-tracking/master-performance-tracker.csv` открывается в Excel
или Google Таблицах.

## 6. Что дальше

- Актуальные метрики -> `performance-tracking/master-performance-tracker.csv`
- Общий план кампании и оценка стоимости -> `CAMPAIGN-PLAN.md`
- Что именно значит "3+ одобренных референса" -> `REFERENCE-POLICY.md`
- Сводка по товару -> `PRODUCT-SUMMARY.md`

---
Кампания: {campaign.campaign_id} | цель: {campaign.campaign_goal} |
статус: {campaign.status} | площадки: {', '.join(campaign.platforms)}

Товар: {product.product_name} ({product.marketplace} / {product.marketplace_article})
"""


def build_product_summary_md(product: "st.Product") -> str:
    return f"""# Сводка по товару

- **Название:** {product.product_name}
- **Маркетплейс:** {product.marketplace}
- **Артикул:** {product.marketplace_article}
- **Ссылка:** {product.marketplace_url}
- **Категория:** {product.category}
- **Целевая аудитория:** {product.target_audience}
- **Основная боль:** {product.main_pain}
- **Описание:** {product.product_description}
"""


def build_campaign_plan_md(plan: dict) -> str:
    campaign = plan["campaign"]
    lines = [
        "# План кампании (dry-run)",
        "",
        f"- **Кампания:** {campaign['campaign_id']}",
        f"- **Цель:** {campaign['campaign_goal']}",
        f"- **Площадки:** {', '.join(plan['platforms'])}",
        f"- **Статус:** {plan['status']}",
        "",
        "## Контентный пакет (план, ничего ещё не сгенерировано)",
        "",
        f"- Сцен запланировано: {len(plan['planned_scenes'])}",
        f"- Видео-вариантов запланировано: {plan['planned_video_variants']['total_variants']}",
        f"- Статей для Дзена запланировано: {plan['planned_dzen_articles']['total_articles']}",
        f"- Изображений на статью Дзена: {plan['planned_dzen_articles']['images_per_article']}",
        f"- Дней публикации в очереди: "
        f"{'да' if plan['planned_publishing_queue']['video_posting_times'] else 'нет'} "
        f"(video) / "
        f"{'да' if plan['planned_publishing_queue']['dzen_posting_times'] else 'нет'} (dzen)",
        "",
        "## Оценка стоимости",
        "",
        f"- Оценка вызовов OpenAI Images (если запустить реальную генерацию): "
        f"{plan['estimated_image_calls']}",
        f"- Оценка локальных рендеров MP4: {plan['estimated_video_renders']}",
        f"- Оценка стоимости: ${plan['estimated_cost_usd']}",
        "",
        "## Статус на текущий момент",
        "",
        f"- status: {plan['status']} -- ни один OpenAI/Higgsfield вызов ещё не сделан "
        f"(openai_calls={plan['openai_calls']}, higgsfield_calls={plan['higgsfield_calls']}, "
        f"external_api_calls={plan['external_api_calls']}, "
        f"auto_posting_triggered={plan['auto_posting_triggered']})",
    ]
    return "\n".join(lines) + "\n"


def build_reference_policy_md(plan: dict) -> str:
    refs = plan["references_used"]
    lines = [
        "# Политика product references",
        "",
        f"Минимум одобренных референсов для запуска генерации: "
        f"{pol.MIN_APPROVED_REFERENCES}.",
        "",
        f"Использовано одобренных референсов в этом плане: {len(refs)}.",
        "",
        "## Использованные референсы",
        "",
    ]
    for r in refs:
        lines.append(f"- `{r['file_path']}` (role={r['role']}, notes={r['notes'] or '-'})")
    lines += [
        "",
        "## Проверка на запрещённые пути (forbidden_refs_scan)",
        "",
        f"- scanned: {plan['forbidden_refs_scan']['scanned']}",
        f"- forbidden_found: {plan['forbidden_refs_scan']['forbidden_found']}",
    ]
    return "\n".join(lines) + "\n"


def build_next_steps_md(product: "st.Product", campaign: "st.Campaign") -> str:
    return f"""# Что дальше

1. Проверьте `PRODUCT-SUMMARY.md` и `CAMPAIGN-PLAN.md` -- всё верно?
2. Если нужно что-то поправить в товаре/референсах -- вернитесь на страницу
   товара в админке (`/b2b/products/{product.product_id}`) и обновите
   данные/одобрение референсов.
3. Реальная генерация контента запускается агентством вручную отдельной
   командой (не автоматически из этого комплекта) -- по готовности будет
   отдельный делайвери с реальными видео/статьями в `upload-ready/`.
4. После публикации вручную заносите ссылки и метрики в
   `performance-tracking/master-performance-tracker.csv`.

Статус кампании на момент сборки этого комплекта: {campaign.status}.
"""


def build_delivery_kit_structure(client_id: str, product_id: str, campaign_id: str,
                                 repo_root: str = ".") -> dict:
    client = st.load_client(client_id, repo_root)
    product = st.load_product(client_id, product_id, repo_root)
    campaign = st.load_campaign(client_id, product_id, campaign_id, repo_root)

    # Fail-closed reference gate (via build_campaign_dry_run) -- raises
    # B2BReferencePolicyError if approved references are missing/insufficient;
    # never builds a delivery kit for a campaign that couldn't be planned.
    plan = build_campaign_dry_run(client_id, product_id, campaign_id, repo_root)

    gen_dir = st.campaign_generated_dir(client_id, product_id, campaign_id, repo_root)
    delivery_dir = gen_dir / "delivery"
    for sub in DELIVERY_SUBDIRS:
        (delivery_dir / sub).mkdir(parents=True, exist_ok=True)

    paths = {}
    paths["readme_path"] = delivery_dir / "OWNER-README.md"
    paths["readme_path"].write_text(build_owner_readme(product, campaign), encoding="utf-8")

    paths["product_summary_path"] = delivery_dir / "PRODUCT-SUMMARY.md"
    paths["product_summary_path"].write_text(build_product_summary_md(product), encoding="utf-8")

    paths["campaign_plan_path"] = delivery_dir / "CAMPAIGN-PLAN.md"
    paths["campaign_plan_path"].write_text(build_campaign_plan_md(plan), encoding="utf-8")

    paths["reference_policy_path"] = delivery_dir / "REFERENCE-POLICY.md"
    paths["reference_policy_path"].write_text(build_reference_policy_md(plan), encoding="utf-8")

    paths["next_steps_path"] = delivery_dir / "NEXT-STEPS.md"
    paths["next_steps_path"].write_text(build_next_steps_md(product, campaign), encoding="utf-8")

    return {
        "delivery_dir": str(delivery_dir),
        "subdirs": list(DELIVERY_SUBDIRS),
        **{k: str(v) for k, v in paths.items()},
    }


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
