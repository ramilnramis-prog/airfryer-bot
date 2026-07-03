"""Product-locked compositing pipeline.

Вывод отрицательного теста scene-05-regeneration-01: full-frame generation
перерисовывает критичную геометрию ручек даже при пяти референсах и строгом
prompt. Здесь товар — отдельный канонический RGBA-слой:

- AI может генерировать кухню, руки, аэрогриль, свет, фон, пар;
- AI НЕ рисует форму: её пиксели берутся из product asset pack и меняются
  только детерминированными глобальными трансформациями (uniform scale,
  translation, ограниченные rotation и perspective);
- руки перекрывают ручки только foreground occlusion-масками (пиксели товара
  скрываются, но не изменяются);
- после каждой композиции product_lock_validator сравнивает итоговый слой с
  каноническим ассетом; несовпадение = hard fail product_lock_violation.

Зависимости: Pillow + numpy (устанавливаются отдельно от stdlib-ядра
api/media_pipeline; сеть и платные API не используются вообще).
"""
from .product_lock_validator import ProductLockError  # noqa: F401
