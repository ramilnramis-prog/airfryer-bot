# Scene-05: финальный prompt package (Set A утверждён, DRY-RUN, генерация НЕ запущена)

`visual_set_id: coating-protect-visual-set-01`, `selected_set: A`,
`owner_approved: true` (см. `campaign_visual_lock.json`).

Основа зафиксирована и не меняется: baseplate B (canvas 720×1280, scale
0.56, rotation -1.0°, translate [137.24, 20.48], perspective 0.0), реальный
DE'MIAND, реальная чистая корзина, real-product-v1 (product_45deg,
`api/media_pipeline/compositor/scene05_baseplate.py:APPROVED_TRANSFORM_B`).
Ничего из этого промптами не описывается и не перегенерируется — только
2 слоя ниже.

**Исключено из генерации scene-05** (решение владельца): `v2-form-in-basket-01`
(положение формы уже задано baseplate B; аэрогриль/товар на этом фото не
совпадают с активными канонами) и `food-wings-01` (крылья могут загрязнить
состав сцены — только scene-spec).

## Общие hard-requirements для рук (CALL 1)

- Appearance строго по `person-b-exhausted-01` (Set A, единственный
  primary_hands_asset_id): та же девушка, тот же тон кожи и общий вид рук,
  причёска с пучком, серый рубчатый кардиган (рукав виден у запястья),
  белая кухня с плиткой-кабанчиком, дневной свет слева.
- Поза/механика хвата — ТОЛЬКО из `real-grip-motion-01`
  (`influence_scope: hand_pose_only`): траектория подъёма, обе руки,
  большие пальцы сверху. Этот референс НЕ влияет на пол/кожу/одежду/
  украшения/внешний вид рук — только на движение.
- Без часов, колец, браслетов, без лака на ногтях.
- Ровно 5 пальцев на каждой видимой кисти.
- Хват — ТОЛЬКО за реальные плоские угловые ручки-язычки (handle bbox:
  left [190,44,275,100], right [549,166,595,259] на canvas 720×1280),
  большие пальцы сверху ручек — НЕ за верхний борт формы/корзины.
- Короткая горизонтальная прорезь ручки должна остаться различимой,
  не закрытой пальцами полностью.
