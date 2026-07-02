"""Product asset pack: извлечение и загрузка канонических слоёв товара.

Источник — ТОЛЬКО канонический референс forma_6angles.png (6 ракурсов на
белом фоне). Ничего не дорисовываем: если ракурса нет в источнике, он
помечается requires_real_photo в манифесте.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

CANONICAL_SOURCE = Path("D:/OzonGrowthProject/content/assets/forma_6angles.png")
SECONDARY_SOURCE = Path("D:/OzonGrowthProject/content/assets/02_master_keyframe_REAL.png")
PACK_DIR = Path("assets/product-lock/airfryer-silicone-form")

# Панели сетки 2x3 источника (нормализованные bbox) и что на них.
PANELS = {
    "three_quarter_high": (0.00, 0.00, 0.50, 0.333),   # 3/4 сверху, задняя ручка видна
    "top": (0.50, 0.00, 1.00, 0.333),                  # строго сверху, обе ручки
    "side": (0.00, 0.334, 0.50, 0.666),                # сбоку, обе ручки в профиль
    "bottom": (0.50, 0.334, 1.00, 0.666),              # дно (ручки в профиль по бокам)
    "three_quarter_45": (0.00, 0.667, 0.50, 1.00),     # ~45°, обе ручки видны
    "three_quarter_45b": (0.50, 0.667, 1.00, 1.00),    # ~45° другой угол
}

# Луминанс ниже порога = пиксель товара (фон источника — белый).
PRODUCT_LUMA_THRESHOLD = 200

# Регионы ручек ВНУТРИ каждого извлечённого вида (нормализованные bbox по
# обрезанному изображению вида). Подобраны по канону.
HANDLE_REGIONS = {
    "top": {"left": (0.00, 0.25, 0.18, 0.80), "right": (0.82, 0.25, 1.00, 0.80)},
    "three_quarter_45": {"left": (0.00, 0.10, 0.22, 0.55),
                         "right": (0.78, 0.05, 1.00, 0.50)},
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _require_pil():
    try:
        from PIL import Image, ImageFilter  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "compositor требует Pillow и numpy (pip install pillow numpy); "
            "сеть/платные API не используются") from e


def extract_view(source_img, panel_bbox: tuple):
    """Возвращает (rgba, mask) вида: товар с прозрачным фоном + маска L.

    Прозрачны и фон, и сквозные вырезы ручек (через них виден белый фон
    источника) — вырезы остаются настоящими дырами, как у товара.
    """
    _require_pil()
    from PIL import Image, ImageFilter
    import numpy as np

    w, h = source_img.size
    x0, y0, x1, y1 = panel_bbox
    panel = source_img.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)))
    rgb = np.asarray(panel.convert("RGB"), dtype=np.float32)
    luma = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    mask = (luma < PRODUCT_LUMA_THRESHOLD).astype(np.uint8) * 255
    mask_img = Image.fromarray(mask, "L").filter(ImageFilter.MedianFilter(5))
    mask = np.asarray(mask_img)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise ValueError("товар не найден в панели — проверьте порог/панель")
    pad = 6
    bx0, bx1 = max(0, xs.min() - pad), min(panel.width, xs.max() + pad)
    by0, by1 = max(0, ys.min() - pad), min(panel.height, ys.max() + pad)
    panel = panel.crop((bx0, by0, bx1, by1))
    mask_img = mask_img.crop((bx0, by0, bx1, by1))
    rgba = panel.convert("RGBA")
    rgba.putalpha(mask_img)
    return rgba, mask_img


def handle_masks_for_view(view_name: str, mask_img):
    """Маски левой/правой ручки вида: product mask ∧ регион ручки."""
    _require_pil()
    from PIL import Image
    import numpy as np

    regions = HANDLE_REGIONS.get(view_name)
    if not regions:
        return {}
    m = np.asarray(mask_img)
    h, w = m.shape
    out = {}
    for side, (x0, y0, x1, y1) in regions.items():
        region = np.zeros_like(m)
        region[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)] = 255
        out[side] = Image.fromarray(np.minimum(m, region), "L")
    return out


def build_asset_pack(repo_root: str | Path = ".") -> dict:
    """Строит воспроизводимый product asset pack из канонического источника.
    Возвращает манифест (и пишет его на диск). Без сети, без платных API."""
    _require_pil()
    from PIL import Image

    root = Path(repo_root)
    pack = root / PACK_DIR
    for sub in ("source", "isolated", "masks", "handles",
                "perspective-guides", "validation"):
        (pack / sub).mkdir(parents=True, exist_ok=True)

    src = Image.open(CANONICAL_SOURCE)
    assets = {}
    for view, bbox in PANELS.items():
        rgba, mask = extract_view(src, bbox)
        iso = pack / "isolated" / f"form_{view}.png"
        msk = pack / "masks" / f"form_{view}_mask.png"
        rgba.save(iso)
        mask.save(msk)
        entry = {"isolated": str(iso.relative_to(root)),
                 "mask": str(msk.relative_to(root)),
                 "size": list(rgba.size),
                 "sha256_isolated": sha256_file(iso),
                 "sha256_mask": sha256_file(msk)}
        hm = handle_masks_for_view(view, mask)
        for side, img in hm.items():
            p = pack / "masks" / f"form_{view}_handle_{side}_mask.png"
            img.save(p)
            entry[f"handle_{side}_mask"] = str(p.relative_to(root))
            entry[f"sha256_handle_{side}_mask"] = sha256_file(p)
            # крупный crop ручки (upscale x2) для сравнения силуэтов
            import numpy as np
            m = np.asarray(img)
            ys, xs = np.nonzero(m)
            if len(xs):
                pad2 = 10
                box = (max(0, xs.min() - pad2), max(0, ys.min() - pad2),
                       min(rgba.width, xs.max() + pad2),
                       min(rgba.height, ys.max() + pad2))
                crop = rgba.crop(box)
                crop = crop.resize((crop.width * 2, crop.height * 2),
                                   Image.LANCZOS)
                cp = pack / "handles" / f"handle_{view}_{side}_x2.png"
                crop.save(cp)
                entry[f"handle_{side}_crop"] = str(cp.relative_to(root))
                entry[f"sha256_handle_{side}_crop"] = sha256_file(cp)
        assets[view] = entry

    manifest = {
        "product_code": "airfryer-silicone-form",
        "pack_version": 1,
        "canonical_source": {
            "path": str(CANONICAL_SOURCE),
            "sha256": sha256_file(CANONICAL_SOURCE),
            "note": "единственный источник пикселей товара; ничего не дорисовано",
        },
        "secondary_source_candidate": {
            "path": str(SECONDARY_SOURCE),
            "sha256": (sha256_file(SECONDARY_SOURCE)
                       if SECONDARY_SOURCE.is_file() else None),
            "status": "not_extracted",
            "note": "кадр '02_master_keyframe_REAL' прошлой кампании: геометрия "
                    "ручек совпадает с каноном, но происхождение (реальное фото "
                    "или рендер) должен подтвердить владелец до использования",
        },
        "extraction": {"threshold_luma": PRODUCT_LUMA_THRESHOLD,
                       "tool": "api.media_pipeline.compositor.product_assets",
                       "reproduce": "python -m api.media_pipeline.compositor.cli extract"},
        "assets": assets,
        "handles_reference_crop": {
            "path": "assets/visual-bible/airfryer-silicone-form/references/handles_reference_crop.png",
            "sha256": sha256_file(root / "assets/visual-bible/airfryer-silicone-form/references/handles_reference_crop.png"),
        },
        "requires_real_photo": [
            "форма с ЕДОЙ внутри (product layer сцен 4-5) — из forma_6angles не получить, не дорисовываем",
            "фронтальный ракурс на уровне глаз (medium shot scene-05)",
            "форма в корзине аэрогриля (scene-03/04)",
            "реальный аэрогриль владельца: спереди и с выдвинутой корзиной",
            "женские руки владельца, держащие форму за обе ручки",
        ],
    }
    (pack / "product_asset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def load_manifest(repo_root: str | Path = ".") -> dict:
    return json.loads((Path(repo_root) / PACK_DIR /
                       "product_asset_manifest.json").read_text(encoding="utf-8"))


def load_view(view: str, repo_root: str | Path = ".", verify: bool = True):
    """Возвращает (rgba, mask, handle_masks: {side: Image}) канонического вида.
    verify=True сверяет SHA256 с манифестом (защита от подмены ассета)."""
    _require_pil()
    from PIL import Image

    root = Path(repo_root)
    entry = load_manifest(root)["assets"][view]
    iso, msk = root / entry["isolated"], root / entry["mask"]
    if verify:
        if sha256_file(iso) != entry["sha256_isolated"]:
            raise ValueError(f"asset подменён: {iso}")
        if sha256_file(msk) != entry["sha256_mask"]:
            raise ValueError(f"mask подменена: {msk}")
    handles = {}
    for side in ("left", "right"):
        key = f"handle_{side}_mask"
        if key in entry:
            p = root / entry[key]
            if verify and sha256_file(p) != entry[f"sha256_{key}"]:
                raise ValueError(f"handle mask подменена: {p}")
            handles[side] = Image.open(p).convert("L")
    return Image.open(iso).convert("RGBA"), Image.open(msk).convert("L"), handles
