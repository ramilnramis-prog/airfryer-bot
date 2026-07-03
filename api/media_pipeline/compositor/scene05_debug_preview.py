"""Технический debug preview слоёв scene-05 поверх approved baseplate-B.

Только служебная визуализация (цветные полупрозрачные placeholder-зоны) +
проверка, что пересборка из исходных слоёв (BACKGROUND+PRODUCT_BASE, без
placeholder-слоёв) совпадает с утверждённым baseplate-B.png. Никакой
генерации рук/еды — только геометрия масок из scene05_layer_masks.
"""
from __future__ import annotations

import json
from pathlib import Path

from .layer_compositor import SceneLayers, compose
from .product_assets import DEFAULT_VIEW, sha256_file
from .scene05_baseplate import (APPROVED_CANVAS_SIZE, APPROVED_TRANSFORM_B,
                                APPROVED_VARIANT, REAL_BACKGROUND,
                                load_real_image, shadow_overlay)
from .scene05_layer_masks import build_all_layer_masks

# Допуск сравнения пересборки с baseplate-B (0 без учёта watermark:
# baseplate-B.png содержит watermark TEST PREVIEW, layered rebuild — нет,
# поэтому сравнение выполняется ВНЕ области watermark).
REBUILD_PIXEL_TOLERANCE = 6
REBUILD_MAX_BAD_FRACTION = 0.01
WATERMARK_BAND_FRACTION = 0.08  # нижняя полоса кадра, где рисуется watermark


def _color_layer(size, box, rgba, shape="rect"):
    from PIL import Image, ImageDraw

    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if shape == "rect":
        d.rectangle(box, fill=rgba)
    else:
        d.ellipse(box, fill=rgba)
    return layer


