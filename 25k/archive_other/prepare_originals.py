"""Fetch released Baltic originals and prepare their measurement manifest."""

import argparse
import csv
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AUDIT = REPO / "new/genshtab-audit"
sys.path.insert(0, str(REPO / "50k/archive_other"))
from fetch_released import fetch


def prepare(work, sheets, jobs):
    with (AUDIT / "25k-provenance.csv").open() as stream:
        released = {row["sheet"]: row for row in csv.DictReader(stream)}
    with (AUDIT / "25k-selected-originals.csv").open() as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = [row for row in reader if not sheets or Path(row["name"]).stem in sheets]
    ids = {Path(row["name"]).stem for row in rows}
    if sheets - ids:
        raise ValueError("Unknown sheet IDs: " + ", ".join(sorted(sheets - ids)))
    directory = work / "selected-originals"
    directory.mkdir(parents=True, exist_ok=True)

    def download(row):
        sheet = Path(row["name"]).stem
        release = released[sheet]
        if row["name"] != sheet + ".jpg" or (row["sha256"], row["bytes"]) != (
            release["original_sha256"], release["original_bytes"]
        ):
            raise ValueError(f"Original does not match the release register for {sheet}")
        fetch(directory / row["name"], dict(release, scan_id=sheet, source_sha256=row["sha256"]))

    with ThreadPoolExecutor(jobs) as executor:
        list(executor.map(download, rows))
    with tempfile.NamedTemporaryFile("w", dir=work, newline="", delete=False) as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    Path(f.name).replace(work / "25k-selected-originals.csv")
    print(f"Prepared {len(rows)} originals in {work}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    parser.add_argument("sheets", nargs="*", help="Omit to fetch all 291 physical originals")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    prepare(args.work, set(args.sheets), args.jobs)
