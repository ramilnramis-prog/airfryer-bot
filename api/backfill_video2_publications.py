"""Локальный, идемпотентный backfill публикаций видео 2 «Форма для аэрогриля»
(content_code=video2-forma-ad, хуки A/B/C) в единый реестр (api/registry_db.py).

НИЧЕГО не публикует и не обращается ни к каким внешним API — только читает/пишет
локальную SQLite реестра, и только при явном --apply. По умолчанию — dry-run
(ничего не пишет, только показывает план).

Требует, чтобы product/content/hooks A/B/C уже были засеяны:
    python -m api.seed_registry --yes

Факты (подтверждены владельцем 2026-07-01, см. project memory project-video2-forma-ad):
  Hook A: status=published, published_date=2026-06-30, точное время неизвестно -> published_at=NULL
  Hook B: status=published, published_date=2026-07-01, точное время неизвестно -> published_at=NULL
  Hook C: status=scheduled, scheduled_at=2026-07-01T18:30:00Z (=21:30 МСК, подтверждено владельцем)
Каналы (одинаковые для всех трёх хуков): youtube_shorts, instagram_reels, tiktok, vk_video.
Канал vk_video ранее в реестре отсутствовал — создаётся этим скриптом, если его ещё нет.

После фактического выхода C статус на published НЕ переключается автоматически — это
отдельный, явно подтверждённый шаг (update_publication), не часть этого backfill'а.

Запуск:
    python -m api.backfill_video2_publications                                  # dry-run, config.DB_PATH
    python -m api.backfill_video2_publications --db-path /tmp/test.db --apply   # запись на тестовую БД
    python -m api.backfill_video2_publications --apply --allow-config-db --yes  # запись в config.DB_PATH

Без --apply НИКОГДА ничего не пишет. Без интерактивного input().
"""
import sys
import json
import argparse

from . import registry_db as R

PRODUCT_CODE = "airfryer-silicone-form"
CONTENT_CODE = "video2-forma-ad"

CHANNELS = ["youtube_shorts", "instagram_reels", "tiktok", "vk_video"]
CHANNEL_NAMES = {
    "youtube_shorts": "YouTube Shorts",
    "instagram_reels": "Instagram Reels",
    "tiktok": "TikTok",
    "vk_video": "VK Видео",
}

# (hook_code, status, published_date, scheduled_at) — published_at всегда NULL здесь,
# время исторической публикации A/B неизвестно и не придумывается (см. docstring модуля).
HOOK_PLAN = [
    ("A", "published", "2026-06-30", None),
    ("B", "published", "2026-07-01", None),
    ("C", "scheduled", None, "2026-07-01T18:30:00Z"),
]


class BackfillError(RuntimeError):
    """Продукт/контент/хук не найдены — сначала нужен seed. Ничего не пишем."""


def _publication_code(channel_code, hook_code):
    return f"{CONTENT_CODE}-{channel_code}-{hook_code}-v1"


