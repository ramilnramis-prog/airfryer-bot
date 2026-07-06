# Scene-05 — final product-only prompt (ready for future run, NOT executed)

Собран из `content/autopilot/coating-protect-2026-07/video-continuity-block.md`
(ТОЛЬКО clean blockquote-текст, распарсенный
`product_only_policy.parse_clean_continuity_prompt()` — НЕ весь .md файл)
+ `video-scene-prompts-product-only.md` (scene-05, **C3 revision** —
no-hands result shot), через
`api.media_pipeline.product_only_scene_runner.run_product_only_scene(campaign_dir,
"scene-05", apply=False)` — тот же код и тот же вызов, что построит реальный
`ImageRequest` для будущего `--apply`. Этот .md файл сгенерирован из
фактического dry-run отчёта, не напечатан вручную — text здесь и в
`scene-05-product-only-apply-dry-run.json` гарантированно идентичен
(включая SHA256 промпта).

**Статус: план. Ни один API (OpenAI/Higgsfield) НЕ вызывался для
получения этого текста.** `openai_calls: 0`, `higgsfield_calls: 0`.
`prompt_sha256: 9842d38e3aae2777460ca9789e7acb5cad79aae941e88e3376c0043b7c464f04`.

**C3 decision (после отклонения C1 и C2).** В product-only compositing руки,
держащие ручки, требуют корректного front/back occlusion вокруг вставленного
real-product-v1 слоя. C1 (frontal basket, level hand tabs) и C2 (high 3/4
top-down, asymmetric hand heights) оба показали, что сгенерированные руки не
выравниваются надёжно с real-product-v1 после deterministic overlay — это
occlusion-проблема compositing'а, не решается только правкой текста prompt
(см. `scene-05-qa-report.json` для C1, `scene-05-c2-qa-report.json` для C2).
Решение: scene-05 больше не пытается быть "руки поднимают форму за ручки".
Новый смысл сцены — **no-hands result shot**: готовое блюдо в реальной форме
внутри чистого аэрогриля, без рук/человека в кадре, без lifting action, без
handle-grip взаимодействия. Рекламный смысл сохраняется: "еда готовится в
форме, корзина остаётся чистой". Товар остаётся 100% канонический
real-product-v1.

**Approach: `product_placement_plate`** (PRODUCT PLACEMENT PLATE), без
hands-слоя: AI рисует только "plate" (кухня/корзина/пустое место под товар +
rough food cluster, БЕЗ рук/человека), финальный товар вставляется отдельным
deterministic шагом ПОСЛЕ генерации.

