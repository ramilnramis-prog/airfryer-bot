# Higgsfield-промпты: coating-protect-ad

⚠️ **Платная генерация — только после явного подтверждения владельца. Higgsfield НЕ запускать.**
Этот файл — заготовка промптов, ничего не генерировалось.

⚠️ **2026-07-03: full-frame генерация товара признана ненадёжной** (отрицательный
тест scene-05-regeneration-01: модель перерисовывает геометрию ручек даже с 5
референсами). Решение владельца: товар — неизменяемый RGBA-слой из
`api/media_pipeline/compositor` (product-locked compositing), см.
`scene-05-real-v1-composite-plan.json`. Промпты ниже сохранены для слоёв, где
AI-генерация остаётся допустимой (кухня, руки, аэрогриль, свет, пар), и как
текстовый эталон корректной геометрии — но НЕ как план full-frame генерации формы.

## Технические требования (для всех кадров)

- Reference image геометрии товара — ТОЛЬКО real-product-v1:
  `assets/product-lock/airfryer-silicone-form/references/real-v1/product/product_45deg_master.png`
  + `references/real-v1/handles/both_handles_master.png` (реальные фото; форма 1:1:
  матовая графитово-серая, квадратная со скруглёнными углами, рифлёное дно,
  две боковые ручки-язычка). `content/assets/forma_6angles.png` — OBSOLETE
  AI-канон, НЕ использовать как референс геометрии (см.
  `product_asset_manifest.json.legacy_sources`).
- Aspect ratio: 9:16 (вертикаль), один пресет стиля на все кадры.
- Единый seed, если инструмент поддерживает.
- Блюдо в кадрах 4–5 идентичное: 3 куриных бёдрышка + дольки картофеля.
- **NO on-screen text, no captions, no watermarks, no logos** — в каждом промпте.
- Не приписывать товару свойств: без надписей о температуре, сертификатах и т.п.

## STYLE ANCHOR (копируется в начало КАЖДОГО промпта без изменений)

```
ENVIRONMENT: the same bright airy modern kitchen in every shot — white subway-tile
backsplash, light greige stone countertop, a light-wood cutting board leaning at
camera-right, a small potted green plant at camera-left, a clear glass olive-oil
bottle on the counter. Clean and minimal. (Matches the brand's Ozon listing cards.)

LIGHTING: bright soft daylight from a window on camera-left, clean and airy,
neutral ~5200K, gentle soft shadows, no harsh highlights — same mood in every shot.

CHARACTER: the same woman in every shot — early 30s, light-brown hair in a low bun,
natural friendly look, wearing an oatmeal/beige apron over a white tee. For brand
match many shots may show only her hands.

PRODUCT: PRODUCT-LOCKED COMPOSITING REQUIRED — do not redraw the liner from
scratch; the exact same matte graphite-gray SQUARE silicone air fryer liner —
rounded corners, ribbed/grooved bottom (parallel raised ridges), two cut-out
handles on opposite walls, ~18.5×18.5 cm, 5 cm walls. HANDLE GEOMETRY (critical,
hard fail if violated, canonical source = real-product-v1 real photographs, NOT
an AI rendering): the handles are FLAT CORNER TABS sitting almost FLUSH with the
top rim (built into the wall's corner curve, NOT a tall loop/arch rising above
the rim), with a SHORT HORIZONTAL rectangular/slightly rounded cut-out (NOT a
tall vertical oval); left and right handles consistent with each other within
natural perspective; NOT rounded, NOT puffy, NOT arched, NOT hook-shaped, never
merging into a rounded rim. The OBSOLETE legacy shape (tall vertical loop handle
with an elongated vertical oval cut-out) does NOT match the real product and
must never be used. The silhouette must match real-product-v1 exactly and must
NOT change during motion. Use the real-product-v1 master crops as reference for
fidelity (see product_asset_manifest.json).

AIR FRYER: the real DE'MIAND air fryer (black, drawer-style, touch control panel
on top with Russian labels; see real-v1/airfryer/airfryer_front_master.png) —
replaces the previous generic AI air fryer design, per owner decision. Do not
emphasize the DE'MIAND brand in marketing copy; do not claim the product only
fits DE'MIAND.

CAMERA / LENS: 35mm look, eye-level, shallow depth of field, subtle handheld feel.

COLOR GRADE: clean bright neutral palette, soft contrast, true-to-life, cohesive.

FORMAT: vertical 9:16, realistic cinematic, 4K, photographic (not illustration).
```

