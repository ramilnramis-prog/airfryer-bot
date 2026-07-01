-- 0002_add_published_date.sql
-- Добавляет в publications nullable published_date (формат 'YYYY-MM-DD').
-- Нужен для исторических публикаций, где известна только календарная дата выхода,
-- а точное время неизвестно — published_at (полный UTC ISO8601) в этом случае
-- остаётся NULL, время НЕ придумывается.
-- Повторное применение исключено раннером (registry_db.run_migrations фиксирует
-- версию в schema_version) — сам ALTER TABLE не оборачиваем в IF NOT EXISTS
-- (SQLite это не поддерживает для ADD COLUMN).
ALTER TABLE publications ADD COLUMN published_date TEXT;
