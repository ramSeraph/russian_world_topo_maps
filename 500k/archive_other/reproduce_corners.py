# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "opencv-python-headless>=4,<5"]
# ///
"""Find the four frame corners on the released November 2026 1:500,000 scans."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "1m" / "archive_other"))
from detect_corners import cv2, detect


def detector_dpi(row):
    if row["source"] == "Archive.org":
        match = re.search(r"_(\d+)dpi", row["source_member"], re.IGNORECASE)
        if match:
            return int(match[1])
    elif row["source"] in ("State Library of Western Australia", "The Red Atlas"):
        return 200
    raise ValueError(f"No recorded detector DPI for {row['sheet']}")


def measure(row, originals, corrections):
    sheet = row["sheet"]
    path = originals / row["original"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != row["source_sha256"]:
        raise ValueError(f"{sheet}: original JPEG checksum differs from provenance")

    manual = {}
    if sheet in corrections:
        decision = corrections[sheet]
        if decision["sha256"] != digest:
            raise ValueError(f"{sheet}: manual readings belong to a different scan")
        manual = decision["corners"]

    dpi = detector_dpi(row)
    result = detect(path, dpi=dpi)
    reviewed = {}
    for corner in ("NW", "NE", "SE", "SW"):
        candidate = result["corners"].get(corner, {}).get("pixel")
        pixel = manual.get(corner, candidate)
        if pixel is None:
            raise ValueError(f"{sheet}: missing {corner} candidate and manual reading")
        reviewed[corner] = {"pixel": pixel, "method": "manual" if corner in manual else "detector"}
    return {"sheet": sheet, "sha256": digest, "dpi": dpi, "detector": result, "reviewed": reviewed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--originals", required=True, type=Path, help="Directory of released JPEGs")
    parser.add_argument("--provenance", required=True, type=Path, help="Released 500k-provenance.csv")
    parser.add_argument("--output", required=True, type=Path, help="Directory for per-sheet JSON")
    parser.add_argument("--sheet", action="append", help="Limit to this release sheet ID (repeatable)")
    args = parser.parse_args()
    with args.provenance.open(encoding="utf-8", newline="") as stream:
        rows = {row["sheet"]: row for row in csv.DictReader(stream)}
    sheets = args.sheet or list(rows)
    unknown = set(sheets) - rows.keys()
    if unknown:
        parser.error("Unknown sheet IDs: " + ", ".join(sorted(unknown)))

    corrections = json.loads((HERE / "manual_corners.json").read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    cv2.setNumThreads(1)
    for sheet in sheets:
        result = measure(rows[sheet], args.originals, corrections)
        (args.output / f"{sheet}.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
