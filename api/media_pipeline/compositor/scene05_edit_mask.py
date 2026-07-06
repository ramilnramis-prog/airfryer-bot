"""Детерминированная mask-PNG для CALL 1 scene-05 (masked image edit
approved baseplate B) + проверка, что editable-область совпадает ТОЛЬКО с
утверждёнными 4 зонами (`scene05_layer_masks.call1_edit_mask_zones`).

alpha=0   -> EDIT (внутри зон)
alpha=255 -> PROTECT (везде остальное)

Без feathering, без автоматического расширения зон — ровно прямоугольники,
которые уже прошли геометрическую проверку в scene05_layer_masks.
"""
from __future__ import annotations

from pathlib import Path

from ..image_mask import MaskValidationError


def build_call1_edit_mask_image(zones: dict, canvas_size: tuple):
    """RGBA-канвас: alpha=255 везде (protected), alpha=0 внутри каждой
    зоны из `zones` (editable). RGB-каналы не несут смысла для API —
    заданы (0,0,0) для наглядности превью."""
    from PIL import Image, ImageDraw

    mask = Image.new("RGBA", canvas_size, (0, 0, 0, 255))
    draw = ImageDraw.Draw(mask)
    for bbox in zones.values():
        draw.rectangle(bbox, fill=(0, 0, 0, 0))
    return mask


def assert_editable_area_matches_zones(mask_path, zones: dict) -> None:
    """Бросает MaskValidationError, если editable-область (alpha=0) не
    совпадает ТОЧНО с объединением approved zones: ни одного editable
    пикселя снаружи зон, ни одного защищённого пикселя внутри зон."""
    from PIL import Image
    import numpy as np

    with Image.open(mask_path) as im:
        alpha = np.asarray(im.getchannel("A"))

    # PIL ImageDraw.rectangle() включает обе границы (x1,y1) — numpy-срез
    # должен быть тоже включающим, иначе край прямоугольника (нарисованный
    # PIL) не совпадёт с "allowed"-маской (off-by-one на каждой стороне).
    allowed = np.zeros(alpha.shape, dtype=bool)
    for (x0, y0, x1, y1) in zones.values():
        allowed[y0:y1 + 1, x0:x1 + 1] = True

    editable = alpha == 0
    stray = editable & ~allowed
    if stray.any():
        raise MaskValidationError(
            "MASK_EDIT_ZONE_MISMATCH",
            f"{int(stray.sum())} editable пикселей вне утверждённых зон")

    missing = allowed & ~editable
    if missing.any():
        raise MaskValidationError(
            "MASK_EDIT_ZONE_MISMATCH",
            f"{int(missing.sum())} пикселей внутри утверждённых зон не editable (alpha != 0)")


def build_call1_mask_artifacts(out_dir, view: str = None, repo_root: str | Path = ".") -> dict:
    """Строит call1-edit-mask.png + preview + overlay + audit.json под
    out_dir (untracked/gitignored). Возвращает audit dict."""
    import json

    from PIL import Image, ImageDraw

    from .product_assets import DEFAULT_VIEW
    from .scene05_baseplate import APPROVED_CANVAS_SIZE, APPROVED_TRANSFORM_B
    from .scene05_debug_preview import rebuild_layered_scene
    from .scene05_layer_masks import build_all_layer_masks, call1_edit_mask_zones
    from ..image_mask import validate_mask_file

    view = view or DEFAULT_VIEW
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    masks = build_all_layer_masks(view, APPROVED_TRANSFORM_B, APPROVED_CANVAS_SIZE, repo_root)
    zones = call1_edit_mask_zones(masks)

    mask_img = build_call1_edit_mask_image(zones, APPROVED_CANVAS_SIZE)
    mask_path = out / "call1-edit-mask.png"
    mask_img.save(mask_path, "PNG")

    # preview: альфа-канал как grayscale (белое = protected, чёрное = editable)
    preview_path = out / "call1-edit-mask-preview.png"
    mask_img.getchannel("A").convert("L").save(preview_path, "PNG")

    # overlay: зоны поверх чистой пересборки baseplate B (для ручного QA)
    rebuilt = rebuild_layered_scene(view, repo_root)["image"].convert("RGB").convert("RGBA")
    overlay_layer = Image.new("RGBA", APPROVED_CANVAS_SIZE, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay_layer)
    for name, (x0, y0, x1, y1) in zones.items():
        color = (255, 0, 150, 110) if "fingers" in name else (0, 150, 255, 90)
        d.rectangle((x0, y0, x1, y1), fill=color, outline=(255, 255, 255, 255), width=2)
    overlay = Image.alpha_composite(rebuilt, overlay_layer)
    overlay_path = out / "call1-edit-mask-overlay.png"
    overlay.convert("RGB").save(overlay_path, "PNG")

    # audit: валидация контракта (dims/alpha/size) + zone-match + bboxes
    primary_input_path = out / "_primary_input_for_audit.png"
    rebuild_layered_scene(view, repo_root)["image"].convert("RGB").save(primary_input_path)
    contract_audit = validate_mask_file(mask_path, primary_input_path)
    assert_editable_area_matches_zones(mask_path, zones)
    primary_input_path.unlink(missing_ok=True)

    audit = dict(contract_audit)
    audit["bounding_boxes"] = {name: list(bbox) for name, bbox in zones.items()}
    audit["canvas_size"] = list(APPROVED_CANVAS_SIZE)
    audit["editable_area_matches_approved_zones_only"] = True

    (out / "call1-edit-mask-audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    return audit