- Руки не изменяют пиксели продукта: CALL 1 — masked image edit, пиксели
  ВНЕ edit-маски (форма, ручки, DE'MIAND, корзина, фон, кухня) защищены
  самим механизмом маскированного edit и не могут быть изменены моделью.
- Одинаковый набор across scene-01…scene-07 и hooks A/B/C этого ролика.

---

## CALL 1 — MASKED IMAGE EDIT of approved baseplate B (NOT a free isolated-layer generation)

**Изменение подхода (эта правка):** прежний prompt на "isolated RGBA hands
cutout" НЕ используется для реального запуска. CALL 1 — это **masked image
edit** уже утверждённого `baseplate-B.png`, а не отдельная генерация слоя.

### PRIMARY INPUT

Чистая (без watermark) пересборка baseplate B —
`api/media_pipeline/compositor/scene05_debug_preview.py:rebuild_layered_scene`
— пиксель-в-пиксель совпадает с утверждённым
`content/autopilot/coating-protect-2026-07/generated/scene-05-real-baseplate/baseplate-B.png`
(720×1280, sha256 `65be9fc5c869a26abed23b852f484ad81b0558c34d3a3774115c40a6b62ab7e6`,
зафиксирован в `scene-05-baseplate-selection.json`) ВНЕ полосы watermark
(`compare_to_approved_baseplate`, tolerance 6, max bad fraction 0.01).
**Сам файл `baseplate-B.png` содержит надпись "TEST PREVIEW" — как primary
input для реального edit-вызова используется НЕ он, а его чистая
пересборка без watermark** (иначе нарушается требование "no text, no
watermark").

**Неизменяемые параметры** (проверены компоновкой baseplate-B, менять запрещено):
scale `0.56`, rotation `-1.0°`, translate `[137.24, 20.48]`, perspective `0.0`
(`api/media_pipeline/compositor/scene05_baseplate.py:APPROVED_TRANSFORM_B`).

### Edit mask (разрешено менять ТОЛЬКО внутри этих 4 зон)

Вычислено детерминированно `api/media_pipeline/compositor/scene05_layer_masks.py:call1_edit_mask_zones`
(canvas 720×1280):

| zone | bbox (x0,y0,x1,y1) |
|---|---|
| left forearm + hand | `[80, 36, 266, 268]` |
| right forearm + hand | `[554, 152, 655, 380]` |
| left fingers over handle | `[190, 44, 275, 72]` |
| right fingers over handle | `[549, 166, 595, 212]` |

Правая forearm/hand-зона **обрезана** по нижней границе `product_full_bbox`
(y1: 538 → 380): исходная зона `back_hand_right_zone` спроектирована для
слоистой компоновки (PRODUCT_BASE рисуется поверх неё в более позднем
z-order) и в плоском edit заходила бы в открытую корзину — визуально
подтверждено сверкой с самим `baseplate-B.png`. Left-зона уже была в
безопасных пределах, не обрезалась.

**Всё вне этих 4 зон защищено** (edit API не меняет пиксели снаружи маски):
real-product-v1 (форма, ручки), DE'MIAND, корзина, фон, кухня.

**Известное остаточное наблюдение** (не блокер, для сведения владельца):
левый край left-зоны (x=80) слегка заходит в видимый край корпуса
аэрогриля/отражение слева от формы — на этом узком участке модель, скорее
всего, просто дорисует руку поверх (рука естественно закрывает то, что за
ней), но это стоит проверить на первом реальном кадре.

### Prompt

> Edit ONLY the masked regions of this exact image (baseplate-B.png). Do
> not alter any pixel outside the provided mask. Within the mask, paint a
> woman's forearms and hands reaching in from outside the frame and
> gripping the square silicone liner by its two flat corner handle tabs,
> thumbs resting on top of each handle — pose and motion trajectory match
> the grip mechanics reference (asset_id real-grip-motion-01: reference
> for hand pose and trajectory ONLY — it must not affect skin tone,
> gender, clothing, or hand appearance). Skin tone, hand shape, and nail
> style must exactly match the locked appearance reference (asset_id
> person-b-exhausted-01): same woman, short unpolished nails, no rings, no
> bracelets, no watch. Sleeve of the same grey ribbed cardigan visible at
> each wrist (from person-b-exhausted-01). Five fingers per hand, natural
> anatomy, no extra or missing fingers, no morphing, no fused fingers. Use
> the real left/right handle crops only for handle geometry and contact
> points — fingers wrap over the flat corner tab exactly where it exists
> in the unedited image; do not reshape, resize, or move the handle. The
> handle's short horizontal cut-out must remain at least partially
> visible through the grip. Fingers must not pass through the product's
> silicone silhouette. Do not grip the basket's upper rim — grip only the
> two real flat handles. Do not alter the product, handles, basket,
> DE'MIAND air fryer body, background, or kitchen in any way, inside or
> outside the mask. No text, no watermark, no logo.

### Порядок inputs (точный, 5 images + отдельное поле mask)

| images[i] | ref | роль |
|---|---|---|
| `images[0]` | чистая пересборка baseplate B (primary image) | edit target |
| `images[1]` | `person-b-exhausted-01` | appearance only |
| `images[2]` | `real-grip-motion-01` | pose mechanics only |
| `images[3]` | `left_handle_master.png` (sha256 `4c6603ed59a01ff4a200144cc89222dc332521915d07dd38fb63e3c8ef65b2b8`) | geometry/contact only |
| `images[4]` | `right_handle_master.png` (sha256 `9ca357bafd5f0a14041bbda8adfe6f398f8cafc3dc4493c609582efe57f2311e`) | geometry/contact only |
| `mask` | `call1-edit-mask.png` (sha256 `85c0dfe30d3050c38d6362ab8815628460d4818682111b27745d2107382caf23`, 720×1280, 6393 bytes) | применяется ТОЛЬКО к `images[0]` |

**Request contract**: `model=gpt-image-2`, `size=720x1280`, `n=1`,
`output_format=png`, `retries=0`. `input_fidelity` для gpt-image-2 явно не
передаётся (capability map). `background` не запрашивается. Multipart
fields: `image[]` ×5 (в указанном порядке) + отдельное поле `mask` (не
пятый `image[]`, не reference) + `model`/`prompt`/`size`/`n`/`output_format`.

`mask` — PNG с alpha-каналом: **alpha=0 = EDIT**, **alpha=255 = PROTECT**.
Построена детерминированно
`api/media_pipeline/compositor/scene05_edit_mask.py:build_call1_edit_mask_image`
из тех же 4 зон (без feathering, без автоматического расширения):
67425 editable пикселей (7.3% кадра), 854175 protected.

### Expected output

Один PNG 720×1280 (raw edit result — DONOR FRAME, не final frame напрямую),
пиксель-в-пиксель идентичный чистой пересборке `baseplate-B.png` везде
**вне** 4 edit-зон (гарантируется самим mask-механизмом API); внутри зон —
две женские руки (Set A appearance), держащие обе реальные плоские ручки,
короткие горизонтальные прорези частично видны, пять пальцев на кисть, без
часов/колец/браслетов, без watermark/текста. Из raw edit result в
финальный candidate composite берутся ТОЛЬКО пиксели рук/рукавов из
разрешённых зон — BACKGROUND/DE'MIAND/basket берутся из исходного
baseplate B, PRODUCT/handles — из real-product-v1 (см. ШАГ 4 детерминированной
сборки в `scene-05-generation-dry-run.json`).

---

## CALL 2 — FOOD LAYER

**Zone (canvas 720×1280)**: interior mask bbox `[200, 79, 539, 329]`
(строго внутри маски `product_interior_food_mask`, не bbox поверх стенок/
ручек/дна).

**Prompt:**
> Isolated RGBA cutout of exactly 3 roasted golden-brown chicken thighs
> with potato wedges, same arrangement and browning level as scene-04 of
> this campaign (content_code coating-protect-ad), natural realistic
> browning. Food must be fully contained within the interior silhouette
> of a square container — do not draw any container walls, rim, handles,
> or ribbed bottom (those are supplied separately from real-product-v1
> and must not be touched or implied by this layer). No plate, no dish,
> no cutlery, no hands in this layer. No steam in this layer (steam is a
> separate deterministic procedural overlay, not generated here).
> Transparent background outside the food footprint. Photographic,
> realistic. No text, no watermark.

**References passed (exact order):**
1. scene-spec only: `content/autopilot/coating-protect-2026-07/scene-specs/scene-05.json`
   `exact_food_count` (3 chicken thighs + potato wedges) — no reference image passed
   (`food-wings-01` explicitly excluded per owner decision).

---

## Final deterministic composite (no AI call — pure code)

CALL 1 меняет подход: теперь это ОДИН отредактированный кадр (background +
shadow + product + hands уже совмещены edit-моделью в масках), а не
отдельный прозрачный RGBA-слой для последующей ручной компоновки. Поверх
него докомпонуются только FOOD (CALL 2) и уже существующие процедурные
слои:

```
CALL 1 OUTPUT (masked edit of clean baseplate-B rebuild)
  = BACKGROUND + CAST_SHADOW + PRODUCT_BASE + HANDS — уже единое изображение
    -> FOOD               [CALL 2 output, masked to interior_food_mask]
    -> PRODUCT_FRONT_OCCLUDER [derived mask from real-product-v1, re-applied поверх еды, no generation]
    -> STEAM_EFFECTS       [procedural: cli._steam_overlay]
```

Итоговый кадр проверяется `product_lock_validator` (silhouette,
handle_geometry, aspect_ratio, pixel_similarity, no_local_warp) ПЛЮС
дополнительная проверка "вне edit-маски пиксели совпадают с чистой
пересборкой baseplate B" (см. тесты) — только после этого кадр может
считаться candidate frame.
