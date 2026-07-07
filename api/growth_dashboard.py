"""Growth dashboard: aggregates campaign manifest, the 14-day publishing plan
and the master performance tracker into ONE offline HTML page for the owner.
Pure local file I/O -- no network, no secrets, no auto-posting. Every data
source is optional: a missing file renders as an explicit "нет данных" block
instead of failing, so the dashboard is usable at any campaign stage.

Usage:
    python -m api.growth_dashboard \
        --campaign content/autopilot/coating-protect-2026-07 \
        --out dashboard/index.html
"""
from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path

OZON_SKU = "1931921872"
OZON_URL = f"https://www.ozon.ru/product/{OZON_SKU}/"
TELEGRAM_URL = "https://t.me/receptochkaru"

# Минимальный дневной KPI из docs/GROWTH_PLAN_30_DAYS.md
KPI_VIDEOS_PER_DAY = 3
KPI_DZEN_PER_DAY = 1

PLAN_RELPATH = "generated/content-factory/publishing/first-14-days-publishing-plan.json"
TRACKER_RELPATH = "generated/content-factory/performance-tracking/master-performance-tracker.json"


def _load_json(path: Path):
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_campaign_data(campaign_dir: str, repo_root: str = ".") -> dict:
    base = Path(repo_root) / campaign_dir
    return {
        "campaign_dir": str(base),
        "manifest": _load_json(base / "campaign_manifest.json"),
        "plan": _load_json(base / PLAN_RELPATH),
        "tracker": _load_json(base / TRACKER_RELPATH),
    }


def _int_or_zero(value) -> int:
    try:
        return int(str(value).strip() or 0)
    except (TypeError, ValueError):
        return 0


def summarize_tracker(tracker: dict | None) -> dict:
    """KPI totals over tracker rows. Empty string metrics count as 0 (not yet
    filled in by the owner) -- the dashboard never invents numbers."""
    summary = {
        "total_slots": 0, "published": 0, "views_24h": 0,
        "likes_24h": 0, "clicks_24h": 0, "by_platform": {},
    }
    if not tracker:
        return summary
    rows = tracker.get("rows", [])
    summary["total_slots"] = len(rows)
    for row in rows:
        published = row.get("publish_status") == "published"
        if published:
            summary["published"] += 1
        summary["views_24h"] += _int_or_zero(row.get("views_24h"))
        summary["likes_24h"] += _int_or_zero(row.get("likes_24h"))
        summary["clicks_24h"] += _int_or_zero(row.get("clicks_24h"))
        platform = row.get("platform", "?")
        p = summary["by_platform"].setdefault(
            platform, {"slots": 0, "published": 0, "views_24h": 0})
        p["slots"] += 1
        if published:
            p["published"] += 1
        p["views_24h"] += _int_or_zero(row.get("views_24h"))
    return summary


def current_plan_day(plan: dict | None) -> int | None:
    """First plan day that still has an unpublished video -- «что делать сегодня»."""
    if not plan:
        return None
    for day in plan.get("days", []):
        for video in day.get("videos", []):
            if video.get("publish_status") != "published":
                return day.get("day")
    days = plan.get("days", [])
    return days[-1].get("day") if days else None


def collect_approvals(manifest: dict | None) -> list[str]:
    """Everything explicitly waiting on the owner, straight from the manifest."""
    if not manifest:
        return []
    items = []
    status = manifest.get("status")
    if status and status.startswith("awaiting"):
        items.append(f"Статус кампании: {status}")
    required = manifest.get("approval_required_for")
    if required:
        items.append(f"Требует подтверждения: {required}")
    for scene, info in (manifest.get("scene_status") or {}).items():
        anim = info.get("animation_status", "")
        if "rejected" in anim or "await" in anim:
            reason = info.get("animation_reject_reason", "")
            items.append(f"{scene}: {anim}" + (f" — {reason}" if reason else ""))
    items.extend(f"Открытый вопрос: {q}" for q in manifest.get("unresolved_questions", []))
    return items


