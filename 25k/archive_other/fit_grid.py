"""Fit a sheet to its printed SK-42 grid and check independent interior and edge readings."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import math
from pathlib import Path

import cv2
import numpy as np
from pyproj import Transformer

from measure_frames import NAMES, projected
from check_crossings import scan_axis
from measure import tps
from refine import borders


def polynomial(ground, pixels):
    center = ground.mean(axis=0)

    def design(xy):
        x, y = ((xy - center) / 5000).T
        return np.column_stack([np.ones(len(x)), x, y, x * x, x * y, y * y])

    a = design(ground)
    weights = np.ones(len(a))
    for _ in range(4):
        coef = np.linalg.lstsq(
            a * weights[:, None], pixels * weights[:, None], rcond=None
        )[0]
        weights = 1 / np.maximum(1, np.linalg.norm(a @ coef - pixels, axis=1) / 2)
    return lambda xy: design(xy) @ coef


def distribution(points, bounds, proj):
    w, s, e, n = bounds
    chosen = []
    for v in (0.07, 0.36, 0.64, 0.93):
        for u in (0.07, 0.36, 0.64, 0.93):
            target = proj(w + (e - w) * u, s + (n - s) * v)
            dist = np.linalg.norm(points[:, :2] - target, axis=1) + 3 * np.maximum(
                0, 40 - points[:, 4]
            )
            dist[chosen] = np.inf
            chosen.append(int(dist.argmin()))
    return chosen


def fit_one(args):
    work, path = args
    row = json.loads(path.read_text())
    cv2.setNumThreads(1)
    im = cv2.imread(
        str(work / "selected-originals" / row["original"]),
        cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION,
    )
    m = np.load(path.with_suffix(".npz"))["points"]
    if len(m) < 32:
        raise ValueError(f"{path.stem}: only {len(m)} grid checks")
    pr = projected(row["bounds"])
    corners = row["corners"]
    native = np.array([pr(*corners[k]["lonlat"]) for k in NAMES])
    initial = np.array([corners[k]["pixel"] for k in NAMES])
    train = distribution(m, row["bounds"], pr)
    test = np.ones(len(m), dtype=bool)
    test[train] = False
    grid = m[train]
    predict = polynomial(grid[:, :2], grid[:, 2:4])
    prior = predict(native)
    final = initial.copy()
    corner_checks = {}
    for i, name in enumerate(NAMES):
        ax, ay = initial[i ^ 1] - initial[i], initial[3 - i] - initial[i]
        ax, ay = ax / np.linalg.norm(ax), ay / np.linalg.norm(ay)
        x = scan_axis(im, prior[i], ax, ay, 300)
        y = scan_axis(im, prior[i], ay, ax, 300)
        delta = np.array([x["offset"], y["offset"]])
        # Only accept a local line that continues across the collar and agrees with the independent grid extrapolation.
        for j, axis in enumerate([ax, ay]):
            read = (x, y)[j]
            if (
                abs(delta[j]) <= 10
                and read["outside"] >= 0.34
                and read["inside"] >= 0.25
                and read["separation"] >= 0.025
            ):
                final[i] += axis * (delta[j] - np.dot(final[i] - prior[i], axis))
        corner_checks[name] = dict(
            initial=initial[i].tolist(),
            extrapolated=prior[i].round(2).tolist(),
            extrapolation_error=round(float(np.linalg.norm(final[i] - prior[i])), 2),
        )
        corners[name]["pixel"] = final[i].round(2).tolist()
    g = np.vstack([native, grid[:, :2]])
    px = np.vstack([final, grid[:, 2:4]])
    F = tps(g, px)
    _, b = borders(pr, row, F, im)
    edge_training = []
    for side in ("north", "east", "south", "west"):
        choices = [q for q in b if q["side"] == side]
        for frac in (0.20, 0.50, 0.80):
            possible = [q for q in choices if abs(q["f"] - frac) < 0.095]
            if not possible:
                continue
            q = min(
                possible,
                key=lambda q: abs(q["f"] - frac) + 0.0005 * max(0, 50 - q["strength"]),
            )
            # Both the independent grid prediction and the printed border constrain this reading.
            if (
                abs(q["displacement"]) <= 10
                and np.linalg.norm(q["xy"] - F(q["en"][None, :])[0]) <= 11
            ):
                edge_training.append(q)
    if edge_training:
        g = np.vstack([g, [q["en"] for q in edge_training]])
        px = np.vstack([px, [q["xy"] for q in edge_training]])
        F = tps(g, px)
    edges, edge_points = borders(pr, row, F, im)
    for side in edges:
        held = [
            abs(q["displacement"])
            for q in edge_points
            if q["side"] == side
            and not any(
                other["side"] == side and abs(other["f"] - q["f"]) < 0.003
                for other in edge_training
            )
        ]
        edges[side]["independent_count"] = len(held)
        edges[side]["independent_max_px"] = round(max(held), 2) if held else None
    extras = [
        dict(
            lonlat=list(pr(*p[:2], inverse=True)),
            pixel=p[2:4].round(2).tolist(),
            method="Printed 1 km grid",
        )
        for p in grid
    ]
    extras += [
        dict(
            lonlat=q["ll"].tolist(),
            pixel=q["xy"].round(2).tolist(),
            method="Neatline and 1 km grid",
        )
        for q in edge_training
    ]
    errors = np.linalg.norm(F(m[test, :2]) - m[test, 2:4], axis=1)
    quant = np.quantile(errors, [0.5, 0.95, 1]).round(2).tolist()
    row["other_gcps"] = extras
    row["method"] = "Grayscale neatline and printed 1 km grid"
    row["warp_tolerance_px"] = 0.025
    row["native_geographic_crs"] = (
        "+proj=longlat +ellps=krass +towgs84="
        + ("22,-126,-85" if row["country"] == "Estonia" else "24,-124,-82")
        + " +type=crs"
    )
    row["source_crs"] = row["native_geographic_crs"].replace(
        "+proj=longlat",
        f"+proj=tmerc +k=1 +lat_0=0 +lon_0={6*math.floor((row['bounds'][0]+row['bounds'][2])/12)+3} +x_0=500000 +y_0=0 +units=m",
    )
    WGS = Transformer.from_crs(row["native_geographic_crs"], 4326, always_xy=True)
    outline = np.array([corners[k]["lonlat"] for k in NAMES])
    ring = [
        WGS.transform(*((1 - t) * a + t * z))
        for a, z in zip(outline, np.roll(outline, -1, axis=0))
        for t in np.arange(16) / 16
    ]
    row["footprint"] = dict(type="Polygon", coordinates=[ring + ring[:1]])
    checks = dict(
        held=len(errors),
        median=quant[0],
        p95=quant[1],
        maximum=quant[2],
        corners=corner_checks,
        edges=edges,
        withheld=[
            dict(lonlat=list(pr(*p[:2], inverse=True)), pixel=p[2:4].tolist())
            for p in m[test]
        ],
    )
    dest = work / "fitted" / path.name
    dest.with_suffix(".tmp").write_text(
        json.dumps(dict(control=row, checks=checks), separators=(",", ":")) + "\n"
    )
    dest.with_suffix(".tmp").replace(dest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args()
    root = args.work.resolve()
    (root / "fitted").mkdir(exist_ok=True)
    files = sorted((root / "measurements").glob("*.json"))
    with ProcessPoolExecutor(args.jobs) as workers:
        for i, _ in enumerate(workers.map(fit_one, [(root, f) for f in files]), 1):
            if i % 50 == 0 or i == len(files):
                print(i, "/", len(files), "grid fits", flush=True)
