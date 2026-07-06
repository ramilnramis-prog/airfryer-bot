"""Fail-closed валидация PNG mask-файла для OpenAI Images Edit API.

Официальный контракт (POST /v1/images/edits, gpt-image-2):
- mask — PNG с alpha-каналом;
- mask имеет ТЕ ЖЕ width/height, что и первое input image (reference_images[0]);
- alpha=0   -> EDIT (разрешённая область редактирования);
- alpha=255 -> PROTECT (защищённая область);
- размер файла < 4 MB.

Вся валидация — локальная (hashlib/PIL/numpy), без сети. Ошибка здесь
гарантирует, что сетевой вызов вообще не произойдёт (см.
OpenAIImagesProvider.generate — валидация выполняется ДО apply-ветки).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

MASK_MAX_BYTES = 4 * 1024 * 1024


class MaskValidationError(RuntimeError):
    """code — одно из: MASK_NOT_FOUND, MASK_TOO_LARGE, MASK_NOT_PNG,
    MASK_NO_ALPHA, MASK_SIZE_MISMATCH, MASK_NOT_BINARY, MASK_EMPTY,
    MASK_FULL_FRAME, MASK_EDIT_ZONE_MISMATCH."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_mask_file(mask_path, primary_image_path,
                       max_bytes: int = MASK_MAX_BYTES) -> dict:
    """Проверяет mask-файл против официального контракта OpenAI Images Edit.

    Возвращает audit dict при успехе (dimensions, sha256, alpha stats).
    Бросает MaskValidationError при первом нарушении — до любого сетевого
    вызова."""
    mask_path = Path(mask_path)
    if not mask_path.is_file():
        raise MaskValidationError("MASK_NOT_FOUND", f"mask file not found: {mask_path}")

    size_bytes = mask_path.stat().st_size
    if size_bytes >= max_bytes:
        raise MaskValidationError(
            "MASK_TOO_LARGE", f"{mask_path}: {size_bytes} bytes >= limit {max_bytes}")

    from PIL import Image
    with Image.open(mask_path) as im:
        if (im.format or "").upper() != "PNG":
            raise MaskValidationError(
                "MASK_NOT_PNG", f"{mask_path}: format={im.format!r}, expected PNG")
        if im.mode not in ("RGBA", "LA"):
            raise MaskValidationError(
                "MASK_NO_ALPHA", f"{mask_path}: mode={im.mode!r}, no alpha channel")
        mask_size = im.size
        alpha_channel = im.getchannel("A")

    primary_path = Path(primary_image_path)
    with Image.open(primary_path) as pim:
        primary_size = pim.size

    if mask_size != primary_size:
        raise MaskValidationError(
            "MASK_SIZE_MISMATCH", f"mask {mask_size} != primary image {primary_size}")

    import numpy as np
    arr = np.asarray(alpha_channel)
    unique_vals = set(int(v) for v in np.unique(arr).tolist())
    if not unique_vals <= {0, 255}:
        raise MaskValidationError(
            "MASK_NOT_BINARY",
            f"alpha содержит значения кроме 0/255: {sorted(unique_vals)} "
            "(полупрозрачность не разрешена)")

    transparent = int((arr == 0).sum())
    opaque = int((arr == 255).sum())
    total = int(arr.size)

    if transparent == 0:
        raise MaskValidationError("MASK_EMPTY", "mask не содержит editable (alpha=0) пикселей")
    if opaque == 0:
        raise MaskValidationError(
            "MASK_FULL_FRAME",
            "mask не содержит protected (alpha=255) пикселей — редактировался бы весь кадр")

    return {
        "mask_path": str(mask_path),
        "sha256": sha256_file(mask_path),
        "width": mask_size[0],
        "height": mask_size[1],
        "file_size_bytes": size_bytes,
        "alpha_min": int(arr.min()),
        "alpha_max": int(arr.max()),
        "transparent_pixel_count": transparent,
        "opaque_pixel_count": opaque,
        "editable_fraction": round(transparent / total, 6),
    }
