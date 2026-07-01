# Локальный проверочный прогон реестра

- **Дата/время (UTC):** 2026-06-30T18:42Z
- **Python:** 3.14.6 — `C:\Users\user\AppData\Local\Python\pythoncore-3.14-64\python.exe`
- **Интерпретатор прогона:** `D:\OzonGrowthProject\telegram-bot\.venv\Scripts\python.exe`
- **Disposable-база:** `.local-validation-data\jobs.db` (и `.local-validation-data-fresh\jobs.db` для auto-migrate-OFF). Production/`data`/`/data`/`state.json` **не трогались**.

## Зависимости (из существующего api/requirements.txt; новых проектных не добавлялось)
Установлены в `.venv`: `fastapi==0.138.2`, `uvicorn==0.49.0`, `fpdf2==2.8.7` + транзитивные:
`starlette==1.3.1`, `pydantic==2.13.4`, `anyio==4.14.1`, `h11==0.16.0`, `click==8.4.2`, `pillow==12.2.0`,
`httptools`, `websockets`, `watchfiles`, `python-dotenv`, `pyyaml`, `idna`, `colorama`, `defusedxml`, `fonttools`.
- `pip check`: **No broken requirements found.**
- Прокси: в среде `ALL_PROXY=socks5://…`; для установки очищен только на время процесса (PySocks не ставился, requirements не менялся).

## Статика
- `python -m compileall api` → **exit 0**.
- `from api import config, registry_db, registry, seed_registry` → **imports: OK**.

## Unit-тесты
`python -m unittest api.tests.test_registry -v` → **Ran 21 tests — OK** (failed 0, errors 0, skipped 0, 1.465s).
Исправлений после реального запуска **не потребовалось**.

## Миграция (на disposable-базе)
- #1: `schema_version = [(1, 2026-06-30T18:42:06Z)]`.
- #2 (повтор): `schema_version = [(1, 2026-06-30T18:42:06Z)]` — та же версия/метка, повторно не применилась, таблицы не пересоздавались.
- Таблицы: channels, commerce_snapshots, contents, decision_records, hooks, metric_snapshots, products, publications, schema_version.
- UNIQUE-индексов: 10; **partial**: ux_commerce_pub, ux_commerce_nopub, ux_products_external, ux_publications_external.
- Деньги: `revenue_minor INTEGER`, `spend_minor INTEGER`; **REAL в commerce — нет**.

## Seed (дважды)
- #1: `created` = product, 5 channels, content, 3 hooks (A/B/C). Counts: products 1, contents 1, hooks 3, channels 5, publications 0.
- #2: `created = {}`, всё `existing`. Counts **идентичны** → дублей нет.
- Тексты хуков — verbatim из `content/video2-voiceover.md` (не выдуманы). content_code = `video2-forma-ad`.

## Проверка БД
- `PRAGMA integrity_check` → **ok**.
- `PRAGMA foreign_key_check` → **[]** (пусто), и после попытки orphan — тоже пусто.
- `PRAGMA foreign_keys` (соединение реестра) → **1**.
- `schema_version` → **[1]**.
- Orphan (content с несуществующим product_id) → **отклонён `sqlite3.IntegrityError`**, строка не добавлена (contents так и 1).

## jobs
- `db.init_db()` + `create_job` → status `queued`; `set_status('ready', result=...)` → `get_job` status `ready`, result присутствует.
- Таблица `jobs` и реестр сосуществуют в одной базе, реестр не мешает. **jobs compatibility: PASS.**

## Auto-migrate (на отдельной чистой базе)
- `config.REGISTRY_AUTO_MIGRATE` (env не задан) → **False**.
- До миграции `schema_present()` → **False** (схема сама не создаётся).
- `registry._require_migrated()` → **HTTPException 503** с понятным сообщением о миграции.
- После явной `run_migrations()` → `schema_present()` → **True**.

## Исправленные ошибки
- Нет — все проверки прошли с первого запуска.

## Оставшиеся ограничения
- Не проверено: смонтирован ли Volume `/data` на **API-сервисе** Railway; поведение при >1 uvicorn worker/replica.
- Production-миграция/деплой не выполнялись (по запрету).
- Секреты (API_KEY/BOT_TOKEN) в отчёт не попадают.
