"""Типы данных reference library resolver'а. Никакого I/O здесь нет."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class ReferenceLibraryError(RuntimeError):
    """Единая ошибка resolver'а. code — одно из:
    REFERENCE_ROOT_NOT_SET, REFERENCE_ASSET_NOT_FOUND, REFERENCE_HASH_MISMATCH,
    REFERENCE_PATH_ESCAPE, REFERENCE_ASSET_AMBIGUOUS."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ResolvedAsset:
    asset_id: str
    path: Path
    sha256: str
    width: int
    height: int
    file_size_bytes: int
    categories: list = field(default_factory=list)
    source_type: str = ""
    ownership_status: str = ""
    approved_for_reference_only: bool = True
    prohibited_as_product_geometry_source: bool = False
    restrictions: list = field(default_factory=list)
    already_in_repo: bool = False

    def as_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "resolved_path": str(self.path),
            "sha256": self.sha256,
            "width": self.width,
            "height": self.height,
            "file_size_bytes": self.file_size_bytes,
            "categories": self.categories,
            "source_type": self.source_type,
            "ownership_status": self.ownership_status,
            "approved_for_reference_only": self.approved_for_reference_only,
            "prohibited_as_product_geometry_source": self.prohibited_as_product_geometry_source,
            "restrictions": self.restrictions,
            "already_in_repo": self.already_in_repo,
        }
