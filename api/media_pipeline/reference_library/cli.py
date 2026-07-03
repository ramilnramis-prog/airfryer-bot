"""CLI reference library resolver (всё локально, сети нет вообще).

Команды:
  resolve-campaign <campaign_visual_lock.json>
      dry-run: резолвит все asset_id из locked_elements через
      REFERENCE_LIBRARY_ROOT, проверяет SHA256/размер/формат каждого файла,
      подтверждает, что один и тот же resolved-набор относится ко всем
      сценам и всем трём hooks (locked_for_all_scenes/shared_across_hooks),
      и что product_canon НЕ резолвится через reference library. Ничего не
      копирует, не генерирует, не изменяет campaign lock. Результат
      сохраняется ТОЛЬКО локально в generated/resolved-campaign-visual-lock.json
      (в .gitignore).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import ReferenceLibraryError
from .resolver import ROOT_ENV_VAR, load_index, resolve_asset


def resolve_campaign(campaign_lock_path: str, index: dict | None = None,
                     root: str | None = None) -> dict:
    lock = json.loads(Path(campaign_lock_path).read_text(encoding="utf-8"))
    index = index if index is not None else load_index()

    if lock["product_canon_resolution"] != "repository_only":
        raise ReferenceLibraryError(
            "REFERENCE_ASSET_AMBIGUOUS",
            "product_canon_resolution должен быть 'repository_only' — "
            "product_canon никогда не резолвится через reference library")

    resolved = []
    for element in lock["locked_elements"]:
        ra = resolve_asset(element["asset_id"], root=root, index=index)
        if ra.sha256 != element["expected_sha256"]:
            raise ReferenceLibraryError(
                "REFERENCE_HASH_MISMATCH",
                f"{element['asset_id']}: campaign lock expected_sha256="
                f"{element['expected_sha256']} != index sha256={ra.sha256}")
        resolved.append({
            "role": element["role"],
            "asset_id": element["asset_id"],
            "locked_for_all_scenes": element["locked_for_all_scenes"],
            "shared_across_hooks": element["shared_across_hooks"],
            "resolved_path": str(ra.path),
            "sha256": ra.sha256,
            "width": ra.width,
            "height": ra.height,
            "file_size_bytes": ra.file_size_bytes,
            "already_in_repo": ra.already_in_repo,
            "reference_only": element["reference_only"],
            "restrictions": element["restrictions"],
        })

    hooks = lock["hooks"]
    all_shared = all(r["shared_across_hooks"] for r in resolved)
    same_for_all_hooks = {
        "variants": hooks["variants"],
        "same_resolved_set_confirmed": all_shared and hooks["shared_main_body"],
        "shared_visual_lock_file": hooks["shared_visual_lock"],
    }

    report = {
        "campaign_code": lock["campaign_code"],
        "content_code": lock["content_code"],
        "product_canon": lock["product_canon"],
        "product_canon_resolved_via": "repository (product_asset_manifest.json)",
        "product_canon_never_resolved_via_reference_library": True,
        "reference_library_root_env_var": ROOT_ENV_VAR,
        "resolved_elements": resolved,
        "resolved_element_count": len(resolved),
        "hooks_share_one_resolved_set": same_for_all_hooks,
        "images_api_calls": 0,
        "animation_api_calls": 0,
        "network_calls": 0,
    }
    return report


def cmd_resolve_campaign(args) -> int:
    try:
        report = resolve_campaign(args.campaign_lock_path)
    except ReferenceLibraryError as e:
        print(json.dumps({"error": e.code, "message": str(e)},
                         ensure_ascii=True, indent=2))
        return 1

    out_path = args.out
    if out_path is None:
        lock_dir = Path(args.campaign_lock_path).resolve().parent
        out_path = lock_dir / "generated" / "resolved-campaign-visual-lock.json"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # ensure_ascii=True для stdout — избегает UnicodeEncodeError/побитого
    # вывода при перенаправлении в файл на Windows-консоли с cp1251
    print(json.dumps(report, ensure_ascii=True, indent=2))
    print(f"\n[resolve-campaign] сохранено локально (не в git): {out_path}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m api.media_pipeline.reference_library.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p_resolve = sub.add_parser("resolve-campaign",
                               help="dry-run: резолвить все asset_id кампании и проверить SHA256")
    p_resolve.add_argument("campaign_lock_path")
    p_resolve.add_argument("--out", default=None,
                           help="куда сохранить resolved-campaign-visual-lock.json "
                                "(по умолчанию <campaign_dir>/generated/, всегда вне git)")
    p_resolve.set_defaults(func=cmd_resolve_campaign)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
