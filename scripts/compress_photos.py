"""将照片另存为接近目标体积的 JPEG；默认不改变分辨率。"""

from __future__ import annotations

import argparse
import io
import math
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image

PROJECT = Path(__file__).resolve().parents[1]
ALBUM = "2025级九寨沟CAS WEEK"
JPEG_SUFFIXES = {".jpg", ".jpeg"}


def encode(source: Path, quality: int) -> bytes:
    """始终读取原图；不做旋转、缩放或色彩空间转换。"""
    with Image.open(source) as photo:
        photo.load()
        if photo.format != "JPEG":
            raise ValueError(f"扩展名为 JPEG，但内容不是 JPEG：{source}")
        options = dict(quality=quality, optimize=True, progressive=True,
                       subsampling="keep")
        for key in ("exif", "icc_profile", "dpi", "comment"):
            if key in photo.info:
                options[key] = photo.info[key]
        buffer = io.BytesIO()
        photo.save(buffer, format="JPEG", **options)
        result = buffer.getvalue()
        with Image.open(io.BytesIO(result)) as check:
            check.load()
            if check.size != photo.size:
                raise ValueError(f"编码后像素尺寸改变：{source}")
    return result


def atomic_write(source: Path, destination: Path, data: bytes | None = None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False,
                                         suffix=".partial") as stream:
            temporary = Path(stream.name)
            if data is not None:
                stream.write(data)
        if data is None:
            shutil.copy2(source, temporary)
        if source.suffix.lower() in JPEG_SUFFIXES:
            with Image.open(temporary) as check:
                check.load()
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def compress(source: Path, output: Path, target_gb: float) -> int:
    source, output = source.resolve(), output.resolve()
    if not math.isfinite(target_gb) or target_gb <= 0:
        raise ValueError("--target-gb 必须是大于 0 的有限数值")
    if not source.is_dir():
        raise ValueError(f"源目录不存在：{source}")
    if output == source or source in output.parents:
        raise ValueError("输出目录不能与源目录相同或位于源目录内部")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f"输出目录必须为空：{output}")
    paths = sorted(source.rglob("*"))
    if any(path.is_symlink() or path.is_junction() for path in paths):
        raise ValueError("源目录包含符号链接或目录联接，请先移除链接")
    files = [path for path in paths if path.is_file()]
    photos = [path for path in files if path.suffix.lower() in JPEG_SUFFIXES]
    if not photos:
        raise ValueError("源目录中没有 JPG/JPEG 照片")
    sizes = {path: path.stat().st_size for path in files}
    original = sum(sizes.values())
    fixed = original - sum(sizes[path] for path in photos)
    lower, upper = target_gb * 1e9 * .95, target_gb * 1e9 * 1.05
    print(f"共 {len(photos)} 张 JPEG，{len(files)} 个文件，原始大小 {original / 1e9:.3f} GB", flush=True)

    # 将按大小排序的图片均分为至多 12 层，每层取中位样本。
    ordered = sorted(photos, key=lambda path: sizes[path])
    strata = [ordered[i * len(ordered) // min(12, len(ordered)):
                      (i + 1) * len(ordered) // min(12, len(ordered))]
              for i in range(min(12, len(ordered)))]
    estimate_quality = 75
    for quality in range(95, 74, -1):
        estimate = fixed
        for group in strata:
            sample = group[len(group) // 2]
            ratio = min(len(encode(sample, quality)), sizes[sample]) / sizes[sample]
            estimate += ratio * sum(sizes[path] for path in group)
        print(f"抽样质量 {quality}：预计 {estimate / 1e9:.3f} GB", flush=True)
        if estimate <= upper:
            estimate_quality = quality
            break

    output.mkdir(parents=True, exist_ok=True)
    for path in paths:
        if path.is_dir():
            (output / path.relative_to(source)).mkdir(parents=True, exist_ok=True)
    for path in files:
        if path.suffix.lower() not in JPEG_SUFFIXES:
            atomic_write(path, output / path.relative_to(source))

    def run(quality: int) -> int:
        total = fixed
        for index, path in enumerate(photos, 1):
            data = encode(path, quality)
            use_original = len(data) >= sizes[path]
            atomic_write(path, output / path.relative_to(source),
                         None if use_original else data)
            total += sizes[path] if use_original else len(data)
            if index == 1 or index % 25 == 0 or index == len(photos):
                print(f"质量 {quality} | {index}/{len(photos)} | 累计 {total / 1e9:.3f} GB", flush=True)
        return total

    # 实测后寻找最高质量。逐级检查避免假定 JPEG 大小严格单调。
    # 先测抽样建议值，再从 95 向下检查；已测值无需重复判断。
    measured = {estimate_quality: run(estimate_quality)}
    current_quality = estimate_quality
    chosen = 75
    for quality in range(95, 74, -1):
        if quality not in measured:
            measured[quality] = run(quality)
            current_quality = quality
        if measured[quality] <= upper or quality == 75:
            chosen = quality
            break
    if current_quality != chosen:
        run(chosen)

    result_files = [path for path in output.rglob("*") if path.is_file()]
    total = sum(path.stat().st_size for path in result_files)
    if len(result_files) != len(files) or total != measured[chosen]:
        raise RuntimeError("输出数量或体积校验失败，结果不完整")
    achieved = lower <= total <= upper
    print(f"\n完成：质量 {chosen}，{original / 1e9:.3f} → {total / 1e9:.3f} GB，"
          f"减少 {(1 - total / original) * 100:.1f}%")
    print(f"输出：{output}")
    if achieved:
        print("目标达成（±5%）。")
        return 0
    if total > upper:
        print("目标未达成：质量 75 仍超出上限，已保留结果，不再降低画质。")
    else:
        print("目标未达成：最高质量 95 的结果仍低于下限，不人为增大文件。")
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=PROJECT / "public" / "Photos" / ALBUM)
    parser.add_argument("--output", type=Path, default=PROJECT.parent / f"{ALBUM}-compressed")
    parser.add_argument("--target-gb", type=float, default=4.0,
                        help="十进制 GB，包含缩略图等附带文件，默认 4")
    args = parser.parse_args()
    try:
        return compress(args.source, args.output, args.target_gb)
    except (OSError, ValueError, RuntimeError, Image.DecompressionBombError) as error:
        print(f"失败：{error}\n原图未改动；输出可能不完整，请检查后另选空目录重试。", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已中断，原图未改动；输出不完整。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