**model_prompt_clean: true. no_hands_prompt: true.**
`build_model_prompt()` берёт `plan["clean_continuity_prompt"]`
(только английский blockquote), не `plan["continuity_block_text"]` (весь
файл) -- **кроме** сцен с `scene_variant == "no_hands_result_shot"`: для них
вместо этого используется `NO_HANDS_CONTINUITY_PROMPT` (тот же текст без
строк про руки/рукава — "Same woman's natural hands...", "Same grey ribbed
sweater sleeves..."). **Fix (замечание владельца на первом C3 draft):**
раньше continuity-текст с позитивной инструкцией про руки/рукава всё равно
попадал в model_prompt, а сцено-специфичный текст пытался её "отменить"
фразой "this overrides..." — противоречивый prompt. Теперь позитивная
инструкция про руки/рукава просто никогда не отправляется для этой сцены,
и никакого "override" в тексте больше нет.

**Mandatory image refs: НЕТ.** `reference_images: []` — `mode=generate`
(НЕ `edit`): AI получает только текстовый prompt ниже, без единого
input-изображения.

---

## model_prompt — ТОЛЬКО это уходит в API (дословно, ничего больше)

> Cozy clean white home kitchen, warm daylight coming from the left. Same black air fryer with an open square basket in every shot. Realistic home cooking photo, DSLR 50mm look, shallow depth of field. No CGI, no illustration, no 3D render. No text, no watermark, no logo. Vertical 9:16, 720×1280.

High 3/4 top-down camera angle looking down into the open air fryer basket, matching the framing used for the real product photography (compatible with product_45deg), with the basket occupying the upper/middle area of the frame. The basket interior shows a clean, empty central placement area where the square silicone liner will be inserted later. In the central placement area, include a loose cluster of exactly 3 roasted golden chicken thighs with potato wedges, positioned where the liner interior will be after compositing. Do not draw a completed silicone liner. Do not draw redesigned or fake handles. Do not draw any duplicate tray or basket insert. Do not draw a black insert or black liner inside the basket. Only very soft contact shadows/cues are allowed in the empty placement area. Around and below the placement area, the black air fryer basket is visibly clean and shiny. No hands, no arms, no fingers, no person anywhere in this frame.

The final silicone form is inserted after generation from real-product-v1. Do not invent or redesign the product. Leave the product placement area clean.

Negative prompt (avoid): a completed or fully rendered silicone liner, redesigned or fake handles, loop handles, vertical oval holes, any duplicate tray or basket insert, a black insert or black liner inside the basket, hands, arms, fingers, a person or any part of a person visible in frame, frontal straight-on camera angle, dirty basket, text, watermark, logo.

**Ничего из pipeline_product_lock_instruction (геометрия ручек, материал,
силуэт) в этот текст НЕ входит** — модель не может достоверно нарисовать
real-product-v1 и не должна пытаться; PLACEMENT_NOTE внутри model_prompt
выше — единственное, что модель знает о товаре, и это негативная
инструкция ("оставь место чистым"), не просьба нарисовать.

## pipeline_product_lock_instruction — НЕ отправляется модели

Используется ТОЛЬКО compositor'ом/QA после генерации:

> PIPELINE ONLY — NOT sent to the image model as a drawing instruction; used by the compositor/QA instead. The silicone form is not generated from imagination. The final product layer must be inserted from real-product-v1 and remain pixel-faithful: exact flat corner handle tabs, short horizontal slots, matte dark grey silicone, ribbed bottom, proportions, silhouette. Вставляется через APPROVED_TRANSFORM_B (deterministic compositing) или, при необходимости, минимальный rigid per-plate transform в тех же пределах (uniform scale + малый rotation + translation, без warp) — никогда не из AI-редактирования. C3: сцена больше не показывает руки/захват ручек — C1 и C2 (см. их отчёты и scene-05-hands-experiment-retrospective.md) показали, что сгенерированные руки не выравниваются надёжно с real-product-v1 после deterministic overlay; front_hand extraction для этой сцены больше не нужен (front_hand_extraction: not_needed), т.к. рук в кадре нет вообще. Food cluster извлекается из AI plate ТОЛЬКО внутри product_interior_food_mask (см. scene-05-product-only-apply-dry-run.json:food_composite_strategy) и композитится внутрь товара отдельным шагом — не в этом model_prompt. См. `scene-05-product-only-plan.json` для полного плана и QA reject conditions.

## C3: что убрано по сравнению с C1/C2

- **hands_interact_with_flat_tabs**, **hands_positioned_near_real_handle_tabs**,
  **candidate_rejected_if_product_overlay_breaks_hands** — не применяются к
  этому сценарию (в кадре нет рук вообще);
- **front_hand_extraction**: `not_needed` (было `not_implemented` для C1/C2 —
  теперь вопрос снят, а не отложен);
- **hands_grip_qa**: `not_applicable`.

## STEP 5 — QA_GATES_C3_NO_HANDS

```json
[
  {
    "id": "c3-1",
    "name": "no_hands_visible",
    "check": "нет рук в кадре — сцена больше не показывает захват ручек"
  },
  {
    "id": "c3-2",
    "name": "no_person_visible",
    "check": "нет человека/частей тела в кадре — чистый product result shot"
  },
  {
    "id": "c3-3",
    "name": "no_duplicate_ai_product_visible",
    "check": "AI не нарисовал собственную силиконовую форму/вставку в placement area — если нарисовал, candidate reject даже после наложения real-product-v1"
  },
  {
    "id": "c3-4",
    "name": "no_black_insert_or_black_liner",
    "check": "AI не нарисовал чёрный insert/liner/container внутри корзины"
  },
  {
    "id": "c3-5",
    "name": "no_fake_handles_visible",
    "check": "AI не нарисовал собственные (redesigned/fake) ручки — видны только реальные ручки real-product-v1 после compositing"
  },
  {
    "id": "c3-6",
    "name": "basket_perspective_compatible_with_product_45deg",
    "check": "ракурс корзины совместим с product_45deg (high 3/4 top-down, корзина в верхней/средней части кадра)"
  },
  {
    "id": "c3-7",
    "name": "product_inserted_from_real_product_v1",
    "check": "real-product-v1 вставлен через APPROVED_TRANSFORM_B (или rigid per-plate transform в тех же пределах), не пропущен"
  },
  {
    "id": "c3-8",
    "name": "product_lock_passed",
    "check": "product_lock_validator.validate_composite: silhouette, handle_geometry, aspect_ratio, pixel_similarity, no_local_warp"
  },
  {
    "id": "c3-9",
    "name": "food_extracted_only_inside_interior_mask",
    "check": "food cluster извлечён из AI plate ТОЛЬКО внутри product_interior_food_mask"
  },
  {
    "id": "c3-10",
    "name": "food_count_exact",
    "check": "визуально ровно 3 куриных бедра + картофельные дольки"
  },
  {
    "id": "c3-11",
    "name": "basket_clean_around_product",
    "check": "корзина аэрогриля чистая вокруг/под вставленным real-product-v1"
  },
  {
    "id": "c3-12",
    "name": "no_text_or_watermark",
    "check": "нет текста/watermark/логотипа в кадре"
  },
  {
    "id": "c3-13",
    "name": "manual_review_required",
    "check": "manual_review_required: true — accepted никогда не проставляется автоматически"
  }
]
```

## food_composite_strategy — тоже НЕ отправляется модели

`food_extraction: implemented`. Метод:
extract_food_cluster(): AI plate pixels restricted to product_interior_food_mask (deterministic geometry from real-product-v1 + APPROVED_TRANSFORM_B, NOT AI-guessed) -- silicone/handles/walls/background NEVER taken from AI

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
| prompt_sha256 | `9842d38e3aae2777460ca9789e7acb5cad79aae941e88e3376c0043b7c464f04` |
| per_plate_transform_allowed | `true` |
| allowed_transform_type | `rigid_only` |
| front_hand_extraction | `not_needed` |
| hands_grip_qa | `not_applicable` |

## Что явно ЗАПРЕЩЕНО просить у модели

- рисовать законченную силиконовую форму;
- рисовать любые (redesigned/fake) ручки;
- рисовать дублирующий лоток/вставку в корзину;
- рисовать чёрный insert/liner внутри корзины;
- рисовать руки/человека в этом кадре (C3, новое: сцена теперь без рук).

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

## Composite strategy (STEP 4) — без hands-слоя

1. AI plate background / air fryer basket / food placement (без рук/человека);
2. real-product-v1 вставляется через APPROVED_TRANSFORM_B, или, при
   необходимости, минимальный rigid per-plate transform в тех же пределах
   (uniform scale + малый rotation + translation, без warp);
3. food cluster извлекается из AI plate ТОЛЬКО внутри трансформированного
   product_interior_food_mask;
4. product front occluder / rim / handle pixels из real-product-v1
   перерисовываются поверх еды;
5. QA (см. QA_GATES_C3_NO_HANDS выше).

Нет hands-слоя. Нет front-hand extraction. Нет handle-grip alignment.

## image_generation_timeout_seconds (после client_read_timeout на первой реальной попытке)

Первая реальная попытка `--apply` для этой сцены упала с `TimeoutError` --
запрос был отправлен, но ответ не пришёл за 300s (старый таймаут). Это не
retry-достойная ошибка приложения, а слишком короткий таймаут для реальной
латентности image generation. Исправлено в
`api/media_pipeline/openai_images_client.py`:

| поле | значение |
|---|---|
| image_generation_timeout_seconds (default) | `900` |
| env override | `IMAGE_GENERATION_TIMEOUT_SECONDS` (integer, 60-1800s; невалидное значение -> fallback на default + warning, никогда не падает) |
| auto_retry_on_timeout | `false` -- по-прежнему ровно один вызов, retries не добавлены |
| timeout_error_policy | `{"request_sent": true, "response_received": false, "candidate_status": "no_candidate_timeout", "explicit_owner_authorization_required_for_new_attempt": true}` |

Если новый timeout всё равно недостаточен и `--apply` снова упадёт с
`client_read_timeout` -- runner возвращает структурированный отчёт
(`candidate_status: no_candidate_timeout`, НЕ `rejected` -- кандидата не
существует, чтобы его отклонять) вместо необработанного traceback, не
делает retry и не запускает composite/QA. Новая попытка `--apply` требует
отдельного явного разрешения владельца.

## Хуки A/B/C

Этот prompt — shared body, одинаков для всех трёх hooks этого видео (см.
`hooks_usage` в `video-scene-prompts-product-only.md`). Тексты hook A/B/C
не менялись. Между hooks меняется только opener перед scene-01, не этот
кадр.

## Перед реальным запуском

Реальный OpenAI вызов по этому prompt — через
`python -m api.media_pipeline.cli product-only-scene --campaign
coating-protect-2026-07 --scene scene-05 --apply` — требует
`OPENAI_API_KEY` в окружении, ограничен hard cap `$0.5`,
`max_calls=1`, `retries=0`, и отдельного явного подтверждения владельца.
Этот файл — только план. `openai_calls_executed: 0`, `higgsfield_calls_executed: 0`.
