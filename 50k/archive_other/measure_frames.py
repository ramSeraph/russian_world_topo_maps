"""Measure initial frame corners on released originals and prepare native grid checks."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile

from fetch_released import selection

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "100k" / "archive_other"))
import apply_reviewed_controls
import check_crossings
import find_controls
import red_controls
import refine_frames
from stage_warps import prepare, write_json


def measure(task):
    work, row = task
    archive = row["source"] == "Archive.org"
    root = work / ("archive" if archive else "red-atlas")
    images = "originals" if archive else "mosaics"
    source = root / images / row["original"]
    with source.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != row["source_sha256"]:
            raise ValueError(f"Original differs from the release: {source}")
    native = source.stem + ".json"
    first = root / "controls" / native
    if archive:
        find_controls.stage((root, root / "receipts" / native))
        refine_frames.refine((root, first))
        first = root / "refined" / native
    else:
        red_controls.stage((root, root / "retrieval" / native))
    check_crossings.check((root, images, root / "checked", first))
    measured = json.loads((root / "checked" / native).read_bytes())
    if measured["sha256"] != row["source_sha256"]:
        raise ValueError(f"Cached corner readings use another edition: {native}")
    if not archive:
        return

    grid = work / "grid"
    link = grid / "originals" / row["original"]
    if not os.path.lexists(link):
        link.symlink_to(source)
    elif not link.samefile(source):
        raise ValueError(f"Conflicting measurement input: {link}")
    name = row["scan_id"] + ".json"
    review = grid / "review"
    with zipfile.ZipFile(HERE / "review-inputs.zip") as overrides:
        for directory in ("amended", "manually-confirmed", "gallery-accepted"):
            key = directory + "/" + name
            if key in overrides.namelist():
                reading = json.loads(overrides.read(key))
                if reading["sha256"] != row["source_sha256"]:
                    raise ValueError(f"Review input has the wrong source digest: {key}")
                write_json(review / key, reading)
    if (review / "amended" / name).exists():
        return
    edits = json.loads((HERE / "reviewed-controls.json").read_bytes())
    if source.stem in edits:
        measured = apply_reviewed_controls.apply(measured, edits[source.stem])
    info = dict(
        row,
        sha256=row["source_sha256"],
        width=row["source_width"],
        height=row["source_height"],
    )
    write_json(review / "proposed" / name, prepare(measured, info))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    parser.add_argument("sheets", nargs="*")
    parser.add_argument("--jobs", type=int, default=3)
    args = parser.parse_args()
    work = args.work.resolve()
    rows = selection(args.sheets)
    os.environ["OMP_THREAD_LIMIT"] = "1"
    for name in ("archive", "red-atlas"):
        for sub in ("controls", "checked", "orientation", "refined"):
            (work / name / sub).mkdir(parents=True, exist_ok=True)
    grid = work / "grid"
    (grid / "originals").mkdir(parents=True, exist_ok=True)
    for sub in (
        "proposed",
        "amended",
        "manually-confirmed",
        "gallery-accepted",
        "native",
        "measurements",
        "qualified",
    ):
        (grid / "review" / sub).mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(args.jobs) as pool:
        for _ in pool.map(measure, ((work, row) for row in rows)):
            pass
    write_json(
        grid / "review" / "priority.json",
        [r["scan_id"] for r in rows if r["source"] == "Archive.org"],
    )
    print(f"Measured {len(rows):,} source frames.")


if __name__ == "__main__":
    main()
