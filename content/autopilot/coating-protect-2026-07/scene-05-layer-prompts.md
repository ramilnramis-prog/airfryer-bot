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
- Руки не изменяют пиксели продукта (product/handle layer остаётся
  read-only RGBA — руки композитятся вокруг него по маскам).
- Одинаковый набор across scene-01…scene-07 и hooks A/B/C этого ролика.

---

## CALL 1 — HANDS LAYER (unified back_hand + front_fingers)

**Zones (canvas 720×1280)**:
back `[80, 36, 266, 268]` / `[554, 152, 655, 538]`,
front `[190, 44, 275, 72]` / `[549, 166, 595, 212]`

**Prompt:**
> Isolated RGBA cutout of a woman's two hands and forearms (no body below
> the elbow, no background — transparent elsewhere), positioned reaching
> up and gripping a square silicone liner by two flat corner handle tabs,
> thumbs on top, exactly as in the grip mechanics reference (asset_id
> real-grip-motion-01 — reference for hand pose and motion trajectory
> ONLY, this reference must not affect skin tone, gender, clothing, or
> hand appearance). Skin tone, hand shape, and nail style must match the
> locked appearance reference (asset_id person-b-exhausted-01) exactly:
> same woman, short unpolished nails, no rings, no bracelets, no watch.
> Sleeve of the same grey ribbed cardigan visible at the wrist (from the
> same appearance reference person-b-exhausted-01). Five fingers per
> hand, natural anatomy, no extra or missing fingers, no morphing, no
> fused fingers. Fingers must not pass through the product silhouette;
> the handle's short horizontal cut-out stays visually readable through
> the grip. Photographic, realistic skin texture. No product pixels
> altered — this layer composites around the product, not over it. No
> text, no watermark, no logo. Transparent background (alpha channel).

**References passed (exact order):**
1. `person-b-exhausted-01` (appearance: skin tone, hand shape, nails, cardigan)
2. `real-grip-motion-01` (mechanics: pose/trajectory only)

**Masks applied post-generation (deterministic split, no extra API call):**
`back_hand_left_zone`, `back_hand_right_zone` → BACK_HAND layer (behind product);
`front_fingers_left_zone`, `front_fingers_right_zone` → FRONT_FINGERS layer (in front of product) —
both computed by `api/media_pipeline/compositor/scene05_layer_masks.py:build_all_layer_masks`.

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

```
BACKGROUND (real-v1 clean_basket_master.png)                — unchanged
  -> CAST_SHADOW        [procedural: scene05_baseplate.shadow_overlay]
  -> BACK_HAND          [CALL 1 output, masked to back_hand_*_zone]
  -> PRODUCT_BASE        [real-product-v1, APPROVED_TRANSFORM_B — untouched pixels]
  -> FOOD               [CALL 2 output, masked to interior_food_mask]
  -> PRODUCT_FRONT_OCCLUDER [derived mask from real-product-v1, no generation]
  -> FRONT_FINGERS       [CALL 1 output, masked to front_fingers_*_zone]
  -> STEAM_EFFECTS       [procedural: cli._steam_overlay]
```

Composite assembled by `layer_compositor.compose()` with `validate=True`
(product-lock checks: silhouette, handle_geometry, aspect_ratio,
pixel_similarity, no_local_warp) before acceptance as a candidate frame.
