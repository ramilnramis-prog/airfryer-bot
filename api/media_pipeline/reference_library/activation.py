"""Guard: proposed visual-set lock (v2) не должен запускать платную
генерацию, пока владелец явно не подтвердил его (owner_approved: true)."""
from __future__ import annotations

from .models import ReferenceLibraryError


class VisualSetNotApprovedError(ReferenceLibraryError):
    def __init__(self, visual_set_id: str):
        super().__init__(
            "VISUAL_SET_NOT_APPROVED",
            f"visual_set_id={visual_set_id!r}: owner_approved != true — "
            "платная генерация запрещена до явного подтверждения владельца")


def require_owner_approval(lock: dict) -> None:
    """Бросает VisualSetNotApprovedError, если lock['owner_approved'] is not True.
    Вызывать перед ЛЮБЫМ платным API-вызовом, использующим этот visual lock."""
    if lock.get("owner_approved") is not True:
        raise VisualSetNotApprovedError(lock.get("visual_set_id", "<unknown>"))
