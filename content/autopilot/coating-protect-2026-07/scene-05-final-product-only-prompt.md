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
`prompt_sha256: b2da7a7b09703a0639f6cbdd4ba22cc1edf7a0dad04976f32abf419a58da1fa7`.

**Mandatory image refs: НЕТ.** `reference_images: []` — background-first,
`mode=generate` (НЕ `edit`): AI получает только текстовый prompt, без
единого input-изображения. Единственный image lock — `real-product-v1`,
вставляется отдельным deterministic compositing шагом ПОСЛЕ генерации, не
входит в этот API-запрос вообще.

---

## Готовый prompt для будущего запуска (дословно, включая continuity block)

> Cozy clean white home kitchen, warm daylight coming from the left. Same
> black air fryer with an open square basket in every shot. Same woman's
> natural hands throughout — no rings, no bracelets, no watch, short
> unpolished nails. Same grey ribbed sweater sleeves visible at the wrists
> in every shot. Realistic home cooking photo, DSLR 50mm look, shallow
> depth of field. No CGI, no illustration, no 3D render. No text, no
> watermark, no logo. Vertical 9:16, 720×1280.
>
> The woman lifts the square silicone liner out of the open air fryer basket by its two flat corner handle tabs, thumbs resting on top of each handle, the handles' short horizontal slots partially visible through the grip; inside the liner exactly 3 roasted golden chicken thighs and potato wedges, light steam rising; below, the inside of the black air fryer basket is visibly clean and shiny, untouched by grease.
>
> **The silicone form is not generated from imagination. The final
> product layer must be inserted from real-product-v1 and remain
> pixel-faithful: exact flat corner handle tabs, short horizontal slots,
> matte dark grey silicone, ribbed bottom, proportions, silhouette.**

## Product lock instruction

> The silicone form is not generated from imagination. The final product layer must be inserted from real-product-v1 and remain pixel-faithful: exact flat corner handle tabs, short horizontal slots, matte dark grey silicone, ribbed bottom, proportions, silhouette. Вставляется через APPROVED_TRANSFORM_B (deterministic compositing), никогда не из AI-редактирования. См. `scene-05-product-only-plan.json` для полного плана и QA reject conditions.

## Negative prompt

> redesigned handles, loop handles, vertical oval holes, wrong colour, warped silicone, extra handles, missing slots, hands holding the rim instead of the tabs, dirty basket in this clean-basket scene, not exactly 3 chicken thighs, excessive steam covering the product, text, watermark.

---

## Request contract (совпадает с scene-05-product-only-apply-dry-run.json)

| поле | значение |
|---|---|
| model | `gpt-image-2` |
| endpoint | `POST /images/generations` |
| mode | `generate` (background-first — НЕ `edit`, нет reference images/масок) |
| size | `720x1280` |
| n | `1` |
| output_format | `png` |
| retries | `0` |
| max_calls | `1` |
| hard_cap_usd | `0.5` |
| prompt_sha256 | `b2da7a7b09703a0639f6cbdd4ba22cc1edf7a0dad04976f32abf419a58da1fa7` |

## Что описывает этот prompt (текстом, НЕ image reference)

- уютная белая кухня (continuity block);
- тот же чёрный аэрогриль с открытой квадратной корзиной (continuity block);
- женские руки, серый ребристый свитер (continuity block);
- руки поднимают силиконовую форму за две плоские боковые ручки-язычки;
- большие пальцы сверху;
- короткие горизонтальные прорези ручек частично видны сквозь хват;
- внутри формы ровно 3 куриных бедра и картофельные дольки;
- корзина аэрогриля чистая и блестящая под формой;
- реалистичное фото домашней готовки, 9:16, 720×1280;
- без CGI/иллюстрации/3D-рендера, без текста/watermark.

## Что НЕ входит в этот prompt

- никаких mandatory image refs для рук/человека/кухни/аэрогриля
  (`reference_images: []`, `mode=generate`);
- никакого творческого описания формы товара — товар не в этом
  API-запросе вообще, он вставляется отдельным compositing-шагом;
- никакой ссылки на `person-b-exhausted-01`, `real-grip-motion-01`,
  `v2-hand-hold-01`, `v2-form-in-basket-01`, `food-wings-01` — все пять
  запрещены `campaign_visual_policy.json` и проверяются
  `api.media_pipeline.product_only_policy.assert_no_forbidden_appearance_refs`.

## Approach: Background-first (не Product-guide)

AI генерирует ВЕСЬ кадр свободно (кухня/руки/рукава/еда/фон) без единой
reference-картинки — значит, ему физически нечего "нарушать" (в отличие
от CALL 1 HANDS, где именно нарушение edit-маски и было корнем всех
четырёх отклонённых итераций). real-product-v1 вставляется ПОСЛЕ,
deterministic compositing'ом, в фиксированную экранную позицию
(`APPROVED_TRANSFORM_B`) — независимо от того, что нарисовал AI в этом
месте кадра. Если AI всё равно нарисовал похожую форму где-то в кадре —
QA gate 5 (`no_ai_redesigned_product_accepted`) отклоняет кандидата.
Подробное обоснование — в `scene-05-product-only-apply-dry-run.json` и
`api/media_pipeline/product_only_scene_runner.py` (docstring).

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
