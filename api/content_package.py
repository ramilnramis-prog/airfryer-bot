"""Content package: валидированный мост между выходом контентного skill и реестром.

Формат пакета — см. api/CONTENT_PACKAGE.md, пример — api/examples/content_package.example.json.
Импорт — ОДНА SQLite-транзакция (product -> content -> hooks -> channel-check -> publications).
Любая ошибка откатывает весь пакет целиком. Повторный импорт того же пакета не создаёт дублей
(идемпотентность — через те же стабильные коды, что и у registry_db: product_code,
(product_id, content_code), (content_id, hook_code), publication_code).

На этом слое НЕ публикуется ничего: статус публикаций из пакета всегда 'draft'.
Используется и HTTP-эндпоинтом (registry.py), и локальным CLI (import_content_package.py) —
без дублирования логики.
"""
import re

from . import registry_db as R

SCHEMA_VERSION = 1

# Пока разрешаем только черновики — ни для content/hooks, ни для publication_drafts
# импорт пакета не должен молча продвигать статус дальше 'draft'.
ALLOWED_STATUS = ("draft",)

_SECRET_KEY_RE = re.compile(r"(token|secret|password|api[_-]?key|authorization)", re.IGNORECASE)


class PackageError(Exception):
    """Ошибка валидации/структуры — до открытия транзакции или внутри неё (полный откат). HTTP 400."""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


class ProductNotFoundError(PackageError):
    """product_code из пакета не найден в реестре. HTTP 404."""


class PackageConflict(PackageError):
    """Существующая запись реестра конфликтует с пакетом (не перезаписываем молча). HTTP 409."""


