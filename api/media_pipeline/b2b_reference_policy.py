"""B2B_PRODUCT_REFERENCE_ONLY_POLICY -- universal image-reference policy for
the B2B seller traffic factory. Same "PRODUCT ONLY MEANS PRODUCT ONLY" spirit
as the single-campaign pipeline, generalized across sellers:

- image references can ONLY come from the seller-uploaded product reference
  folder (content/b2b/.../products/<id>/references/);
- generated outputs can NEVER become product references automatically --
  this is non-negotiable in BOTH policy modes below;
- for this MVP, non-product context images (kitchen/background/food/hands/
  person) are not supported as references at all -- every uploaded
  reference is treated as a product-only shot;
- fails CLOSED if there are no uploaded product references at all -- never
  falls back to a default/placeholder reference.

Two policy modes, selected per call via `strict_approved_refs_required`:

- **Seller MVP flow (default, strict=False)**: any uploaded, non-forbidden
  reference is usable -- manual admin approval is NOT required to unblock a
  seller's own dry-run/delivery-kit. Minimum 1 uploaded photo; 3-8 is only a
  quality recommendation, never a hard blocker. This exists because
  requiring manual approve=true before a seller can even preview their own
  content package reads as a broken flow from the outside.
- **Admin strict policy (opt-in, strict=True)**: requires >= MIN_APPROVED_
  REFERENCES approved references, same as the original MVP behavior. For
  internal quality-controlled campaigns where an admin wants to gate on
  reviewed references specifically.
"""
from __future__ import annotations

from pathlib import Path

from . import b2b_storage as st

MIN_APPROVED_REFERENCES = 3          # admin strict-mode threshold
MIN_SELLER_FLOW_REFERENCES = 1       # seller MVP hard minimum
RECOMMENDED_REFERENCE_RANGE = "3-8"  # quality recommendation, never a blocker

# Any of these substrings appearing in a reference path is an automatic,
# non-negotiable rejection -- generated output, prior candidates, or any
# path outside the seller's own approved references/ folder. Applies in
# BOTH policy modes -- generated/candidate images are never usable as
# references no matter how lenient the approval requirement is.
FORBIDDEN_PATH_MARKERS = ("generated", "candidate", "-c1.", "-c2.", "-c3.",
                         "dzen-publishing", "video-renders")


class B2BReferencePolicyError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _is_forbidden_path(path_str: str) -> list:
    normalized = str(path_str).replace("\\", "/").lower()
    return [marker for marker in FORBIDDEN_PATH_MARKERS if marker in normalized]


def validate_reference_entry(ref, repo_root: str = ".", require_approved: bool = True) -> None:
    """Raises B2BReferencePolicyError (fail closed) if this single reference
    entry violates policy. Never silently drops or auto-fixes a bad entry.
    require_approved=False is used by the seller MVP flow, where uploaded
    references don't need manual admin approval to be usable -- the
    forbidden-path/role/file-exists checks still always apply."""
    if require_approved and not ref.approved:
        raise B2BReferencePolicyError("REFERENCE_NOT_APPROVED",
                                      f"{ref.file_path} is not marked approved=true")
    forbidden = _is_forbidden_path(ref.file_path)
    if forbidden:
        raise B2BReferencePolicyError("FORBIDDEN_REFERENCE_PATH",
                                      f"{ref.file_path} matches forbidden marker(s): {forbidden}")
    if ref.role not in st.PRODUCT_REFERENCE_ROLES:
        raise B2BReferencePolicyError("UNKNOWN_REFERENCE_ROLE",
                                      f"{ref.file_path} has unknown role {ref.role!r}")
    full_path = Path(repo_root) / ref.file_path
    if not full_path.is_file():
        raise B2BReferencePolicyError("REFERENCE_FILE_MISSING",
                                      f"{full_path} does not exist on disk")


def get_approved_references(client_id: str, product_id: str, repo_root: str = ".") -> list:
    refs = st.load_references(client_id, product_id, repo_root)
    return [r for r in refs if r.approved]


