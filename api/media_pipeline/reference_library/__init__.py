"""Portable, private-safe reference library resolver.

Материалы reference library (кроме двух уже отслеживаемых в git кадров
real-product-v1) хранятся вне репозитория. Git хранит только
assets/reference-library/**/manifest.json + reference_library_index.json:
asset_id, относительный приватный путь, SHA256, описание, ограничения.
Фактический абсолютный путь собирается только локально из переменной
окружения REFERENCE_LIBRARY_ROOT — она никогда не коммитится.
"""
from .activation import VisualSetNotApprovedError, require_owner_approval
from .models import ReferenceLibraryError, ResolvedAsset
from .resolver import ROOT_ENV_VAR, load_index, resolve_asset

__all__ = ["ReferenceLibraryError", "ResolvedAsset", "ROOT_ENV_VAR",
          "load_index", "resolve_asset", "VisualSetNotApprovedError",
          "require_owner_approval"]
