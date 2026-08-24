from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


def iter_blocks(document: Document):
    body = document.element.body
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, document)
        elif child.tag.endswith("}tbl"):
            yield Table(child, document)


def extract_document(source: Path, output_root: Path) -> dict:
    document = Document(source)
    blocks: list[dict] = []
    for block in iter_blocks(document):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            images = []
            for blip in block._p.xpath(".//a:blip"):
                relationship_id = blip.get(qn("r:embed"))
                if relationship_id and relationship_id in document.part.rels:
                    images.append(Path(document.part.rels[relationship_id].target_part.partname).name)
            if text or images:
                blocks.append(
                    {
                        "type": "paragraph",
                        "style": block.style.name,
                        "text": text,
                        "images": images,
                    }
                )
            continue

        rows = []
        for row in block.rows:
            rows.append([cell.text.strip() for cell in row.cells])
        blocks.append({"type": "table", "rows": rows})

    media_dir = output_root / source.parent.name
    media_dir.mkdir(parents=True, exist_ok=True)
    media_files: list[str] = []
    with zipfile.ZipFile(source) as archive:
        for member in archive.namelist():
            if not member.startswith("word/media/") or member.endswith("/"):
                continue
            target = media_dir / Path(member).name
            with archive.open(member) as reader, target.open("wb") as writer:
                shutil.copyfileobj(reader, writer)
            media_files.append(str(target))

    return {
        "source": str(source),
        "blocks": blocks,
        "media": media_files,
        "inline_shape_count": len(document.inline_shapes),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_root", type=Path)
    parser.add_argument("sources", nargs="+", type=Path)
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    result = [extract_document(source, args.output_root) for source in args.sources]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