def get_uploaded_references(client_id: str, product_id: str, repo_root: str = ".") -> list:
    """All uploaded references regardless of approved flag -- what the
    seller MVP flow treats as usable product references."""
    return st.load_references(client_id, product_id, repo_root)


def assert_campaign_generation_allowed(client_id: str, product_id: str, repo_root: str = ".",
                                       strict_approved_refs_required: bool = False) -> list:
    """Fail-closed gate: MUST be called before any campaign generation
    (dry-run or real, product-reference-bearing calls). Returns the
    validated usable-reference list on success; raises
    B2BReferencePolicyError otherwise -- never proceeds with zero references.

    Default (strict_approved_refs_required=False) is the seller MVP policy:
    at least 1 uploaded, non-forbidden reference is enough. Pass
    strict_approved_refs_required=True for the admin-only stricter policy
    (>= MIN_APPROVED_REFERENCES approved references)."""
    refs = st.load_references(client_id, product_id, repo_root)
    if not refs:
        raise B2BReferencePolicyError(
            "NO_REFERENCES_UPLOADED",
            f"product {product_id!r} has no uploaded references at all -- upload at "
            f"least {MIN_SELLER_FLOW_REFERENCES} product photo first")

    if strict_approved_refs_required:
        usable = [r for r in refs if r.approved]
        if len(usable) < MIN_APPROVED_REFERENCES:
            raise B2BReferencePolicyError(
                "INSUFFICIENT_APPROVED_REFERENCES",
                f"product {product_id!r} has {len(usable)} approved reference(s), "
                f"needs at least {MIN_APPROVED_REFERENCES}")
        for ref in usable:
            validate_reference_entry(ref, repo_root, require_approved=True)
    else:
        if len(refs) < MIN_SELLER_FLOW_REFERENCES:
            raise B2BReferencePolicyError(
                "NO_REFERENCES_UPLOADED",
                f"product {product_id!r} has no uploaded references at all -- upload at "
                f"least {MIN_SELLER_FLOW_REFERENCES} product photo first")
        usable = refs
        for ref in usable:
            validate_reference_entry(ref, repo_root, require_approved=False)

    return usable


def build_reference_quality(client_id: str, product_id: str, repo_root: str = ".") -> dict:
    """Descriptive quality signal for the dry-run report -- never a gate by
    itself, just tells the seller/admin how confident to be in the result."""
    refs = st.load_references(client_id, product_id, repo_root)
    uploaded_count = len(refs)
    approved_count = sum(1 for r in refs if r.approved)

    if uploaded_count >= 3:
        quality_risk = "low"
        notes = "Отлично: фото товара достаточно для старта."
    elif uploaded_count == 2:
        quality_risk = "medium"
        notes = "Хорошо. Для лучшего результата добавьте ещё фото сверху/сбоку/детали."
    elif uploaded_count == 1:
        quality_risk = "high"
        notes = ("Можно продолжить, но лучше загрузить 3-8 фото с разных ракурсов, чтобы "
                "AI точнее сохранял внешний вид товара.")
    else:
        quality_risk = "high"
        notes = "Фото товара ещё не загружены."

    return {
        "uploaded_count": uploaded_count,
        "approved_count": approved_count,
        "minimum_required_for_seller_flow": MIN_SELLER_FLOW_REFERENCES,
        "recommended_count": RECOMMENDED_REFERENCE_RANGE,
        "quality_risk": quality_risk,
        "notes": notes,
    }


def scan_reference_images_list(reference_images: list, repo_root: str = ".") -> dict:
    """Defense-in-depth audit of a raw reference_images path list (as would
    be attached to an actual generation request) -- confirms every path is
    clean, independent of the usable-references gate above."""
    findings = []
    for path in reference_images:
        hits = _is_forbidden_path(path)
        if hits:
            findings.append({"path": path, "reason": f"forbidden_path_marker:{hits}"})
        elif not Path(repo_root, path).is_file():
            findings.append({"path": path, "reason": "file_missing"})
    return {"scanned": len(reference_images), "forbidden_found": len(findings) > 0,
           "findings": findings}
