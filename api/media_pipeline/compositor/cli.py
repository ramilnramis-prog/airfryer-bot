"""CLI product-locked compositing (всё локально, сети нет вообще).

Команды:
  extract  — построить/перестроить product asset pack из forma_6angles.png
  preview  — тестовый rigid-animation preview scene-05 (плейсхолдер-фон,
             канонический product layer, watermark TEST PREVIEW)
  validate <frame.png> — проверить кадр против канона (нужны transform-параметры)
"""
from __future__ import annotations

import argparse
import json
import sys

from .perspective import RigidTransform
from .product_assets import build_asset_pack, load_view
from .layer_compositor import SceneLayers
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


def cmd_extract(args) -> int:
    manifest = build_asset_pack(args.repo_root)
    print(json.dumps({"pack": "built",
                      "views": sorted(manifest["assets"]),
                      "requires_real_photo": manifest["requires_real_photo"]},
                     ensure_ascii=False, indent=2))
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

    e = sub.add_parser("extract", help="построить product asset pack")
    e.add_argument("--repo-root", default=".")
    e.set_defaults(fn=cmd_extract)

    v = sub.add_parser("preview", help="rigid animation preview (локально)")
    v.add_argument("--repo-root", default=".")
    v.add_argument("--view", default="three_quarter_45")
    v.add_argument("--out", required=True)
    v.add_argument("--width", type=int, default=540)
    v.add_argument("--duration", type=float, default=4.5)
    v.add_argument("--fps", type=int, default=12)
    v.set_defaults(fn=cmd_preview)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
