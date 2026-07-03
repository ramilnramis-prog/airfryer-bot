# QA-сравнение v1 → v2 — scene-05 (coating-protect-2026-07)

Дата v2: 2026-07-02. Кандидаты НЕ перегенерировались: те же три PNG
(`scene-05-c1/c2/c3.png`), Images API calls = 0. Оценка — reevaluate,
gpt-5.4-mini, арбитр OFF, hard cap $2.00.

## Что было исправлено между v1 и v2

**Дефект 1 — ложный adjacent_scene_break.** В v1 evaluator получал
`NEXT SCENE REQUIREMENTS: scene-06 — форма уже вынута, пустая чистая корзина`
без объяснения семантики и трактовал это как требование к ТЕКУЩЕМУ кадру:
все три кандидата получили hard fail за то, что в них «ещё есть еда и форма
не вынута» — хотя scene-05 по собственному спеку и должна показывать подъём
формы с блюдом. В v2 код `adjacent_scene_break` удалён и заменён на:
- `current_scene_violation` — кадр нарушает собственный scene spec;
- `transition_impossible` — из кадра физически невозможно анимировать переход
  в состояние следующей сцены;
- `next_scene_state_not_yet_present` — информационный флаг, НЕ дефект.

**Дефект 2 — ненадёжный food count.** В v1 модель возвращала одно число
`food_count` без доказательств. В v2 обязателен `food_count_detail`
(visible/partially_occluded/uncertain/expected, confidence, evidence,
расположение каждого элемента, region формы) + при confidence < 0.85,
расхождении с expected или uncertain > 0 — second-pass подсчёт на
увеличенном crop области формы. Расхождение проходов → `food_count_uncertain`
(блокирует победителя, число не утверждается).

**Попутный дефект, вскрытый при v2 (шкала scores).** Первый прогон v2 показал,
что модель отдаёт scores в шкале 0–1 (в v1 — 0–10: «9» из отчёта v1 — это та
же болезнь), из-за чего детерминированный порог 70 срезал всех. Исправлено:
structured-схема теперь требует INTEGER 0–100 + явная инструкция шкалы.
Финальный прогон v2 — корректные значения 92–98.

## Hard fails: v1 → v2

| Кандидат | v1 hard fails | v2 hard fails |
|---|---|---|
| A (c1) | adjacent_scene_break | — (нет) |
| B (c2) | hand_anatomy, impossible_intersection, not_animatable, adjacent_scene_break | — (нет) |
| C (c3) | not_animatable, adjacent_scene_break | — (нет) |

**Почему исчез adjacent_scene_break:** это был артефакт неверной семантики
перехода, а не свойство изображений. В v2 все кандидаты получили
`transition_possible=true` — кадр подъёма формы естественно анимируется в
состояние scene-06 (форма вынута, корзина пуста, под формой корзина уже
видна чистой). Ложные v1-коды B (hand_anatomy из «обрезанных кистей»,
impossible_intersection из нейтрального наблюдения «корзина опирается на
проём как положено», not_animatable из заниженного continuity) в v2 при
корректном промпте не подтвердились: анатомия чистая, пересечений нет,
анимируемость высокая.

## Food count v2 (подтверждено)

| Кандидат | visible | occluded | uncertain | expected | conf | second pass | статус |
|---|---|---|---|---|---|---|---|
| A (c1) | 3 | 0 | 0 | 3 | 0.98 | не требовался | confirmed = 3 |
| B (c2) | 3 | 0 | 0 | 3 | 0.93 | не требовался | confirmed = 3 |
| C (c3) | 3 | 0 | 0 | 3 | 0.94 | не требовался | confirmed = 3 |

Что модель посчитала (items, только целевая еда; картофель явно исключён):
- A: chicken thigh — left side; center/top; right/front of basket.
- B: chicken thigh — left side; center-back; right side of basket.
- C: chicken thigh — left side; center top; right side of basket.

Независимая проверка оператора: crop области формы каждого кандидата
(upscale ×2, по region из отчёта) — на всех трёх отчётливо ровно 3 бёдрышка.
Подозрение «в B и C только 2» возникло из-за мелких превью контактного листа
(задний трети́й элемент в B/C читался как картофель). Расхождения проходов
нет → second pass по правилам не требовался, статус confirmed честный.

## Итоговые scores v2 (0–100)

| Измерение | A (c1) | B (c2) | C (c3) |
|---|---|---|---|
| product_reference_match | 98 | 98 | 98 |
| airfryer_reference_match | 98 | 97 | 97 |
| human_continuity | 97 | 96 | 96 |
| hand_anatomy | 98 | 98 | 96 |
| food_continuity | 96 | 95 | 98 |
| photorealism | 97 | 96 | 95 |
| composition | 95 | 93 | 92 |
| marketing_clarity | 94 | 94 | 94 |
| animation_readiness | 96 | 96 | 96 |
| adjacent_scene_continuity | 95 | 92 | 94 |
| **total** | **96.4** | **95.5** | **95.6** |

## Может ли кандидат быть победителем

- A (c1): ДА — прошёл все hard-fail (форма-канон, ровно 2 овальные ручки,
  тот же аэрогриль, женские руки с чистой анатомией, захват за обе ручки,
  еда 3/3 confirmed, фотореализм, анимируемость, логичный переход в scene-06)
  и оба порога (все измерения ≥ 70, total 96.4 ≥ 80).
- B (c2): мог бы (все проверки пройдены, total 95.5), проиграл по total.
- C (c3): мог бы (все проверки пройдены, total 95.6), проиграл по total.

**ПОБЕДИТЕЛЬ v2: scene-05-c1 (A), total 96.4.** Выбран не «потому что пропал
adjacent_scene_break», а по полному проходу hard-fail + scoring; A лидирует
по большинству измерений (композиция, фотореализм, руки, переход).

Оговорка: разрыв total между A и C — 0.8 < 5, по правилу needs_arbitration
это спорный случай для арбитра, но gpt-5.5 запрещён условиями задачи
(arbiter OFF, calls = 0). Детерминированное правило «максимальный total»
даёт A; финальное слово — за владельцем.

## Расход v2 (только vision, генерации не было)

- Основные оценки: 2 прогона × 3 вызова gpt-5.4-mini (первый прогон вскрыл
  дефект шкалы scores и был повторён после фикса) = 6 vision-вызовов.
- Second pass: 0. Арбитр: 0. Images API: 0. Higgsfield: BLOCKED.
- Оценка по гейту бюджета: 6 × $0.05 = $0.30 (cap $2.00 не приближен).
- Реальные токены финального прогона: 3 × (9153 input + ~400 output);
  первого прогона: 3 × (9088 input + ~417 output). Точный actual в USD
  недоступен (usage без таблицы цен) — сверять по биллингу OpenAI.

## Файлы

- v1 (не изменялся): `pilot-report.json` (+ резервная копия `pilot-report.json.bak`)
- v2: `pilot-report-v2.json`
- Это сравнение: `qa-comparison-v1-v2.md`
