# Кампания coating-protect-2026-07 («Защита антипригарного покрытия»)

Первый контентный цикл агента-оркестратора **ozon-autopilot**
(`.claude/agents/ozon-autopilot.md`, документация — `AUTOPILOT_ORCHESTRATOR.md`
в корне репозитория).

- **campaign_code:** `coating-protect-2026-07`
- **content_code:** `coating-protect-ad` (короткий ролик 9:16)
- **product_code:** `airfryer-silicone-form` (Ozon арт. 1931921872)
- **Идея:** аэрогриль чаще портит не готовка, а мытьё — жёсткая губка может повреждать антипригарное
  покрытие; форма-барьер бережёт чашу (угол №2 из MARKETING_HYPOTHESIS.md, loss aversion).

## Файлы

| Файл | Что это |
|---|---|
| `campaign_manifest.json` | Паспорт кампании: коды, статус, допущения, что требует подтверждения |
| `brief.md` | Обоснование темы, анти-дубль с видео №2, факт-чек рамка |
| `short-video-script.md` | Сценарий ролика: идея, 3 хука, voice-over, CTA, тайминг, кадры |
| `hooks.json` | Хуки A/B/C (машиночитаемо) |
| `storyboard.md` | Раскадровка 7 кадров с таймингом и озвучкой |
| `higgsfield-prompts.md` | Промпты на каждый кадр (Style Anchor, товар 1:1) — генерация НЕ запускалась |
| `platform-captions.md` | Тексты YouTube Shorts / Reels / TikTok / VK с `{{OZON_ARTIKUL}}` / `{{OZON_LINK}}` |
| `dzen-article.md` | Статья Дзена (отдельный материал кампании) |
| `telegram-post.md` | Пост Telegram (отдельный материал кампании) |
| `ad-angles.md` | 2 рекламных угла (заготовки, реклама не запускалась) |
| `content-package.json` | Пакет для реестра: content + 3 hooks + 12 draft-публикаций |
| `qa-report.md` | Результаты QA и локального dry-run |

### Визуальный конвейер (добавлено 2026-07-02)

| Файл | Что это |
|---|---|
| `visual-generation-plan.json` | План генерации: 3 кандидата/сцену, ≤3 раундов, бюджет, гейты |
| `scene-specs/scene-01..07.json` | Спецификации сцен: immutable elements, референсы, точное число еды, руки, камера, связи, animation intent |
| `visual-qa-report.template.json` | Шаблон отчёта visual-director |
| `sequence-qa-report.template.json` | Шаблон отчёта sequence-director |

Канон внешнего вида: `assets/visual-bible/airfryer-silicone-form/`.
Конвейер: `VISUAL_AUTOMATION_PIPELINE.md`. Изображения НЕ генерировались, API spend: $0.

## Статус и следующий шаг

Статус кампании — в `campaign_manifest.json` (`status`).
Всё создано локально, только draft. Production не изменялся, ничего не
публиковалось, платные генерации не запускались.

**Следующее подтверждение владельца:** запуск платной генерации КАНДИДАТОВ кадров
через OpenAI Images API (`--apply`, ~$6.30 за первый раунд 7×3). Higgsfield —
только после победителей всех сцен + sequence approval + отдельного «да».
