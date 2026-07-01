"""Единый реестр (источник истины): products -> contents -> hooks -> channels ->
publications -> metric_snapshots / commerce_snapshots / decision_records.

Живёт в ТОЙ ЖЕ SQLite-базе, что и очередь `jobs` (config.DB_PATH). Только stdlib `sqlite3`.

Идемпотентность — через СТАБИЛЬНЫЕ бизнес-коды (не зависят от изменяемых name/title):
  product_code, (product_id, content_code), (content_id, hook_code), publication_code.
Повторный create с тем же кодом возвращает существующую строку, дубли не создаются.

Время: UTC, ISO8601 'YYYY-MM-DDTHH:MM:SSZ'. Деньги: целые минорные единицы (копейки), без float.
FOREIGN KEYS включаются на КАЖДОМ соединении. busy_timeout — на случай конкуренции писателей.
Применение схемы — только явно (run_migrations); автоприменение на старте гейтится флагом в main.py.
"""
import re
import sys
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, date, timezone

from .config import DB_PATH  # ТОТ ЖЕ файл БД, что и у jobs

log = logging.getLogger("api.registry")
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), timeout=5.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")   # включаем на КАЖДОМ соединении
    c.execute("PRAGMA busy_timeout = 5000") # ждём блокировку до 5с (несколько писателей в одном процессе)
    return c


def _d(row):
    return dict(row) if row is not None else None


