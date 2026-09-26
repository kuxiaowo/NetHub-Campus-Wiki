"""Stage existing local image thumbnails for the R2 thumbnail key layout.

This script never uploads, renames, deletes, or modifies files below public/.
It copies valid legacy ``.thumbs/<source-stem>.webp`` files into an external
staging directory as ``<source-name>.image.webp``.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from PIL import Image, UnidentifiedImageError


IMAGE_SUFFIXES = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
VIDEO_SUFFIXES = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
ROOTS = ("Photos", "yearbook")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--staging",
        type=Path,
        default=Path(r"C:\Users\admin\AppData\Local\NetHub\R2ThumbnailStaging"),
        help="仓库外 staging 目录",
    )
    parser.add_argument("--report", type=Path, default=None)
    return parser.parse_args()


def valid_thumbnail(path: Path) -> tuple[bool, str | None]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            if image.width < 1 or image.height < 1:
                return False, "invalid_dimensions"
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        return False, type(exc).__name__
    return True, None


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    public = project_root / "public"
    staging = args.staging.resolve()
    staging.mkdir(parents=True, exist_ok=True)

    report: dict[str, object] = {
        "staging": str(staging),
        "copied": [],
        "missing": [],
        "invalid": [],
        "ambiguous": [],
        "skipped_videos": 0,
    }

    for root_name in ROOTS:
        root = public / root_name
        if not root.is_dir():
            continue
        for source in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if not source.is_file() or ".thumbs" in source.parts:
                continue
            suffix = source.suffix.casefold()
            if suffix in VIDEO_SUFFIXES:
                report["skipped_videos"] = int(report["skipped_videos"]) + 1
                continue
            if suffix not in IMAGE_SUFFIXES:
                continue

            thumb_dir = source.parent / ".thumbs"
            candidates = [
                item for item in thumb_dir.glob("*.webp")
                if item.stem.casefold() == source.stem.casefold()
            ] if thumb_dir.is_dir() else []
            relative = source.relative_to(public)
            if not candidates:
                report["missing"].append(relative.as_posix())
                continue
            if len(candidates) != 1:
                report["ambiguous"].append({
                    "source": relative.as_posix(),
                    "candidates": [item.name for item in candidates],
                })
                continue

            thumbnail = candidates[0]
            valid, reason = valid_thumbnail(thumbnail)
            if not valid:
                report["invalid"].append({
                    "source": relative.as_posix(),
                    "thumbnail": str(thumbnail),
                    "reason": reason,
                })
                continue

            destination = staging / "thumbnails" / relative.parent / f"{relative.name}.image.webp"
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if destination.stat().st_size != thumbnail.stat().st_size:
                    raise RuntimeError(f"staging 冲突，拒绝覆盖：{destination}")
            else:
                shutil.copy2(thumbnail, destination)
            report["copied"].append({
                "source": relative.as_posix(),
                "legacy": str(thumbnail),
                "staged": str(destination),
            })

    report_path = args.report or staging / "thumbnail-staging-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "staging": str(staging),
        "copied": len(report["copied"]),
        "missing": len(report["missing"]),
        "invalid": len(report["invalid"]),
        "ambiguous": len(report["ambiguous"]),
        "skipped_videos": report["skipped_videos"],
        "report": str(report_path),
    }, ensure_ascii=False))
    return 1 if report["missing"] or report["invalid"] or report["ambiguous"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
