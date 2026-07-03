"""Локальная проверка resolved-файла против записи манифеста.
Никаких сетевых вызовов — только hashlib/PIL по локальному файлу."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .models import ReferenceLibraryError

_CHUNK = 1 << 20


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_asset_file(path: Path, asset: dict) -> None:
    """Бросает ReferenceLibraryError при несовпадении SHA256/размера/формата.
    Ничего не возвращает — успех означает отсутствие исключения."""
    actual_sha256 = sha256_file(path)
    if actual_sha256 != asset["sha256"]:
        raise ReferenceLibraryError(
            "REFERENCE_HASH_MISMATCH",
            f"{path}: manifest sha256={asset['sha256']} != actual sha256={actual_sha256}")

    actual_size = path.stat().st_size
    if actual_size != asset["file_size_bytes"]:
        raise ReferenceLibraryError(
            "REFERENCE_HASH_MISMATCH",
            f"{path}: manifest file_size_bytes={asset['file_size_bytes']} != "
            f"actual={actual_size}")

    from PIL import Image
    with Image.open(path) as im:
        actual_w, actual_h = im.size
        actual_format = (im.format or "").upper()
    if [actual_w, actual_h] != [asset["width"], asset["height"]]:
        raise ReferenceLibraryError(
            "REFERENCE_HASH_MISMATCH",
            f"{path}: manifest {asset['width']}x{asset['height']} != "
            f"actual {actual_w}x{actual_h}")
    expected_suffix = Path(asset["filename"]).suffix.lstrip(".").upper()
    if expected_suffix and actual_format and expected_suffix != actual_format \
            and not (expected_suffix == "JPG" and actual_format == "JPEG"):
        raise ReferenceLibraryError(
            "REFERENCE_HASH_MISMATCH",
            f"{path}: filename suffix {expected_suffix} != actual format {actual_format}")
