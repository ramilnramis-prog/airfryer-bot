# Единый реестр (источник истины)

Связывает: **product → content → hook → channel → publication → tracking link → metrics → orders/revenue**.
Живёт в **той же SQLite-базе**, что и очередь `jobs` (`config.DB_PATH`), отдельным набором таблиц.
Слой данных — `registry_db.py` (только stdlib `sqlite3`). HTTP — `registry.py` (роуты `/registry/*`).

## Журнал решения
> **Единый источник истины размещён в существующей SQLite текущего FastAPI**, чтобы не создавать
> новый сервис и не дублировать данные. Google Sheets не используется, n8n не вводится,
> новые библиотеки не добавлялись.

## Таблицы и связи
```
products 1─n contents 1─n hooks
products 1─n contents 1─n publications n─1 channels ; publications n─1 hooks (nullable)
publications 1─n metric_snapshots (временной ряд)
publications 1─n commerce_snapshots ; products 1─n commerce_snapshots (publication_id nullable)
publications 1─n decision_records
```
8 таблиц + служебная `schema_version`. Таблица `jobs` не изменяется.

## Правила
- **Время — UTC, ISO8601** `YYYY-MM-DDTHH:MM:SSZ`. *(Легаси `jobs` хранит epoch — не трогаем; явное допущение.)*
- **Идемпотентность — по СТАБИЛЬНЫМ бизнес-кодам** (не зависят от изменяемых `name`/`title`):
  `product_code`, `(product_id, content_code)`, `(content_id, hook_code)`, `publication_code`.
  Повторный create с тем же кодом возвращает существующую строку и `"created": false`.
- `external_id`/`offer_id`, `name`, `title` — **редактируемые** атрибуты (PATCH), на идентичность не влияют.
- **Метрики — снимки во времени**, не перезапись.
- **Деньги — целые минорные единицы** (`revenue_minor`, `spend_minor`; для RUB 1 minor = 1 копейка). **Без float.**
- **Атрибуция**: `direct/platform_reported/utm_reported` — подтверждённые; `estimated` — только оценка (никогда не смешивается с подтверждённым); `unattributed`.
- **Статусы публикации**: `draft, approved, scheduled, publishing, published, failed, stopped`.
- **Решения**: `SCALE, ITERATE, HOLD, STOP, INVESTIGATE` (только хранение; авто-правил нет).
- **FOREIGN KEYS** включаются на **каждом** соединении (`PRAGMA foreign_keys = ON`) + `busy_timeout = 5000`.

## UNIQUE / индексы (всё отдельными `CREATE UNIQUE INDEX`, не внутри `CREATE TABLE`)
| Индекс | Ключ |
|---|---|
| ux_products_code | `(product_code)` |
| ux_products_external | `(marketplace, external_id)` **WHERE external_id IS NOT NULL** |
| ux_contents_code | `(product_id, content_code)` |
| ux_hooks_key | `(content_id, hook_code)` |
| ux_channels_code | `(code)` |
| ux_publications_code | `(publication_code)` |
| ux_publications_external | `(channel_id, external_publication_id)` **WHERE external_publication_id IS NOT NULL** |
| ux_metric_snapshot | `(publication_id, source, captured_at)` |
| ux_commerce_pub | `(product_id, publication_id, source, captured_at)` **WHERE publication_id IS NOT NULL** |
| ux_commerce_nopub | `(product_id, source, captured_at)` **WHERE publication_id IS NULL** |

> Для коммерции — **два partial-индекса** (без фиктивного `COALESCE(...,0)`).

## Endpoints (под `X-API-Key` + проверка миграции, на уровне роутера)
`POST /registry/products` (по product_code) · `GET /registry/products/{product_code}` · `PATCH /registry/products/{product_code}` ·
`POST /registry/contents` (по content_code) · `GET /registry/contents/{id}/summary` ·
`POST /registry/hooks` · `POST /registry/channels` · `GET /registry/channels` ·
`POST /registry/publications` · `GET|PATCH /registry/publications/{publication_code}` · `GET /registry/publications` ·
`GET /registry/publications/{publication_code}/summary` ·
`POST /registry/metric-snapshots` · `POST /registry/commerce-snapshots` · `POST /registry/decisions`

## Локальный запуск
```bash
cd telegram-bot
python -m api.registry_db                       # ЯВНО применить миграцию (создаёт таблицы)
python -m api.seed_registry --yes               # засеять (повторно безопасно)
python -m unittest api.tests.test_registry -v   # тесты
REGISTRY_AUTO_MIGRATE=1 uvicorn api.main:app --reload   # локально с авто-миграцией
```