def build_plan(conn):
    """Только чтение: собирает план (что уже есть / что будет создано). Не пишет в БД."""
    product = conn.execute(
        "SELECT * FROM products WHERE product_code=?", (PRODUCT_CODE,)).fetchone()
    if not product:
        raise BackfillError(
            f"product not found: {PRODUCT_CODE} — сначала выполни "
            "python -m api.seed_registry --yes")

    content = conn.execute(
        "SELECT * FROM contents WHERE product_id=? AND content_code=?",
        (product["id"], CONTENT_CODE)).fetchone()
    if not content:
        raise BackfillError(
            f"content not found: {CONTENT_CODE} — сначала выполни "
            "python -m api.seed_registry --yes")

    hook_ids = {}
    for hook_code, _status, _pdate, _sched in HOOK_PLAN:
        row = conn.execute(
            "SELECT * FROM hooks WHERE content_id=? AND hook_code=?",
            (content["id"], hook_code)).fetchone()
        if not row:
            raise BackfillError(
                f"hook not found: {hook_code} — сначала выполни "
                "python -m api.seed_registry --yes")
        hook_ids[hook_code] = row["id"]

    channels_to_create = []
    for code in CHANNELS:
        row = conn.execute("SELECT id FROM channels WHERE code=?", (code,)).fetchone()
        if not row:
            channels_to_create.append(code)

    publications = []
    for hook_code, status, published_date, scheduled_at in HOOK_PLAN:
        for channel_code in CHANNELS:
            pub_code = _publication_code(channel_code, hook_code)
            existing = conn.execute(
                "SELECT id FROM publications WHERE publication_code=?", (pub_code,)).fetchone()
            publications.append({
                "publication_code": pub_code,
                "hook_code": hook_code,
                "channel_code": channel_code,
                "status": status,
                "published_date": published_date,
                "published_at": None,
                "scheduled_at": scheduled_at,
                "already_exists": existing is not None,
            })

    return {
        "product_id": product["id"],
        "content_id": content["id"],
        "hook_ids": hook_ids,
        "channels_to_create": channels_to_create,
        "publications": publications,
    }


def apply_plan(plan):
    """Пишет: создаёт недостающий канал(ы) и публикации. Идемпотентно (create_or_get_*)."""
    created_channels = []
    for code in plan["channels_to_create"]:
        _row, created = R.create_or_get_channel(code=code, name=CHANNEL_NAMES[code])
        if created:
            created_channels.append(code)

    channel_ids = {code: R.get_channel_by_code(code)["id"] for code in CHANNELS}

    created_pubs, existing_pubs = [], []
    for item in plan["publications"]:
        _row, created = R.create_or_get_publication(
            content_id=plan["content_id"],
            channel_id=channel_ids[item["channel_code"]],
            publication_code=item["publication_code"],
            hook_id=plan["hook_ids"][item["hook_code"]],
            status=item["status"],
            published_date=item["published_date"],
            scheduled_at=item["scheduled_at"],
        )
        (created_pubs if created else existing_pubs).append(item["publication_code"])

    return {
        "created_channels": created_channels,
        "created_publications": created_pubs,
        "existing_publications": existing_pubs,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill historical/scheduled publications for video2-forma-ad hooks "
                    "A/B/C. Local SQLite only — no external calls, nothing is really published.")
    parser.add_argument("--apply", action="store_true",
                        help="write to the database (default is dry-run, no writes)")
    parser.add_argument("--db-path", default=None,
                        help="use this SQLite file instead of config.DB_PATH")
    parser.add_argument("--allow-config-db", action="store_true",
                        help="permit writing to config.DB_PATH (shared jobs.db) when --db-path "
                             "is not given; must be combined with --yes")
    parser.add_argument("--yes", action="store_true",
                        help="required together with --allow-config-db to confirm writing to "
                             "config.DB_PATH")
    args = parser.parse_args(argv)

    if args.apply and not args.db_path and not (args.allow_config_db and args.yes):
        print(
            "refusing to write: --apply requires --db-path, OR both --allow-config-db and "
            "--yes to write to config.DB_PATH", file=sys.stderr)
        return 2

    if args.db_path:
        R.DB_PATH = args.db_path

    if not R.schema_present():
        print("registry schema not migrated; run: python -m api.registry_db", file=sys.stderr)
        return 2

    conn = R._connect()
    try:
        try:
            plan = build_plan(conn)
        except BackfillError as e:
            print(str(e), file=sys.stderr)
            return 2
    finally:
        conn.close()

    if not args.apply:
        print(json.dumps({"mode": "dry-run", "db_path": str(R.DB_PATH), **plan},
                         ensure_ascii=False, indent=2))
        return 0

    result = apply_plan(plan)
    print(json.dumps({"mode": "apply", "db_path": str(R.DB_PATH), **result},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
