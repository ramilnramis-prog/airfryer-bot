"""Резолвер reference library: asset_id -> проверенный локальный путь.

Ничего не скачивает и не генерирует. Для приватных внешних ассетов путь
собирается из REFERENCE_LIBRARY_ROOT (переменная окружения, никогда не
коммитится) + relative_private_path из манифеста. Для двух already_in_repo
ассетов (реальные кадры real-product-v1) путь собирается от корня
репозитория напрямую — они уже публично отслеживаются в git и не требуют
REFERENCE_LIBRARY_ROOT.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .models import ReferenceLibraryError, ResolvedAsset
from .validator import validate_asset_file

ROOT_ENV_VAR = "REFERENCE_LIBRARY_ROOT"
REPO_ROOT = Path(__file__).resolve().parents[3]
INDEX_PATH = REPO_ROOT / "assets" / "reference-library" / "reference_library_index.json"


def load_index(index_path=INDEX_PATH) -> dict:
    return json.loads(Path(index_path).read_text(encoding="utf-8"))


def _find_asset(index: dict, asset_id: str, category: str | None) -> dict:
    matches = [a for a in index["assets"] if a["asset_id"] == asset_id]
    if not matches:
        raise ReferenceLibraryError(
            "REFERENCE_ASSET_NOT_FOUND",
            f"asset_id={asset_id!r} отсутствует в reference_library_index.json")
    if category is not None:
        matches = [a for a in matches if category in a["categories"]]
        if not matches:
            raise ReferenceLibraryError(
                "REFERENCE_ASSET_NOT_FOUND",
                f"asset_id={asset_id!r} не найден в категории {category!r}")
    if len(matches) > 1:
        raise ReferenceLibraryError(
            "REFERENCE_ASSET_AMBIGUOUS",
            f"asset_id={asset_id!r} соответствует {len(matches)} записям индекса")
    return matches[0]


def _resolve_path(asset: dict, root: str | None) -> Path:
    if asset.get("already_in_repo"):
        return (REPO_ROOT / asset["repo_path"]).resolve()

    if root is None:
        root = os.environ.get(ROOT_ENV_VAR)
    if not root:
        raise ReferenceLibraryError(
            "REFERENCE_ROOT_NOT_SET",
            f"переменная окружения {ROOT_ENV_VAR} не задана, а asset_id="
            f"{asset['asset_id']!r} не отслеживается в репозитории")

    root_path = Path(root).resolve()
    candidate = (root_path / asset["relative_private_path"]).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError:
        raise ReferenceLibraryError(
            "REFERENCE_PATH_ESCAPE",
            f"resolved path {candidate} выходит за пределы "
            f"{ROOT_ENV_VAR}={root_path}")
    return candidate


def resolve_asset(asset_id: str, category: str | None = None,
                  root: str | None = None, index: dict | None = None) -> ResolvedAsset:
    """Резолвит asset_id в проверенный локальный путь.

    Порядок: найти запись манифеста -> собрать путь (root+relative или
    repo-относительный) -> запретить выход за пределы root -> проверить
    существование файла -> проверить SHA256/размер/формат -> вернуть
    ResolvedAsset. Никаких сетевых вызовов."""
    index = index if index is not None else load_index()
    asset = _find_asset(index, asset_id, category)
    path = _resolve_path(asset, root)

    if not path.is_file():
        raise ReferenceLibraryError(
            "REFERENCE_ASSET_NOT_FOUND",
            f"asset_id={asset_id!r}: файл не найден по пути {path}")

    validate_asset_file(path, asset)

    return ResolvedAsset(
        asset_id=asset["asset_id"],
        path=path,
        sha256=asset["sha256"],
        width=asset["width"],
        height=asset["height"],
        file_size_bytes=asset["file_size_bytes"],
        categories=asset["categories"],
        source_type=asset["source_type"],
        ownership_status=asset["ownership_status"],
        approved_for_reference_only=asset["approved_for_reference_only"],
        prohibited_as_product_geometry_source=asset["prohibited_as_product_geometry_source"],
        restrictions=asset["restrictions"],
        already_in_repo=asset.get("already_in_repo", False),
    )
