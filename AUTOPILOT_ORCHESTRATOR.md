# AUTOPILOT_ORCHESTRATOR — агент ozon-autopilot

Центральный проектный агент, ведущий контентные кампании внешнего трафика Ozon
для товара `airfryer-silicone-form` (арт. 1931921872) — от идеи до пакета,
готового к импорту в реестр, с обязательными остановками перед платными и
производственными действиями.

## Что делает

Один цикл = одна кампания:

```
анализ текущего состояния (реестр, прошлые кампании, метрики)
→ выбор следующей идеи (новый угол, без повторов тем)
→ создание контента (сценарий, hooks, storyboard, промпты, тексты площадок, Дзен, Telegram, ad-angles)
→ QA и факт-чек (qa-report.md)
→ формирование content-package.json
→ локальный dry-run на временной SQLite + тесты
→ ОСТАНОВКА: отчёт владельцу + одно требуемое подтверждение
→ (по подтверждениям, поэтапно) генерация ассетов → регистрация → публикация → метрики
```

## Где лежит агент

- Версионируемая копия (в этом репо): `.claude/agents/ozon-autopilot.md`
- Активный project scope Claude Code (корень рабочей папки проекта):
  `D:/OzonGrowthProject/.claude/agents/ozon-autopilot.md`

Обе копии идентичны; при изменении агента обновлять обе.

## Что использует (существующие компоненты, НЕ дублируются)

| Компонент | Путь |
|---|---|
| Skill ozon-airfryer-growth (роли, гипотезы, углы, Style Anchor) | `D:/OzonGrowthProject/.claude/skills/ozon-airfryer-growth/` |
| Реестр products/contents/hooks/channels/publications/metrics | `api/registry_db.py`, `api/REGISTRY.md` |
| Content-package bridge (валидация + импорт, dry-run по умолчанию) | `api/content_package.py`, `api/import_content_package.py`, `api/CONTENT_PACKAGE.md` |
| Seed и historical backfill | `api/seed_registry.py`, `api/backfill_video2_publications.py` |
| Пакетный клиент метрик | `api/import_metrics_via_api.py` |
| Telegram-бот (автопостинг, лид-магнит) | `bot.py`, `posts.py` |
| Higgsfield MCP (генерация — только по подтверждению) | подключён в Claude Code |
| Анализ товара и отзывов | `D:/OzonGrowthProject/analysis/product-analysis_1931921872.md` |
| UTM-разметка каналов | память `reference-ozon-utm-links` |

## Где лежат результаты

Каждая кампания: `content/autopilot/<campaign_code>/` (13 файлов: манифест, brief,
сценарий, hooks.json, storyboard, higgsfield-prompts, platform-captions, dzen-article,
telegram-post, ad-angles, content-package.json, qa-report, README — состав см. в
README кампании).

Первая кампания: `content/autopilot/coating-protect-2026-07/`
(content_code=`coating-protect-ad`, угол «защита антипригарного покрытия»).

## Состояния кампании

`planned → content_ready → qa_passed → package_validated →
awaiting_asset_generation → assets_ready → awaiting_registration → registered →
awaiting_publication → scheduled → published → metrics_pending → completed`

Текущее состояние — поле `status` в `campaign_manifest.json`. Состояние
переводится вперёд только после фактического завершения этапа; из `awaiting_*`
выход только по команде владельца.

## Действия, требующие подтверждения владельца

1. **Генерация платных ассетов** (Higgsfield) — по `higgsfield-prompts.md` кампании.
2. **Import в production реестр** — `python -m api.import_content_package <pkg> --apply`
   (или HTTP POST на Railway). Без подтверждения — только dry-run на временной БД.
3. **Публикация** на любой площадке (и перевод статусов в scheduled/published).
4. **Реклама/бюджет/карточка Ozon** — агент не трогает вообще.
5. **git push / merge / Railway-команды** — запрещены агенту.

## Как запустить следующий цикл

1. Убедиться, что текущая кампания доведена до своей СТОП-точки (см. `status`).
2. Вызвать агента: «ozon-autopilot: новый контентный цикл» (subagent `ozon-autopilot`).
3. Агент сам: прочитает реестр и `content/autopilot/`, исключит занятые темы
   (video1 — мытьё чаши, `video2-forma-ad` — must-have, `coating-protect-ad` —
   защита покрытия, ПП-рецепты), выберет следующий угол из MARKETING_HYPOTHESIS.md §3,
   создаст кампанию и остановится после dry-run с отчётом.

## Что пока остаётся ручным

- Озвучка (записывает владелец) и монтаж (CapCut).
- Запуск генерации Higgsfield и приёмка кадров.
- Собственно публикация (SMMplanner/вручную; Дзен — RSS/вручную, API нет).
- `--apply` импорта пакета и ввод метрик (`api/import_metrics_via_api.py`).
- Решения по бюджету/рекламе.

## Путь к полной автоматизации (дальше)

1. **Сейчас**: агент делает контент+пакет, человек — ассеты, импорт, публикацию, метрики.
2. **Следующий шаг**: автоимпорт пакета в production по одному «да» (существующий
   CLI/HTTP), автогенерация ассетов через Higgsfield MCP по одному «да» на кампанию.
3. **Затем**: автопостинг через планировщик (SMMplanner уже в стратегии), бот —
   Telegram-часть уже автоматическая; автоматический сбор метрик по расписанию
   поверх `import_metrics_via_api.py`.
4. **Цель**: владелец подтверждает только идею кампании и бюджет; всё остальное —
   конвейер с контрольными точками и журналом в реестре.
