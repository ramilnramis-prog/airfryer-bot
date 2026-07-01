# Content Package

Формат обмена между контентным skill (`ozon-airfryer-growth`, живёт вне Git —
`D:/OzonGrowthProject/.claude/skills/ozon-airfryer-growth`, см. раздел «Skill bridge» ниже)
и единым реестром (`api/REGISTRY.md`). Один пакет = один content + его hooks +
draft-публикации по каналам. Пакет проходит валидацию и импортируется одной SQLite-транзакцией:
`content_package.py` (общая логика), `POST /registry/content-packages` (HTTP),
`python -m api.import_content_package` (локальный CLI, без HTTP).

Ничего в пакете не публикуется. Импорт создаёт только записи со статусом `draft`.

## Пример

Синтетический fixture-пакет (не привязан к реальному контенту/видео) — см. `_base_package()`
в [`api/tests/test_content_package.py`](tests/test_content_package.py). Отдельного файла-примера
в репозитории нет намеренно: JSON-пример вне тестов легко принять за описание реального контента.

## Схема (schema_version: 1)

```jsonc
{
  "schema_version": 1,
  "product": {
    "product_code": "airfryer-silicone-form"   // ДОЛЖЕН уже существовать в реестре
  },
  "content": {
    "content_code": "synthetic-content-example-001",       // стабильный, не меняется
    "content_type": "short_video",             // video / article / post / short_video / ...
    "title": "...",                            // редактируемое
    "core_idea": "...",
    "audience_segment": "...",
    "pain_or_desire": "...",
    "hypothesis": "...",
    "source_path": "content/....md",           // путь к исходнику скрипта/сценария в репозитории
    "status": "draft"                          // сейчас разрешено только "draft"
  },
  "hooks": [
    {
      "hook_code": "A",                        // стабильный в рамках content
      "hook_text": "...",                      // редактируемое
      "version": 1,
      "status": "draft"                        // сейчас разрешено только "draft"
    }
  ],
  "publication_drafts": [
    {
      "publication_code": "synthetic-content-example-001-tiktok-A-v1", // стабильный, глобально уникальный
      "hook_code": "A",                          // опционально; должен существовать (в пакете или в БД)
      "channel_code": "tiktok",                  // ДОЛЖЕН существовать в реестре (см. GET /registry/channels)
      "status": "draft",                         // сейчас разрешено ТОЛЬКО "draft"
      "destination_url": null,
      "tracking_url": null,
      "utm_source": "tiktok",
      "utm_medium": "organic",
      "utm_campaign": "...",
      "utm_content": "..."
    }
  ]
}
```

## Правила

- **Стабильные ключи**: `product_code`, `content_code`, `hook_code`, `publication_code` не
  меняются между импортами. Отображаемые `title`/`hook_text`/`hypothesis` и т.п. — редактируемые,
  но этот импортёр их **не перезаписывает** молча (см. «Конфликты» ниже).
- **Идемпотентность**: повторный импорт того же пакета не создаёт дублей. Идентичность — по тем
  же стабильным кодам, что использует `registry_db.py`.
- **product_code обязателен и должен существовать** — пакет не создаёт товар. Если товара нет —
  `404`.
- **channel_code проверяется целиком до записи** — один неизвестный канал отменяет весь пакет.
- **Один некорректный элемент отменяет весь пакет** (атомарная транзакция, `ROLLBACK`).
- **Публикуется только `draft`** — `publishing`/`published`/`failed` через этот импортёр
  запрещены, как и любой другой статус, кроме `draft`, для content/hooks/publication_drafts.
- **Секретов быть не должно** — ключи вида `token`/`secret`/`password`/`api_key`/`authorization`
  (в любом регистре, на любом уровне вложенности) отклоняют весь пакет ещё до обращения к БД.

## Конфликты (HTTP 409 / CLI `conflicts`)

Если `content_code` уже существует в реестре, но:

- принадлежит **другому** `product_code` — конфликт по полю `content.content_code`;
- имеет другой `content_type` — конфликт по полю `content.content_type`.

В обоих случаях запись **не обновляется**, весь пакет отклоняется целиком с описанием
конфликтующего поля.

Если существующий `content`/`hook` найден, но у него отличаются редактируемые поля
(`title`, `core_idea`, `hypothesis`, `hook_text` и т.д.) — это **не конфликт**: импорт продолжается,
используется существующая запись (`existing`), а расхождение попадает в `warnings`. Обновление
этих полей — отдельная, явно подтверждённая операция (не часть этого импортёра).

## Ответ импорта

```jsonc
{
  "created": {"content": true, "hooks": ["A", "B"], "publications": ["synthetic-content-example-001-tiktok-A-v1"]},
  "existing": {"content": false, "hooks": [], "publications": []},
  "content_id": 4,
  "hook_ids": {"A": 7, "B": 8},
  "publication_ids": {"synthetic-content-example-001-tiktok-A-v1": 12},
  "warnings": []
}
```

## HTTP: `POST /registry/content-packages`

Тело — content package (см. схему выше). Требует `X-API-Key` (как остальные `/registry/*`).

| Ситуация | HTTP |
|---|---|
| успех (создано и/или уже существовало) | 200 |
| `product_code` не найден | 404 |
| конфликт `content_code`/`content_type` с существующей записью | 409 |
| ошибка валидации (нет обязательного поля, неизвестный `channel_code`, недопустимый статус, секрет в пакете) | 400 |

## CLI: `python -m api.import_content_package`

Работает напрямую с локальной SQLite (без HTTP, без production API/Railway).

```bash
# dry-run (по умолчанию) — ничего не пишет, показывает planned/existing/conflicts
python -m api.import_content_package pkg.json

# реальная запись — только с явным флагом
python -m api.import_content_package pkg.json --apply

# на отдельной временной базе (не production jobs.db)
python -m api.import_content_package pkg.json --apply --db-path /tmp/registry-test.db
```

`pkg.json` — файл с content package в вашей файловой системе (см. схему выше); в репозитории
такого файла нет, чтобы не путать демонстрационные данные с реальным контентом.

Коды выхода: `0` — успех (или dry-run без конфликтов), ненулевой — ошибка валидации,
конфликт (только для dry-run — показывает их в выводе) или нечитаемый файл/немигрированная схема.

## Skill bridge

Skill `ozon-airfryer-growth` живёт **вне Git-репозитория** (`D:/OzonGrowthProject/.claude/skills/`)
и сам по себе создаёт только Markdown (сценарии, hooks-списки, промпты) — без стабильных кодов
и без JSON. Он не изменён этим мостом. Рекомендуемый способ связи:

1. Skill продолжает работать как раньше (Markdown в `content/`).
2. Дополнительно, по запросу владельца, агент вручную формирует один content-package JSON
   (по этой схеме) на основе уже готового сценария/hooks.
3. JSON проходит `python -m api.import_content_package <path>` (dry-run) для проверки.
4. Импорт в реестр (`--apply` или HTTP) выполняется только по отдельному подтверждению владельца —
   автоматической записи из skill в реестр нет.
