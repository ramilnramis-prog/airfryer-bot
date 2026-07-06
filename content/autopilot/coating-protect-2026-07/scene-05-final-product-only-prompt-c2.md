# Scene-05 — final product-only prompt (ready for future run, NOT executed)

Собран из `content/autopilot/coating-protect-2026-07/video-continuity-block.md`
(ТОЛЬКО clean blockquote-текст, распарсенный
`product_only_policy.parse_clean_continuity_prompt()` — НЕ весь .md файл)
+ `video-scene-prompts-product-only.md` (scene-05, **C2 revision** —
angled/asymmetric framing), через
`api.media_pipeline.product_only_scene_runner.run_product_only_scene(campaign_dir,
"scene-05", apply=False)` — тот же код и тот же вызов, что построит реальный
`ImageRequest` для будущего `--apply`. Этот .md файл сгенерирован из
фактического dry-run отчёта, не напечатан вручную — text здесь и в
`scene-05-product-only-apply-dry-run.json` гарантированно идентичен
(включая SHA256 промпта).

**Статус: план. Ни один API (OpenAI/Higgsfield) НЕ вызывался для
получения этого текста.** `openai_calls: 0`, `higgsfield_calls: 0`.
`prompt_sha256: 9b93134892de66037c4c9cbada46c1d9a74218cd94aaed49b920621a7f23e08a`.

**C2 root cause fix.** scene-05 C1 (frontal basket, level left/right hand
tabs) и его local-transform V2 salvage были отклонены: `real-product-v1/
product_45deg` — это 3/4-ракурс с асимметричной высотой ручек (левая выше,
правая ниже), а C1's AI plate рисовал фронтальный ракурс с ручками на одном
уровне. Ни один rigid transform (только uniform scale + малый rotation +
translation, БЕЗ warp) не может согласовать обе ручки одновременно —
подгонка одной неизбежно уводит другую на 150+px (см.
`scene-05-qa-report-v2.json`). C2 просит AI plate сразу рисовать high 3/4
top-down ракурс, диагональную ось upper-left→lower-right и асимметричные
руки (левая выше/ближе к будущей верхне-левой ручке, правая ниже/ближе к
будущей нижне-правой ручке) — совместимые с `product_45deg` +
`APPROVED_TRANSFORM_B` напрямую, без per-plate transform (per-plate
transform остаётся разрешён как fallback, `per_plate_transform_allowed: true`,
но цель C2 — сделать его ненужным).

**Approach: `product_placement_plate`** (PRODUCT PLACEMENT PLATE). AI рисует
только "plate" (кухня/руки/корзина/пустое место под товар + rough food
cluster), никогда финальный товар.

**model_prompt_clean: true.**
`build_model_prompt()` берёт `plan["clean_continuity_prompt"]`
(только английский blockquote), не `plan["continuity_block_text"]` (весь
файл).

**Mandatory image refs: НЕТ.** `reference_images: []` — `mode=generate`
(НЕ `edit`): AI получает только текстовый prompt ниже, без единого
input-изображения.

---

## model_prompt — ТОЛЬКО это уходит в API (дословно, ничего больше)

> Cozy clean white home kitchen, warm daylight coming from the left. Same black air fryer with an open square basket in every shot. Same woman's natural hands throughout — no rings, no bracelets, no watch, short unpolished nails. Same grey ribbed sweater sleeves visible at the wrists in every shot. Realistic home cooking photo, DSLR 50mm look, shallow depth of field. No CGI, no illustration, no 3D render. No text, no watermark, no logo. Vertical 9:16, 720×1280.

High 3/4 top-down camera angle looking down and slightly forward into the open air fryer basket, matching a diagonal product axis from the upper-left to the lower-right of the frame, not a frontal straight-on view. The woman's hands, in grey ribbed sweater sleeves, are positioned asymmetrically along that diagonal as if lifting an object out of the basket: the left hand is higher in the frame, near the upper-left corner of the basket where the future flat handle tab will be, and the right hand is lower in the frame, near the lower-right corner of the basket where the other future flat handle tab will be; thumbs angled toward those future flat handle tab positions. This leaves a clean, empty central placement area in the basket, aligned with the diagonal axis, for a square silicone liner to be inserted later. In the central placement area, include a loose cluster of exactly 3 roasted golden chicken thighs with potato wedges, positioned where the liner interior will be after compositing. Do not draw a completed silicone liner. Do not draw redesigned or fake handles. Do not draw any duplicate tray or basket insert. Do not draw a black insert or black liner inside the basket. Only very soft contact shadows/cues are allowed in the empty placement area. Around and below the placement area, the black air fryer basket is visibly clean and shiny.

