# Scene-05 — final product-only prompt (ready for future run, NOT executed)

Собран из `content/autopilot/coating-protect-2026-07/video-continuity-block.md`
(ТОЛЬКО clean blockquote-текст, распарсенный
`product_only_policy.parse_clean_continuity_prompt()` — НЕ весь .md файл)
+ `video-scene-prompts-product-only.md` (scene-05), через
`api.media_pipeline.product_only_scene_runner.run_product_only_scene(campaign_dir,
"scene-05", apply=False)` — тот же код и тот же вызов, что построит реальный
`ImageRequest` для будущего `--apply`. Этот .md файл сгенерирован из
фактического dry-run отчёта, не напечатан вручную — text здесь и в
`scene-05-product-only-apply-dry-run.json` гарантированно идентичен
(включая SHA256 промпта).

**Статус: план. Ни один API (OpenAI/Higgsfield) НЕ вызывался для
получения этого текста.** `openai_calls: 0`, `higgsfield_calls: 0`.
`prompt_sha256: 057c4df255e0174397b7349905cb9c45da3f7f96abae31ee6b2c040d541f5695`.

**Approach: `product_placement_plate`** (PRODUCT PLACEMENT PLATE). AI рисует
только "plate" (кухня/руки/корзина/пустое место под товар + rough food
cluster), никогда финальный товар.

**model_prompt_clean: true.** Предыдущая версия этого файла по ошибке
включала ВЕСЬ текст `video-continuity-block.md` целиком — русские
заголовки, "## Правила применения", объяснения pipeline, file paths.
Это никогда не должно было уходить в image API. Исправлено:
`build_model_prompt()` теперь берёт `plan["clean_continuity_prompt"]`
(только английский blockquote), не `plan["continuity_block_text"]` (весь
файл).

**Mandatory image refs: НЕТ.** `reference_images: []` — `mode=generate`
(НЕ `edit`): AI получает только текстовый prompt ниже, без единого
input-изображения.

---

## model_prompt — ТОЛЬКО это уходит в API (дословно, ничего больше)

> Cozy clean white home kitchen, warm daylight coming from the left. Same black air fryer with an open square basket in every shot. Same woman's natural hands throughout — no rings, no bracelets, no watch, short unpolished nails. Same grey ribbed sweater sleeves visible at the wrists in every shot. Realistic home cooking photo, DSLR 50mm look, shallow depth of field. No CGI, no illustration, no 3D render. No text, no watermark, no logo. Vertical 9:16, 720×1280.

The woman's hands, in grey ribbed sweater sleeves, are positioned as if lifting an object out of the open air fryer basket: hands placed at the expected left and right side-handle positions, thumbs angled toward where the flat handle tabs will be, leaving a clean, empty central placement area in the basket for a square silicone liner to be inserted later. In the central placement area, include a loose cluster of exactly 3 roasted golden chicken thighs with potato wedges, positioned where the liner interior will be after compositing. Do not draw a completed silicone liner. Do not draw redesigned or fake handles. Do not draw any duplicate tray or basket insert. Only very soft contact shadows/cues are allowed in the empty placement area. Below, the black air fryer basket is visibly clean and shiny.

The final silicone form is inserted after generation from real-product-v1. Do not invent or redesign the product. Leave the product placement area clean.

Negative prompt (avoid): a completed or fully rendered silicone liner, redesigned or fake handles, loop handles, vertical oval holes, any duplicate tray or basket insert, hands gripping the basket rim instead of the expected handle positions, extra fingers, missing fingers, jewelry, dirty basket, text, watermark, logo.

**Ничего из pipeline_product_lock_instruction (геометрия ручек, материал,
силуэт) в этот текст НЕ входит** — модель не может достоверно нарисовать
real-product-v1 и не должна пытаться; PLACEMENT_NOTE внутри model_prompt
выше — единственное, что модель знает о товаре, и это негативная
инструкция ("оставь место чистым"), не просьба нарисовать.

## pipeline_product_lock_instruction — НЕ отправляется модели

Используется ТОЛЬКО compositor'ом/QA после генерации:

> PIPELINE ONLY — NOT sent to the image model as a drawing instruction; used by the compositor/QA instead. The silicone form is not generated from imagination. The final product layer must be inserted from real-product-v1 and remain pixel-faithful: exact flat corner handle tabs, short horizontal slots, matte dark grey silicone, ribbed bottom, proportions, silhouette. Вставляется через APPROVED_TRANSFORM_B (deterministic compositing), никогда не из AI-редактирования. Food cluster извлекается из AI plate ТОЛЬКО внутри product_interior_food_mask (см. scene-05-product-only-apply-dry-run.json:food_composite_strategy) и композитится внутрь товара отдельным шагом — не в этом model_prompt. См. `scene-05-product-only-plan.json` для полного плана и QA reject conditions.

## food_composite_strategy — тоже НЕ отправляется модели

`food_extraction: implemented`. Метод:
extract_food_cluster(): AI plate pixels restricted to product_interior_food_mask (deterministic geometry from real-product-v1 + APPROVED_TRANSFORM_B, NOT AI-guessed) -- silicone/handles/walls/background NEVER taken from AI

