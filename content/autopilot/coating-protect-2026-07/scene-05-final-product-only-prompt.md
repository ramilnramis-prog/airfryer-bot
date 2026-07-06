# Scene-05 — final product-only prompt (ready for future run, NOT executed)

Собран из `content/autopilot/coating-protect-2026-07/video-continuity-block.md`
+ `video-scene-prompts-product-only.md` (scene-05) через
`api.media_pipeline.product_only_policy.plan_scene_request(campaign_dir,
"scene-05")` — тот же код, что генерирует
`scene-05-product-only-generation-dry-run.json`, так что этот prompt и тот
dry-run гарантированно согласованы (один источник истины, не два
независимо написанных текста).

**Статус: план. Ни один API (OpenAI/Higgsfield) НЕ вызывался для
получения этого текста.** `openai_calls: 0`, `higgsfield_calls: 0`.

**Mandatory image refs: НЕТ.** Для рук/персонажа/кухни/аэрогриля — ни
одного обязательного image reference (см. `appearance_image_refs` /
`hands_image_refs` / `kitchen_image_refs` / `airfryer_image_refs` — все
пустые в `scene-05-product-only-generation-dry-run.json`). Единственный
image lock — `real-product-v1`, вставляется deterministic compositing'ом,
не текстовым prompt'ом.

---

## Готовый prompt для будущего запуска

> Cozy clean white home kitchen, warm daylight coming from the left. Same
> black air fryer with an open square basket in every shot. Same woman's
> natural hands throughout — no rings, no bracelets, no watch, short
> unpolished nails. Same grey ribbed sweater sleeves visible at the wrists
> in every shot. Realistic home cooking photo, DSLR 50mm look, shallow
> depth of field. No CGI, no illustration, no 3D render. No text, no
> watermark, no logo. Vertical 9:16, 720×1280.
>
> The woman lifts the square silicone liner out of the open air fryer
> basket by its two flat corner handle tabs, thumbs resting on top of each
> handle; inside the liner exactly 3 roasted golden chicken thighs and
> potato wedges, light steam rising; below, the inside of the black basket
> is visibly clean and dry, untouched by grease.
>
> **The silicone form is not generated from imagination. It is inserted
> from real-product-v1 and must remain pixel-faithful.**

## Product lock instruction

> product/handle pixels — исключительно из real-product-v1
> (APPROVED_TRANSFORM_B), никогда не из AI-редактирования. Хват строго за
> flat corner handle tabs (не за борт формы/корзины), большие пальцы
> сверху, короткая горизонтальная прорезь ручки частично видна сквозь
> хват, пальцы не проходят сквозь силикон. См.
> `scene-05-product-only-plan.json` для полного плана и QA reject
> conditions.

## Negative prompt

> not exactly 3 chicken thighs is a hard fail, grip on basket rim instead
> of handle tab is a hard fail, handle geometry other than real-product-v1
> (tall loop handle, vertical oval cut-out) is a hard fail, dirty basket
> under the liner is a hard fail, excessive steam covering the product, no
> text, no watermark.

---

## Что описывает этот prompt (текстом, НЕ image reference)

- женщина в сером ребристом свитере;
- уютная белая кухня;
- чёрный аэрогриль с открытой квадратной корзиной;
- руки достают форму строго за плоские боковые ручки;
- большие пальцы сверху;
- прорези ручек частично видны;
- внутри формы 3 куриных бёдрышка и картофель;
- корзина аэрогриля чистая;
- реалистичное фото, 9:16.

## Что НЕ входит в этот prompt

- никаких mandatory image refs для рук/человека/кухни/аэрогриля;
- никакого творческого описания формы товара (форма — не текст, а
  real-product-v1 compositing);
- никакой ссылки на `person-b-exhausted-01`, `real-grip-motion-01`,
  `v2-hand-hold-01`, `v2-form-in-basket-01`, `food-wings-01` — все пять
  запрещены `campaign_visual_policy.json` и явно проверяются
  `api.media_pipeline.product_only_policy.assert_no_forbidden_appearance_refs`.

## Хуки A/B/C

Этот prompt — shared body, одинаков для всех трёх hooks этого видео (см.
`hooks_usage` в `video-scene-prompts-product-only.md`). Между hooks
меняется только opener перед scene-01, не этот кадр.

## Перед реальным запуском

Реальный OpenAI/Higgsfield вызов по этому prompt требует отдельного явного
подтверждения владельца с hard cap — так же, как это было для CALL 1
HANDS pilot (см. `scene-05-hands-experiment-retrospective.md`). Этот файл
— только план.
