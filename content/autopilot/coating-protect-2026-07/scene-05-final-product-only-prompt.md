# Scene-05 — final product-only prompt (ready for future run, NOT executed)

Собран из `content/autopilot/coating-protect-2026-07/video-continuity-block.md`
+ `video-scene-prompts-product-only.md` (scene-05) через
`api.media_pipeline.product_only_scene_runner.build_request_contract(campaign_dir,
"scene-05")` — тот же код, что строит реальный `ImageRequest` для будущего
`--apply` вызова и `scene-05-product-only-apply-dry-run.json`, так что этот
prompt и тот dry-run гарантированно согласованы (один источник истины,
включая SHA256 промпта).

**Статус: план. Ни один API (OpenAI/Higgsfield) НЕ вызывался для
получения этого текста.** `openai_calls: 0`, `higgsfield_calls: 0`.
`prompt_sha256: 4067602b93fa23f883cea27f0df7cea4b663336da747a19d8831a8e31ada6f75`.

**Approach: `product_placement_plate`** (PRODUCT PLACEMENT PLATE, не "нарисуй
финальный товар" — см. раздел ниже). Предыдущая версия этого файла просила
AI нарисовать законченную силиконовую форму, хотя dry-run говорил, что
товар вставляется ПОСЛЕ генерации — это создавало риск ghost/double
product. Исправлено: model_prompt теперь просит только "plate" (кухня,
руки в ожидаемой позиции, пустое место под товар), явно запрещая рисовать
готовую форму.

**Mandatory image refs: НЕТ.** `reference_images: []` — `mode=generate`
(НЕ `edit`): AI получает только текстовый prompt, без единого
input-изображения.

---

## model_prompt — ТОЛЬКО это уходит в API (дословно)

> Cozy clean white home kitchen, warm daylight coming from the left. Same
> black air fryer with an open square basket in every shot. Same woman's
> natural hands throughout — no rings, no bracelets, no watch, short
> unpolished nails. Same grey ribbed sweater sleeves visible at the wrists
> in every shot. Realistic home cooking photo, DSLR 50mm look, shallow
> depth of field. No CGI, no illustration, no 3D render. No text, no
> watermark, no logo. Vertical 9:16, 720×1280.
>
> The woman's hands, in grey ribbed sweater sleeves, are positioned as if lifting an object out of the open air fryer basket: hands placed at the expected left and right side-handle positions, thumbs angled toward where the flat handle tabs will be, leaving a clean, empty central placement area in the basket for a square silicone liner to be inserted later. Do not draw a completed silicone liner. Do not draw redesigned or fake handles. Do not draw any duplicate tray or basket insert. Only very soft contact shadows/cues are allowed in the empty placement area. Below, the black air fryer basket is visibly clean and shiny. Food may be represented only as a rough, loose internal food area if needed — final food/product alignment is checked separately by QA, not guaranteed by this generation step.
>
> The final silicone form is inserted after generation from real-product-v1. Do not invent or redesign the product. Leave the product placement area clean.
>
> Negative prompt (avoid): a completed or fully rendered silicone liner, redesigned or fake handles, loop handles, vertical oval holes, any duplicate tray or basket insert, hands gripping the basket rim instead of the expected handle positions, dirty basket, text, watermark, logo.

**Ничего из product_lock_instruction (геометрия ручек, материал, силуэт)
в этот текст НЕ входит** — модель не может достоверно нарисовать
real-product-v1 и не должна пытаться; PLACEMENT_NOTE выше — единственное,
что модель знает о товаре, и это негативная инструкция ("оставь место
чистым"), не просьба нарисовать.

## pipeline_product_lock_instruction — НЕ отправляется модели

Используется ТОЛЬКО compositor'ом/QA после генерации:

> PIPELINE ONLY — NOT sent to the image model as a drawing instruction; used by the compositor/QA instead. The silicone form is not generated from imagination. The final product layer must be inserted from real-product-v1 and remain pixel-faithful: exact flat corner handle tabs, short horizontal slots, matte dark grey silicone, ribbed bottom, proportions, silhouette. Вставляется через APPROVED_TRANSFORM_B (deterministic compositing), никогда не из AI-редактирования. См. `scene-05-product-only-plan.json` для полного плана и QA reject conditions.

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
| prompt_sha256 | `4067602b93fa23f883cea27f0df7cea4b663336da747a19d8831a8e31ada6f75` |

## Что описывает model_prompt (текстом, НЕ image reference)

- уютная белая кухня (continuity block);
- тот же чёрный аэрогриль с открытой квадратной корзиной, чистая и
  блестящая корзина (continuity block + scene action);
- женские руки, серый ребристый свитер, расположены как перед подъёмом
  предмета — у ожидаемых позиций боковых ручек, большие пальцы развёрнуты
  туда, где будут flat handle tabs;
- пустое, чистое место в центре корзины под будущую вставку формы;
- еда (если вообще нарисована) — только грубый, необязательный намёк на
  область еды, финальное совпадение еды/товара проверяется отдельно QA;
- реалистичное фото домашней готовки, 9:16, 720×1280;
- без CGI/иллюстрации/3D-рендера, без текста/watermark.

## Что явно ЗАПРЕЩЕНО просить у модели

- рисовать законченную силиконовую форму;
- рисовать любые (redesigned/fake) ручки;
- рисовать дублирующий лоток/вставку в корзину.

## Что НЕ входит в этот prompt

- никаких mandatory image refs для рук/человека/кухни/аэрогриля
  (`reference_images: []`, `mode=generate`);
- никакого творческого описания формы товара — товар не в этом
  API-запросе вообще, он вставляется отдельным compositing-шагом;
- никакой ссылки на `person-b-exhausted-01`, `real-grip-motion-01`,
  `v2-hand-hold-01`, `v2-form-in-basket-01`, `food-wings-01` — все пять
  запрещены `campaign_visual_policy.json` и проверяются
  `api.media_pipeline.product_only_policy.assert_no_forbidden_appearance_refs`.

## Approach: Product Placement Plate (не Background-first-с-товаром, не Product-guide)

AI генерирует ТОЛЬКО plate — кухню, руки в ожидаемой позиции, чистое место
под товар — и явно инструктируется НЕ рисовать законченный товар/ручки/
лоток. real-product-v1 вставляется ПОСЛЕ, deterministic compositing'ом, в
фиксированную экранную позицию (`APPROVED_TRANSFORM_B`) — независимо от
того, что нарисовал AI. Если AI всё равно нарисовал похожую форму/лоток/
ручки несмотря на инструкцию — QA gates 11-13
(`no_duplicate_ai_product_visible`, `no_ai_tray_under_real_product`,
`no_fake_handles_visible`) отклоняют кандидата. Product-guide (передать
real-product-v1 как reference в mode=edit) по-прежнему отклонён — см.
`scene-05-product-only-apply-dry-run.json` и
`api/media_pipeline/product_only_scene_runner.py` (docstring).

## Composite mechanics (после будущей генерации, ещё НЕ выполнено)

1. raw AI plate (kitchen/hands/basket/placement area) сохраняется как есть
2. real-product-v1 вставляется через APPROVED_TRANSFORM_B (deterministic compositing, layer_compositor.compose)
3. front_hand extraction (палец/рукав поверх handle tabs) НЕ реализована в этом runner'е -- см. front_hand_extraction ниже
4. если руки закрыты продуктом целиком или не взаимодействуют с handle tabs -- candidate reject
5. если AI нарисовал собственную форму/лоток/вставку несмотря на PLACEMENT_NOTE -- candidate reject (no_duplicate_ai_product_visible)

**front_hand_extraction: `not_implemented`.** Честно: этот
runner НЕ реализует извлечение пальцев/рукава поверх handle tabs (как
пыталась scene-05-hands-experiment-retrospective.md V3). `manual_review_required:
true` всегда, и есть риск, что руки на AI-plate будут частично перекрыты
слоем товара после вставки — это не скрывается, а помечается в каждом
отчёте runner'а.

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
