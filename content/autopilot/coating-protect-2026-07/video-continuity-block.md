# Video continuity block — coating-protect-ad (product-only policy)

Этот блок — **единственный источник continuity** для всего, что НЕ товар.
Используется одинаковым текстом во всех 7 сценах и во всех трёх hooks
(A/B/C) этого видео. Между сценами меняется только действие/композиция/food
state (см. `video-scene-prompts-product-only.md`); между hooks — только
первые 1-3 секунды (см. `hook_openers` в том же файле).

Для другого видео можно взять другой continuity block — товар
(`real-product-v1`) остаётся неизменным всегда.

## Текст блока (вставляется в каждый scene prompt дословно)

> Cozy clean white home kitchen, warm daylight coming from the left. Same
> black air fryer with an open square basket in every shot. Same woman's
> natural hands throughout — no rings, no bracelets, no watch, short
> unpolished nails. Same grey ribbed sweater sleeves visible at the wrists
> in every shot. Realistic home cooking photo, DSLR 50mm look, shallow
> depth of field. No CGI, no illustration, no 3D render. No text, no
> watermark, no logo. Vertical 9:16, 720×1280.

## Правила применения

- **Товар не описывается творчески.** Продукт вставляется из
  `real-product-v1` (deterministic compositing), не генерируется текстом и
  не переописывается словами формы/цвета/материала в prompt — только
  контекст действия с ним (достаёт, моет, показывает).
- AI может генерировать руки/окружение/фон/еду, но **не имеет права
  перерисовывать товар** — реальные пиксели товара всегда накладываются
  поверх сгенерированного слоя через product-lock compositing (см.
  `product-only-generation-dry-run.json`).
- Когда по сценарию сцены руки держат товар — они должны естественно
  держать его за реальные плоские угловые ручки-язычки (flat corner
  handle tabs), не за верхний борт формы или корзины.
- Короткие горизонтальные прорези ручек должны оставаться хотя бы частично
  видны в кадрах, где показан хват.
- Кухня, аэрогриль, руки, одежда и свет — **одни и те же по тексту** во
  всех 7 сценах и во всех 3 hooks этого видео (это текстовая continuity,
  не image lock — см. `campaign_visual_policy.json.not_image_locked`).

## Что явно НЕ входит в этот блок

Состав и количество еды — сцено-специфичны, задаются отдельно в
`video-scene-prompts-product-only.md` для каждой сцены (например, ровно 3
куриных бедра + картофельные дольки в сценах, где показано блюдо).