`product_interior_food_mask`: bbox `[200, 79, 539, 329]`
на канвасе `[720, 1280]`
(источник: `api/media_pipeline/compositor/scene05_layer_masks.py:product_interior_food_mask (deterministic, from real-product-v1 geometry via APPROVED_TRANSFORM_B, NOT from the AI plate)`).

**final_composite_order:**

1. AI plate background/hands/basket (raw; everything outside the interior mask is discarded for food purposes)
2. real-product-v1 base/exterior inserted via APPROVED_TRANSFORM_B
3. extracted food cluster (AI plate pixels masked to product_interior_food_mask) composited inside the product
4. product front occluder / rim / handle pixels from real-product-v1 redrawn on top (covers food edges, same real pixels, no new product pixels)
5. QA: food_count_exact (exactly 3 chicken thighs) -- if AI did not draw exactly 3, candidate reject / manual_review_required

Если AI не нарисовал ровно 3 бедра в placement area: candidate_status=manual_review_required / rejected -- QA gate food_count_exact catches this; the extraction mechanism itself does not count or validate food count (that's a vision QA step, not implemented here)

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
| prompt_sha256 | `057c4df255e0174397b7349905cb9c45da3f7f96abae31ee6b2c040d541f5695` |

## Что явно ЗАПРЕЩЕНО просить у модели

- рисовать законченную силиконовую форму;
- рисовать любые (redesigned/fake) ручки;
- рисовать дублирующий лоток/вставку в корзину.

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

## Approach: Product Placement Plate (не Background-first-с-товаром, не Product-guide)

AI генерирует ТОЛЬКО plate — кухню, руки в ожидаемой позиции, чистое место
под товар (плюс rough food cluster) — и явно инструктируется НЕ рисовать
законченный товар/ручки/лоток. real-product-v1 вставляется ПОСЛЕ,
deterministic compositing'ом, в фиксированную экранную позицию
(`APPROVED_TRANSFORM_B`) — независимо от того, что нарисовал AI. Если AI
всё равно нарисовал похожую форму/лоток/ручки несмотря на инструкцию — QA
gates 11-13 (`no_duplicate_ai_product_visible`, `no_ai_tray_under_real_product`,
`no_fake_handles_visible`) отклоняют кандидата. Product-guide (передать
real-product-v1 как reference в mode=edit) по-прежнему отклонён.

## Composite mechanics (после будущей генерации, ещё НЕ выполнено)

1. raw AI plate (kitchen/hands/basket/placement area/rough food cluster) сохраняется как есть
2. real-product-v1 base/exterior вставляется через APPROVED_TRANSFORM_B (deterministic compositing, layer_compositor.compose)
3. food cluster извлекается из AI plate СТРОГО внутри product_interior_food_mask (extract_food_cluster(), детерминированная геометрия из real-product-v1, не из AI) и композитится внутрь товара
4. product front occluder / rim / handle pixels из real-product-v1 перерисовываются поверх еды (закрывают края, без новых пикселей товара)
5. front_hand extraction (палец/рукав поверх handle tabs) НЕ реализована в этом runner'е -- см. front_hand_extraction ниже
6. если руки закрыты продуктом целиком или не взаимодействуют с handle tabs -- candidate reject
7. если AI нарисовал собственную форму/лоток/вставку несмотря на PLACEMENT_NOTE -- candidate reject (no_duplicate_ai_product_visible)
8. QA: food_count_exact -- если AI не нарисовал ровно 3 бедра, candidate reject/manual_review_required (extraction сам не считает еду, это отдельная visual QA проверка)

**front_hand_extraction: `not_implemented`.** Честно: этот
runner НЕ реализует извлечение пальцев/рукава поверх handle tabs (как
пыталась scene-05-hands-experiment-retrospective.md V3). `manual_review_required:
true` всегда, и есть риск, что руки на AI-plate будут частично перекрыты
слоем товара после вставки — это не скрывается, а помечается в каждом
отчёте runner'а.

**food_extraction: `implemented`.** extract_food_cluster()
реализована и покрыта тестами на синтетическом plate (реального AI-plate
ещё нет — ни одного --apply вызова не было). Если этот статус когда-либо
станет `not_implemented`, --apply автоматически блокируется
(`FOOD_EXTRACTION_NOT_IMPLEMENTED`), т.к. QA gate `food_count_exact` было
бы невозможно выполнить.

## Хуки A/B/C

Этот prompt — shared body, одинаков для всех трёх hooks этого видео (см.
`hooks_usage` в `video-scene-prompts-product-only.md`). Между hooks
меняется только opener перед scene-01, не этот кадр.

## Перед реальным запуском

Реальный OpenAI вызов по этому prompt — через
`python -m api.media_pipeline.cli product-only-scene --campaign
coating-protect-2026-07 --scene scene-05 --apply` — требует
`OPENAI_API_KEY` в окружении, ограничен hard cap `$0.5`,
`max_calls=1`, `retries=0`, и
отдельного явного подтверждения владельца — так же, как это было для
CALL 1 HANDS pilot (см. `scene-05-hands-experiment-retrospective.md`).
Этот файл — только план.
