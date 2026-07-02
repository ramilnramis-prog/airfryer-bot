"""Пакетный локальный клиент поверх УЖЕ существующего HTTP API реестра.

Ничего не меняет в схеме БД и не добавляет новых endpoint'ов — только вызывает
существующие GET /registry/publications/{code}/summary и
POST /registry/metric-snapshots (см. api/registry.py). Только stdlib
(argparse, json, urllib.request) — новых зависимостей нет.

Формат входного JSON — один снимок времени на весь пакет (см.
api/examples/metric_snapshots.template.json):

    {
      "schema_version": 1,
      "captured_at": "2026-07-02T18:30:00Z",
      "snapshots": [
        {"publication_code": "...", "source": "youtube_shorts",
         "views": 0, "likes": 0, "comments": 0, "shares": null, "saves": null}
      ]
    }

Правила валидации (проверяются ДО любой отправки, весь пакет целиком):
  - publication_code и source обязательны, непустые строки;
  - captured_at (общий для пакета) — валидный UTC ISO8601 'YYYY-MM-DDTHH:MM:SSZ';
  - неизвестные поля внутри snapshot-элемента -> ошибка (не молча игнорируются);
  - null = показатель неизвестен (сохранится как NULL); 0 = фактический ноль;
  - отрицательные числа запрещены;
  - source должен совпадать с channel_code найденной публикации (проверяется по
    сети, если передан --base-url);
  - один невалидный элемент -> ошибка на весь запуск, ни один snapshot не уходит.

Идемпотентность дублей обеспечивает СЕРВЕР (UNIQUE(publication_id, source,
captured_at) в metric_snapshots, см. api/migrations/0001_init_registry.sql) —
клиент её не переизобретает, а просто показывает created/existing из ответа API.

Запуск:
    python -m api.import_metrics_via_api <path.json>
        -> офлайн dry-run (формат/типы/отрицательные числа), без сети.

    python -m api.import_metrics_via_api <path.json> --base-url https://host
        -> dry-run + чтение API: проверяет существование публикации и
           соответствие source/channel. POST не выполняется.

    python -m api.import_metrics_via_api <path.json> --base-url https://host --apply
        -> после успешной проверки всего пакета отправляет snapshots через
           существующий POST /registry/metric-snapshots.

API-ключ читается ТОЛЬКО из переменной окружения API_KEY (обязательна, если
передан --base-url — /registry/* требует X-API-Key даже для GET, см. api/auth.py).
Ключ никогда не принимается аргументом командной строки и никогда не печатается.

Если сеть оборвётся в середине --apply: скрипт останавливается на первой ошибке
и печатает, что уже было отправлено. Повторный запуск того же файла безопасен —
сервер идемпотентен по (publication_id, source, captured_at), уже принятые
snapshot'ы вернутся как existing, не задвоятся.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
import urllib.request
import urllib.error

_ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_METRIC_KEYS = ("views", "likes", "comments", "shares", "saves")
_ALLOWED_SNAPSHOT_KEYS = {"publication_code", "source"} | set(_METRIC_KEYS)


def _is_valid_iso_utc(value):
    if not isinstance(value, str) or not _ISO_UTC_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def load_batch(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _validate_item(item, prefix):
    """Офлайн-проверки одного snapshot-элемента (без сети). Возвращает список ошибок."""
    if not isinstance(item, dict):
        return [f"{prefix}: должен быть объектом"]
    errors = []
    unknown = set(item) - _ALLOWED_SNAPSHOT_KEYS
    if unknown:
        errors.append(f"{prefix}: неизвестные поля {sorted(unknown)}")
    pub_code = item.get("publication_code")
    if not isinstance(pub_code, str) or not pub_code:
        errors.append(f"{prefix}: publication_code обязателен и должен быть непустой строкой")
    source = item.get("source")
    if not isinstance(source, str) or not source:
        errors.append(f"{prefix}: source обязателен и должен быть непустой строкой")
    for k in _METRIC_KEYS:
        if k not in item:
            continue  # отсутствующий показатель = не придумываем, эквивалентно null
        v = item[k]
        if v is None:
            continue  # явно неизвестен -> NULL, это разрешено
        if isinstance(v, bool) or not isinstance(v, int):
            errors.append(f"{prefix}.{k}: должно быть целым числом или null, получено {v!r}")
        elif v < 0:
            errors.append(f"{prefix}.{k}: отрицательные значения запрещены ({v!r})")
    return errors


class ApiError(RuntimeError):
    """HTTP-запрос к реестру вернул ошибку (не 2xx) или сеть недоступна."""


def _request(base_url, method, path, api_key, payload=None, timeout=10):
    body = None
    headers = {"X-API-Key": api_key}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        base_url.rstrip("/") + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"detail": raw}
    except urllib.error.URLError as e:
        raise ApiError(f"не удалось соединиться с {base_url}: {e.reason}") from e


def resolve_publication(base_url, api_key, publication_code):
    """GET /registry/publications/{code}/summary (уже существующий endpoint).
    Возвращает (publication_id, channel_code, error_message)."""
    status, data = _request(
        base_url, "GET", f"/registry/publications/{publication_code}/summary", api_key)
    if status == 404:
        return None, None, f"публикация не найдена: {publication_code}"
    if status != 200:
        return None, None, f"{publication_code}: API вернул {status}: {data.get('detail', data)}"
    pub = data.get("publication") or {}
    channel = data.get("channel") or {}
    return pub.get("id"), channel.get("code"), None


def plan_batch(data, base_url, api_key):
    """Проверяет пакет целиком (офлайн +, если есть base_url, по сети) и строит план
    отправки. НИ ОДНОГО POST не выполняет. Возвращает (planned, errors)."""
    errors = []
    planned = []
    if not isinstance(data, dict):
        return planned, ["корневой элемент JSON должен быть объектом"]
    if data.get("schema_version") != 1:
        errors.append(f"schema_version должен быть 1, получено {data.get('schema_version')!r}")
    captured_at = data.get("captured_at")
    captured_at_ok = _is_valid_iso_utc(captured_at)
    if not captured_at_ok:
        errors.append(
            f"captured_at должен быть валидным UTC ISO8601 'YYYY-MM-DDTHH:MM:SSZ': {captured_at!r}")
    snapshots = data.get("snapshots")
    if not isinstance(snapshots, list) or not snapshots:
        errors.append("snapshots должен быть непустым списком")
        return planned, errors

    for i, item in enumerate(snapshots):
        prefix = f"snapshots[{i}]"
        item_errors = _validate_item(item, prefix)
        if item_errors:
            errors.extend(item_errors)
            continue  # заведомо невалидный элемент по сети не резолвим
        pub_code = item["publication_code"]
        source = item["source"]
        pub_id = None
        if base_url:
            pub_id, channel_code, err = resolve_publication(base_url, api_key, pub_code)
            if err:
                errors.append(f"{prefix}: {err}")
                continue
            if channel_code != source:
                errors.append(
                    f"{prefix}: source={source!r} не совпадает с channel_code "
                    f"публикации ({channel_code!r})")
                continue
        if not captured_at_ok:
            continue  # общий captured_at сломан -> этот snapshot всё равно не уйдёт
        planned.append({
            "publication_code": pub_code,
            "publication_id": pub_id,
            "source": source,
            "captured_at": captured_at,
            "metrics": {k: item.get(k) for k in _METRIC_KEYS},
        })
    return planned, errors


def apply_batch(planned, base_url, api_key):
    """Отправляет snapshots через существующий POST /registry/metric-snapshots.
    Останавливается на первой ошибке; уже обработанные элементы остаются в results
    (повторный запуск всего файла безопасен благодаря идемпотентности сервера)."""
    results = []
    for item in planned:
        payload = {
            "publication_id": item["publication_id"],
            "source": item["source"],
            "captured_at": item["captured_at"],
            **item["metrics"],
        }
        status, data = _request(base_url, "POST", "/registry/metric-snapshots", api_key, payload)
        if status != 200:
            raise ApiError(f"{item['publication_code']}: отправка не удалась ({status}): {data}")
        results.append((item["publication_code"], bool(data.get("created"))))
    return results


def _print_report(data, planned, errors, base_url):
    print(f"schema_version={data.get('schema_version')} captured_at={data.get('captured_at')}")
    print(f"planned={len(planned)} errors={len(errors)}")
    for p in planned:
        print(f"  OK   {p['publication_code']:<45} source={p['source']:<16} "
              f"pub_id={p['publication_id']} metrics={p['metrics']}")
    for e in errors:
        print(f"  ERR  {e}")
    if not base_url:
        print("(сетевые проверки пропущены: --base-url не передан — существование "
              "публикации и соответствие source/channel НЕ проверены)")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Пакетная запись ручных замеров через существующий registry API "
                     "(без изменений схемы/endpoint'ов).")
    parser.add_argument("json_path", help="путь к JSON-файлу с snapshots (см. Step 3 формата)")
    parser.add_argument("--base-url", default=None,
                        help="базовый URL API реестра; без него — только офлайн dry-run")
    parser.add_argument("--apply", action="store_true",
                        help="реально отправить snapshots (требует --base-url и API_KEY в окружении)")
    args = parser.parse_args(argv)

    if args.apply and not args.base_url:
        print("ошибка: --apply требует --base-url", file=sys.stderr)
        return 2

    api_key = os.environ.get("API_KEY", "")
    if args.base_url and not api_key:
        print("ошибка: переменная окружения API_KEY не задана (обязательна для "
              "обращения к /registry/*, включая чтение)", file=sys.stderr)
        return 2

    try:
        data = load_batch(args.json_path)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ошибка чтения {args.json_path}: {e}", file=sys.stderr)
        return 2

    try:
        planned, errors = plan_batch(data, args.base_url, api_key)
    except ApiError as e:
        print(f"ошибка сети при проверке пакета: {e}", file=sys.stderr)
        return 1

    _print_report(data, planned, errors, args.base_url)

    if errors:
        print("\nесть ошибки валидации — пакет НЕ отправлен", file=sys.stderr)
        return 1

    if not args.apply:
        print("\ndry-run: ничего не отправлено (передайте --base-url и --apply для записи)")
        return 0

    try:
        results = apply_batch(planned, args.base_url, api_key)
    except ApiError as e:
        print(f"\nостановлено при отправке: {e}", file=sys.stderr)
        print("повторный запуск этого же файла безопасен: сервер идемпотентен по "
              "(publication_id, source, captured_at)", file=sys.stderr)
        return 1

    created = sum(1 for _, was_created in results if was_created)
    existing = len(results) - created
    print(f"\napply завершён: created={created} existing={existing}")
    for code, was_created in results:
        print(f"  {'created' if was_created else 'existing'}  {code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