## Миграция (без Alembic)
- Версионированные `.sql` в `api/migrations/` + раннер `registry_db.run_migrations()` (отмечает версии в `schema_version`, всё `IF NOT EXISTS` → повторно безопасно).
- **Авто-миграция на старте API ВЫКЛЮЧЕНА по умолчанию** (`REGISTRY_AUTO_MIGRATE` пуст). Прод не мигрирует случайно при деплое кода. Если схема отсутствует — `/registry/*` отвечают **503** с понятным сообщением, а не работают частично.
- **Production-миграция Railway (только с отдельным подтверждением, НЕ выполнять сейчас):**
  1. `cp /data/jobs.db /data/jobs.db.bak.<UTC-дата>` (бэкап);
  2. применить миграцию явно (одноразовый запуск `python -m api.registry_db` в среде API **или** временно `REGISTRY_AUTO_MIGRATE=1` → рестарт → выключить);
  3. проверить `GET /registry/channels`, `PRAGMA integrity_check`, `PRAGMA foreign_key_check`.

## Rollback (DROP TABLE автоматически НЕ выполняется)
**A. Обычный безопасный откат:**
- вернуть предыдущую версию кода;
- **оставить** новые (неиспользуемые) таблицы реестра в БД;
- `jobs` **не трогать** (продолжает принимать задания);
- удалить таблицы реестра позже — отдельной подтверждённой миграцией.

**B. Полное восстановление из бэкапа `jobs.db.bak` — только если:**
- API и бот **остановлены**;
- после бэкапа **не появлялись новые jobs** (иначе они будут потеряны) — либо сначала экспортировать новые строки `jobs` и восстановить их после;
- после восстановления выполнить `PRAGMA integrity_check` и `PRAGMA foreign_key_check`.

## Railway-архитектура (определено по файлам/конфигам)
- **Бот и API — РАЗНЫЕ Railway-сервисы** (разные проекты, разные ФС/Volume).
- **Бот jobs.db НЕ использует** — он пишет `state.json` (`STATE_FILE = DATA_DIR/state.json`) на свой Volume `/data`.
- **API** использует `jobs.db` (+ реестр) в `DATA_DIR/jobs.db`. По логам `DATA_DIR=/data` задан; **смонтирован ли Volume на /data именно у API — НЕ подтверждено** (проверить — см. ниже).
- **Общего физического `jobs.db` у бота и API нет** → кросс-сервисной конкуренции на запись в `jobs.db` нет.
- Запуск API: `uvicorn api.main:app` (один worker, без `--workers`); реплик по умолчанию 1 → один процесс-писатель.

### Что проверить владельцу в Railway (без раскрытия секретов)
1. Открыть **сервис API** (`appealing-serenity / worker`, домен `worker-production-6ce1…`).
2. **Settings → Volumes**: есть ли Volume и его **Mount path** (ожидаем `/data`). Прислать: есть/нет + mount path.
3. **Variables**: присутствует ли `DATA_DIR` и её значение (ожидаем `/data`). Прислать только имя+значение пути (не секреты).
4. **Settings → Deploy / Start Command**: одна ли команда `uvicorn …` без `--workers`. Прислать строку.
5. **Replicas**: значение (ожидаем 1). Прислать число.
6. `BOT_TOKEN`, `API_KEY` и др. секреты — **не присылать**.

## Конкурентный доступ
- Писатели в `jobs.db` = **только процесс API** (очередь `jobs` + реестр, в одном процессе, возможны параллельные потоки FastAPI/BackgroundTasks). Бот сюда не пишет.
- На соединениях реестра — `busy_timeout=5000` + перехват `sqlite3.OperationalError/IntegrityError` в `main.py` (ответ без stack trace). WAL **намеренно не включаем** (требует отдельного теста).
- Если в будущем у API станет >1 worker/replica — пересмотреть (busy_timeout уже смягчает; WAL — отдельным решением).

## Известные ограничения / что НЕ автоматизировано
- Метрики/заказы **вносятся вручную** (или будущим импортером) — система их хранит и связывает, **не выдумывает**.
- Нет авто-правил решений; нет авто-публикации; внешние API не подключены.
- `db.py` (очередь `jobs`) намеренно не менялся (нет `busy_timeout`) — при росте нагрузки можно добавить отдельным решением.
- Тесты на stdlib `unittest`; **в текущей Windows-среде Python отсутствует** — запускает владелец.
