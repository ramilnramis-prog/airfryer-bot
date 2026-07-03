# Scene-05: prompt package для недостающих слоёв (DRY-RUN, генерация НЕ запущена)

Основа зафиксирована и не меняется: baseplate B (canvas 720×1280, scale
0.56, rotation -1.0°, translate [137.24, 20.48], perspective 0.0), реальный
DE'MIAND, реальная чистая корзина, real-product-v1 (product_45deg,
`api/media_pipeline/compositor/scene05_baseplate.py:APPROVED_TRANSFORM_B`).
Ничего из этого промптами не описывается и не перегенерируется — только
слои ниже.

Referenced asset_id — из `campaign_visual_lock.json` (resolved и
SHA256-проверены в `scene-05-locked-assets-plan.json`). Фактические файлы
резолвятся только через `REFERENCE_LIBRARY_ROOT`, в промпт передаются как
image references, не как встроенный текст с путями.

## Общие hard-requirements для рук (все layer-промпты ниже)

- Строго соответствуют `hands_reference`: asset_id `person-rinse-01` +
  `v2-hand-hold-01` (тот же тон кожи, форма кистей, форма и длина ногтей —
  короткие, без лака).
- Механика хвата — по `grip_reference`: asset_id `real-grip-motion-01`
  (только траектория/поза движения, НЕ внешний вид рук).
- Одежда — по `clothing_reference`: asset_id `person-b-exhausted-01`
  (серый кардиган) — рукав виден в кадре у запястья.
- Без колец, часов, браслетов, лака (`hand_requirements.jewelry: none` из
  scene-05.json).
- Ровно 5 пальцев на каждой видимой кисти.
- Хват — ТОЛЬКО за реальные плоские угловые ручки-язычки (handle bbox:
  left [190,44,275,100], right [549,166,595,259] на canvas 720×1280),
  большие пальцы сверху ручек — НЕ за верхний борт формы/корзины.
- Короткая горизонтальная прорезь ручки не должна быть закрыта пальцами
  настолько, чтобы прорезь переставала читаться на референс-фото.
- Руки не изменяют пиксели продукта (product/handle layer остаётся
  read-only RGBA — руки композитятся вокруг него по маскам, не поверх
  перерисовкой).
- Одинаковый набор across scene-01…scene-07 и hooks A/B/C этого ролика.

---

## Layer 1 — BACK_HAND (за продуктом, под PRODUCT_BASE)

**Zones (canvas 720×1280)**: left `[80, 36, 266, 268]`, right `[554, 152, 655, 538]`

**Prompt:**
> Isolated RGBA cutout of a woman's two hands and forearms only (no body,
> no background, transparent elsewhere), positioned as if reaching up and
> gripping a square silicone liner by two handles from slightly behind/
> below the rim. Skin tone, hand shape, and nail style must match the
> locked reference (asset_id person-rinse-01 / v2-hand-hold-01) exactly:
> short unpolished nails, no rings, no bracelets, no watch. Sleeve of a
> grey cardigan visible at the wrist (clothing reference asset_id
> person-b-exhausted-01). Both thumbs point upward and slightly forward,
> as in the grip mechanics reference (asset_id real-grip-motion-01) —
> reference for hand/arm pose and motion trajectory only, not final skin
> tone. Five fingers per hand, natural anatomy, no extra or missing
> fingers, no morphing, no fused fingers. Photographic, realistic skin
> texture. No product visible in this layer (composited separately). No
> text, no watermark, no logo. Transparent background (alpha channel).

**References passed (in order):** person-rinse-01, v2-hand-hold-01, real-grip-motion-01, person-b-exhausted-01

---

## Layer 2 — FRONT_FINGERS (перед продуктом, над PRODUCT_FRONT_OCCLUDER)

**Zones (canvas 720×1280)**: left `[190, 44, 275, 72]`, right `[549, 166, 595, 212]`

**Prompt:**
> Isolated RGBA cutout of fingertips and thumb only (cropped tight to the
> handle-grip area, transparent elsewhere), shown wrapping over the top of
> a flat corner handle tab with a short horizontal cut-out. Same skin tone,
> hand shape, and nail style as the locked hands reference (asset_id
> person-rinse-01 / v2-hand-hold-01) — must be visually identical to Layer
> 1 (same hands, same lighting). No rings, no polish. Fingers must not
> pass through or occlude the handle's horizontal cut-out silhouette —
> the cut-out shape stays fully readable. Five fingers total per visible
> hand fragment, natural bend, no morphing. Photographic, realistic.
> Transparent background. No text, no watermark.

**References passed (in order):** person-rinse-01, v2-hand-hold-01, real-grip-motion-01

**Alternative (recommended, minimizes calls) — UNIFIED HANDS LAYER:**
> Generate ONE isolated RGBA hands+forearms cutout (both hands, full grip
> gesture, as described in Layer 1) at full canvas resolution. Split it
> deterministically in code (no second API call) into a "back" portion
> (masked to back_hand_left_zone/back_hand_right_zone) and a "front"
> portion (masked to front_fingers_left_zone/front_fingers_right_zone)
> using the already-computed zone bounding boxes from
> `scene05_layer_masks.build_all_layer_masks`. Falls back to the two
> separate prompts above only if QA rejects the single-pass split (e.g.
> fingers not readable at the front zone crop).

---

## Layer 3 — FOOD (внутри формы, между PRODUCT_BASE и PRODUCT_FRONT_OCCLUDER)

**Zone (canvas 720×1280)**: interior mask bbox `[200, 79, 539, 329]`
(строго внутри — маска реального product_interior_food_mask, не bbox еды
поверх стенок/ручек/дна).

**Prompt:**
> Isolated RGBA cutout of exactly 3 roasted golden-brown chicken thighs
> with potato wedges around them, same arrangement and browning level as
> scene-04 of this campaign (content_code coating-protect-ad), styled
> similarly to the reference asset_id food-wings-01 (glaze/color/light
> steam style only — ignore the wings shown there; this scene uses thighs
> + potato per scene-specs/scene-05.json exact_food_count). Food must be
> fully contained within the interior silhouette of a square container —
> do not draw any container walls, rim, handles, or ribbed bottom (those
> are supplied separately from real-product-v1 and must not be touched or
> implied by this layer). No steam in this layer (steam is a separate
> deterministic procedural overlay). Transparent background outside the
> food footprint. Photographic, realistic. No text, no watermark.

**References passed (in order):** food-wings-01 (style only), scene-04 rendered frame (once available, for exact plating continuity — not yet generated at this stage)

---

## Final deterministic composite (no AI call — pure code)

Order (`api/media_pipeline/compositor/layer_compositor.py` convention):

```
BACKGROUND (real-v1 clean_basket_master.png)
  -> CAST_SHADOW        [procedural: scene05_baseplate.shadow_overlay]
  -> BACK_HAND          [generated Layer 1 above, masked to back_hand_*_zone]
  -> PRODUCT_BASE        [real-product-v1, APPROVED_TRANSFORM_B — untouched pixels]
  -> FOOD               [generated Layer 3 above, masked to interior_food_mask]
  -> PRODUCT_FRONT_OCCLUDER [derived mask from real-product-v1, no generation]
  -> FRONT_FINGERS       [generated Layer 2 above (or split from unified hands), masked to front_fingers_*_zone]
  -> STEAM_EFFECTS       [procedural: cli._steam_overlay]
```

Composite is assembled by `layer_compositor.compose()` with
`validate=True` (product-lock checks: silhouette, handle_geometry,
aspect_ratio, pixel_similarity, no_local_warp) before it is accepted as a
candidate frame.
