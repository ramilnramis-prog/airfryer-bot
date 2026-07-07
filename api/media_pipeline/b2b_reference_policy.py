"""B2B_PRODUCT_REFERENCE_ONLY_POLICY -- universal image-reference policy for
the B2B seller traffic factory. Same "PRODUCT ONLY MEANS PRODUCT ONLY" spirit
as the single-campaign pipeline, generalized across sellers:

- image references can ONLY come from the seller-uploaded, approved product
  reference folder (content/b2b/.../products/<id>/references/);
- generated outputs can NEVER become product references automatically;
- for this MVP, non-product context images (kitchen/background/food/hands/
  person) are not supported as references at all -- every uploaded
  reference is treated as a product-only shot;
- fails CLOSED if there are no (or too few) approved product references --
  never falls back to a default/placeholder reference.
"""
from __future__ import annotations

from pathlib import Path

from . import b2b_storage as st

MIN_APPROVED_REFERENCES = 3

# Any of these substrings appearing in a reference path is an automatic,
# non-negotiable rejection -- generated output, prior candidates, or any
# path outside the seller's own approved references/ folder.
FORBIDDEN_PATH_MARKERS = ("generated", "candidate", "-c1.", "-c2.", "-c3.",
                         "dzen-publishing", "video-renders")


class B2BReferencePolicyError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _is_forbidden_path(path_str: str) -> list:
    normalized = str(path_str).replace("\\", "/").lower()
    return [marker for marker in FORBIDDEN_PATH_MARKERS if marker in normalized]


def validate_reference_entry(ref, repo_root: str = ".") -> None:
    """Raises B2BReferencePolicyError (fail closed) if this single reference
    entry violates policy. Never silently drops or auto-fixes a bad entry."""
    if not ref.approved:
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


def assert_campaign_generation_allowed(client_id: str, product_id: str, repo_root: str = ".") -> list:
    """Fail-closed gate: MUST be called before any campaign generation
    (dry-run or real, product-reference-bearing calls). Returns the
    validated approved-reference list on success; raises
    B2BReferencePolicyError otherwise -- never proceeds with zero or
    insufficient references."""
    refs = st.load_references(client_id, product_id, repo_root)
    if not refs:
        raise B2BReferencePolicyError(
            "NO_REFERENCES_UPLOADED",
            f"product {product_id!r} has no uploaded references at all -- upload and "
            f"approve at least {MIN_APPROVED_REFERENCES} product photos first")

    approved = [r for r in refs if r.approved]
    if len(approved) < MIN_APPROVED_REFERENCES:
        raise B2BReferencePolicyError(
            "INSUFFICIENT_APPROVED_REFERENCES",
            f"product {product_id!r} has {len(approved)} approved reference(s), "
            f"needs at least {MIN_APPROVED_REFERENCES}")

    for ref in approved:
        validate_reference_entry(ref, repo_root)

    return approved


def scan_reference_images_list(reference_images: list, repo_root: str = ".") -> dict:
    """Defense-in-depth audit of a raw reference_images path list (as would
    be attached to an actual generation request) -- confirms every path is
    clean, independent of the approved-references gate above."""
    findings = []
    for path in reference_images:
        hits = _is_forbidden_path(path)
        if hits:
            findings.append({"path": path, "reason": f"forbidden_path_marker:{hits}"})
        elif not Path(repo_root, path).is_file():
            findings.append({"path": path, "reason": "file_missing"})
    return {"scanned": len(reference_images), "forbidden_found": len(findings) > 0,
           "findings": findings}
