"""Measure Baltic 1:25,000 map frames and check them against their printed kilometre grid."""

import argparse
import csv
import hashlib
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from pyproj import Proj

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(REPO / "100k/archive_other"),
    str(REPO / "50k/archive_other/native_grid"),
]
from refine_frames import frame, inner_corner  # noqa: E402
from measure import measure as grid_measure  # noqa: E402
from stage_controls import NAMES, coordinates, sheet_to_bounds  # noqa: E402


def projected(bounds):
    return Proj(
        proj="tmerc",
        ellps="krass",
        k=1,
        x_0=500000,
        lon_0=6 * math.floor((bounds[0] + bounds[2]) / 12) + 3,
    )


def measure_one(task):
    root, entry, force = task
    source = root / "selected-originals" / entry["name"]
    dest = root / "measurements" / (source.stem + ".json")
    cv2.setNumThreads(1)
    if dest.exists() and not force:
        old = json.loads(dest.read_text())
        if old["sha256"] == entry["sha256"]:
            return
    with source.open("rb") as f:
        if hashlib.file_digest(f, "sha256").hexdigest() != entry["sha256"]:
            raise ValueError(f"Wrong original for {source.name}")
    im = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION)
    rectangles = np.asarray([sheet_to_bounds(k) for k in source.stem.split("_")])
    bounds = [*rectangles[:, :2].min(axis=0), *rectangles[:, 2:].max(axis=0)]
    if source.stem == "O34-095-3-3_O34-095-3-4":
        if (
            entry["sha256"]
            != "be0845d57ad2b3e8fc2dee5a42d47d5b7626a724077c07df46b862eda089c8ae"
        ):
            raise ValueError("The Mērsrags extent was read from a different scan")
        bounds[2] = (
            23 + 9 / 60
        )  # The NE and SE collars print 23°09′, inside the eastern cell.
    lonlat = coordinates(bounds)
    anchors, scores = frame(im)
    readings = [inner_corner(im, anchors, i) for i in range(4)]
    corners = {
        k: dict(pixel=r["pixel"], lonlat=lonlat[k]) for k, r in zip(NAMES, readings)
    }
    row = dict(
        scan_id=source.stem,
        original=source.name,
        width=im.shape[1],
        height=im.shape[0],
        sha256=entry["sha256"],
        country=entry["country"],
        year=int(entry["edition_year"]),
        source="Archive.org",
        source_url="https://archive.org/details/" + entry["collection"],
        archive_member=entry["member"],
        bounds=bounds,
        corners=corners,
        other_gcps=[],
        outer_support=scores,
        readings=readings,
        component_ids=source.stem.split("_"),
    )
    meta, points = grid_measure(row, im)
    row.update(initial_grid=meta)
    np.savez_compressed(dest.with_suffix(".npz"), points=points)
    dest.with_suffix(".tmp").write_text(json.dumps(row, separators=(",", ":")) + "\n")
    dest.with_suffix(".tmp").replace(dest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    parser.add_argument("sheets", nargs="*")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    work = args.work.resolve()
    (work / "measurements").mkdir(exist_ok=True)
    rows = list(csv.DictReader((work / "25k-selected-originals.csv").open()))
    if args.sheets:
        rows = [row for row in rows if Path(row["name"]).stem in args.sheets]
    with ProcessPoolExecutor(args.jobs) as pool:
        for i, _ in enumerate(
            pool.map(measure_one, [(work, r, args.force) for r in rows]), 1
        ):
            if i % 40 == 0 or i == len(rows):
                print(i, "/", len(rows), "frames measured", flush=True)
