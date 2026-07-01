"""CLI: импорт content package JSON напрямую в локальный реестр, без HTTP и без Railway.

Использует тот же код реестра (registry_db / content_package), что и API, но работает
на локальной SQLite-базе (config.DB_PATH по умолчанию, либо --db-path). Никогда не
обращается к production API.

Запуск:
    python -m api.import_content_package <путь-к-json>               # dry-run (по умолчанию)
    python -m api.import_content_package <путь-к-json> --apply       # реальная запись
    python -m api.import_content_package <путь-к-json> --apply --db-path /tmp/test.db

Dry-run ничего не пишет: проверяет форму пакета и показывает planned/existing/conflicts.
--apply выполняет ту же транзакцию, что и HTTP-эндпоинт (весь пакет или откат).
Секреты не печатаются: пакет должен их не содержать (см. content_package.validate_package).
"""
import sys
import json
import argparse

from . import registry_db as R
from . import content_package as CP


def _load_package(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def plan_import(pkg: dict) -> dict:
    """Только чтение: что случилось бы при --apply. Не открывает запись/транзакцию."""
    CP.validate_package(pkg)

    product_code = pkg["product"]["product_code"]
    content_in = pkg["content"]

    plan = {
        "planned": {"content": False, "hooks": [], "publications": []},
        "existing": {"content": False, "hooks": [], "publications": []},
        "conflicts": [],
    }

    conn = R._connect()
    try:
        product = conn.execute(
            "SELECT * FROM products WHERE product_code=?", (product_code,)).fetchone()
        if not product:
            plan["conflicts"].append({
                "field": "product.product_code",
                "message": f"product not found: {product_code}",
            })
            return plan

        other_owner = conn.execute(
            "SELECT id FROM contents WHERE content_code=? AND product_id!=?",
            (content_in["content_code"], product["id"])).fetchone()
        if other_owner:
            plan["conflicts"].append({
                "field": "content.content_code",
                "message": f"content_code '{content_in['content_code']}' already registered "
                           "under a different product_code",
            })
            return plan

        existing_content = conn.execute(
            "SELECT * FROM contents WHERE product_id=? AND content_code=?",
            (product["id"], content_in["content_code"])).fetchone()

        if existing_content:
            plan["existing"]["content"] = True
            if existing_content["content_type"] != content_in["content_type"]:
                plan["conflicts"].append({
                    "field": "content.content_type",
                    "message": f"existing='{existing_content['content_type']}' "
                               f"incoming='{content_in['content_type']}'",
                })
        else:
            plan["planned"]["content"] = True

        content_id = existing_content["id"] if existing_content else None
        known_hook_codes = set()
        for h in pkg.get("hooks", []):
            known_hook_codes.add(h["hook_code"])
            row = None
            if content_id is not None:
                row = conn.execute(
                    "SELECT 1 FROM hooks WHERE content_id=? AND hook_code=?",
                    (content_id, h["hook_code"])).fetchone()
            (plan["existing"]["hooks"] if row else plan["planned"]["hooks"]).append(h["hook_code"])

        for p in pkg.get("publication_drafts", []):
            ch = conn.execute(
                "SELECT 1 FROM channels WHERE code=?", (p["channel_code"],)).fetchone()
            if not ch:
                plan["conflicts"].append({
                    "field": "publication_drafts.channel_code",
                    "message": f"unknown channel_code: {p['channel_code']}",
                })
                continue
            hcode = p.get("hook_code")
            if hcode and hcode not in known_hook_codes:
                existing_hook = None
                if content_id is not None:
                    existing_hook = conn.execute(
                        "SELECT 1 FROM hooks WHERE content_id=? AND hook_code=?",
                        (content_id, hcode)).fetchone()
                if not existing_hook:
                    plan["conflicts"].append({
                        "field": "publication_drafts.hook_code",
                        "message": f"publication references unknown hook_code: {hcode}",
                    })
                    continue
            row = conn.execute(
                "SELECT 1 FROM publications WHERE publication_code=?",
                (p["publication_code"],)).fetchone()
            (plan["existing"]["publications"] if row else plan["planned"]["publications"]).append(
                p["publication_code"])
    finally:
        conn.close()

    return plan


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Import a content package into the local registry (no HTTP, no Railway).")
    parser.add_argument("path", help="path to content package JSON file")
    parser.add_argument("--apply", action="store_true",
                         help="write to the database (default is dry-run, no writes)")
    parser.add_argument("--db-path", default=None,
                         help="use this SQLite file instead of config.DB_PATH")
    args = parser.parse_args(argv)

    if args.db_path:
        R.DB_PATH = args.db_path

    if not R.schema_present():
        print("registry schema not migrated; run: python -m api.registry_db", file=sys.stderr)
        return 2

    try:
        pkg = _load_package(args.path)
    except (OSError, json.JSONDecodeError) as e:
        print(f"failed to read package: {e}", file=sys.stderr)
        return 2

    try:
        if args.apply:
            result = CP.import_package(pkg)
            print(json.dumps({"mode": "apply", **result}, ensure_ascii=False, indent=2))
            return 0
        else:
            plan = plan_import(pkg)
            print(json.dumps({"mode": "dry-run", **plan}, ensure_ascii=False, indent=2))
            return 1 if plan["conflicts"] else 0
    except CP.PackageError as e:
        print(json.dumps({"error": str(e), "field": e.field}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
