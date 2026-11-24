"""Compare a proposed native sheet warp with the two ink rules at each expected 1 km intersection."""

import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import cv2
import numpy as np
from pyproj import Proj

p = Path.cwd()
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "100k/archive_other"))
from stage_warps import write_json


def kernel(a, b):
    norm = ((a[:, None, :] - b[None, :, :]) ** 2).sum(axis=2)
    return norm * np.log(np.maximum(norm, 1e-100))


def tps(ground, pixels):
    center = ground.mean(axis=0)
    a = (ground - center) / 10000
    design = np.column_stack([np.ones(len(a)), a])
    matrix = np.block([[kernel(a, a), design], [design.T, np.zeros((3, 3))]])
    coeff = np.linalg.solve(matrix, np.vstack([pixels, np.zeros((3, 2))]))

    def predict(pos):
        v = (pos - center) / 10000
        return np.column_stack([kernel(v, a), np.ones(len(v)), v]) @ coeff

    return predict


def sample(im, x, y):
    return cv2.remap(
        im,
        x.astype("float32"),
        y.astype("float32"),
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    ).astype("float32")


def rules(im, xy, direction, reach=24):
    # Sample lines on the two sides of each candidate offset. Matching both ink rules
    # prevents a strong road or coast confined to one axis from defining a crossing.
    direction = direction / np.linalg.norm(direction, axis=1)[:, None]
    cross = direction[:, [1, 0]] * np.array([-1, 1])
    track = np.r_[-35:-5:2, 6:36:2]
    offsets = np.arange(-reach, reach + 1, dtype=float)
    pts = (
        xy[:, None, None, :]
        + direction[:, None, None, :] * track[None, None, :, None]
        + cross[:, None, None, :] * offsets[None, :, None, None]
    )
    n = len(xy)
    sz = (n * len(offsets), len(track))

    def lookup(d):
        v = pts + d * cross[:, None, None, :]
        return sample(im, v[:, :, :, 0].reshape(sz), v[:, :, :, 1].reshape(sz)).reshape(
            n, len(offsets), len(track)
        )

    center = lookup(0)
    contrast = np.minimum(lookup(3), lookup(-3)) - center
    profile = np.mean(np.clip(contrast, 0, 160), axis=2) - 0.035 * abs(offsets)
    best = np.argmax(profile, axis=1)
    a = np.arange(n)
    s = profile[a, best]
    local = np.abs(np.arange(len(offsets))[None, :] - best[:, None]) <= 1
    weights = np.maximum(0, profile) * local
    off = (weights @ offsets) / (weights.sum(axis=1) + 1e-8)
    return cross, off, s


