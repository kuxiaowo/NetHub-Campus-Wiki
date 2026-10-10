"""Convert legacy v1/v2 JSON offline, without writing the online database."""

import argparse
import json
from pathlib import Path

from backend.data_transfer import validate_transfer_document
from backend.project_assets import infer_asset_dir, normalize_project_updates


def convert(document):
    if document.get("version") not in {1, 2}:
        raise ValueError("Expected transfer version 1 or 2")
    result = json.loads(json.dumps(document))
    for project in result.get("projects", []):
        directory = project.get("assetDir") or infer_asset_dir(
            project.get("icon"), project.get("updates")
        )
        if not directory:
            raise ValueError("Project asset directory could not be inferred")
        project["assetDir"] = directory
        project.pop("icon", None)
        project["updates"] = normalize_project_updates(
            project.get("updates", []), directory, allow_legacy=True
        )
        for update in project["updates"]:
            update.pop("authorPersonId", None)
            update.pop("authorUserId", None)
    result["version"] = 3
    normalized, warnings = validate_transfer_document(result)
    return normalized, warnings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result, warnings = convert(json.loads(args.input.read_text(encoding="utf-8-sig")))
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"version": 3, "warnings": warnings}, ensure_ascii=False))
