-- 0001_init_registry.sql
-- Единый реестр в ТОЙ ЖЕ SQLite-базе, что и очередь `jobs`. Таблицу `jobs` не трогаем.
-- Все выражения IF NOT EXISTS -> повторно безопасно (идемпотентно).
-- Время: UTC, ISO8601 'YYYY-MM-DDTHH:MM:SSZ' (registry_db.now_utc).
-- Деньги: только целые минорные единицы (копейки), без float.
-- UNIQUE через ОТДЕЛЬНЫЕ CREATE UNIQUE INDEX (в т.ч. partial) — НЕ внутри UNIQUE(...) в CREATE TABLE.
-- schema_version создаёт раннер registry_db.run_migrations.

-- 1) ТОВАРЫ -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    product_code TEXT NOT NULL,                 -- СТАБИЛЬНЫЙ бизнес-ключ (не меняется)
    external_id  TEXT,                          -- offer_id / артикул Ozon; nullable, добавляется позже
    name         TEXT NOT NULL,                 -- редактируемое отображаемое имя
    marketplace  TEXT NOT NULL DEFAULT 'ozon',
    status       TEXT NOT NULL DEFAULT 'active',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
-- идемпотентность товара — по стабильному коду
CREATE UNIQUE INDEX IF NOT EXISTS ux_products_code ON products(product_code);
-- один external_id (артикул) не должен принадлежать двум товарам — только когда задан
CREATE UNIQUE INDEX IF NOT EXISTS ux_products_external
    ON products(marketplace, external_id) WHERE external_id IS NOT NULL;

-- 2) КОНТЕНТ ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contents (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id       INTEGER NOT NULL REFERENCES products(id),
    content_code     TEXT NOT NULL,             -- СТАБИЛЬНЫЙ бизнес-ключ в рамках товара
    content_type     TEXT NOT NULL,             -- video / article / post / ...
    title            TEXT NOT NULL,             -- редактируемое отображаемое
    core_idea        TEXT,
    audience_segment TEXT,
    pain_or_desire   TEXT,
    hypothesis       TEXT,
    source_path      TEXT,
    status           TEXT NOT NULL DEFAULT 'draft',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_contents_code ON contents(product_id, content_code);

-- 3) ХУКИ ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hooks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id  INTEGER NOT NULL REFERENCES contents(id),
    hook_code   TEXT NOT NULL,                  -- A / B / C
    hook_text   TEXT,                           -- NULL -> требует заполнения владельцем
    version     INTEGER NOT NULL DEFAULT 1,
    status      TEXT NOT NULL DEFAULT 'draft',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_hooks_key ON hooks(content_id, hook_code);

-- 4) КАНАЛЫ -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS channels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL,                  -- telegram / youtube_shorts / instagram_reels / tiktok / dzen
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_channels_code ON channels(code);

-- 5) ПУБЛИКАЦИИ ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS publications (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id              INTEGER NOT NULL REFERENCES contents(id),
    hook_id                 INTEGER REFERENCES hooks(id),
    channel_id              INTEGER NOT NULL REFERENCES channels(id),
    publication_code        TEXT NOT NULL,                 -- СТАБИЛЬНЫЙ бизнес-ключ
    external_publication_id TEXT,
    status                  TEXT NOT NULL DEFAULT 'draft'
                              CHECK (status IN ('draft','approved','scheduled','publishing','published','failed','stopped')),
    scheduled_at            TEXT,
    published_at            TEXT,
    destination_url         TEXT,
    tracking_url            TEXT,
    utm_source              TEXT,
    utm_medium              TEXT,
    utm_campaign            TEXT,
    utm_content             TEXT,
    error_message           TEXT,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_publications_code ON publications(publication_code);
-- один внешний id в одном канале не дублируем (только когда внешний id задан)
CREATE UNIQUE INDEX IF NOT EXISTS ux_publications_external
    ON publications(channel_id, external_publication_id)
    WHERE external_publication_id IS NOT NULL;

-- 6) СНИМКИ МЕТРИК (временной ряд, не перезапись) -----------------------------
CREATE TABLE IF NOT EXISTS metric_snapshots (
    id                            INTEGER PRIMARY KEY AUTOINCREMENT,
    publication_id                INTEGER NOT NULL REFERENCES publications(id),
    captured_at                   TEXT NOT NULL,   -- UTC ISO8601 — момент снимка
    views                         INTEGER,
    impressions                   INTEGER,
    unique_viewers                INTEGER,
    likes                         INTEGER,
    comments                      INTEGER,
    shares                        INTEGER,
    saves                         INTEGER,
    clicks                        INTEGER,
    watch_time_seconds            INTEGER,         -- целые секунды (без float)
    average_view_duration_seconds INTEGER,
    source                        TEXT NOT NULL,
    created_at                    TEXT NOT NULL
);
-- снимок уникален по (публикация, источник, момент) -> повтор не плодит дубли
CREATE UNIQUE INDEX IF NOT EXISTS ux_metric_snapshot
    ON metric_snapshots(publication_id, source, captured_at);

-- 7) КОММЕРЦИЯ (деньги — целые минорные единицы) ------------------------------
CREATE TABLE IF NOT EXISTS commerce_snapshots (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id       INTEGER NOT NULL REFERENCES products(id),
    publication_id   INTEGER REFERENCES publications(id),   -- NULL = снимок уровня товара
    captured_at      TEXT NOT NULL,
    visits           INTEGER,
    add_to_cart      INTEGER,
    orders           INTEGER,
    units            INTEGER,
    revenue_minor    INTEGER,                       -- деньги в копейках (без float)
    spend_minor      INTEGER,                       -- деньги в копейках (без float)
    currency         TEXT NOT NULL DEFAULT 'RUB',
    attribution_type TEXT NOT NULL
                       CHECK (attribution_type IN ('direct','platform_reported','utm_reported','estimated','unattributed')),
    source           TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
-- ДВА partial-индекса вместо COALESCE(...,0):
-- (a) для снимков, привязанных к публикации:
CREATE UNIQUE INDEX IF NOT EXISTS ux_commerce_pub
    ON commerce_snapshots(product_id, publication_id, source, captured_at)
    WHERE publication_id IS NOT NULL;
-- (b) для снимков уровня товара (publication_id IS NULL):
CREATE UNIQUE INDEX IF NOT EXISTS ux_commerce_nopub
    ON commerce_snapshots(product_id, source, captured_at)
    WHERE publication_id IS NULL;

-- 8) ЖУРНАЛ РЕШЕНИЙ (структура; авто-правил нет) -----------------------------
CREATE TABLE IF NOT EXISTS decision_records (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    publication_id    INTEGER NOT NULL REFERENCES publications(id),
    decision          TEXT NOT NULL
                        CHECK (decision IN ('SCALE','ITERATE','HOLD','STOP','INVESTIGATE')),
    reason            TEXT,
    evidence_json     TEXT,
    data_window_start TEXT,
    data_window_end   TEXT,
    created_at        TEXT NOT NULL
);
