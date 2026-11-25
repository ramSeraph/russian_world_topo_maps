"""Fetch selected released originals under their native filenames and write detector receipts."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from urllib.request import Request, urlopen


AUDIT = Path(__file__).resolve().parents[2] / "new" / "genshtab-audit"


def selection(ids):
    with (AUDIT / "50k-provenance.csv").open() as stream:
        rows = {r["scan_id"]: r for r in csv.DictReader(stream)}
    missing = set(ids) - rows.keys()
    if missing:
        raise ValueError("Unknown released sheet IDs: " + ", ".join(sorted(missing)))
    return [rows[k] for k in sorted(set(ids) or rows)]


def fetch(path, row):
    expected = row["source_sha256"]
    if expected != row["original_sha256"]:
        raise ValueError(f"Released and native digests differ for {row['scan_id']}")
    if path.exists():
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError(f"Existing original has the wrong digest: {path}")
        return
    request = Request(
        row["original_url"], headers={"User-Agent": "russian-world-topo-maps"}
    )
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        temporary = Path(tmp.name)
    try:
        with urlopen(request, timeout=120) as response, temporary.open("wb") as stream:
            shutil.copyfileobj(response, stream)
        with temporary.open("rb") as stream:
            if (
                temporary.stat().st_size != int(row["original_bytes"])
                or hashlib.file_digest(stream, "sha256").hexdigest() != expected
            ):
                raise ValueError(
                    f"Download differs from the published original: {row['scan_id']}"
                )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(root, row, red_metadata):
    filename = row["original"]
    if Path(filename).name != filename:
        raise ValueError(f"Invalid native filename: {filename}")
    if row["source"] == "Archive.org":
        source = root / "archive" / "originals" / filename
        # OSD names its result after the native file, including the two mislabelled scans.
        receipt = root / "archive" / "receipts" / (source.stem + ".json")
        data = dict(
            scan_id=source.stem,
            component_ids=row["catalogue_component_ids"] or row["component_ids"],
            original=filename,
            source=row["source"],
            year=row["year"],
            sha256=row["source_sha256"],
            archive_member=row["archive_member"],
            width=int(row["source_width"]),
            height=int(row["source_height"]),
        )
    elif row["source"] == "The Red Atlas":
        source = root / "red-atlas" / "mosaics" / filename
        receipt = root / "red-atlas" / "retrieval" / (source.stem + ".json")
        data = dict(red_metadata[row["scan_id"]])
        for key in ("source_level_width", "source_level_height"):
            data[key] = int(data[key])
        data["estimated_level_dpi"] = float(data["estimated_level_dpi"])
        if data["mosaic_sha256"] != row["source_sha256"]:
            raise ValueError(f"Red Atlas source digest differs for {source.stem}")
    else:
        raise ValueError(f"Unknown scan source: {row['source']}")
    source.parent.mkdir(parents=True, exist_ok=True)
    fetch(source, row)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=receipt.parent, delete=False) as tmp:
        json.dump(data, tmp, ensure_ascii=False)
        tmp.write("\n")
    Path(tmp.name).replace(receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    parser.add_argument(
        "sheets",
        nargs="*",
        help="Published physical scan IDs; omit to fetch the full set",
    )
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    rows = selection(args.sheets)
    with (AUDIT / "50k-red-atlas-scan-provenance.csv").open() as stream:
        red = {r["sheet"]: r for r in csv.DictReader(stream)}
    with ThreadPoolExecutor(args.jobs) as pool:
        for _ in pool.map(lambda r: prepare(args.work, r, red), rows):
            pass
    print(f"Verified {len(rows):,} released originals.")


if __name__ == "__main__":
    main()
