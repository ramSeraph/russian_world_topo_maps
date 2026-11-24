"""Follow the complete labelled outer rule through faint ink and nearby unrelated lines."""

import json
import math
import argparse
import cv2
import numpy as np
from pyproj import Proj
from measure import p, tps, write_json, sample
from refine import errors

r = p / "review"


def trace(img, F, pr, bounds, side, use_margin=False):
    w, s, e, n = bounds
    f = np.linspace(0.007, 0.993, 141)
    h = side in ("north", "south")

    def geo(f):
        return np.array(
            pr(
                w + f * (e - w) if h else np.full_like(f, w if side == "west" else e),
                np.full_like(f, n if side == "north" else s) if h else s + f * (n - s),
            )
        ).T

    en = geo(f)
    xy = F(en)
    tan = F(geo(f + 0.0001)) - xy
    tan /= np.linalg.norm(tan, axis=1)[:, None]
    normal = tan[:, [1, 0]] * [-1, 1]
    vec = np.array(pr((w + e) / 2, (s + n) / 2)) - en
    sign = np.sign((normal * (F(en + vec * 0.0001) - xy)).sum(axis=1))
    normal *= sign[:, None]
    # Positive normal offsets point into the printed map, away from the exterior collar.
    offsets = np.arange(-24.0, 24.5, 0.5)
    steps = np.r_[-22:-3:2, 3:23:2]
    pts = (
        xy[:, None, None, :]
        + normal[:, None, None, :] * offsets[None, :, None, None]
        + tan[:, None, None, :] * steps[None, None, :, None]
    )

    def read(gray, d):
        pos = pts + normal[:, None, None, :] * d
        columns = pos.shape[2]
        return sample(
            gray,
            pos[:, :, :, 0].reshape(-1, columns),
            pos[:, :, :, 1].reshape(-1, columns),
        ).reshape(pos.shape[:3])

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 1]
    ink = (read(gray, -3) + read(gray, 3)) / 2 - read(gray, 0)
    strength = np.median(np.clip(ink, -45, 165), axis=2)
    if use_margin:
        boundary = np.median(np.clip(read(hsv, 5) - read(hsv, -5), -100, 120), axis=2)
        signal = (
            (0.50 * strength + 3.8 * boundary - 0.15 * np.abs(offsets)[None, :])
            if side == "east"
            else strength + 0.30 * boundary - 0.22 * np.abs(offsets)[None, :]
        )
    else:
        boundary = np.mean(np.clip(read(hsv, 8) - read(hsv, -8), -50, 90), axis=2)
        signal = strength + 0.30 * boundary - 0.22 * np.abs(offsets)[None, :]
    # A physical paper rule follows a smooth track between the known labelled ends. The score retains faint portions.
    jump = np.abs(offsets[:, None] - offsets[None, :])
    pen = 2.7 * jump + 1.8 * jump**2
    scores = signal[0] - abs(offsets) * 4
    prev = []
    for z in signal[1:]:
        ex = scores[:, None] - pen
        parent = np.argmax(ex, axis=0)
        prev.append(parent)
        scores = z + ex[parent, np.arange(len(z))]
    path = [int(np.argmax(scores - abs(offsets) * 4))]
    for parent in prev[::-1]:
        path.append(int(parent[path[-1]]))
    path = np.array(path[::-1])
    best = offsets[path]
    amplitude = strength[np.arange(len(f)), path]
    valid = amplitude >= 10
    support = valid.mean()
    valid &= np.abs(np.diff(best, prepend=best[0])) <= 2.6
    vals = abs(best[valid])
    meta = dict(
        samples=len(f),
        visible=int(valid.sum()),
        coverage=round(float(support), 3),
        normal=errors(vals) if len(vals) else [None, None],
        longest_error=round(float(vals.max()), 2) if len(vals) else None,
    )
    return meta, dict(f=f, xy=xy, normal=normal, path=best, ink=amplitude)


def run(n, use_margin):
    fn = n + ".json"
    cand = next(
        (
            r / a / fn
            for a in ("adaptive-candidates", "refinement-candidates")
            if (r / a / fn).is_file()
        ),
        None,
    )
    if not cand:
        return
    row = json.loads(cand.read_bytes())
    b = row["bounds"]
    pr = Proj(
        proj="tmerc",
        ellps="krass",
        lon_0=6 * math.floor((b[0] + b[2]) / 12) + 3,
        k=1,
        x_0=500000,
    )
    c = [*row["corners"].values(), *row["other_gcps"]]
    F = tps(
        np.array(pr(*np.array([q["lonlat"] for q in c]).T)).T,
        np.array([q["pixel"] for q in c]),
    )
    img = cv2.imread(
        str(p / "originals" / row["original"]),
        cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION,
    )
    stats = {}
    records = {}
    folder = r / "continuous-edges"
    folder.mkdir(exist_ok=True)
    for side in ("north", "south", "west", "east"):
        m, track = trace(img, F, pr, b, side, use_margin)
        stats[side] = m
        for k, v in track.items():
            records[side + "_" + k] = v
    write_json(folder / fn, dict(id=n, sha256=row["sha256"], edges=stats))
    np.savez_compressed(folder / (n + ".npz"), **records)
    print(n, [(k, q["visible"], q["normal"]) for k, q in stats.items()], flush=True)


if __name__ == "__main__":
    cv2.setNumThreads(1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--margin", action="store_true")
    parser.add_argument("sheets", nargs="+")
    args = parser.parse_args()
    for sheet in args.sheets:
        run(sheet, args.margin)