The final silicone form is inserted after generation from real-product-v1. Do not invent or redesign the product. Leave the product placement area clean.

Negative prompt (avoid): a completed or fully rendered silicone liner, redesigned or fake handles, loop handles, vertical oval holes, any duplicate tray or basket insert, a black insert or black liner inside the basket, hands gripping the basket rim instead of the expected handle positions, level or symmetric left/right hand heights, frontal straight-on camera angle, extra fingers, missing fingers, jewelry, dirty basket, text, watermark, logo.

**Ничего из pipeline_product_lock_instruction (геометрия ручек, материал,
силуэт) в этот текст НЕ входит** — модель не может достоверно нарисовать
real-product-v1 и не должна пытаться; PLACEMENT_NOTE внутри model_prompt
выше — единственное, что модель знает о товаре, и это негативная
инструкция ("оставь место чистым"), не просьба нарисовать.

## pipeline_product_lock_instruction — НЕ отправляется модели

Используется ТОЛЬКО compositor'ом/QA после генерации:

> PIPELINE ONLY — NOT sent to the image model as a drawing instruction; used by the compositor/QA instead. The silicone form is not generated from imagination. The final product layer must be inserted from real-product-v1 and remain pixel-faithful: exact flat corner handle tabs, short horizontal slots, matte dark grey silicone, ribbed bottom, proportions, silhouette. Вставляется через APPROVED_TRANSFORM_B (deterministic compositing), никогда не из AI-редактирования. C2: AI plate camera angle/diagonal axis/asymmetric hand heights теперь выбраны так, чтобы APPROVED_TRANSFORM_B (или минимальная rigid-подстройка в его пределах) подошёл напрямую, без риска, что согласование одной ручки разваливает другую (см. scene-05-hands-experiment-retrospective.md и V2 salvage отчёты для истории C1). Food cluster извлекается из AI plate ТОЛЬКО внутри product_interior_food_mask (см. scene-05-product-only-apply-dry-run.json:food_composite_strategy) и композитится внутрь товара отдельным шагом — не в этом model_prompt. См. `scene-05-product-only-plan.json` для полного плана и QA reject conditions.

## expected_plate_geometry (C2, STEP 2) — code-derived, не выдумано

Вычислено из `build_all_layer_masks(DEFAULT_VIEW, APPROVED_TRANSFORM_B,
APPROVED_CANVAS_SIZE, repo_root)` (`api/media_pipeline/product_only_scene_runner.py:
get_expected_plate_geometry_c2`) — те же реальные product/handle маски, что
использует compositor/QA:

```json
{
  "camera_angle": "high_3_4_top_down",
  "expected_product_axis": "upper_left_to_lower_right",
  "left_future_handle_region": [
    190,
    44,
    275,
    100
  ],
  "right_future_handle_region": [
    549,
    166,
    595,
    259
  ],
  "basket_region_target": [
    145,
    28,
    595,
    380
  ],
  "product_interior_food_mask_bbox": [
    200,
    79,
    539,
    329
  ],
  "source": "api/media_pipeline/compositor/scene05_layer_masks.py:build_all_layer_masks with DEFAULT_VIEW (product_45deg) + APPROVED_TRANSFORM_B -- regions are computed from the real product asset, not invented",
  "reject_if_handles_level": true,
  "reject_if_basket_frontal": true,
  "reject_if_black_insert_drawn": true
}
```

## food_composite_strategy — тоже НЕ отправляется модели

`food_extraction: implemented`. Метод:
extract_food_cluster(): AI plate pixels restricted to product_interior_food_mask (deterministic geometry from real-product-v1 + APPROVED_TRANSFORM_B, NOT AI-guessed) -- silicone/handles/walls/background NEVER taken from AI

`product_interior_food_mask`: bbox `[200, 79, 539, 329]`
на канвасе `[720, 1280]`.

---

## Request contract (совпадает с scene-05-product-only-apply-dry-run.json)

