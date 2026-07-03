"""Детерминированные маски слоёв scene-05 поверх approved baseplate-B.

Все маски вычисляются ИЗ реального product layer (real-product-v1) и
зафиксированного transform B — никакого рисования "на глаз" поверх
сплющенного baseplate-B.png, никакой AI-сегментации, никаких внешних API.

Методы:
- product_full_mask / handle masks: точная трансформация реальных масок
  product_asset_manifest.json через apply_transform (тот же путь, что
  использует product_lock_validator).
- product_interior_food_mask: морфологическая эрозия product_full_mask
  (детерминированная операция обработки изображений над РЕАЛЬНОЙ маской,
  без ML) + выделение связной области, содержащей центр формы (чтобы
  отрезанные эрозией фрагменты ручек не попали в "внутреннюю" область).
- product_front_occluder_mask: разность full_mask и interior_mask —
  "оболочка" (борт+ручки), которая перерисовывается поверх еды теми же
  пикселями PRODUCT_BASE (новых пикселей товара не создаётся).
- back-hand / front-fingers zones: получены как расширение/подмножество
  РЕАЛЬНЫХ handle bbox (не независимые координаты на глаз).
- cast_shadow / steam zones: получены как смещение от bbox
  product_full_mask (ниже/выше формы).
"""
from __future__ import annotations

from collections import deque
from pathlib import Path

from .perspective import RigidTransform, apply_transform
from .product_assets import load_view

# Эрозия интерьера: доля от min(bbox_w, bbox_h) силуэта формы — детерминированная
# формула, не подобрана вручную под конкретный кадр.
INTERIOR_EROSION_FRACTION = 0.12
# Минимальный радиус эрозии в пикселях (не даёт формуле выродиться в 0 на
# маленьких масштабах).
INTERIOR_EROSION_MIN_PX = 18

# Насколько back-hand зона шире/ниже реального handle bbox (доли bbox).
BACK_HAND_PAD_OUT = 1.3      # наружу (влево для left, вправо для right)
BACK_HAND_PAD_DOWN = 3.0     # вниз (к камере)
BACK_HAND_PAD_IN = 0.15      # немного внутрь/вверх

# cast_shadow / steam — смещение от bbox формы, в долях высоты bbox.
CAST_SHADOW_DROP_FRACTION = 0.05   # ниже нижней границы формы
CAST_SHADOW_HEIGHT_FRACTION = 0.12
STEAM_HEIGHT_FRACTION = 0.35       # высота зоны пара над формой


def _np():
    import numpy as np
    return np


def load_product_layers(view: str, repo_root: str | Path = "."):
    """Загружает product RGBA + маску + handle-маски (в системе координат
    исходного real-product-v1 asset, ДО transform)."""
    return load_view(view, repo_root=repo_root)


def transform_to_canvas(image_or_mask, transform: RigidTransform, canvas_size: tuple):
    """Применяет ЗАФИКСИРОВАННЫЙ transform к слою и возвращает результат на
    холсте canvas_size (тот же путь, что apply_transform в compositor)."""
    return apply_transform(image_or_mask, transform, canvas_size)


def product_full_mask(product_rgba, transform: RigidTransform, canvas_size: tuple):
    """Маска всего силуэта формы на холсте (альфа-канал transformed product)."""
    canvas = transform_to_canvas(product_rgba, transform, canvas_size)
    return canvas.getchannel("A")


def handle_masks_on_canvas(handle_masks: dict, transform: RigidTransform,
                           canvas_size: tuple) -> dict:
    """left/right handle mask -> точный transform B -> холст."""
    from PIL import Image

    out = {}
    for side, m in handle_masks.items():
        rgba = Image.new("RGBA", m.size, (255, 255, 255, 0))
        rgba.putalpha(m)
        out[side] = transform_to_canvas(rgba, transform, canvas_size).getchannel("A")
    return out


