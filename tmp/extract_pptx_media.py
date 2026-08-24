from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree


REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, list[str]] = {}
    with zipfile.ZipFile(args.source) as archive:
        media_names = [name for name in archive.namelist() if name.startswith("ppt/media/")]
        for name in media_names:
            target = args.output_dir / PurePosixPath(name).name
            with archive.open(name) as reader, target.open("wb") as writer:
                shutil.copyfileobj(reader, writer)

        for rel_name in sorted(
            name
            for name in archive.namelist()
            if name.startswith("ppt/slides/_rels/slide") and name.endswith(".xml.rels")
        ):
            root = ElementTree.fromstring(archive.read(rel_name))
            targets = []
            for relationship in root.findall(f"{{{REL_NS}}}Relationship"):
                target = relationship.get("Target", "")
                if target.startswith("../media/"):
                    targets.append(PurePosixPath(target).name)
            slide_name = PurePosixPath(rel_name).name.removesuffix(".xml.rels")
            report[slide_name] = targets

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
