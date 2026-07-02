# VISUAL_AUTOMATION_PIPELINE — автоматизированный визуальный конвейер

Система, в которой ozon-autopilot доводит кадры кампании от идеи до готовности
к анимации без ручного перебора генераций — с жёстким QA на каждом шаге и
обязательными подтверждениями владельца перед любыми тратами.

## Архитектура

```
идея + storyboard (ozon-autopilot, кампания в content/autopilot/<code>/)
        │
        ▼
creative-scout ──── паттерны рекламы кухонных товаров → creative-research.md
        │
        ▼
scene-specs/scene-NN.json  ←── Visual Bible (assets/visual-bible/<product>/)
        │
        ▼
image-producer ── api/media_pipeline (OpenAI Images API, **gpt-image-2**)
        │           3 кандидата/сцену, reference images (fidelity автоматическая)
        │           dry-run по умолчанию; реальный вызов только --apply
        ▼
VisionEvaluator ── OpenAIVisionEvaluator (gpt-5.4-mini, Responses API,
        │           image inputs + structured output json_schema strict):
        │           РЕАЛЬНЫЙ анализ пикселей кандидата против референсов;
        │           арбитр gpt-5.5 — выключен по умолчанию, только спорные случаи
        ▼
visual-director ── hard-fail проверки → scoring 10×(0-100) → РОВНО 1 победитель
        │           или отклонить всех + regeneration brief
        │◄──────── перегенерация (максимум 3 раунда) ──┐
        │                                              │
        ▼                                              │
sequence-director ── все победители вместе, скачки между смежными кадрами
        │            список сцен на перегенерацию ─────┘
        ▼ approved
ГЕЙТ higgsfield_gate: победители всех сцен + sequence approved + «да» владельца
        │
        ▼
Higgsfield MCP (анимация «денежных» кадров) → animation-qa → монтаж (CapCut)
```

Claude Code — оркестратор. ChatGPT-интерфейс и браузерная автоматизация не
используются. Higgsfield — только после визуального approval.

## Роли агентов (.claude/agents/, синхронизированы с D:/OzonGrowthProject/.claude/agents/)

| Агент | Роль | Решения |
|---|---|---|
| `ozon-autopilot` | Оркестратор кампании целиком | ведёт состояния, останавливается на гейтах |
| `creative-scout` | Исследование рекламных паттернов (принципы, не копии) | не генерит, только research |
| `image-producer` | Промпты + запуск генерации через media_pipeline | НЕ судит качество |
| `visual-director` | Hard-fail + scoring 3 кандидатов, один победитель | может отклонить всех |
| `sequence-director` | Целостность последовательности 1→7 | approved только при 0 скачков |
| `animation-qa` | Приёмка клипов Higgsfield | hard fail = клип не идёт в монтаж |

## Visual Bible (`assets/visual-bible/airfryer-silicone-form/`)

- `visual_bible.json` — канон: форма (тёмно-серый матовый квадрат ~18.5×18.5×5 см,
  РОВНО 2 овальные ручки на противоположных стенках, рифлёное дно), один чёрный
  аэрогриль с окном и одной корзиной, женские руки одного вида, одна кухня, свет
  слева, камера 35mm/9:16, правила количества еды, запрещённые изменения.
- `continuity_rules.json` — hard-fail коды, scoring, sequence-проверки, лимиты, гейты.
- `references/{product,airfryer,kitchen,hands,food}/sources.json` — указатели на
  существующие референсы (бинарники не дублируются; канон товара —
  `content/assets/forma_6angles.png`). Отсутствующие референсы перечислены в
  README Visual Bible — их предоставляет владелец, они не выдумываются.
- `approved/` — утверждённые кадры кампаний с метаданными.

## media_pipeline (`api/media_pipeline/`, только stdlib)

| Модуль | Что делает |
|---|---|
| `models.py` | SceneSpec, CandidateObservation, вердикты, ImageRequest/Result, интерфейс **ImageProvider** (не привязаны к одному вендору) |
| `openai_images_client.py` | OpenAIImagesProvider: **gpt-image-2 по умолчанию** (OPENAI_IMAGE_MODEL для override, gpt-image-1 — legacy fallback), **capability map** (gpt-image-2 никогда не получает `input_fidelity` — модель обрабатывает image inputs с высокой fidelity сама), generations + edits, бюджет-гейт, лимит кандидатов, без retries |
| `vision_provider.py` | Интерфейс **VisionEvaluator**, строгая схема результата (validate_vision_result), MockVisionEvaluator, перевод в CandidateObservation, условия арбитража (needs_arbitration) |
| `openai_vision_evaluator.py` | **OpenAIVisionEvaluator**: gpt-5.4-mini (OPENAI_VISION_MODEL), Responses API с image inputs (кандидат + референсы по категориям + prev scene) и structured output (json_schema strict); арбитр gpt-5.5 (OPENAI_VISION_ARBITER_MODEL) — выключен по умолчанию, отдельный флаг, не для каждого изображения |
| `budget.py` | **SpendTracker**: estimate до вызова, hard cap с немедленной остановкой, фактический usage → actual_spend_usd (когда считаемо), раздельно image_generation / vision_evaluation, без retries |
| `mock_provider.py` | MockImageProvider для тестов и репетиций без сети |
| `visual_qa.py` | 13 hard-fail правил, scoring 10 измерений, выбор победителя, regeneration brief |
| `sequence_qa.py` | 8 типов скачков между смежными кадрами, вердикт approved |
| `pipeline.py` | раунды генерации (≤3), `higgsfield_gate`, сохранение отчётов |
| `cli.py` | `plan` / `generate [--apply]` / **`pilot`** (только scene-05, cap $2.00) / `qa` / `sequence-qa` — структурированный JSON, коды выхода 0/1/2 |