# ---------- миграции (версионированный SQL + schema_version, без Alembic) ----------
def run_migrations() -> None:
    """Идемпотентно применяет api/migrations/*.sql, отмечая версии в schema_version.
    Вызывается ЯВНО (python -m api.registry_db) или в тестах. На старте API — только при
    включённом флаге REGISTRY_AUTO_MIGRATE (см. main.py)."""
    c = _connect()
    try:
        c.execute(
            "CREATE TABLE IF NOT EXISTS schema_version("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        c.commit()
        applied = {r["version"] for r in c.execute("SELECT version FROM schema_version")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            try:
                ver = int(path.name.split("_", 1)[0])
            except ValueError:
                continue
            if ver in applied:
                continue
            c.executescript(path.read_text(encoding="utf-8"))
            c.execute(
                "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES(?,?)",
                (ver, now_utc()),
            )
            c.commit()
            log.info("registry migration %s applied", ver)
    finally:
        c.close()


def schema_present() -> bool:
    """True, если реестр мигрирован (есть schema_version и таблица products)."""
    c = _connect()
    try:
        c.execute("SELECT 1 FROM schema_version LIMIT 1")
        c.execute("SELECT 1 FROM products LIMIT 1")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        c.close()


# ---------- товары ----------
def create_or_get_product(product_code, name, marketplace="ozon", external_id=None,
                          status="active"):
    """Идемпотентно по product_code. Существующий товар НЕ перезаписываем (см. update_product)."""
    now = now_utc()
    c = _connect()
    try:
        existing = c.execute(
            "SELECT * FROM products WHERE product_code=?", (product_code,)
        ).fetchone()
        if existing:
            return _d(existing), False
        c.execute(
            "INSERT OR IGNORE INTO products(product_code,external_id,name,marketplace,status,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (product_code, external_id, name, marketplace, status, now, now),
        )
        c.commit()
        row = c.execute("SELECT * FROM products WHERE product_code=?", (product_code,)).fetchone()
        return _d(row), True
    finally:
        c.close()


_PRODUCT_UPDATABLE = ("external_id", "name", "marketplace", "status")


def update_product(product_code, **fields):
    """Точечно обновляет товар по product_code (например, дополняет external_id позже).
    product_code не меняется -> второй товар не создаётся."""
    sets, vals = [], []
    for k in _PRODUCT_UPDATABLE:
        if k in fields:
            sets.append(f"{k}=?")
            vals.append(fields[k])
    if not sets:
        return get_product_by_code(product_code)
    sets.append("updated_at=?"); vals.append(now_utc())
    vals.append(product_code)
    c = _connect()
    try:
        c.execute(f"UPDATE products SET {','.join(sets)} WHERE product_code=?", vals)
        c.commit()
    finally:
        c.close()
    return get_product_by_code(product_code)


def get_product(product_id):
    c = _connect()
    try:
        return _d(c.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone())
    finally:
        c.close()


def get_product_by_code(product_code):
    c = _connect()
    try:
        return _d(c.execute("SELECT * FROM products WHERE product_code=?", (product_code,)).fetchone())
    finally:
        c.close()


# ---------- контент ----------
def create_or_get_content(product_id, content_code, content_type, title, core_idea=None,
                          audience_segment=None, pain_or_desire=None, hypothesis=None,
                          source_path=None, status="draft"):
    """Идемпотентно по (product_id, content_code). title — редактируемое, на ключ не влияет."""
    now = now_utc()
    c = _connect()
    try:
        existing = c.execute(
            "SELECT * FROM contents WHERE product_id=? AND content_code=?",
            (product_id, content_code),
        ).fetchone()
        if existing:
            return _d(existing), False
        c.execute(
            "INSERT OR IGNORE INTO contents(product_id,content_code,content_type,title,core_idea,"
            "audience_segment,pain_or_desire,hypothesis,source_path,status,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (product_id, content_code, content_type, title, core_idea, audience_segment,
             pain_or_desire, hypothesis, source_path, status, now, now),
        )
        c.commit()
        row = c.execute(
            "SELECT * FROM contents WHERE product_id=? AND content_code=?",
            (product_id, content_code),
        ).fetchone()
        return _d(row), True
    finally:
        c.close()


_CONTENT_UPDATABLE = ("content_type", "title", "core_idea", "audience_segment",
                      "pain_or_desire", "hypothesis", "source_path", "status")


def update_content(content_id, **fields):
    sets, vals = [], []
    for k in _CONTENT_UPDATABLE:
        if k in fields:
            sets.append(f"{k}=?"); vals.append(fields[k])
    if not sets:
        return get_content(content_id)
    sets.append("updated_at=?"); vals.append(now_utc())
    vals.append(content_id)
    c = _connect()
    try:
        c.execute(f"UPDATE contents SET {','.join(sets)} WHERE id=?", vals)
        c.commit()
    finally:
        c.close()
    return get_content(content_id)


def get_content(content_id):
    c = _connect()
    try:
        return _d(c.execute("SELECT * FROM contents WHERE id=?", (content_id,)).fetchone())
    finally:
        c.close()


# ---------- хуки ----------
def add_hook(content_id, hook_code, hook_text=None, version=1, status="draft"):
    """Идемпотентно по (content_id, hook_code). Существующий хук НЕ перезаписываем."""
    now = now_utc()
    c = _connect()
    try:
        existing = c.execute(
            "SELECT * FROM hooks WHERE content_id=? AND hook_code=?", (content_id, hook_code)
        ).fetchone()
        if existing:
            return _d(existing), False
        c.execute(
            "INSERT OR IGNORE INTO hooks(content_id,hook_code,hook_text,version,status,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (content_id, hook_code, hook_text, version, status, now, now),
        )
        c.commit()
        row = c.execute(
            "SELECT * FROM hooks WHERE content_id=? AND hook_code=?", (content_id, hook_code)
        ).fetchone()
        return _d(row), True
    finally:
        c.close()


def get_hooks(content_id):
    c = _connect()
    try:
        return [_d(r) for r in c.execute(
            "SELECT * FROM hooks WHERE content_id=? ORDER BY hook_code", (content_id,))]
    finally:
        c.close()


# ---------- каналы ----------
def create_or_get_channel(code, name, status="active"):
    now = now_utc()
    c = _connect()
    try:
        existing = c.execute("SELECT * FROM channels WHERE code=?", (code,)).fetchone()
        if existing:
            return _d(existing), False
        c.execute("INSERT OR IGNORE INTO channels(code,name,status,created_at) VALUES(?,?,?,?)",
                  (code, name, status, now))
        c.commit()
        return _d(c.execute("SELECT * FROM channels WHERE code=?", (code,)).fetchone()), True
    finally:
        c.close()


def get_channel_by_code(code):
    c = _connect()
    try:
        return _d(c.execute("SELECT * FROM channels WHERE code=?", (code,)).fetchone())
    finally:
        c.close()


def list_channels():
    c = _connect()
    try:
        return [_d(r) for r in c.execute("SELECT * FROM channels ORDER BY code")]
    finally:
        c.close()


# ---------- публикации ----------
_PUB_UPDATABLE = (
    "hook_id", "external_publication_id", "status", "scheduled_at", "published_at",
    "published_date", "destination_url", "tracking_url", "utm_source", "utm_medium",
    "utm_campaign", "utm_content", "error_message",
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_published_date(value):
    """published_date — только 'YYYY-MM-DD' (календарная дата, без времени/зоны).
    NULL разрешён (время/дата ещё не известны). Невалидные строки/несуществующие
    календарные даты (напр. 2026-02-30) отклоняются ValueError."""
    if value is None:
        return
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValueError(f"published_date must be 'YYYY-MM-DD': {value!r}")
    date.fromisoformat(value)  # бросает ValueError на несуществующую календарную дату


def create_or_get_publication(content_id, channel_id, publication_code, hook_id=None,
                              status="draft", **fields):
    """Идемпотентно по publication_code. Существующую публикацию НЕ перезаписываем."""
    _validate_published_date(fields.get("published_date"))
    now = now_utc()
    c = _connect()
    try:
        existing = c.execute(
            "SELECT * FROM publications WHERE publication_code=?", (publication_code,)
        ).fetchone()
        if existing:
            return _d(existing), False
        cols = ["content_id", "channel_id", "publication_code", "hook_id", "status",
                "created_at", "updated_at"]
        vals = [content_id, channel_id, publication_code, hook_id, status, now, now]
        for k in _PUB_UPDATABLE:
            if k in fields and k not in ("hook_id", "status"):
                cols.append(k); vals.append(fields[k])
        ph = ",".join("?" * len(cols))
        c.execute(f"INSERT OR IGNORE INTO publications({','.join(cols)}) VALUES({ph})", vals)
        c.commit()
        row = c.execute(
            "SELECT * FROM publications WHERE publication_code=?", (publication_code,)
        ).fetchone()
        return _d(row), True
    finally:
        c.close()


def update_publication(publication_code, **fields):
    _validate_published_date(fields.get("published_date"))
    sets, vals = [], []
    for k in _PUB_UPDATABLE:
        if k in fields:
            sets.append(f"{k}=?"); vals.append(fields[k])
    if not sets:
        return get_publication_by_code(publication_code)
    sets.append("updated_at=?"); vals.append(now_utc())
    vals.append(publication_code)
    c = _connect()
    try:
        c.execute(f"UPDATE publications SET {','.join(sets)} WHERE publication_code=?", vals)
        c.commit()
    finally:
        c.close()
    return get_publication_by_code(publication_code)


def get_publication_by_code(publication_code):
    c = _connect()
    try:
        return _d(c.execute(
            "SELECT * FROM publications WHERE publication_code=?", (publication_code,)).fetchone())
    finally:
        c.close()


def list_publications(product_id=None, channel_code=None, status=None):
    sql = ("SELECT p.* FROM publications p "
           "JOIN contents ct ON ct.id=p.content_id "
           "JOIN channels ch ON ch.id=p.channel_id WHERE 1=1")
    params = []
    if product_id is not None:
        sql += " AND ct.product_id=?"; params.append(product_id)
    if channel_code is not None:
        sql += " AND ch.code=?"; params.append(channel_code)
    if status is not None:
        sql += " AND p.status=?"; params.append(status)
    sql += " ORDER BY p.id"
    c = _connect()
    try:
        return [_d(r) for r in c.execute(sql, params)]
    finally:
        c.close()


def list_publications_for_content(content_id):
    c = _connect()
    try:
        return [_d(r) for r in c.execute(
            "SELECT * FROM publications WHERE content_id=? ORDER BY id", (content_id,))]
    finally:
        c.close()


# ---------- снимки метрик (временной ряд) ----------
_METRIC_FIELDS = ("views", "impressions", "unique_viewers", "likes", "comments", "shares",
                  "saves", "clicks", "watch_time_seconds", "average_view_duration_seconds")


def add_metric_snapshot(publication_id, source, captured_at=None, **metrics):
    """Идемпотентно по (publication_id, source, captured_at). Снимок не перезаписывается."""
    captured_at = captured_at or now_utc()
    now = now_utc()
    c = _connect()
    try:
        existing = c.execute(
            "SELECT * FROM metric_snapshots WHERE publication_id=? AND source=? AND captured_at=?",
            (publication_id, source, captured_at),
        ).fetchone()
        if existing:
            return _d(existing), False
        cols = ["publication_id", "source", "captured_at", "created_at"]
        vals = [publication_id, source, captured_at, now]
        for k in _METRIC_FIELDS:
            if k in metrics:
                cols.append(k); vals.append(metrics[k])
        ph = ",".join("?" * len(cols))
        c.execute(f"INSERT OR IGNORE INTO metric_snapshots({','.join(cols)}) VALUES({ph})", vals)
        c.commit()
        row = c.execute(
            "SELECT * FROM metric_snapshots WHERE publication_id=? AND source=? AND captured_at=?",
            (publication_id, source, captured_at),
        ).fetchone()
        return _d(row), True
    finally:
        c.close()


def get_metric_snapshots(publication_id):
    c = _connect()
    try:
        return [_d(r) for r in c.execute(
            "SELECT * FROM metric_snapshots WHERE publication_id=? ORDER BY captured_at",
            (publication_id,))]
    finally:
        c.close()


# ---------- коммерческие снимки (деньги — минорные единицы) ----------
_COMMERCE_FIELDS = ("visits", "add_to_cart", "orders", "units", "revenue_minor", "spend_minor")
CONFIRMED_ATTRIB = ("direct", "platform_reported", "utm_reported")  # estimated сюда НЕ входит


def add_commerce_snapshot(product_id, source, attribution_type, captured_at=None,
                          publication_id=None, currency="RUB", **metrics):
    """Идемпотентно: при publication_id -> (product,publication,source,captured_at);
    при NULL -> (product,source,captured_at) (два partial-индекса)."""
    captured_at = captured_at or now_utc()
    now = now_utc()
    c = _connect()
    try:
        if publication_id is None:
            existing = c.execute(
                "SELECT * FROM commerce_snapshots WHERE product_id=? AND publication_id IS NULL "
                "AND source=? AND captured_at=?", (product_id, source, captured_at)).fetchone()
        else:
            existing = c.execute(
                "SELECT * FROM commerce_snapshots WHERE product_id=? AND publication_id=? "
                "AND source=? AND captured_at=?",
                (product_id, publication_id, source, captured_at)).fetchone()
        if existing:
            return _d(existing), False
        cols = ["product_id", "publication_id", "source", "attribution_type",
                "captured_at", "currency", "created_at"]
        vals = [product_id, publication_id, source, attribution_type, captured_at, currency, now]
        for k in _COMMERCE_FIELDS:
            if k in metrics:
                cols.append(k); vals.append(metrics[k])
        ph = ",".join("?" * len(cols))
        c.execute(f"INSERT OR IGNORE INTO commerce_snapshots({','.join(cols)}) VALUES({ph})", vals)
        c.commit()
        if publication_id is None:
            row = c.execute(
                "SELECT * FROM commerce_snapshots WHERE product_id=? AND publication_id IS NULL "
                "AND source=? AND captured_at=?", (product_id, source, captured_at)).fetchone()
        else:
            row = c.execute(
                "SELECT * FROM commerce_snapshots WHERE product_id=? AND publication_id=? "
                "AND source=? AND captured_at=?",
                (product_id, publication_id, source, captured_at)).fetchone()
        return _d(row), True
    finally:
        c.close()


# ---------- журнал решений (только хранение, без авто-правил) ----------
def add_decision_record(publication_id, decision, reason=None, evidence_json=None,
                        data_window_start=None, data_window_end=None):
    c = _connect()
    try:
        c.execute(
            "INSERT INTO decision_records(publication_id,decision,reason,evidence_json,"
            "data_window_start,data_window_end,created_at) VALUES(?,?,?,?,?,?,?)",
            (publication_id, decision, reason, evidence_json,
             data_window_start, data_window_end, now_utc()),
        )
        c.commit()
    finally:
        c.close()


# ---------- сводки ----------
def publication_summary(publication_code):
    pub = get_publication_by_code(publication_code)
    if not pub:
        return None
    c = _connect()
    try:
        content = _d(c.execute("SELECT * FROM contents WHERE id=?", (pub["content_id"],)).fetchone())
        hook = _d(c.execute("SELECT * FROM hooks WHERE id=?", (pub["hook_id"],)).fetchone()) \
            if pub["hook_id"] else None
        channel = _d(c.execute("SELECT * FROM channels WHERE id=?", (pub["channel_id"],)).fetchone())
        metrics = [_d(r) for r in c.execute(
            "SELECT * FROM metric_snapshots WHERE publication_id=? ORDER BY captured_at", (pub["id"],))]
        commerce = [_d(r) for r in c.execute(
            "SELECT * FROM commerce_snapshots WHERE publication_id=? ORDER BY captured_at", (pub["id"],))]
        decisions = [_d(r) for r in c.execute(
            "SELECT * FROM decision_records WHERE publication_id=? ORDER BY created_at", (pub["id"],))]
    finally:
        c.close()
    # estimated НИКОГДА не смешиваем с подтверждённым
    confirmed = [r for r in commerce if r["attribution_type"] in CONFIRMED_ATTRIB]
    estimated = [r for r in commerce if r["attribution_type"] == "estimated"]
    other = [r for r in commerce if r["attribution_type"] not in CONFIRMED_ATTRIB
             and r["attribution_type"] != "estimated"]
    return {
        "publication": pub, "content": content, "hook": hook, "channel": channel,
        "metric_snapshots": metrics, "latest_metric": metrics[-1] if metrics else None,
        "commerce_confirmed": confirmed, "commerce_estimated": estimated,
        "commerce_unattributed": other, "decisions": decisions,
    }


def content_summary(content_id):
    content = get_content(content_id)
    if not content:
        return None
    return {"content": content, "hooks": get_hooks(content_id),
            "publications": list_publications_for_content(content_id)}


# ---------- явная команда миграции (НЕ авто на старте) ----------
if __name__ == "__main__":
    run_migrations()
    c = _connect()
    try:
        rows = list(c.execute("SELECT version, applied_at FROM schema_version ORDER BY version"))
        print("schema_version:", [(r["version"], r["applied_at"]) for r in rows])
    finally:
        c.close()
    sys.exit(0)