def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def _kpi_card(label: str, value, target=None) -> str:
    target_html = f'<div class="target">цель: {_esc(target)}</div>' if target is not None else ""
    return (f'<div class="card"><div class="value">{_esc(value)}</div>'
            f'<div class="label">{_esc(label)}</div>{target_html}</div>')


def _today_section(plan: dict | None) -> str:
    day_no = current_plan_day(plan)
    if not plan or day_no is None:
        return '<p class="empty">Нет плана публикаций — сгенерируйте publishing plan.</p>'
    day = next((d for d in plan.get("days", []) if d.get("day") == day_no), None)
    if not day:
        return '<p class="empty">План пуст.</p>'
    rows = []
    for video in day.get("videos", []):
        status = video.get("publish_status", "not_published")
        rows.append(
            f'<tr class="{_esc(status)}"><td>{_esc(video.get("posting_time"))}</td>'
            f'<td>видео</td><td>{_esc(video.get("hook"))}</td>'
            f'<td>{_esc(video.get("native_platform"))} + кросспост</td>'
            f'<td>{_esc(status)}</td></tr>')
    for article in day.get("dzen_articles", []) or []:
        status = article.get("publish_status", "not_published")
        rows.append(
            f'<tr class="{_esc(status)}"><td>{_esc(article.get("posting_time"))}</td>'
            f'<td>Дзен</td><td>{_esc(article.get("title") or article.get("article_id"))}</td>'
            f'<td>dzen</td><td>{_esc(status)}</td></tr>')
    return (f'<p>День плана: <b>{day_no}</b> (первый день с неопубликованными слотами)</p>'
            '<table><tr><th>Время</th><th>Тип</th><th>Хук/тема</th><th>Площадки</th>'
            '<th>Статус</th></tr>' + "".join(rows) + "</table>")


def _plan_overview_section(plan: dict | None) -> str:
    if not plan:
        return '<p class="empty">Нет плана публикаций.</p>'
    rows = []
    for day in plan.get("days", []):
        videos = day.get("videos", [])
        published = sum(1 for v in videos if v.get("publish_status") == "published")
        rows.append(f'<tr><td>{_esc(day.get("day"))}</td><td>{len(videos)}</td>'
                    f'<td>{published}</td><td>{len(videos) - published}</td></tr>')
    return ('<table><tr><th>День</th><th>Видео в плане</th><th>Опубликовано</th>'
            '<th>Осталось</th></tr>' + "".join(rows) + "</table>")


def _approvals_section(manifest: dict | None) -> str:
    approvals = collect_approvals(manifest)
    if not approvals:
        return '<p class="empty">Нет действий, ожидающих подтверждения.</p>'
    return "<ul>" + "".join(f"<li>{_esc(a)}</li>" for a in approvals) + "</ul>"


def _platform_section(summary: dict) -> str:
    if not summary["by_platform"]:
        return '<p class="empty">Трекер пуст — метрики появятся после первых публикаций.</p>'
    rows = "".join(
        f"<tr><td>{_esc(name)}</td><td>{p['slots']}</td><td>{p['published']}</td>"
        f"<td>{p['views_24h']}</td></tr>"
        for name, p in sorted(summary["by_platform"].items()))
    return ('<table><tr><th>Площадка</th><th>Слотов</th><th>Опубликовано</th>'
            '<th>Просмотры 24ч</th></tr>' + rows + "</table>")