### Честная история vision-оценки

До 2026-07-02 реальные пиксели автоматически НЕ анализировались: visual_qa
применял правила к наблюдениям, которые заполнял вручную агент (или mock в
тестах). Теперь кандидатов смотрит OpenAIVisionEvaluator (gpt-5.4-mini) —
изображения передаются в Responses API как base64 image inputs, ответ строго
валидируется схемой; свободному тексту не доверяем.

Журналируется для каждого кандидата: prompt, revised prompt, provider, model,
timestamp, candidate id, результат QA.

### Безопасность и бюджет

- `OPENAI_API_KEY` — только из environment, читается в момент вызова, не
  логируется, не сохраняется, в dry-run даже не читается.
- **Dry-run по умолчанию**: без `--apply` сетевых вызовов нет вообще (проверено тестом).
- **Бюджет (SpendTracker)**: фиксированных смет нет — estimate до каждого вызова,
  hard cap с немедленной остановкой до следующего запроса, фактический usage из
  ответа API (actual_spend_usd, когда цены токенов позволяют посчитать),
  раздельный учёт image generation и vision evaluation. Без автоматических retries.
- Лимиты: 3 кандидата на запрос, максимум 3 раунда на сцену, дальше — эскалация владельцу.
- Пилот: только scene-05, hard cap $2.00, 0 перегенераций (cmd_pilot отклоняет
  остальные сцены).

## Hard-fail правила (кандидат отклоняется при любом)

форма ≠ эталон · ручек не ровно 2 · изменён цвет/материал · другой аэрогриль ·
мужские руки · плохая анатомия рук · захват не за ручки · изменилось число еды ·
текст/watermark · невозможные пересечения · CGI-вид · кадр неанимируем ·
не стыкуется с соседней сценой. Плюс сценные условия из scene spec
(например, «форма НЕ должна быть в кадре» для сцен 1-2, 6).

## Scoring (после hard-fail)

10 измерений 0–100: product_reference_match, airfryer_reference_match,
human_continuity, hand_anatomy, food_continuity, photorealism, composition,
marketing_clarity, animation_readiness, adjacent_scene_continuity.
Пороги: каждое ≥ 70 И среднее ≥ 80. Ниже порога победитель НЕ выбирается.

## Выбор из трёх и перегенерация

1. image-producer генерирует 3 кандидатов сцены (с референсами).
2. visual-director заполняет наблюдения → `cli qa` детерминированно применяет
   правила: hard-fail кандидаты вылетают, остальные скорятся, победитель —
   максимум total. Сохраняются: оценки, причины, победитель, причины отклонения
   каждого проигравшего.
3. Если победителя нет — regeneration brief (конкретные починки: «exactly TWO
   oval handles», «woman's hands…») автоматически добавляется в промпт
   следующего раунда. Максимум 3 раунда, дальше `needs_owner`.

## Sequence QA

sequence-director смотрит всех победителей вместе: 8 типов скачков по каждой
паре смежных кадров + сквозные проверки (одна форма в сценах 3–7, одна корзина
в 1/2/5/6, идентичная еда в 4–5). Любой скачок → `approved: false` + список
сцен на перегенерацию (`cli sequence-qa` возвращает exit 2).

## Блокировка Higgsfield

`media_pipeline.pipeline.higgsfield_gate(scene_decisions, sequence_report, owner_approved)`
бросает `PipelineGateError`, если: (а) хоть у одной сцены нет победителя,
(б) sequence QA не выполнялся, (в) sequence не approved, (г) нет явного «да»
владельца. Все четыре условия покрыты тестами. animation-qa затем бракует
клипы с деформациями до монтажа.

## Что требует подтверждения владельца

1. **Платная генерация кандидатов** (OpenAI `--apply`) — первый раунд кампании
   coating-protect ~$6.30 (7 сцен × 3 × ~$0.30).
2. **Анимация Higgsfield** — после sequence approval, отдельное «да».
3. Перегенерация сверх 3 раундов любой сцены.
4. Обновление канона Visual Bible.
5. Import в production реестр и публикация (вне этого конвейера, как раньше).

## Путь к снятию ручных подтверждений

1. Сейчас: «да» на каждый платный этап (изображения, анимация).
2. Далее: владелец утверждает бюджет кампании один раз (например $15) —
   конвейер сам ходит в OpenAI в пределах cap, отчёт по факту; Higgsfield всё
   ещё по отдельному «да».
3. Затем: авто-анимация по списку «денежных» кадров при зелёном sequence QA,
   владелец смотрит только финальный набор перед монтажом.
4. Цель: подтверждаются только идея кампании и общий бюджет; остальное — гейты
   конвейера (hard-fail, scoring, sequence, animation QA) вместо человека.

## Как запустить (когда владелец скажет «да»)

```bash
# план (без сети)
python -m api.media_pipeline.cli plan content/autopilot/coating-protect-2026-07

# ОДНОСЦЕНОВЫЙ ПИЛОТ (первый платный шаг; gpt-image-2, quality medium,
# 3 кандидата, cap $2.00, авто-VisionEvaluator, без перегенераций)
set OPENAI_API_KEY=...   # только в env
python -m api.media_pipeline.cli pilot content/autopilot/coating-protect-2026-07 --scene scene-05 --apply

# полная генерация сцены (после решения по пилоту)
python -m api.media_pipeline.cli generate content/autopilot/coating-protect-2026-07 --scene scene-01 --apply

# вердикт по наблюдениям visual-director / последовательности
python -m api.media_pipeline.cli qa <observations.json>
python -m api.media_pipeline.cli sequence-qa <transitions.json>
```
