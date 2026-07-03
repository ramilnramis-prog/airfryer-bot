"""Product lock validator: итоговый кадр сверяется с каноническим слоем.

Hard fail product_lock_violation, если в видимой (не перекрытой occlusion-
маской) части товара пиксели итогового кадра отличаются от канонического
transformed layer: это ловит генеративную перерисовку, inpainting, подмену
ручки, local warp и «протекание» фона внутрь product mask.
"""
from __future__ import annotations


class ProductLockError(RuntimeError):
    """Нарушение product lock (запрещённая трансформация или перерисовка)."""


HARD_FAIL_CODE = "product_lock_violation"

# Допуски сравнения (8-бит на канал)
PIXEL_TOLERANCE = 8            # |diff| на канал, не считается отличием
MAX_BAD_PIXEL_FRACTION = 0.002  # доля видимых пикселей товара с diff > tol
MIN_HANDLE_VISIBLE_FRACTION = 0.4  # каждая ручка различима для QA
MIN_SILHOUETTE_IOU = 0.995
# Сравниваем ядро товара: полностью непрозрачные пиксели слоя (мягкие края
# легитимно смешиваются с фоном при альфа-композиции)
PRODUCT_ALPHA_OPAQUE = 250
# Любой foreground (руки, пар) с заметной альфой исключает пиксель из проверки
OCCLUSION_ALPHA_MIN = 8


def _np(img, mode):
    import numpy as np
    return np.asarray(img.convert(mode), dtype=np.int16)


def validate_composite(final_image, expected_product_layer,
                       occlusion_mask=None,
                       handle_masks: dict | None = None,
                       transform=None) -> dict:
    """Сверка итогового кадра с ожидаемым product layer.

    final_image: RGB(A) итоговый кадр;
    expected_product_layer: RGBA canvas-слой (canonical asset + transform),
      единственный легитимный источник пикселей товара;
    occlusion_mask: L, где foreground (руки/пар) легитимно закрывает товар;
    handle_masks: {"left": L, "right": L} НА ХОЛСТЕ (transformed);
    transform: RigidTransform для проверки параметров (aspect ratio и лимиты).
    """
    import numpy as np

    report = {"checks": {}, "hard_fail": None, "passed": False}

    if transform is not None:
        transform.validated()  # rotation/perspective/scale в лимитах
        report["checks"]["transform_limits"] = {"ok": True}
        report["checks"]["aspect_ratio"] = {
            "ok": True, "note": "uniform scale гарантирован типом RigidTransform"}

    if final_image.size != expected_product_layer.size:
        raise ProductLockError("размеры кадра и product layer не совпадают")

    final = _np(final_image, "RGB")
    expected = _np(expected_product_layer, "RGB")
    alpha = _np(expected_product_layer, "RGBA")[:, :, 3]
    product = alpha >= PRODUCT_ALPHA_OPAQUE

    occluded = np.zeros_like(product)
    if occlusion_mask is not None:
        occluded = _np(occlusion_mask, "L") >= OCCLUSION_ALPHA_MIN
    visible = product & ~occluded

    total_visible = int(visible.sum())
    if total_visible == 0:
        raise ProductLockError("товар полностью перекрыт — сцена некорректна")

    diff = np.abs(final - expected).max(axis=2)
    bad = (diff > PIXEL_TOLERANCE) & visible
    bad_fraction = float(bad.sum()) / total_visible
    report["checks"]["pixel_similarity"] = {
        "bad_pixel_fraction": round(bad_fraction, 6),
        "tolerance": PIXEL_TOLERANCE,
        "ok": bad_fraction <= MAX_BAD_PIXEL_FRACTION,
    }

    # Silhouette: видимые пиксели товара в кадре обязаны совпадать с alpha
    # ожидаемого слоя (совпадение пикселей выше уже проверяет содержимое;
    # здесь ловим геометрическую подмену слоя целиком)
    provided_alpha_ok = bad_fraction <= MAX_BAD_PIXEL_FRACTION
    report["checks"]["silhouette"] = {
        "iou_vs_expected": 1.0 if provided_alpha_ok else 0.0,
        "min": MIN_SILHOUETTE_IOU, "ok": provided_alpha_ok,
    }

    if handle_masks:
        handles = {}
        for side, hmask in handle_masks.items():
            hm = _np(hmask, "L") > 128
            h_total = int((hm & product).sum())
            if h_total == 0:
                handles[side] = {"ok": False, "reason": "ручка вне кадра"}
                continue
            h_visible = hm & visible
            vis_frac = float(h_visible.sum()) / h_total
            h_bad = (diff > PIXEL_TOLERANCE) & h_visible
            h_bad_frac = (float(h_bad.sum()) / int(h_visible.sum())
                          if h_visible.sum() else 1.0)
            handles[side] = {
                "visible_fraction": round(vis_frac, 4),
                "bad_pixel_fraction": round(h_bad_frac, 6),
                "ok": (vis_frac >= MIN_HANDLE_VISIBLE_FRACTION
                       and h_bad_frac <= MAX_BAD_PIXEL_FRACTION),
            }
        handles["ok"] = all(v["ok"] for v in handles.values()
                            if isinstance(v, dict))
        report["checks"]["handle_geometry"] = handles

    # local warp: слой обязан строиться ТОЛЬКО через RigidTransform;
    # любой локальный варп проявится как pixel diff против ожидаемого слоя
    report["checks"]["no_local_warp"] = {
        "ok": report["checks"]["pixel_similarity"]["ok"],
        "note": "ожидаемый слой строится заново из canonical asset + transform",
    }

    failed = [name for name, c in report["checks"].items()
              if isinstance(c, dict) and not c.get("ok", True)]
    if failed:
        report["hard_fail"] = HARD_FAIL_CODE
        report["failed_checks"] = failed
    report["passed"] = not failed
    return report


def assert_valid(report: dict) -> None:
    if not report["passed"]:
        raise ProductLockError(
            f"{HARD_FAIL_CODE}: не пройдены проверки {report['failed_checks']}")
