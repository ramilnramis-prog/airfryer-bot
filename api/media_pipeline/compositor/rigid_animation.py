"""Rigid animation: движение товара как единого твёрдого объекта.

Никакого image-to-video морфинга товара: каждый кадр — заново собранная
композиция, где product layer получает интерполированный RigidTransform.
Форма и ручки не меняют ни одного пикселя, кроме глобальной трансформации.
Preview рендерится локально (Pillow + ffmpeg через imageio) без платных API.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .layer_compositor import SceneLayers, compose
from .perspective import RigidTransform, interpolate
from .product_lock_validator import assert_valid


@dataclass
class RigidAnimationPlan:
    duration_s: float = 4.5
    fps: int = 12
    # ключевые трансформации товара: (время 0..1, RigidTransform)
    keyframes: list = field(default_factory=list)
    # руки двигаются синхронно с товаром (то же смещение)
    hands_follow_product: bool = True
    camera: str = "static"          # static | minimal_push_in
    notes: str = ""

    def frame_count(self) -> int:
        return max(2, round(self.duration_s * self.fps))

    def transform_at(self, u: float) -> RigidTransform:
        kfs = sorted(self.keyframes, key=lambda k: k[0])
        if not kfs:
            return RigidTransform()
        if u <= kfs[0][0]:
            return kfs[0][1]
        for (t0, tr0), (t1, tr1) in zip(kfs, kfs[1:]):
            if t0 <= u <= t1:
                local = (u - t0) / (t1 - t0) if t1 > t0 else 0.0
                return interpolate(tr0, tr1, local)
        return kfs[-1][1]

    def to_dict(self) -> dict:
        return {"duration_s": self.duration_s, "fps": self.fps,
                "camera": self.camera,
                "hands_follow_product": self.hands_follow_product,
                "notes": self.notes,
                "keyframes": [
                    {"t": t, "scale": tr.scale, "rotation_deg": tr.rotation_deg,
                     "translate": list(tr.translate),
                     "perspective": tr.perspective}
                    for t, tr in sorted(self.keyframes, key=lambda k: k[0])]}


def _watermark(img, text="TEST PREVIEW"):
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", max(16, img.width // 18))
    except OSError:
        font = ImageFont.load_default()
    draw.text((12, img.height - max(30, img.width // 14)), text,
              fill=(255, 255, 255, 180), font=font)
    return img


def render_preview(plan: RigidAnimationPlan, base_layers: SceneLayers,
                   out_dir: str | Path, size: tuple = (540, 960),
                   watermark: bool = True, validate_frames: bool = True,
                   write_mp4: bool = True) -> dict:
    """Технический preview 9:16: кадры + mp4. Каждый кадр проходит
    product-lock validation. Никакой сети."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    n = plan.frame_count()
    validations = []
    frame_paths = []
    for i in range(n):
        u = i / (n - 1)
        layers = SceneLayers(
            background=base_layers.background,
            product=base_layers.product,
            product_transform=plan.transform_at(u),
            back_hand=base_layers.back_hand,
            front_hand=base_layers.front_hand,
            effects=list(base_layers.effects),
            handle_masks=dict(base_layers.handle_masks))
        result = compose(layers, validate=validate_frames)
        if validate_frames:
            assert_valid(result["validation"])
            validations.append({"frame": i,
                                "passed": result["validation"]["passed"]})
        frame = result["image"].convert("RGB").resize(size)
        if watermark:
            frame = _watermark(frame)
        p = out / f"frame-{i:04d}.png"
        frame.save(p)
        frame_paths.append(p)

    video_path = None
    if write_mp4:
        import imageio.v3 as iio
        import numpy as np
        frames = [iio.imread(p) for p in frame_paths]
        video_path = out / "preview.mp4"
        iio.imwrite(video_path, np.stack(frames), fps=plan.fps,
                    plugin="pyav", codec="libx264")
    report = {"frames": n, "size": list(size), "fps": plan.fps,
              "duration_s": plan.duration_s,
              "all_frames_validated": validate_frames,
              "validations_passed": all(v["passed"] for v in validations)
              if validations else None,
              "video": str(video_path) if video_path else None,
              "plan": plan.to_dict()}
    (out / "preview-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
