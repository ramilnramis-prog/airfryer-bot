"""Occlusion-маски: руки поверх ручек БЕЗ изменения пикселей товара.

Принцип: продукт никогда не редактируется. Пальцы «лежат» на ручке потому,
что foreground-слой рук композится ПОВЕРХ product layer; его альфа — это
occlusion mask. Validator получает эту маску и исключает перекрытые пиксели
из сравнения, но требует, чтобы ВИДИМЫЕ пиксели совпадали с каноном 1-в-1.
"""
from __future__ import annotations


def union(masks: list, size: tuple):
    """Объединение L-масок в одну (максимум по пикселю)."""
    from PIL import Image
    import numpy as np

    out = np.zeros((size[1], size[0]), dtype=np.uint8)
    for m in masks:
        if m.size != size:
            m = m.resize(size)
        out = np.maximum(out, np.asarray(m.convert("L")))
    return Image.fromarray(out, "L")


def occlusion_fraction(occlusion_mask, region_mask) -> float:
    """Какая доля региона (например, ручки) закрыта foreground-слоем."""
    import numpy as np

    occ = np.asarray(occlusion_mask.convert("L")) > 128
    reg = np.asarray(region_mask.convert("L")) > 128
    total = int(reg.sum())
    return float((occ & reg).sum()) / total if total else 0.0


def check_contact_zones(occlusion_mask, handle_masks: dict,
                        max_covered: float = 0.6) -> dict:
    """Пальцы могут перекрывать ручку лишь частично: обе ручки обязаны
    оставаться различимыми для QA (перекрытие каждой <= max_covered)."""
    report = {}
    for side, hmask in handle_masks.items():
        frac = occlusion_fraction(occlusion_mask, hmask)
        report[side] = {"covered_fraction": round(frac, 4),
                        "ok": frac <= max_covered}
    report["ok"] = all(v["ok"] for v in report.values() if isinstance(v, dict))
    return report