---

## Кадр 1 — HOOK (руки трут чашу губкой)

```
[STYLE ANCHOR]

ACTION: at the kitchen sink, the woman's hands scrub the removable black air fryer
basket with a yellow-green kitchen sponge, soap foam on the sponge, greasy smears
visible inside the basket, a tired slow scrubbing motion. The silicone liner is NOT
in this shot. No text, no watermarks, no logos.

CAMERA: medium close-up on the hands and basket, subtle handheld sway, eye-level.
```

## Кадр 2 — БОЛЬ (макро: губка по покрытию)

```
[STYLE ANCHOR]

ACTION: extreme close-up inside the black air fryer basket: the scouring side of a
kitchen sponge drags slowly across the dark non-stick coated bottom, smearing a thin
film of grease, tiny soap bubbles. Moody but same lighting. No text, no watermarks.

CAMERA: macro shot, very slow lateral tracking following the sponge, shallow focus.
```

## Кадр 3 — РЕШЕНИЕ (форма опускается в чашу)

```
[STYLE ANCHOR]

ACTION: the woman's hand lowers the empty matte graphite-gray square silicone liner
(exact product from reference photo) into the clean black air fryer basket on the
countertop; the liner settles in neatly, ribbed bottom visible, both handles
visible — flat corner tabs almost flush with the top rim, with a short
horizontal rectangular cut-out, identical left and right, exactly as in
real-product-v1 (NOT the obsolete tall loop/vertical-oval shape). No food yet.
No text, no watermarks.

CAMERA: 45-degree high angle over the basket, static, shallow depth of field.
```

## Кадр 4 — ГОТОВКА (окно аэрогриля)

```
[STYLE ANCHOR]

ACTION: front view of the closed modern black air fryer working on the countertop;
through its front viewing window the graphite-gray square silicone liner is visible
holding exactly 3 golden chicken thighs and potato wedges, warm cooking glow inside,
subtle heat shimmer. No steam outside, no text, no watermarks.

CAMERA: frontal close crop on the viewing window, static with a very subtle push-in.
```

## Кадр 5 — ДОСТАВАНИЕ (денежный кадр, кандидат на анимацию)

```
[STYLE ANCHOR]

ACTION: the woman lifts the graphite-gray square silicone liner out of the open air
fryer basket by its two handles (flat corner tabs almost flush with the top rim,
short horizontal rectangular cut-out, identical left and right, exactly as in
real-product-v1 — NOT the obsolete tall loop/vertical-oval shape, silhouette
unchanged during motion); inside the liner exactly 3 roasted
golden chicken thighs and potato wedges, light steam rising; below, the inside of
the black basket is visibly clean and dry, untouched by grease. No text, no watermarks.

CAMERA: medium shot, gentle upward tilt following the liner as it rises, shallow focus.
```

## Кадр 6 — КОНТРАСТ (чистая чаша)

```
[STYLE ANCHOR]

ACTION: the woman's hands tilt the empty black air fryer basket toward the camera:
the dark non-stick interior is perfectly clean, smooth and evenly matte, no grease,
no scratches, softly reflecting the window light. No liner in this shot. No text,
no watermarks.

CAMERA: close-up, short slow push-in on the clean coating, eye-level.
```

## Кадр 7 — CTA (product shot)

```
[STYLE ANCHOR]

ACTION: clean product composition on the light greige countertop: the empty matte
graphite-gray square silicone liner in front, both handles (flat corner tabs
almost flush with the top rim, short horizontal rectangular cut-out, identical
left and right, exactly as in real-product-v1) and ribbed
bottom ridges clearly visible, the black air fryer slightly behind at camera-right,
soft daylight. Styled like an e-commerce listing card. No text, no watermarks, no logos.

CAMERA: static three-quarter product angle, gentle parallax drift, shallow depth of field.
```

---

## План генерации (когда владелец подтвердит)

1. Сгенерировать keyframe-изображения кадров 1–7 (или переиспользовать подход
   видео №2: кадры-изображения → анимация только «денежных»).
2. Анимировать минимум кадр 5 (подъём формы + пар), опционально 1 (движение губки)
   и 6 (наезд на чистую чашу). Остальные — Ken Burns в CapCut.
3. Перед любой генерацией — проверить баланс кредитов и получить «да» владельца.