def _largest_component_containing(mask_arr, seed_xy):
    """BFS-связная область маски, содержащая seed_xy (x, y). Чистая геометрия
    поверх реального (не сгенерированного) массива — без внешних библиотек
    сегментации."""
    np = _np()
    h, w = mask_arr.shape
    sx, sy = seed_xy
    if not (0 <= sx < w and 0 <= sy < h) or not mask_arr[sy, sx]:
        return np.zeros_like(mask_arr, dtype=bool)
    visited = np.zeros_like(mask_arr, dtype=bool)
    out = np.zeros_like(mask_arr, dtype=bool)
    q = deque([(sx, sy)])
    visited[sy, sx] = True
    while q:
        x, y = q.popleft()
        out[y, x] = True
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx] and mask_arr[ny, nx]:
                visited[ny, nx] = True
                q.append((nx, ny))
    return out


def product_interior_food_mask(full_mask):
    """Эрозия product_full_mask внутрь силуэта + выделение связной области
    вокруг центра bbox формы (исключает оторванные эрозией фрагменты
    ручек). Детерминированная функция реальной маски, без AI."""
    from PIL import Image, ImageFilter
    np = _np()

    bbox = full_mask.getbbox()
    if bbox is None:
        raise ValueError("product_full_mask пуст — форма вне холста")
    x0, y0, x1, y1 = bbox
    radius = max(INTERIOR_EROSION_MIN_PX,
                round(min(x1 - x0, y1 - y0) * INTERIOR_EROSION_FRACTION))
    kernel = radius * 2 + 1  # MinFilter требует нечётный размер
    eroded = full_mask.filter(ImageFilter.MinFilter(kernel))
    arr = np.asarray(eroded) > 128
    seed = ((x0 + x1) // 2, (y0 + y1) // 2)
    component = _largest_component_containing(arr, seed)
    return Image.fromarray((component * 255).astype("uint8"), "L")


def product_front_occluder_mask(full_mask, interior_mask):
    """Оболочка формы (борт+ручки) = full_mask минус interior_mask.
    Перерисовывается ПОВЕРХ еды теми же пикселями PRODUCT_BASE — новых
    пикселей товара не создаётся, только повторное использование реальных."""
    from PIL import Image
    np = _np()

    full = np.asarray(full_mask) > 128
    interior = np.asarray(interior_mask) > 128
    shell = full & ~interior
    return Image.fromarray((shell * 255).astype("uint8"), "L")


def _expand_bbox(bbox, pad_out_frac, pad_down_frac, pad_in_frac, side, canvas_size):
    """Расширяет handle bbox наружу (влево для left / вправо для right) и
    вниз — детерминированная функция самого bbox, не независимые координаты."""
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    cw, ch = canvas_size
    out_pad = w * pad_out_frac
    down_pad = h * pad_down_frac
    in_pad = h * pad_in_frac
    if side == "left":
        nx0, nx1 = max(0, x0 - out_pad), min(cw, x1 - w * 0.1)
    else:
        nx0, nx1 = max(0, x0 + w * 0.1), min(cw, x1 + out_pad)
    ny0 = max(0, y0 - in_pad)
    ny1 = min(ch, y1 + down_pad)
    return (round(nx0), round(ny0), round(nx1), round(ny1))


def back_hand_zone(handle_bbox: tuple, side: str, canvas_size: tuple) -> tuple:
    """Зона BACK_HAND — расширение реального handle bbox наружу/вниз (кисть
    подходит снизу-сбоку к ручке и заходит за форму)."""
    return _expand_bbox(handle_bbox, BACK_HAND_PAD_OUT, BACK_HAND_PAD_DOWN,
                        BACK_HAND_PAD_IN, side, canvas_size)


def front_fingers_zone(handle_bbox: tuple) -> tuple:
    """Зона FRONT_FINGERS — верхняя половина реального handle bbox (палец
    ложится на верхнюю грань ручки; нижняя половина bbox остаётся видна для
    QA силуэта ручки, перекрытие <= ~50-60%)."""
    x0, y0, x1, y1 = handle_bbox
    mid_y = round((y0 + y1) / 2)
    return (x0, y0, x1, mid_y)


def cast_shadow_zone(full_mask_bbox: tuple, canvas_size: tuple) -> tuple:
    """Падающая тень НИЖЕ формы (форма не касается корзины — тень падающая,
    не contact): смещена вниз от нижней границы product_full_mask bbox."""
    x0, y0, x1, y1 = full_mask_bbox
    h = y1 - y0
    drop = h * CAST_SHADOW_DROP_FRACTION
    band = h * CAST_SHADOW_HEIGHT_FRACTION
    cx = (x0 + x1) / 2
    rx = (x1 - x0) * 0.55
    top = y1 + drop
    return (round(cx - rx), round(top), round(cx + rx), round(top + band))


def steam_zone(full_mask_bbox: tuple, canvas_size: tuple) -> tuple:
    """Зона пара — над верхней границей product_full_mask bbox."""
    x0, y0, x1, y1 = full_mask_bbox
    h = y1 - y0
    band = h * STEAM_HEIGHT_FRACTION
    top = max(0, y0 - band)
    return (x0, round(top), x1, y0)


def call1_edit_mask_zones(masks: dict) -> dict:
    """Маска для CALL 1 сцены-05 как MASKED IMAGE EDIT приближённого
    baseplate-B.png (не слоистая компоновка).

    back_hand_zone спроектирована для СЛОИСТОГО рендера, где PRODUCT_BASE
    рисуется поверх неё в более позднем z-order — в плоском edit такой
    гарантии нет: если использовать её как есть, правая зона (без
    обрезки) заходит в открытую корзину/рёбра корзины ниже формы (визуально
    подтверждено сверкой с content/autopilot/coating-protect-2026-07/
    generated/scene-05-real-baseplate/baseplate-B.png). Поэтому обе
    forearm/hand зоны обрезаются по нижней границе product_full_bbox —
    ниже неё начинается корзина/фон, которые нельзя редактировать."""
    x0l, y0l, x1l, y1l = masks["back_hand_left_zone"]
    x0r, y0r, x1r, y1r = masks["back_hand_right_zone"]
    _, _, _, product_y1 = masks["product_full_bbox"]
    return {
        "left_forearm_hand": (x0l, y0l, x1l, min(y1l, product_y1)),
        "right_forearm_hand": (x0r, y0r, x1r, min(y1r, product_y1)),
        "left_fingers_over_handle": masks["front_fingers_left_zone"],
        "right_fingers_over_handle": masks["front_fingers_right_zone"],
    }


def build_all_layer_masks(view: str, transform: RigidTransform,
                          canvas_size: tuple, repo_root: str | Path = "."):
    """Собирает ВСЕ детерминированные маски/зоны за один проход. Возвращает
    dict с масками (PIL L Image) и зонами (bbox tuple)."""
    product_rgba, _src_mask, handle_src_masks = load_product_layers(view, repo_root)
    full_mask = product_full_mask(product_rgba, transform, canvas_size)
    handles_canvas = handle_masks_on_canvas(handle_src_masks, transform, canvas_size)
    interior = product_interior_food_mask(full_mask)
    occluder = product_front_occluder_mask(full_mask, interior)

    full_bbox = full_mask.getbbox()
    left_bbox = handles_canvas["left"].getbbox()
    right_bbox = handles_canvas["right"].getbbox()

    return {
        "product_rgba_on_canvas": transform_to_canvas(product_rgba, transform, canvas_size),
        "product_full_mask": full_mask,
        "product_full_bbox": full_bbox,
        "left_handle_mask": handles_canvas["left"],
        "right_handle_mask": handles_canvas["right"],
        "left_handle_bbox": left_bbox,
        "right_handle_bbox": right_bbox,
        "product_interior_food_mask": interior,
        "product_front_occluder_mask": occluder,
        "back_hand_left_zone": back_hand_zone(left_bbox, "left", canvas_size),
        "back_hand_right_zone": back_hand_zone(right_bbox, "right", canvas_size),
        "front_fingers_left_zone": front_fingers_zone(left_bbox),
        "front_fingers_right_zone": front_fingers_zone(right_bbox),
        "cast_shadow_zone": cast_shadow_zone(full_bbox, canvas_size),
        "steam_zone": steam_zone(full_bbox, canvas_size),
    }