def render_dashboard_html(data: dict, generated_at: str | None = None) -> str:
    manifest = data.get("manifest")
    plan = data.get("plan")
    tracker = data.get("tracker")
    summary = summarize_tracker(tracker)
    generated_at = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    campaign_code = (manifest or {}).get("campaign_code") or Path(data["campaign_dir"]).name
    status = (manifest or {}).get("status", "манифест не найден")
    plan_days = len((plan or {}).get("days", []))

    kpi_cards = "".join([
        _kpi_card("статус кампании", status),
        _kpi_card("опубликовано слотов", f"{summary['published']} / {summary['total_slots']}"),
        _kpi_card("видео в день", KPI_VIDEOS_PER_DAY, target=f"{KPI_VIDEOS_PER_DAY}/день"),
        _kpi_card("просмотры 24ч (сумма)", summary["views_24h"]),
        _kpi_card("клики 24ч (сумма)", summary["clicks_24h"]),
        _kpi_card("дней в плане", plan_days),
    ])

    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>Growth Dashboard — {_esc(campaign_code)}</title>
<style>
 body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px;
        background:#f6f7f9; color:#1c1e21; }}
 h1 {{ font-size: 22px; }} h2 {{ font-size: 17px; margin-top: 28px; }}
 .cards {{ display:flex; flex-wrap:wrap; gap:12px; }}
 .card {{ background:#fff; border-radius:10px; padding:14px 18px; min-width:150px;
         box-shadow:0 1px 3px rgba(0,0,0,.08); }}
 .card .value {{ font-size:20px; font-weight:700; }}
 .card .label {{ font-size:12px; color:#65676b; margin-top:4px; }}
 .card .target {{ font-size:11px; color:#8a8d91; }}
 table {{ border-collapse:collapse; background:#fff; width:100%;
         box-shadow:0 1px 3px rgba(0,0,0,.08); }}
 th, td {{ text-align:left; padding:7px 10px; border-bottom:1px solid #eceef0;
          font-size:13px; }}
 th {{ background:#f0f2f5; }}
 tr.published td {{ color:#31a24c; }}
 tr.not_published td {{ }}
 .empty {{ color:#8a8d91; }}
 .approvals {{ background:#fff7e6; border:1px solid #f0d9a8; border-radius:10px;
              padding:4px 16px; }}
 .links a {{ margin-right: 16px; }}
 footer {{ margin-top:32px; font-size:11px; color:#8a8d91; }}
</style></head><body>
<h1>Growth Dashboard — {_esc(campaign_code)}</h1>
<p>Сгенерировано: {_esc(generated_at)} · товар Ozon арт. {OZON_SKU}</p>
<div class="links">
  <a href="{OZON_URL}">Карточка Ozon</a>
  <a href="{TELEGRAM_URL}">Telegram «Умная готовка»</a>
  <a href="../{_esc(Path(data['campaign_dir']).as_posix())}">Папка кампании</a>
</div>
<h2>KPI</h2><div class="cards">{kpi_cards}</div>
<h2>⚠️ Ждёт твоего подтверждения</h2>
<div class="approvals">{_approvals_section(manifest)}</div>
<h2>Задачи на сегодня</h2>{_today_section(plan)}
<h2>План публикаций по дням</h2>{_plan_overview_section(plan)}
<h2>Метрики по площадкам</h2>{_platform_section(summary)}
<footer>Локальный отчёт. Ничего не публикует и не отправляет — только читает файлы
кампании. Публикация, платные API и реклама — только по явному подтверждению
владельца (docs/GROWTH_PLAN_30_DAYS.md).</footer>
</body></html>"""


def write_dashboard(campaign_dir: str, repo_root: str = ".",
                    out_path: str | None = None) -> str:
    data = load_campaign_data(campaign_dir, repo_root)
    out = Path(out_path) if out_path else Path(repo_root) / "dashboard" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_dashboard_html(data), encoding="utf-8")
    return str(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Собрать offline growth-dashboard (HTML)")
    parser.add_argument("--campaign", required=True,
                        help="Путь к папке кампании относительно repo root")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--out", default=None,
                        help="Куда писать HTML (по умолчанию dashboard/index.html)")
    args = parser.parse_args(argv)
    out = write_dashboard(args.campaign, args.repo_root, args.out)
    print(f"dashboard written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
