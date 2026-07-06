# Video scene prompts — product-only policy (coating-protect-ad)

Стратегия: `campaign_visual_policy.json` (product-only-v1). Единственный
image lock — `real-product-v1`. Всё остальное (руки/персонаж/кухня/
аэрогриль/одежда/свет) — текстом, одинаково для всех 7 сцен и всех 3
hooks, см. `video-continuity-block.md`. Между сценами меняется только
действие/композиция/food state.

Эти prompts НЕ отправлялись ни в один API — это план, dry-run only (см.
`product-only-generation-dry-run.json`, `openai_calls: 0`).

Для каждой сцены, где товар в кадре (`scene-03` … `scene-07`), в prompt
подставляется дословно текст из `video-continuity-block.md` ПЛЮС
`product_lock_instruction` ПЛЮС сцено-специфичный `image_prompt` ниже.

---

## scene-01

- **scene_goal**: проблема — грязная/зажаренная корзина после готовки.
- **image_prompt**: At the kitchen sink, the woman's hands scrub the removable black air fryer basket with a sponge, soap foam, greasy smears visible inside the basket, a tired slow scrubbing motion. The silicone liner is NOT in this shot.
- **product_lock_instruction**: не применяется (товара в кадре нет).
- **negative_prompt**: no silicone liner/form in frame, no text, no watermark, no logo, no CGI look, no illustration, no 3D render.
- **continuity_block_ref**: video-continuity-block.md
- **hooks_usage**: shared body — hook opener подставляется первыми 1-3 секундами перед этой сценой.

## scene-02

- **scene_goal**: боль — макро губки по антипригарному покрытию.
- **image_prompt**: Extreme close-up inside the black air fryer basket: the scouring side of a sponge drags slowly across the dark non-stick coated bottom, smearing a thin film of grease, tiny soap bubbles.
- **product_lock_instruction**: не применяется (товара в кадре нет).
- **negative_prompt**: no silicone liner/form, no deep gouges/scratches (только лёгкий износ, не запугивание), no text, no watermark.
- **continuity_block_ref**: video-continuity-block.md
- **hooks_usage**: shared body.

## scene-03

- **scene_goal**: решение — рука опускает форму в чашу.
- **image_prompt**: The woman's hand lowers the empty silicone liner into the clean black air fryer basket on the countertop; the liner settles in neatly, ribbed bottom visible, both handles visible. No food yet.
- **product_lock_instruction**: product/handle pixels вставляются из real-product-v1 через APPROVED_TRANSFORM_B (deterministic compositing), НЕ генерируются AI. Плоские угловые ручки-язычки, короткая горизонтальная прорезь — обязательны, форма/ручки никогда не перерисовываются.
- **negative_prompt**: no tall vertical loop handle, no vertical oval cut-out (legacy AI shape, obsolete), no food yet, no glossy finish, no colour other than matte dark grey, no text, no watermark.
- **continuity_block_ref**: video-continuity-block.md
- **hooks_usage**: shared body.

## scene-04

- **scene_goal**: готовка — окно работающего аэрогриля с блюдом внутри формы.
- **image_prompt**: Front view of the closed air fryer working on the countertop; through the front viewing window the square silicone liner is visible holding exactly 3 golden chicken thighs and potato wedges, warm cooking glow inside, subtle heat shimmer. No steam outside.
- **product_lock_instruction**: форма внутри окна — real-product-v1 через product-lock compositing, геометрия ручек (если видны) не редактируется AI.
- **negative_prompt**: not exactly 3 chicken thighs is a hard fail, no food outside the liner, no text, no watermark, no CGI look.
- **continuity_block_ref**: video-continuity-block.md
- **hooks_usage**: shared body.

## scene-05

- **scene_goal**: "денежный" кадр — руки достают форму за плоские ручки, блюдо внутри, корзина чистая.
- **image_prompt**: The woman lifts the square silicone liner out of the open air fryer basket by its two flat corner handle tabs, thumbs resting on top of each handle; inside the liner exactly 3 roasted golden chicken thighs and potato wedges, light steam rising; below, the inside of the black basket is visibly clean and dry, untouched by grease.
- **product_lock_instruction**: product/handle pixels — исключительно из real-product-v1 (APPROVED_TRANSFORM_B), никогда не из AI-редактирования. Хват строго за flat corner handle tabs (не за борт формы/корзины), большие пальцы сверху, короткая горизонтальная прорезь ручки частично видна сквозь хват, пальцы не проходят сквозь силикон. См. `scene-05-product-only-plan.json` для полного плана и QA reject conditions.
- **negative_prompt**: not exactly 3 chicken thighs is a hard fail, grip on basket rim instead of handle tab is a hard fail, handle geometry other than real-product-v1 (tall loop handle, vertical oval cut-out) is a hard fail, dirty basket under the liner is a hard fail, excessive steam covering the product, no text, no watermark.
- **continuity_block_ref**: video-continuity-block.md
- **hooks_usage**: shared body — это ГЛАВНЫЙ кадр ролика ("денежный" кадр), одинаков для всех 3 hooks.

## scene-06

- **scene_goal**: контраст — пустая чистая чаша к камере.
- **image_prompt**: The woman's hands tilt the empty black air fryer basket toward the camera: the dark non-stick interior is perfectly clean, smooth and evenly matte, no grease, no scratches, softly reflecting the window light. No liner in this shot.
- **product_lock_instruction**: не применяется (товара в кадре нет).
- **negative_prompt**: no liner/form in frame, no grease or scratches, no text, no watermark.
- **continuity_block_ref**: video-continuity-block.md
- **hooks_usage**: shared body.

## scene-07

- **scene_goal**: CTA — beauty shot товара рядом с чистым аэрогрилем.
- **image_prompt**: Clean product composition on the countertop: the empty silicone liner in front, both handles and ribbed bottom ridges clearly visible; the air fryer slightly behind at camera-right, soft daylight. Styled like an e-commerce listing card.
- **product_lock_instruction**: форма и ручки — 100% real-product-v1 через product-lock compositing, ручки и рёбра дна должны быть чётко видны (это витринный кадр товара), не перерисовываются AI ни при каких обстоятельствах.
- **negative_prompt**: handles or bottom ribs not visible is a hard fail, handle geometry other than real-product-v1 is a hard fail, no food in frame, composition must leave room for a CTA overlay at the bottom, no text, no watermark, no logo.
- **continuity_block_ref**: video-continuity-block.md
- **hooks_usage**: shared body — последний кадр ролика, одинаков для всех 3 hooks; поверх на монтаже накладывается CTA-плашка.

---

## hook_openers (первые 1-3 секунды, варианты A/B/C для ЭТОЙ кампании)

Эти три варианта используются ТОЛЬКО как открывающая фраза/первый кадр
перед scene-01 этого видео. Основное тело ролика (scene-01…scene-07) и
`video-continuity-block.md` — общие для всех трёх. Старые утверждённые
hooks в `hooks.json` (video2) этим НЕ заменяются и не изменяются.

- **A**: «Аэрогрильщики, вы вообще знали про такую штуку?»
- **B**: «Если у тебя есть аэрогриль — это обязано быть у тебя.»
- **C**: «Недорогая вещь, которая помогает беречь аэрогриль за несколько тысяч.»

`hooks_usage` для каждой сцены выше = `shared body`: сама сцена не
меняется между A/B/C, меняется только opener перед scene-01.