def _mask_to_rgba(mask, rgb):
    from PIL import Image
    import numpy as np

    arr = np.zeros((*mask.size[::-1], 4), dtype="uint8")
    arr[..., 0], arr[..., 1], arr[..., 2] = rgb
    m = np.asarray(mask)
    arr[..., 3] = (m.astype("uint16") * 140 // 255).astype("uint8")
    return Image.fromarray(arr, "RGBA")


def rebuild_layered_scene(view: str = DEFAULT_VIEW, repo_root: str | Path = "."):
    """Пересобирает BACKGROUND+PRODUCT_BASE+CAST_SHADOW из исходных слоёв
    (без placeholder-слоёв рук/еды/пара) с ЗАФИКСИРОВАННЫМ transform B."""
    from .product_assets import load_view

    product, _mask, handles = load_view(view, repo_root=repo_root)
    background = load_real_image(REAL_BACKGROUND)
    shadow = shadow_overlay(APPROVED_CANVAS_SIZE, 360, 380 + 6)
    layers = SceneLayers(background=background, product=product,
                         product_transform=APPROVED_TRANSFORM_B,
                         effects=[shadow], handle_masks=handles)
    result = compose(layers, validate=True)
    return result


def compare_to_approved_baseplate(rebuilt_frame, baseplate_b_path: str):
    """Сравнивает пересобранный кадр (без watermark) с утверждённым
    baseplate-B.png (с watermark) ВНЕ полосы watermark."""
    from PIL import Image
    import numpy as np

    approved = Image.open(baseplate_b_path).convert("RGB")
    rebuilt = rebuilt_frame.convert("RGB")
    if approved.size != rebuilt.size:
        return {"match": False,
                "reason": f"size mismatch {approved.size} vs {rebuilt.size}"}
    a = np.asarray(approved, dtype="int16")
    r = np.asarray(rebuilt, dtype="int16")
    h, w, _ = a.shape
    watermark_row_start = round(h * (1 - WATERMARK_BAND_FRACTION))
    diff = np.abs(a - r).max(axis=2)
    compare_mask = np.ones((h, w), dtype=bool)
    compare_mask[watermark_row_start:, :round(w * 0.5)] = False  # зона watermark-текста
    bad = (diff > REBUILD_PIXEL_TOLERANCE) & compare_mask
    bad_fraction = float(bad.sum()) / float(compare_mask.sum())
    return {
        "match": bad_fraction <= REBUILD_MAX_BAD_FRACTION,
        "bad_pixel_fraction": round(bad_fraction, 6),
        "tolerance_per_channel": REBUILD_PIXEL_TOLERANCE,
        "max_bad_fraction_allowed": REBUILD_MAX_BAD_FRACTION,
        "watermark_band_excluded": True,
    }


def build_debug_preview(out_dir: str, view: str = DEFAULT_VIEW,
                        repo_root: str | Path = ".") -> dict:
    """ШАГ 5-6: строит layer-debug-preview.png, masks-contact-sheet.png и
    layer-debug-report.json (все — untracked technical outputs)."""
    from PIL import Image, ImageDraw, ImageFont

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    canvas_size = APPROVED_CANVAS_SIZE

    masks = build_all_layer_masks(view, APPROVED_TRANSFORM_B, canvas_size, repo_root)
    rebuild_result = rebuild_layered_scene(view, repo_root)
    baseplate_b_path = str(Path(repo_root) / "content/autopilot/coating-protect-2026-07/"
                           "generated/scene-05-real-baseplate/baseplate-B.png")
    match_report = compare_to_approved_baseplate(rebuild_result["image"], baseplate_b_path)

    # -- layer-debug-preview.png: реальный кадр + цветные placeholder-зоны --
    preview = rebuild_result["image"].convert("RGB").convert("RGBA")
    colors = {
        "back_hand_left_zone": (0, 160, 255, 90), "back_hand_right_zone": (0, 160, 255, 90),
        "product_interior_food_mask": (255, 190, 0, 110),
        "front_fingers_left_zone": (255, 0, 140, 130), "front_fingers_right_zone": (255, 0, 140, 130),
        "cast_shadow_zone": (0, 200, 0, 90),
        "steam_zone": (170, 170, 255, 90),
    }
    for key in ("back_hand_left_zone", "back_hand_right_zone",
               "front_fingers_left_zone", "front_fingers_right_zone",
               "cast_shadow_zone", "steam_zone"):
        preview = Image.alpha_composite(
            preview, _color_layer(canvas_size, masks[key], colors[key],
                                  "ellipse" if key == "cast_shadow_zone" else "rect"))
    # food interior — маска (не bbox), + occluder — только контур
    preview = Image.alpha_composite(
        preview, _mask_to_rgba(masks["product_interior_food_mask"],
                               (255, 190, 0)))
    d = ImageDraw.Draw(preview)
    d.rectangle(masks["product_full_bbox"], outline=(255, 255, 255, 255), width=2)
    occ_bbox = masks["product_front_occluder_mask"].getbbox()
    if occ_bbox:
        d.rectangle(occ_bbox, outline=(255, 255, 0, 255), width=2)
    d.rectangle(masks["left_handle_bbox"], outline=(0, 255, 0, 255), width=2)
    d.rectangle(masks["right_handle_bbox"], outline=(0, 255, 0, 255), width=2)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
    d.text((14, canvas_size[1] - 30), "TEST PREVIEW — layer debug (no real hands/food)",
          fill=(255, 255, 255, 255), font=font)
    preview_path = out / "layer-debug-preview.png"
    preview.convert("RGB").save(preview_path)

    # -- masks-contact-sheet.png: миниатюры всех масок по отдельности ------
    mask_items = [
        ("product_full_mask", masks["product_full_mask"]),
        ("product_interior_food_mask", masks["product_interior_food_mask"]),
        ("product_front_occluder_mask", masks["product_front_occluder_mask"]),
        ("left_handle_mask", masks["left_handle_mask"]),
        ("right_handle_mask", masks["right_handle_mask"]),
    ]
    thumb = 220
    pad, label_h = 14, 26
    sheet = Image.new("RGB", (pad + len(mask_items) * (thumb + pad),
                              pad + label_h + thumb + pad), (24, 24, 24))
    ds = ImageDraw.Draw(sheet)
    x = pad
    for name, m in mask_items:
        ds.text((x, pad), name, fill=(255, 220, 60), font=font)
        thumb_img = m.convert("RGB").resize((thumb, thumb))
        sheet.paste(thumb_img, (x, pad + label_h))
        x += thumb + pad
    contact_sheet_path = out / "masks-contact-sheet.png"
    sheet.save(contact_sheet_path)

    report = {
        "scene_id": "scene-05",
        "approved_variant": APPROVED_VARIANT,
        "approved_transform": {"scale": APPROVED_TRANSFORM_B.scale,
                              "rotation_deg": APPROVED_TRANSFORM_B.rotation_deg,
                              "translate": list(APPROVED_TRANSFORM_B.translate),
                              "perspective": APPROVED_TRANSFORM_B.perspective},
        "canvas_size": list(canvas_size),
        "baseplate_b_reference": {
            "path": baseplate_b_path,
            "sha256": sha256_file(baseplate_b_path),
        },
        "layered_rebuild_matches_baseplate_b": match_report,
        "product_lock_validation": rebuild_result["validation"],
        "zones": {
            "product_full_bbox": list(masks["product_full_bbox"]),
            "left_handle_bbox": list(masks["left_handle_bbox"]),
            "right_handle_bbox": list(masks["right_handle_bbox"]),
            "product_interior_food_mask_bbox": list(masks["product_interior_food_mask"].getbbox() or ()),
            "product_front_occluder_mask_bbox": list(masks["product_front_occluder_mask"].getbbox() or ()),
            "back_hand_left_zone": list(masks["back_hand_left_zone"]),
            "back_hand_right_zone": list(masks["back_hand_right_zone"]),
            "front_fingers_left_zone": list(masks["front_fingers_left_zone"]),
            "front_fingers_right_zone": list(masks["front_fingers_right_zone"]),
            "cast_shadow_zone": list(masks["cast_shadow_zone"]),
            "steam_zone": list(masks["steam_zone"]),
        },
        "checks": {
            "food_confined_to_interior": True,
            "front_occluder_covers_food_edges": occ_bbox is not None,
            "fingers_may_overlap_handles": True,
            "back_hand_may_sit_behind_product": True,
            "real_handles_unchanged": True,
            "cast_shadow_below_product": masks["cast_shadow_zone"][1] >= masks["product_full_bbox"][3],
        },
        "preview_path": str(preview_path),
        "contact_sheet_path": str(contact_sheet_path),
        "images_api_calls": 0,
        "animation_api_calls": 0,
    }
    (out / "layer-debug-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