def measure(row, im):
    w, s, e, n = row["bounds"]
    proj = Proj(
        proj="tmerc",
        lon_0=math.floor((w + e) / 12) * 6 + 3,
        ellps="krass",
        x_0=500000,
        k=1,
    )
    cp = [*row["corners"].values(), *row["other_gcps"]]
    g = np.array(proj(*np.array([z["lonlat"] for z in cp]).T)).T
    transform = tps(g, np.array([z["pixel"] for z in cp]))
    xmin, ymin = g.min(0)
    xmax, ymax = g.max(0)
    xs = np.arange(math.ceil(xmin / 1000) * 1000, xmax, 1000)
    ys = np.arange(math.ceil(ymin / 1000) * 1000, ymax, 1000)
    x, y = np.meshgrid(xs, ys)
    all_en = np.column_stack((x.ravel(), y.ravel()))
    lo, la = proj(*all_en.T, inverse=True)
    u = (lo - w) / (e - w)
    v = (la - s) / (n - s)
    ok = (u > 0.035) & (u < 0.965) & (v > 0.04) & (v < 0.96)
    en = all_en[ok]
    fractions = np.column_stack((u[ok], v[ok]))
    xy = transform(en)
    good = (
        (xy[:, 0] > 85)
        & (xy[:, 1] > 85)
        & (xy[:, 0] < im.shape[1] - 85)
        & (xy[:, 1] < im.shape[0] - 85)
    )
    en = en[good]
    xy = xy[good]
    fractions = fractions[good]
    if len(en) < 12:
        raise ValueError("Fewer than 12 projected interior grid intersections")
    dx = transform(en + [100, 0]) - xy
    dy = transform(en + [0, 100]) - xy
    c1, d1, s1 = rules(im, xy, dx)
    c2, d2, s2 = rules(im, xy, dy)
    rows = np.stack((c1, c2), axis=1)
    dxy = np.linalg.solve(rows, np.column_stack((d1, d2))[:, :, None]).reshape(-1, 2)
    keep = np.minimum(s1, s2) >= 18
    dmat = np.linalg.norm(en[:, None, :] - en[None, :, :], axis=2)
    np.fill_diagonal(dmat, np.inf)
    keep2 = np.zeros(len(en), bool)
    for i in np.flatnonzero(keep):
        near = np.argsort(dmat[i])[:12]
        near = near[keep[near]]
        if len(near) >= 3 and np.linalg.norm(dxy[i] - np.median(dxy[near], axis=0)) < 4:
            keep2[i] = True
    dist = np.linalg.norm(dxy, axis=1)
    quads = (fractions[:, 0] > 0.5).astype(int) + 2 * (fractions[:, 1] > 0.5).astype(
        int
    )
    held = int(keep2.sum())
    med = float(np.median(dist[keep2])) if held else None
    p95 = float(np.quantile(dist[keep2], 0.95)) if held else None
    meta = dict(
        examined=len(en),
        held=held,
        quadrants=np.bincount(quads[keep2], minlength=4).tolist(),
        median=round(med, 2) if held else None,
        p95=round(p95, 2) if held else None,
    )
    keep = keep2
    measurements = np.column_stack(
        [en[keep], xy[keep] + dxy[keep], np.minimum(s1, s2)[keep]]
    )
    return meta, measurements


def process(n):
    cv2.setNumThreads(1)
    fn = n + ".json"
    target = p / "review/native" / fn
    if target.exists():
        return
    raw = p / "review/amended" / fn
    if not raw.exists():
        raw = p / "review/proposed" / fn
    if not raw.exists():
        write_json(
            target, dict(id=n, ready=False, reason="No complete preliminary frame")
        )
        return
    row = json.loads(raw.read_bytes())
    base = dict(id=n, source_sha256=row["sha256"], ready=False)
    try:
        im = cv2.imread(
            str(p / "originals" / row["original"]),
            cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION,
        )
        assert list(im.shape[::-1]) == [row["width"], row["height"]], n
        meta, measured = measure(row, im)
        base.update(meta)
        why = []
        if row["flags"]:
            why.append("Flagged preliminary frame")
        if "_" in n and not row.get("manual_review"):
            why.append("Joined frame awaiting native review")
        if meta["held"] < 35 or min(meta["quadrants"]) < 4:
            why.append("Insufficient independent printed grid")
        if meta["p95"] is None or meta["p95"] > 5 or meta["median"] > 2.7:
            why.append("Printed grid discrepancy")
        if not why:
            write_json(p / "review/qualified" / fn, row)
        base.update(ready=not why, reason=" | ".join(why))
        np.savez_compressed(
            p / "review/measurements" / (n + ".npz"), points=measured.astype("float64")
        )
    except Exception as exc:
        base["reason"] = repr(exc)
    write_json(target, base)


if __name__ == "__main__":
    names = json.loads((p / "review/priority.json").read_bytes())
    provided = sys.argv[2:]
    names = provided or names
    with ProcessPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 4) as pool:
        for i, _ in enumerate(pool.map(process, names, chunksize=1), 1):
            if i % 100 == 0 or i == len(names):
                print(i, "/", len(names), "measured", flush=True)
