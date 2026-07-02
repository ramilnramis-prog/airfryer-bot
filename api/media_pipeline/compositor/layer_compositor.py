"""Послойная композиция сцены: product layer вставляется, а не рисуется.

Порядок слоёв (scene-05):
  1. BACKGROUND — кухня, стол, аэрогриль, чистая корзина (AI или реальное фото);
  2. BACK HAND — части кистей ЗА формой;
  3. PRODUCT — канонический RGBA товара (+ еда, когда появится реальный ассет),
     только RigidTransform;
  4. FRONT HAND — пальцы поверх ручек (их альфа = occlusion mask);
  5. EFFECTS — пар, тень формы на корзине.

Генеративные слои НИКОГДА не изменяют пиксели внутри product mask: продукт
композится поверх фона, а всё, что рисуется поверх продукта, учитывается как
occlusion и проверяется validator'ом.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .masks import union
from .perspective import RigidTransform, apply_transform
from .product_lock_validator import validate_composite


@dataclass
class SceneLayers:
    background: object                       # RGBA/RGB, размер холста
    product: object                          # канонический RGBA asset
    product_transform: RigidTransform = field(default_factory=RigidTransform)
    back_hand: object | None = None          # RGBA
    front_hand: object | None = None         # RGBA (альфа = occlusion)
    effects: list = field(default_factory=list)  # RGBA overlays поверх всего
    handle_masks: dict = field(default_factory=dict)  # {"left"/"right": L, asset-координаты}


def _transform_mask(mask, transform, canvas_size):
    """Маску ручки переводим на холст той же трансформацией, что и товар."""
    from PIL import Image
    rgba = Image.new("RGBA", mask.size, (255, 255, 255, 0))
    rgba.putalpha(mask)
    return apply_transform(rgba, transform, canvas_size).getchannel("A")


def compose(layers: SceneLayers, validate: bool = True) -> dict:
    """Собирает кадр. Возвращает {'image', 'expected_product_layer',
    'occlusion_mask', 'handle_masks_canvas', 'validation'}."""
    from PIL import Image

    canvas_size = layers.background.size
    frame = layers.background.convert("RGBA").copy()
    if layers.back_hand is not None:
        frame.alpha_composite(layers.back_hand)

    product_layer = apply_transform(layers.product, layers.product_transform,
                                    canvas_size)
    frame.alpha_composite(product_layer)

    occlusions = []
    if layers.front_hand is not None:
        frame.alpha_composite(layers.front_hand)
        occlusions.append(layers.front_hand.getchannel("A"))
    for fx in layers.effects:
        frame.alpha_composite(fx)
        occlusions.append(fx.getchannel("A"))
    occlusion = (union(occlusions, canvas_size) if occlusions
                 else Image.new("L", canvas_size, 0))

    handle_masks_canvas = {
        side: _transform_mask(m, layers.product_transform, canvas_size)
        for side, m in layers.handle_masks.items()}

    out = {"image": frame, "expected_product_layer": product_layer,
           "occlusion_mask": occlusion,
           "handle_masks_canvas": handle_masks_canvas}
    if validate:
        out["validation"] = validate_composite(
            frame, product_layer, occlusion_mask=occlusion,
            handle_masks=handle_masks_canvas or None,
            transform=layers.product_transform)
    return out
