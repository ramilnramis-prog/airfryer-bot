"""real-product-v1: канонический пакет ассетов из РЕАЛЬНЫХ фото/видео товара.

Решение владельца (2026-07-03): реальные фото и видео товара — единственный
источник истины для физической геометрии силиконовой формы. Прежний
AI-канон (forma_6angles.png / handles_reference_crop.png) выведен из
активного QA геометрии — см. legacy_sources в манифесте.

Источник (ВНЕ этого репозитория, только для чтения):
  D:/OzonGrowthProject/content/assets/real-product-reference-shoot/
  airfryer-silicone-form/raw/

Геометрия ручек по реальным фото (замена прежнего "прямая вытянутая ручка
с вертикальным овальным вырезом"):
- плоский угловой боковой язычок, почти вровень с верхней кромкой стенки
  (НЕ высокая ручка-петля, поднимающаяся над кромкой);
- короткая ГОРИЗОНТАЛЬНАЯ прямоугольная/скруглённая прорезь
  (НЕ вертикальный вытянутый овал);
- левая и правая ручки определяются ТОЛЬКО реальными фото (photo_7 primary).

Сегментация в этом модуле — РУЧНАЯ разметка полигонов по видимым фото
(проверено визуальным наложением контура на исходник), НЕ ML-сегментация и
НЕ генеративное восстановление: только вырезка существующих пикселей по
границе, которую человек сверил с фотографией. Точность полигонов —
приблизительная (допуск ~10-15 px), это явно документируется в provenance
каждого ассета.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

CANONICAL_VERSION = "real-product-v1"
RAW_DIR = Path("D:/OzonGrowthProject/content/assets/real-product-reference-shoot/"
              "airfryer-silicone-form/raw")
VIDEO_PATH = RAW_DIR / "IMG_5925.MOV"
VIDEO_FPS = 2997 / 100  # из av-пробы контейнера (29.97 fps, 999 кадров, 33.33s)

PACK_DIR = Path("assets/product-lock/airfryer-silicone-form")
REAL_V1_DIR = PACK_DIR / "references" / "real-v1"

# -- master crops (ШАГ 4): ТОЛЬКО кадрирование + размер, без масок -----------
# (name, source_filename, bbox_px, category, purpose)
MASTER_CROPS = [
    ("product_full_master", "photo_2_2026-06-18_16-53-42.jpg", (60, 300, 910, 1030),
     "product", "дополнительный полный вид формы, 3/4 спереди"),
    ("product_45deg_master", "photo_7_2026-06-18_16-53-42.jpg", (60, 330, 920, 1030),
     "product", "ОСНОВНОЙ 3/4 ракурс (PRIMARY): обе ручки видны целиком"),
    ("product_top_master", "photo_3_2026-06-18_16-53-42.jpg", (60, 300, 850, 1040),
     "product", "вид строго сверху, обе ручки в профиль"),
    ("left_handle_master", "photo_7_2026-06-18_16-53-42.jpg", (150, 360, 340, 500),
     "handles", "левая ручка крупно (источник PRIMARY photo_7)"),
    ("right_handle_master", "photo_7_2026-06-18_16-53-42.jpg", (790, 570, 920, 760),
     "handles", "правая ручка крупно (источник PRIMARY photo_7)"),
    ("both_handles_master", "photo_7_2026-06-18_16-53-42.jpg", (60, 330, 920, 1030),
     "handles", "обе ручки в одном кадре — геометрический контекст"),
    ("bottom_loop_master", "photo_5_2026-06-18_16-53-42.jpg", (250, 370, 800, 820),
     "bottom", "круглая петля-держатель по центру дна"),
]

# -- video frames (ШАГ 5): чистая покадровая экстракция, без генерации -------
# (name, frame_index, category, purpose)
VIDEO_FRAMES = [
    ("airfryer_front_master", 865, "airfryer",
     "фронтальный канон реального аэрогриля DE'MIAND (панель управления и "
     "бренд читаются полностью) — замена AI place.png по решению владельца"),
    ("clean_basket_master", 998, "airfryer",
     "чистый пустой родной лоток аэрогриля — референс для scene-06"),
    ("product_in_basket_master", 931, "motion",
     "форма внутри родного лотка аэрогриля — референс для scene-03/04/05"),
    ("grip_motion_master", 665, "motion",
     "механика захвата одной рукой сверху — ТОЛЬКО motion/grip reference; "
     "рука мужская, НЕ финальный hand canon кампании"),
]

# -- полигоны для сборки product-lock пакета (ШАГ 6) -------------------------
# Ручная разметка, сверенная наложением контура на фото (см. scratchpad
# trace_overlay_v1.png / trace_overlay_photo3.png в истории сессии).
POLY_VIEWS = {
    "product_45deg": {
        "source": "photo_7_2026-06-18_16-53-42.jpg",
        "body_polygon": [
            (175, 460), (175, 400), (230, 383), (310, 392),
            (450, 350), (620, 365), (760, 400), (830, 460),
            (888, 655), (888, 705), (845, 755), (835, 890),
            (500, 968), (145, 930), (95, 680),
        ],
        "handle_regions": {
            "left": (172, 383, 312, 472),
            "right": (818, 590, 900, 745),
        },
        "handle_holes": {
            "left": [(200, 405), (272, 400), (275, 432), (202, 436)],
        },
    },
    "product_top": {
        "source": "photo_3_2026-06-18_16-53-42.jpg",
        "body_polygon": [
            (155, 400), (400, 332), (600, 340), (730, 400),
            (730, 480), (820, 480), (820, 660), (730, 660),
            (770, 880), (650, 1015), (300, 1015), (130, 880),
            (90, 660), (90, 480), (155, 480),
        ],
        "handle_regions": {
            "left": (85, 478, 160, 665),
            "right": (728, 478, 822, 665),
        },
        "handle_holes": {
            "left": [(105, 520), (140, 520), (140, 620), (105, 620)],
            "right": [(770, 520), (805, 520), (805, 620), (770, 620)],
        },
    },
}

# -- легаси-источники, выведенные из активного QA геометрии (ШАГ 2) ---------
LEGACY_SOURCES = [
    {"path": "D:/OzonGrowthProject/content/assets/forma_6angles.png",
     "status": "legacy_incorrect_product_geometry",
     "allowed_for_product_geometry_qa": False,
     "allowed_for_product_lock_source": False,
     "allowed_for_style_reference": False,
     "reason": "does not match the real sold product handle construction "
               "(tall vertical loop handle with elongated vertical oval "
               "cut-out vs real flat corner tab with short horizontal slot)"},
    {"path": "assets/visual-bible/airfryer-silicone-form/references/handles_reference_crop.png",
     "status": "legacy_incorrect_product_geometry",
     "allowed_for_product_geometry_qa": False,
     "allowed_for_product_lock_source": False,
     "allowed_for_style_reference": False,
     "reason": "derived entirely from forma_6angles.png — same incorrect "
               "handle geometry"},
    {"path": "D:/OzonGrowthProject/content/assets/real-product-reference-shoot/"
             "airfryer-silicone-form/raw/cta.png",
     "status": "legacy_incorrect_product_geometry",
     "allowed_for_product_geometry_qa": False,
     "allowed_for_product_lock_source": False,
     "allowed_for_style_reference": "фон/свет кухни допустимо, если не "
                                    "утверждается как геометрия товара",
     "reason": "AI-рендер прошлой кампании (byte-identical to "
               "video2-formaad/cta.png), not a real photo"},
    {"path": "D:/OzonGrowthProject/content/assets/real-product-reference-shoot/"
             "airfryer-silicone-form/raw/shot2_reveal.png",
     "status": "legacy_incorrect_product_geometry",
     "allowed_for_product_geometry_qa": False,
     "allowed_for_product_lock_source": False,
     "allowed_for_style_reference": False,
     "reason": "AI-рендер прошлой кампании: та же неверная вытянуто-овальная "
               "геометрия ручек, которую отклонил владелец"},
    {"path": "D:/OzonGrowthProject/content/assets/real-product-reference-shoot/"
             "airfryer-silicone-form/raw/shot3_place.png",
     "status": "legacy_incorrect_product_geometry",
     "allowed_for_product_geometry_qa": False,
     "allowed_for_product_lock_source": False,
     "allowed_for_style_reference": False,
     "reason": "AI-рендер прошлой кампании: неверная геометрия ручек + "
               "кольцо на руке (нарушает правило 'без украшений')"},
]


def sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_pil():
    try:
        from PIL import Image  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "real_product_assets требует Pillow и numpy; "
            "сеть/платные API не используются") from e


def _video_frame(index: int):
    """Детерминированная покадровая экстракция (без генерации, без сети)."""
    import av
    c = av.open(str(VIDEO_PATH))
    stream = c.streams.video[0]
    for i, frame in enumerate(c.decode(stream)):
        if i == index:
            return frame.to_image()
    raise ValueError(f"кадр {index} не найден в {VIDEO_PATH}")


def build_real_master_crops(repo_root: str | Path = ".") -> dict:
    """ШАГ 4: копирует ТОЛЬКО отобранные master reference crops (кадрирование
    + размер, без масок, без генерации) в references/real-v1/*, с полным
    provenance на каждый файл."""
    _require_pil()
    from PIL import Image

    root = Path(repo_root)
    entries = []

    for name, src_name, bbox, category, purpose in MASTER_CROPS:
        src_path = RAW_DIR / src_name
        out_dir = root / REAL_V1_DIR / category
        out_dir.mkdir(parents=True, exist_ok=True)
        im = Image.open(src_path).convert("RGB")
        crop = im.crop(bbox)
        out_path = out_dir / f"{name}.png"
        crop.save(out_path)
        entries.append({
            "name": name,
            "path": str((REAL_V1_DIR / category / f"{name}.png")).replace("\\", "/"),
            "source_filename": src_name,
            "source_sha256": sha256_file(src_path),
            "derivative_sha256": sha256_file(out_path),
            "crop_coordinates": list(bbox),
            "source_type": "photo",
            "timestamp": None,
            "purpose": purpose,
            "approved": True,
            "canonical_version": CANONICAL_VERSION,
        })

    for name, frame_idx, category, purpose in VIDEO_FRAMES:
        out_dir = root / REAL_V1_DIR / category
        out_dir.mkdir(parents=True, exist_ok=True)
        img = _video_frame(frame_idx)
        out_path = out_dir / f"{name}.png"
        img.save(out_path)
        entries.append({
            "name": name,
            "path": str((REAL_V1_DIR / category / f"{name}.png")).replace("\\", "/"),
            "source_filename": "IMG_5925.MOV",
            "source_sha256": sha256_file(VIDEO_PATH),
            "derivative_sha256": sha256_file(out_path),
            "crop_coordinates": None,
            "source_type": "video_frame",
            "frame_index": frame_idx,
            "timestamp": round(frame_idx / VIDEO_FPS, 3),
            "purpose": purpose,
            "approved": True,
            "canonical_version": CANONICAL_VERSION,
        })

    manifest = {
        "canonical_version": CANONICAL_VERSION,
        "canonical_source_type": "real_photography",
        "canonical_status": "active",
        "video_fps": VIDEO_FPS,
        "entries": entries,
    }
    (root / REAL_V1_DIR / "real_v1_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _build_masked_view(view_name: str, spec: dict, repo_root: Path):
    """Полигон -> RGBA isolate + product mask + handle sub-masks, обрезка по
    bbox полигона (с отступом). Пиксели — только из исходного фото."""
    from PIL import Image, ImageDraw
    import numpy as np

    src_path = RAW_DIR / spec["source"]
    im = Image.open(src_path).convert("RGB")
    poly = spec["body_polygon"]
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    pad = 12
    x0, y0 = max(0, min(xs) - pad), max(0, min(ys) - pad)
    x1, y1 = min(im.width, max(xs) + pad), min(im.height, max(ys) + pad)

    full_mask = Image.new("L", im.size, 0)
    d = ImageDraw.Draw(full_mask)
    d.polygon(poly, fill=255)
    for hole in spec.get("handle_holes", {}).values():
        d.polygon(hole, fill=0)

    crop_im = im.crop((x0, y0, x1, y1))
    crop_mask = full_mask.crop((x0, y0, x1, y1))
    rgba = crop_im.convert("RGBA")
    rgba.putalpha(crop_mask)

    handle_masks = {}
    mask_arr = np.asarray(crop_mask)
    for side, (hx0, hy0, hx1, hy1) in spec.get("handle_regions", {}).items():
        region = np.zeros_like(mask_arr)
        rx0, ry0 = max(0, hx0 - x0), max(0, hy0 - y0)
        rx1, ry1 = min(crop_mask.width, hx1 - x0), min(crop_mask.height, hy1 - y0)
        region[ry0:ry1, rx0:rx1] = 255
        handle_masks[side] = Image.fromarray(np.minimum(mask_arr, region), "L")

    return rgba, crop_mask, handle_masks, src_path


def build_real_asset_pack(repo_root: str | Path = ".") -> dict:
    """ШАГ 6: пересобирает product_asset_manifest.json ТОЛЬКО из
    real-product-v1. Старые (forma_6angles.png-производные) записи не
    удаляются физически — переносятся в legacy_assets с явными флагами
    allowed_for_product_geometry_qa=false / allowed_for_product_lock_source=false,
    чтобы load_view() не мог случайно на них откатиться."""
    _require_pil()

    root = Path(repo_root)
    pack_dir = root / PACK_DIR
    old_manifest_path = pack_dir / "product_asset_manifest.json"
    old_manifest = (json.loads(old_manifest_path.read_text(encoding="utf-8"))
                    if old_manifest_path.is_file() else {})
    legacy_assets = old_manifest.get("assets", {})
    for entry in legacy_assets.values():
        entry["status"] = "legacy_incorrect_product_geometry"
        entry["allowed_for_product_geometry_qa"] = False
        entry["allowed_for_product_lock_source"] = False

    active_assets = {}
    pool_dir = pack_dir / "references" / "real-v1" / "product" / "pack"
    pool_dir.mkdir(parents=True, exist_ok=True)

    for view_name, spec in POLY_VIEWS.items():
        rgba, mask, handle_masks, src_path = _build_masked_view(view_name, spec, root)
        iso_p = pool_dir / f"{view_name}_isolated.png"
        mask_p = pool_dir / f"{view_name}_mask.png"
        rgba.save(iso_p)
        mask.save(mask_p)
        entry = {
            "isolated": str(iso_p.relative_to(root)).replace("\\", "/"),
            "mask": str(mask_p.relative_to(root)).replace("\\", "/"),
            "size": list(rgba.size),
            "sha256_isolated": sha256_file(iso_p),
            "sha256_mask": sha256_file(mask_p),
            "source_filename": spec["source"],
            "source_sha256": sha256_file(RAW_DIR / spec["source"]),
            "source_type": "photo",
            "canonical_version": CANONICAL_VERSION,
            "status": "active",
            "allowed_for_product_geometry_qa": True,
            "allowed_for_product_lock_source": True,
        }
        for side, hmask in handle_masks.items():
            hp = pool_dir / f"{view_name}_handle_{side}_mask.png"
            hmask.save(hp)
            entry[f"handle_{side}_mask"] = str(hp.relative_to(root)).replace("\\", "/")
            entry[f"sha256_handle_{side}_mask"] = sha256_file(hp)
        active_assets[view_name] = entry

    manifest = {
        "product_code": "airfryer-silicone-form",
        "pack_version": 2,
        "canonical_version": CANONICAL_VERSION,
        "canonical_source_type": "real_photography",
        "canonical_status": "active",
        "canonical_source": {
            "primary": "photo_7_2026-06-18_16-53-42.jpg",
            "primary_sha256": sha256_file(RAW_DIR / "photo_7_2026-06-18_16-53-42.jpg"),
            "supplementary": ["photo_1_2026-06-18_16-53-42.jpg",
                             "photo_2_2026-06-18_16-53-42.jpg",
                             "photo_3_2026-06-18_16-53-42.jpg"],
            "bottom_center_loop": ["photo_5_2026-06-18_16-53-42.jpg",
                                  "photo_6_2026-06-18_16-53-42.jpg"],
            "raw_dir": str(RAW_DIR),
            "note": "Реальные фото имеют безусловный приоритет над любыми "
                    "AI-рендерами. Полигоны сегментации — ручная разметка, "
                    "сверенная визуальным наложением на фото (не ML, не "
                    "генеративное восстановление); допуск ~10-15px.",
        },
        "handle_geometry_real": {
            "outer_silhouette": "плоский угловой боковой язычок, почти "
                                "вровень с верхней кромкой стенки",
            "cutout": "короткая горизонтальная прямоугольная/скруглённая "
                      "прорезь",
            "forbidden_legacy_shape": "высокая вертикальная ручка-петля с "
                                     "вытянутым вертикальным овальным "
                                     "вырезом — OBSOLETE, не соответствует "
                                     "реальному товару",
            "source": "photo_7_2026-06-18_16-53-42.jpg (PRIMARY)",
        },
        "legacy_sources": LEGACY_SOURCES,
        "extraction": {
            "tool": "api.media_pipeline.compositor.real_product_assets",
            "reproduce": "python -m api.media_pipeline.compositor.cli extract-real",
            "method": "manual polygon annotation verified against source photo "
                      "(overlay comparison), crop-only, no generative fill",
        },
        "assets": active_assets,
        "legacy_assets": legacy_assets,
        "requires_real_photo": [
            "форма с ЕДОЙ внутри (product layer сцен 4-5)",
            "женские руки без украшений, держащие форму за обе ручки "
            "(текущий видеосет содержит только мужскую руку)",
            "фронтальный ракурс на уровне глаз (medium shot scene-05)",
        ],
    }
    old_manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
