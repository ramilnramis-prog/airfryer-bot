# Кампания coating-protect-2026-07 («Защита антипригарного покрытия»)

Первый контентный цикл агента-оркестратора **ozon-autopilot**
(`.claude/agents/ozon-autopilot.md`, документация — `AUTOPILOT_ORCHESTRATOR.md`
в корне репозитория).

- **campaign_code:** `coating-protect-2026-07`
- **content_code:** `coating-protect-ad` (короткий ролик 9:16)
- **product_code:** `airfryer-silicone-form` (Ozon арт. 1931921872)
- **Идея:** аэрогриль портит не готовка, а мытьё — губка стирает антипригарное
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

## Статус и следующий шаг

Статус кампании — в `campaign_manifest.json` (`status`).
Всё создано локально, только draft. Production не изменялся, ничего не
публиковалось, платные генерации не запускались.

**Следующее подтверждение владельца:** запуск генерации кадров в Higgsfield
по `higgsfield-prompts.md` (платно).
