"""Канонические константы scene-05 baseplate (единый источник истины).

Решение владельца (SELECT B, 2026-07-03): вариант B зафиксирован как
approved baseplate scene-05. Transform НЕ подлежит изменению без нового
явного решения владельца — любой код, которому нужен transform B, обязан
импортировать его отсюда, а не пересчитывать/угадывать заново.
"""
from __future__ import annotations

from .perspective import RigidTransform

REAL_BACKGROUND = ("assets/product-lock/airfryer-silicone-form/references/"
                   "real-v1/airfryer/clean_basket_master.png")

# Геометрия проёма корзины в REAL_BACKGROUND (720x1280, разметка по сетке):
# задняя кромка корзины ~y=400, центр по x ~360, ширина проёма ~530px.
BASKET_CENTER_X = 360
BASKET_RIM_Y = 400

# Все три варианта — исторические (A/C rejected_alternative, не удалены).
BASEPLATE_VARIANTS = {
    "A": {"label": "форма ближе к корзине, начало подъёма",
          "scale": 0.60, "bottom_y": 440, "rotation_deg": 0.0, "dx": 0,
          "status": "rejected_alternative"},
    "B": {"label": "форма на средней высоте, корзина хорошо видна",
          "scale": 0.56, "bottom_y": 380, "rotation_deg": -1.0, "dx": 6,
          "status": "owner_approved"},
    "C": {"label": "форма выше и немного отведена назад, корзина видна почти полностью",
          "scale": 0.50, "bottom_y": 330, "rotation_deg": -2.0, "dx": 10,
          "status": "rejected_alternative"},
}

APPROVED_VARIANT = "B"
APPROVED_CANVAS_SIZE = (720, 1280)

# Точный transform B — ЗАФИКСИРОВАН владельцем, пересчитывать запрещено.
# Совпадает с BASEPLATE_VARIANTS["B"] + product_45deg.size (817x642) —
# variant_transform() ниже воспроизводит именно эти числа детерминированно;
# литералы продублированы здесь как явный, читаемый человеком контракт.
APPROVED_TRANSFORM_B = RigidTransform(
    scale=0.56, rotation_deg=-1.0, translate=(137.24, 20.48), perspective=0.0)


def variant_transform(spec: dict, product_size: tuple) -> RigidTransform:
    """Пересчитывает RigidTransform варианта из его спецификации (bottom_y/
    scale/rotation/dx) + фактического размера product layer. Для B результат
    обязан совпадать с APPROVED_TRANSFORM_B (проверяется тестами)."""
    w, h = product_size
    scale = spec["scale"]
    disp_w, disp_h = w * scale, h * scale
    x0 = BASKET_CENTER_X - disp_w / 2 + spec["dx"]
    y0 = spec["bottom_y"] - disp_h
    return RigidTransform(scale=scale, rotation_deg=spec["rotation_deg"],
                          translate=(x0, y0))


def load_real_image(path: str):
    from PIL import Image
    return Image.open(path).convert("RGBA")


def shadow_overlay(size: tuple, center_x: float, rim_y: float, strength: float = 60):
    """Мягкая тень формы на корзине — отдельный полупрозрачный overlay,
    product mask не затрагивает. (Смысл переименован в CAST_SHADOW на
    уровне layer skeleton — форма не касается корзины, тень падающая.)"""
    from PIL import Image, ImageDraw, ImageFilter

    fx = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(fx)
    rx, ry = 150, 26
    d.ellipse((center_x - rx, rim_y - ry, center_x + rx, rim_y + ry),
             fill=(0, 0, 0, int(strength)))
    return fx.filter(ImageFilter.GaussianBlur(14))