def _scan_for_secrets(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if _SECRET_KEY_RE.search(k):
                raise PackageError(f"secret-like field is not allowed in a content package: {path}{k}",
                                    field=f"{path}{k}")
            _scan_for_secrets(v, f"{path}{k}.")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _scan_for_secrets(v, f"{path}{i}.")


def validate_package(pkg: dict) -> None:
    """Проверяет форму пакета без обращения к БД. Бросает PackageError на первой проблеме."""
    if not isinstance(pkg, dict):
        raise PackageError("package must be a JSON object")

    _scan_for_secrets(pkg)

    if pkg.get("schema_version") != SCHEMA_VERSION:
        raise PackageError(
            f"unsupported schema_version (expected {SCHEMA_VERSION})", field="schema_version")

    product = pkg.get("product")
    if not isinstance(product, dict) or not product.get("product_code"):
        raise PackageError("product.product_code is required", field="product.product_code")

    content = pkg.get("content")
    if not isinstance(content, dict):
        raise PackageError("content is required", field="content")
    for key in ("content_code", "content_type", "title"):
        if not content.get(key):
            raise PackageError(f"content.{key} is required", field=f"content.{key}")
    content_status = content.get("status", "draft")
    if content_status not in ALLOWED_STATUS:
        raise PackageError(
            f"content.status must be one of {ALLOWED_STATUS}", field="content.status")

    hooks = pkg.get("hooks", [])
    if not isinstance(hooks, list):
        raise PackageError("hooks must be a list", field="hooks")
    seen_hook_codes = set()
    for i, h in enumerate(hooks):
        if not isinstance(h, dict) or not h.get("hook_code"):
            raise PackageError(f"hooks[{i}].hook_code is required", field=f"hooks[{i}].hook_code")
        if h["hook_code"] in seen_hook_codes:
            raise PackageError(
                f"duplicate hook_code in package: {h['hook_code']}", field=f"hooks[{i}].hook_code")
        seen_hook_codes.add(h["hook_code"])
        hook_status = h.get("status", "draft")
        if hook_status not in ALLOWED_STATUS:
            raise PackageError(
                f"hooks[{i}].status must be one of {ALLOWED_STATUS}", field=f"hooks[{i}].status")

    pubs = pkg.get("publication_drafts", [])
    if not isinstance(pubs, list):
        raise PackageError("publication_drafts must be a list", field="publication_drafts")
    seen_pub_codes = set()
    for i, p in enumerate(pubs):
        if not isinstance(p, dict):
            raise PackageError(f"publication_drafts[{i}] must be an object", field=f"publication_drafts[{i}]")
        for key in ("publication_code", "channel_code"):
            if not p.get(key):
                raise PackageError(
                    f"publication_drafts[{i}].{key} is required", field=f"publication_drafts[{i}].{key}")
        if p["publication_code"] in seen_pub_codes:
            raise PackageError(
                f"duplicate publication_code in package: {p['publication_code']}",
                field=f"publication_drafts[{i}].publication_code")
        seen_pub_codes.add(p["publication_code"])
        pub_status = p.get("status", "draft")
        if pub_status not in ALLOWED_STATUS:
            raise PackageError(
                f"publication_drafts[{i}].status must be one of {ALLOWED_STATUS} "
                f"(publishing/published/failed are not allowed via package import)",
                field=f"publication_drafts[{i}].status")


_CONTENT_EDITABLE_FIELDS = (
    "title", "core_idea", "audience_segment", "pain_or_desire", "hypothesis", "source_path")
_PUBLICATION_OPTIONAL_FIELDS = (
    "destination_url", "tracking_url", "utm_source", "utm_medium", "utm_campaign", "utm_content")


def import_package(pkg: dict) -> dict:
    """Транзакционный импорт: одна SQLite-транзакция, весь пакет целиком или откат.

    Возвращает: created / existing (по content, hooks, publications), content_id,
    hook_ids (hook_code -> id), publication_ids (publication_code -> id), warnings.
    """
    validate_package(pkg)

    product_code = pkg["product"]["product_code"]
    content_in = pkg["content"]
    hooks_in = pkg.get("hooks", [])
    pubs_in = pkg.get("publication_drafts", [])

    warnings = []
    created = {"content": False, "hooks": [], "publications": []}
    existing = {"content": False, "hooks": [], "publications": []}

    conn = R._connect()
    conn.isolation_level = None  # ручное управление транзакцией (BEGIN/COMMIT/ROLLBACK)
    try:
        conn.execute("BEGIN IMMEDIATE")

        product_row = conn.execute(
            "SELECT * FROM products WHERE product_code=?", (product_code,)).fetchone()
        if not product_row:
            raise ProductNotFoundError(
                f"product not found: {product_code}", field="product.product_code")
        product_id = product_row["id"]

        # content_code не должен молча переезжать на другой товар
        other_owner = conn.execute(
            "SELECT id FROM contents WHERE content_code=? AND product_id!=?",
            (content_in["content_code"], product_id)).fetchone()
        if other_owner:
            raise PackageConflict(
                f"content_code '{content_in['content_code']}' is already registered "
                "under a different product_code",
                field="content.content_code")

        now = R.now_utc()
        existing_content = conn.execute(
            "SELECT * FROM contents WHERE product_id=? AND content_code=?",
            (product_id, content_in["content_code"])).fetchone()

        if existing_content:
            if existing_content["content_type"] != content_in["content_type"]:
                raise PackageConflict(
                    f"content_type conflict for content_code '{content_in['content_code']}': "
                    f"existing='{existing_content['content_type']}' "
                    f"incoming='{content_in['content_type']}'",
                    field="content.content_type")
            content_id = existing_content["id"]
            existing["content"] = True
            for key in _CONTENT_EDITABLE_FIELDS:
                incoming_value = content_in.get(key)
                if incoming_value is not None and existing_content[key] != incoming_value:
                    warnings.append(
                        f"content.{key} differs from existing value; not overwritten "
                        "(use a separate confirmed update operation)")
        else:
            conn.execute(
                "INSERT INTO contents(product_id,content_code,content_type,title,core_idea,"
                "audience_segment,pain_or_desire,hypothesis,source_path,status,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (product_id, content_in["content_code"], content_in["content_type"],
                 content_in["title"], content_in.get("core_idea"), content_in.get("audience_segment"),
                 content_in.get("pain_or_desire"), content_in.get("hypothesis"),
                 content_in.get("source_path"), content_in.get("status", "draft"), now, now))
            content_id = conn.execute(
                "SELECT id FROM contents WHERE product_id=? AND content_code=?",
                (product_id, content_in["content_code"])).fetchone()["id"]
            created["content"] = True

        # hooks: создаём/находим по (content_id, hook_code); hook_text не перезаписываем молча
        hook_id_by_code = {}
        for h in hooks_in:
            row = conn.execute(
                "SELECT * FROM hooks WHERE content_id=? AND hook_code=?",
                (content_id, h["hook_code"])).fetchone()
            if row:
                hook_id_by_code[h["hook_code"]] = row["id"]
                existing["hooks"].append(h["hook_code"])
                incoming_text = h.get("hook_text")
                if incoming_text is not None and row["hook_text"] != incoming_text:
                    warnings.append(
                        f"hooks[{h['hook_code']}].hook_text differs from existing value; not overwritten")
            else:
                conn.execute(
                    "INSERT INTO hooks(content_id,hook_code,hook_text,version,status,created_at,updated_at)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (content_id, h["hook_code"], h.get("hook_text"), h.get("version", 1),
                     h.get("status", "draft"), now, now))
                hook_id_by_code[h["hook_code"]] = conn.execute(
                    "SELECT id FROM hooks WHERE content_id=? AND hook_code=?",
                    (content_id, h["hook_code"])).fetchone()["id"]
                created["hooks"].append(h["hook_code"])

        # ВСЕ channel_code проверяем ДО записи публикаций (неизвестный код -> откат всего пакета)
        channel_id_by_code = {}
        for p in pubs_in:
            code = p["channel_code"]
            if code in channel_id_by_code:
                continue
            ch = conn.execute("SELECT id FROM channels WHERE code=?", (code,)).fetchone()
            if not ch:
                raise PackageError(f"unknown channel_code: {code}", field="publication_drafts.channel_code")
            channel_id_by_code[code] = ch["id"]

        # hook_code, на который ссылается публикация, должен существовать (в пакете или уже в БД)
        for p in pubs_in:
            hcode = p.get("hook_code")
            if hcode and hcode not in hook_id_by_code:
                raise PackageError(
                    f"publication_drafts references unknown hook_code: {hcode}",
                    field="publication_drafts.hook_code")

        publication_id_by_code = {}
        for p in pubs_in:
            pub_code = p["publication_code"]
            existing_pub = conn.execute(
                "SELECT * FROM publications WHERE publication_code=?", (pub_code,)).fetchone()
            if existing_pub:
                existing["publications"].append(pub_code)
                publication_id_by_code[pub_code] = existing_pub["id"]
                expected_channel_id = channel_id_by_code[p["channel_code"]]
                if (existing_pub["content_id"] != content_id
                        or existing_pub["channel_id"] != expected_channel_id):
                    warnings.append(
                        f"publication_drafts[{pub_code}] already exists bound to a different "
                        "content/channel; not changed")
                continue
            hook_id = hook_id_by_code.get(p.get("hook_code")) if p.get("hook_code") else None
            cols = ["content_id", "channel_id", "publication_code", "hook_id", "status",
                    "created_at", "updated_at"]
            vals = [content_id, channel_id_by_code[p["channel_code"]], pub_code, hook_id,
                    p.get("status", "draft"), now, now]
            for key in _PUBLICATION_OPTIONAL_FIELDS:
                if p.get(key) is not None:
                    cols.append(key)
                    vals.append(p[key])
            placeholders = ",".join("?" * len(cols))
            conn.execute(
                f"INSERT INTO publications({','.join(cols)}) VALUES({placeholders})", vals)
            publication_id_by_code[pub_code] = conn.execute(
                "SELECT id FROM publications WHERE publication_code=?", (pub_code,)).fetchone()["id"]
            created["publications"].append(pub_code)

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    return {
        "created": created,
        "existing": existing,
        "content_id": content_id,
        "hook_ids": hook_id_by_code,
        "publication_ids": publication_id_by_code,
        "warnings": warnings,
    }