| поле | значение |
|---|---|
| model | `gpt-image-2` |
| endpoint | `POST /images/generations` |
| mode | `generate` (нет reference images/масок) |
| size | `720x1280` |
| n | `1` |
| output_format | `png` |
| retries | `0` |
| max_calls | `1` |
| hard_cap_usd | `0.5` |
| prompt_sha256 | `9b93134892de66037c4c9cbada46c1d9a74218cd94aaed49b920621a7f23e08a` |
| per_plate_transform_allowed | `true` |
| allowed_transform_type | `rigid_only` |

## Что явно ЗАПРЕЩЕНО просить у модели

- рисовать законченную силиконовую форму;
- рисовать любые (redesigned/fake) ручки;
- рисовать дублирующий лоток/вставку в корзину;
- рисовать чёрный insert/liner внутри корзины (C2, новое: то же, что дало
  duplicate_ai_product_visible в C1);
- рисовать ручки/руки на одном уровне (C2, новое: level handles — сам по
  себе reject, см. QA_GATES_C2_GEOMETRY_PRECHECK ниже) или фронтальный
  ракурс корзины.

## Что НЕ входит в этот prompt

- никаких mandatory image refs для рук/человека/кухни/аэрогриля
  (`reference_images: []`, `mode=generate`);
- никакого творческого описания формы товара — товар не в этом
  API-запросе вообще, он вставляется отдельным compositing-шагом;
- никакой русской документации/markdown-заголовков/file paths (см.
  model_prompt_clean выше);
- никакой ссылки на `person-b-exhausted-01`, `real-grip-motion-01`,
  `v2-hand-hold-01`, `v2-form-in-basket-01`, `food-wings-01` — все пять
  запрещены `campaign_visual_policy.json` и проверяются
  `api.media_pipeline.product_only_policy.assert_no_forbidden_appearance_refs`.

## STEP 3 — QA_GATES_C2_GEOMETRY_PRECHECK (перед transform salvage)

```json
[
  {
    "id": "c2-1",
    "name": "basket_perspective_matches_product_45deg",
    "stage": "precheck_before_transform_salvage",
    "check": "AI plate camera angle reads as high 3/4 top-down (not frontal), compatible with the product_45deg photo angle"
  },
  {
    "id": "c2-2",
    "name": "future_handle_regions_asymmetric",
    "stage": "precheck_before_transform_salvage",
    "check": "left future handle position is visibly higher in frame than the right (matches left_future_handle_region vs right_future_handle_region)"
  },
  {
    "id": "c2-3",
    "name": "no_level_left_right_tabs",
    "stage": "precheck_before_transform_salvage",
    "check": "left/right hand or tab positions are NOT at the same height -- a level pair is the exact C1 failure mode, reject immediately"
  },
  {
    "id": "c2-4",
    "name": "no_black_insert_or_liner_in_basket",
    "stage": "precheck_before_transform_salvage",
    "check": "no AI-drawn black container/liner/tray shape occupies the basket interior (same defect that caused C1 duplicate_ai_product_visible)"
  },
  {
    "id": "c2-5",
    "name": "ai_plate_has_clean_empty_product_area",
    "stage": "precheck_before_transform_salvage",
    "check": "central placement area is empty/clean aside from the rough food cluster -- no pre-drawn product silhouette"
  },
  {
    "id": "c2-6",
    "name": "hands_near_expected_asymmetric_handle_regions",
    "stage": "precheck_before_transform_salvage",
    "check": "left/right hands sit close to left_future_handle_region / right_future_handle_region from get_expected_plate_geometry_c2()"
  }
]
```

Если любой из этих gates не проходит на сыром AI plate — candidate reject
ДО попытки локального transform salvage (V2-стиль подгонки, которая для C1
всё равно не смогла бы решить асимметрию ручек).

## Хуки A/B/C

Этот prompt — shared body, одинаков для всех трёх hooks этого видео (см.
`hooks_usage` в `video-scene-prompts-product-only.md`). Между hooks
меняется только opener перед scene-01, не этот кадр.

## Перед реальным запуском

Реальный OpenAI вызов по этому prompt — через
`python -m api.media_pipeline.cli product-only-scene --campaign
coating-protect-2026-07 --scene scene-05 --apply` — требует
`OPENAI_API_KEY` в окружении, ограничен hard cap `$0.5`,
`max_calls=1`, `retries=0`, и отдельного явного подтверждения владельца.
Этот файл — только план. `openai_calls_executed: 0`, `higgsfield_calls_executed: 0`.
