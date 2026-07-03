"""Детерминированные геометрические преобразования product layer.

Разрешено (product_lock.json): uniform scale, translation, ограниченная
rotation, ограниченная perspective. Запрещено структурно: non-uniform stretch
(API принимает ОДИН scale), local warp/liquify (произвольные сетки/квады не
принимаются вообще), generative fill (модуль не трогает пиксели, только
глобальная геометрия).
"""
from __future__ import annotations

from dataclasses import dataclass

from .product_lock_validator import ProductLockError

MAX_ROTATION_DEG = 8.0
MAX_PERSPECTIVE = 0.08          # доля ширины, на которую сужается верх/низ
SCALE_RANGE = (0.25, 1.60)


@dataclass(frozen=True)
class RigidTransform:
    """Глобальная трансформация слоя товара. scale — ЕДИНЫЙ по обеим осям."""
    scale: float = 1.0
    rotation_deg: float = 0.0
    translate: tuple = (0, 0)          # px на итоговом холсте
    perspective: float = 0.0           # 0..MAX_PERSPECTIVE, + сужает верх

    def validated(self) -> "RigidTransform":
        if not SCALE_RANGE[0] <= self.scale <= SCALE_RANGE[1]:
            raise ProductLockError(
                f"scale {self.scale} вне допуска {SCALE_RANGE}")
        if abs(self.rotation_deg) > MAX_ROTATION_DEG:
            raise ProductLockError(
                f"rotation {self.rotation_deg}° > лимита {MAX_ROTATION_DEG}°")
        if not 0 <= abs(self.perspective) <= MAX_PERSPECTIVE:
            raise ProductLockError(
                f"perspective {self.perspective} > лимита {MAX_PERSPECTIVE}")
        return self


def require_uniform_scale(scale_x: float, scale_y: float) -> float:
    """Единственная дверь для scale: неравные оси = немедленный отказ."""
    if abs(scale_x - scale_y) > 1e-9:
        raise ProductLockError(
            f"non-uniform stretch запрещён: sx={scale_x} sy={scale_y}")
    return scale_x


def _lerp(a, b, t):
    return a + (b - a) * t


def interpolate(t0: RigidTransform, t1: RigidTransform, u: float) -> RigidTransform:
    """Линейная интерполяция для rigid animation (u в [0,1])."""
    return RigidTransform(
        scale=_lerp(t0.scale, t1.scale, u),
        rotation_deg=_lerp(t0.rotation_deg, t1.rotation_deg, u),
        translate=(_lerp(t0.translate[0], t1.translate[0], u),
                   _lerp(t0.translate[1], t1.translate[1], u)),
        perspective=_lerp(t0.perspective, t1.perspective, u),
    ).validated()


def apply_transform(layer, transform: RigidTransform, canvas_size: tuple):
    """RGBA-слой -> RGBA-холст canvas_size с применённой трансформацией.
    Только глобальная геометрия; пиксельные значения не редактируются."""
    from PIL import Image

    t = transform.validated()
    img = layer
    if t.scale != 1.0:
        img = img.resize((max(1, round(img.width * t.scale)),
                          max(1, round(img.height * t.scale))),
                         Image.LANCZOS)
    if t.rotation_deg:
        img = img.rotate(t.rotation_deg, expand=True, resample=Image.BICUBIC)
    if t.perspective:
        w, h = img.size
        dx = t.perspective * w / 2
        # QUAD: источник для каждого угла результата (сужаем верх при p>0)
        quad = (-dx if t.perspective > 0 else 0, 0,
                0 if t.perspective > 0 else -dx, h,
                w if t.perspective > 0 else w + dx, h,
                w + dx if t.perspective > 0 else w, 0)
        img = img.transform((w, h), Image.QUAD, quad, resample=Image.BICUBIC)
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    canvas.alpha_composite(img, (round(t.translate[0]), round(t.translate[1])))
    return canvas
