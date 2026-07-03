"""CLI product-locked compositing (всё локально, сети нет вообще).

Команды:
  extract       — построить/перестроить LEGACY product asset pack из
                  forma_6angles.png (устарело — см. extract-real)
  extract-real  — построить real-product-v1 master crops + пересобрать
                  product_asset_manifest.json ТОЛЬКО из реальных фото/видео
  preview       — тестовый rigid-animation preview scene-05 (плейсхолдер-фон,
                  канонический product layer из real-product-v1 по
                  умолчанию, watermark TEST PREVIEW)
  baseplate     — статичный технический base plate scene-05 (реальный фон
                  DE'MIAND + реальный product layer, 3 варианта положения
                  A/B/C, без рук/еды/пара/анимации)
  validate <frame.png> — проверить кадр против канона (нужны transform-параметры)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .perspective import RigidTransform
from .product_assets import DEFAULT_VIEW, build_asset_pack, load_view
from .real_product_assets import build_real_asset_pack, build_real_master_crops
from .layer_compositor import SceneLayers, compose
from .rigid_animation import RigidAnimationPlan, render_preview


def _placeholder_background(size: tuple):
    """Технический фон-плейсхолдер (НЕ финальный арт): градиент кухни +
    тёмный прямоугольник корзины. Реальный фон придёт из AI/фото отдельно."""
    from PIL import Image, ImageDraw, ImageFilter

    w, h = size
    bg = Image.new("RGB", size)
    for y in range(h):
        k = y / h
        bg.paste((int(214 - 60 * k), int(196 - 58 * k), int(172 - 52 * k)),
                 (0, y, w, y + 1))
    draw = ImageDraw.Draw(bg)
    draw.rounded_rectangle((int(w * 0.08), int(h * 0.62),
                            int(w * 0.92), int(h * 0.95)),
                           radius=int(w * 0.06), fill=(24, 24, 26))
    draw.rounded_rectangle((int(w * 0.14), int(h * 0.66),
                            int(w * 0.86), int(h * 0.90)),
                           radius=int(w * 0.05), fill=(12, 12, 14))
    return bg.filter(ImageFilter.GaussianBlur(1)).convert("RGBA")


def _steam_overlay(size: tuple, seed_step: int = 0):
    """Процедурный лёгкий пар (отдельный overlay, товар не трогает)."""
    from PIL import Image, ImageDraw, ImageFilter

    w, h = size
    fx = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(fx)
    for i in range(3):
        cx = w // 2 + (i - 1) * w // 10 + (seed_step * 3) % 17
        cy = int(h * 0.30) - i * h // 22 - seed_step
        r = w // 12 + i * 3
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 26))
    return fx.filter(ImageFilter.GaussianBlur(10))


# -- scene-05 real base plate (ШАГ 3-5 задачи) ------------------------------

REAL_BACKGROUND = ("assets/product-lock/airfryer-silicone-form/references/"
                   "real-v1/airfryer/clean_basket_master.png")

# Basket opening geometry в REAL_BACKGROUND (720x1280, размечено вручную по
# сетке): задняя кромка корзины ~y=400, центр по x ~360, ширина проёма ~530px.
BASKET_CENTER_X = 360
BASKET_RIM_Y = 400

# Три варианта положения формы (ШАГ 4): только translation/scale/rotation,
# один и тот же real-product-v1 product layer.
BASEPLATE_VARIANTS = {
    "A": {"label": "форма ближе к корзине, начало подъёма",
          "scale": 0.60, "bottom_y": 440, "rotation_deg": 0.0, "dx": 0},
    "B": {"label": "форма на средней высоте, корзина хорошо видна",
          "scale": 0.56, "bottom_y": 380, "rotation_deg": -1.0, "dx": 6},
    "C": {"label": "форма выше и немного отведена назад, корзина видна почти полностью",
          "scale": 0.50, "bottom_y": 330, "rotation_deg": -2.0, "dx": 10},
}


def _load_real_image(path: str):
    from PIL import Image
    return Image.open(path).convert("RGBA")


def _shadow_overlay(size: tuple, center_x: float, rim_y: float, strength: float = 60):
    """Мягкая тень формы на корзине — отдельный полупрозрачный overlay,
    product mask не затрагивает."""
    from PIL import Image, ImageDraw, ImageFilter

    fx = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(fx)
    rx, ry = 150, 26
    d.ellipse((center_x - rx, rim_y - ry, center_x + rx, rim_y + ry),
             fill=(0, 0, 0, int(strength)))
    return fx.filter(ImageFilter.GaussianBlur(14))


def _variant_transform(spec: dict, product_size: tuple) -> "RigidTransform":
    w, h = product_size
    scale = spec["scale"]
    disp_w, disp_h = w * scale, h * scale
    x0 = BASKET_CENTER_X - disp_w / 2 + spec["dx"]
    y0 = spec["bottom_y"] - disp_h
    return RigidTransform(scale=scale, rotation_deg=spec["rotation_deg"],
                          translate=(x0, y0))


def _watermark_baseplate(img):
    from PIL import ImageDraw, ImageFont
    img = img.copy()
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", max(18, img.width // 22))
    except OSError:
        font = ImageFont.load_default()
    draw.text((14, img.height - max(34, img.width // 16)), "TEST PREVIEW",
             fill=(255, 255, 255, 210), font=font)
    return img


def cmd_baseplate(args) -> int:
    product, _mask, handles = load_view(args.view, args.repo_root)
    background = _load_real_image(REAL_BACKGROUND)
    canvas_size = background.size

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    variants_report = {}
    frame_images = []
    for key, spec in BASEPLATE_VARIANTS.items():
        transform = _variant_transform(spec, product.size)
        shadow = _shadow_overlay(canvas_size, BASKET_CENTER_X,
                                 spec["bottom_y"] + 6)
        layers = SceneLayers(background=background, product=product,
                             product_transform=transform,
                             effects=[shadow], handle_masks=handles)
        result = compose(layers, validate=True)
        frame = result["image"].convert("RGB")
        frame = _watermark_baseplate(frame)
        path = out / f"baseplate-{key}.png"
        frame.save(path)
        frame_images.append((key, path))

        handle_canvas = result["handle_masks_canvas"]
        handle_screen_bbox = {}
        for side, hm in handle_canvas.items():
            bbox = hm.getbbox()
            handle_screen_bbox[side] = list(bbox) if bbox else None

        variants_report[key] = {
            "label": spec["label"],
            "path": str(path),
            "transform": {"scale": transform.scale,
                          "rotation_deg": transform.rotation_deg,
                          "translate": list(transform.translate),
                          "perspective": transform.perspective},
            "validation": result["validation"],
            "handle_screen_bbox": handle_screen_bbox,
        }

    # контактный лист A/B/C
    from PIL import Image, ImageDraw, ImageFont
    thumb_w = 360
    pad, label_h = 20, 40
    thumbs = []
    for key, path in frame_images:
        im = Image.open(path)
        h = round(im.height * thumb_w / im.width)
        thumbs.append((key, im.resize((thumb_w, h))))
    max_h = max(t.height for _, t in thumbs)
    sheet = Image.new("RGB", (pad + len(thumbs) * (thumb_w + pad),
                              pad + label_h + max_h + pad), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    x = pad
    for key, im in thumbs:
        d.text((x, pad), key, fill=(255, 200, 60), font=font)
        sheet.paste(im, (x, pad + label_h))
        x += thumb_w + pad
    contact_sheet_path = out / "contact-sheet-ABC.png"
    sheet.save(contact_sheet_path)

    all_passed = all(v["validation"]["passed"] for v in variants_report.values())
    report = {
        "scene_id": "scene-05",
        "stage": "real_baseplate",
        "canonical_version": "real-product-v1",
        "product_view": args.view,
        "background_source": REAL_BACKGROUND,
        "canvas_size": list(canvas_size),
        "variants": variants_report,
        "contact_sheet": str(contact_sheet_path),
        "all_variants_passed_product_lock": all_passed,
        "no_hands_no_food_no_steam_no_animation": True,
        "images_api_calls": 0,
        "animation_api_calls": 0,
    }
    (out / "baseplate-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"saved": str(out), "all_passed": all_passed,
                      "variants": {k: v["validation"]["passed"]
                                  for k, v in variants_report.items()}},
                     ensure_ascii=False, indent=2))
    return 0 if all_passed else 2


def cmd_extract(args) -> int:
    manifest = build_asset_pack(args.repo_root)
    print(json.dumps({"pack": "built (LEGACY forma_6angles.png — устарело)",
                      "views": sorted(manifest["assets"]),
                      "requires_real_photo": manifest["requires_real_photo"]},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_extract_real(args) -> int:
    crops = build_real_master_crops(args.repo_root)
    manifest = build_real_asset_pack(args.repo_root)
    print(json.dumps({
        "canonical_version": manifest["canonical_version"],
        "canonical_status": manifest["canonical_status"],
        "master_crops": [e["name"] for e in crops["entries"]],
        "active_views": sorted(manifest["assets"]),
        "legacy_views_blocked": sorted(manifest["legacy_assets"]),
        "requires_real_photo": manifest["requires_real_photo"],
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_preview(args) -> int:
    product, _mask, handles = load_view(args.view, args.repo_root)
    canvas = (args.width, round(args.width * 16 / 9))
    # товар ~70% ширины кадра, стартует над корзиной
    start_scale = canvas[0] * 0.72 / product.width
    x0 = (canvas[0] - product.width * start_scale) / 2
    start = RigidTransform(scale=start_scale, translate=(x0, canvas[1] * 0.42))
    # медленно вверх и чуть назад (лёгкое уменьшение), очень малая rotation
    end = RigidTransform(scale=start_scale * 0.97, rotation_deg=-1.5,
                         translate=(x0 + canvas[0] * 0.012, canvas[1] * 0.30))
    plan = RigidAnimationPlan(
        duration_s=args.duration, fps=args.fps,
        keyframes=[(0.0, start), (1.0, end)],
        camera="static",
        notes="scene-05 rigid test: подъём формы вверх и немного назад; "
              "корзина неподвижна; пар отдельным overlay; руки появятся "
              "после реальных фото (occlusion-маски)")
    layers = SceneLayers(
        background=_placeholder_background(canvas),
        product=product, product_transform=start,
        effects=[_steam_overlay(canvas)],
        handle_masks=handles)
    report = render_preview(plan, layers, args.out, size=(540, 960),
                            watermark=True)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m api.media_pipeline.compositor.cli",
                                description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("extract", help="LEGACY: пересобрать пакет из forma_6angles.png")
    e.add_argument("--repo-root", default=".")
    e.set_defaults(fn=cmd_extract)

    er = sub.add_parser("extract-real",
                        help="пересобрать real-product-v1 (реальные фото/видео)")
    er.add_argument("--repo-root", default=".")
    er.set_defaults(fn=cmd_extract_real)

    v = sub.add_parser("preview", help="rigid animation preview (локально)")
    v.add_argument("--repo-root", default=".")
    v.add_argument("--view", default=DEFAULT_VIEW)
    v.add_argument("--out", required=True)
    v.add_argument("--width", type=int, default=540)
    v.add_argument("--duration", type=float, default=4.5)
    v.add_argument("--fps", type=int, default=12)
    v.set_defaults(fn=cmd_preview)

    bp = sub.add_parser("baseplate",
                        help="статичный real base plate scene-05 (A/B/C)")
    bp.add_argument("--repo-root", default=".")
    bp.add_argument("--view", default=DEFAULT_VIEW)
    bp.add_argument("--out", required=True)
    bp.set_defaults(fn=cmd_baseplate)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
