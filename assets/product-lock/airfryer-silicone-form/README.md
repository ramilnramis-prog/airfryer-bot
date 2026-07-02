# Product Lock — airfryer-silicone-form

Пакет канонических слоёв товара для product-locked compositing.
Причина: отрицательный тест scene-05-regeneration-01 показал, что full-frame
generation перерисовывает геометрию ручек даже при 5 референсах и строгом
prompt. Товар больше не рисуется AI — он композится готовым слоем.

## Структура

- `product_asset_manifest.json` — манифест: источники, SHA256, ограничения.
- `product_lock.json` — правила неизменности и допустимых трансформаций.
- `source/` — (зарезервировано) локальные копии исходников при необходимости.
- `isolated/` — прозрачные RGBA-виды товара (6 ракурсов из forma_6angles.png).
- `masks/` — маски товара и отдельные маски левой/правой ручки.
- `handles/` — крупные crops ручек (канон: см. также
  `assets/visual-bible/airfryer-silicone-form/references/handles_reference_crop.png`).
- `perspective-guides/` — направляющие соответствия ракурсов сцен ракурсам пакета.
- `validation/` — чек-листы и baseline для product_lock_validator.

## Воспроизводимость

Пакет строится детерминированно из канонического источника:

```
python -m api.media_pipeline.compositor.cli extract
```

Ничего не дорисовывается: отсутствующие ракурсы перечислены в манифесте в
`requires_real_photo` (см. `REAL_PRODUCT_REFERENCE_SHOOT.md` в корне репо).

## Использование

- Композиция: `api/media_pipeline/compositor/layer_compositor.py`.
- Трансформации: только `RigidTransform` (uniform scale, translation,
  rotation ≤ 8°, perspective ≤ 0.08).
- После каждой композиции — `product_lock_validator.validate_composite`;
  несовпадение с каноном = hard fail `product_lock_violation`.
