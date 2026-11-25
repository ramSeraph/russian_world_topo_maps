from pathlib import Path
import sys
import numpy as np
import json
import math
from PIL import Image
from pyproj import Proj
from concurrent.futures import ProcessPoolExecutor

base = Path.cwd()
dest = base / "analysis/grid"
dest.mkdir(exist_ok=True, parents=True)
originals = base / "mosaics"
rows = {
    f.stem: json.loads(f.read_bytes())
    for f in (base / (sys.argv[1] if len(sys.argv) > 1 else "checked")).glob("*.json")
}


def kernel(a, b):
    d = ((a[:, None, :] - b[None, :, :]) ** 2).sum(axis=2)
    return d * np.log(np.maximum(d, 1e-100))


def tps(en, pix):
    m = en.mean(0)
    scale = 10000
    a = (en - m) / scale
    p = np.column_stack([np.ones(len(a)), a])
    B = np.block([[kernel(a, a), p], [p.T, np.zeros((3, 3))]])
    coef = np.linalg.solve(B, np.vstack([pix, np.zeros((3, 2))]))
    return (
        lambda t: np.column_stack(
            [kernel((t - m) / scale, a), np.ones(len(t)), (t - m) / scale]
        )
        @ coef
    )


def line(im, x, y, slope):
    x, y = round(x), round(y)
    xx0 = np.arange(-38, 39, 2)
    xx = x + xx0
    off = np.arange(-28, 29)
    best = None
    for m in [slope - 0.035, slope - 0.017, slope, slope + 0.017, slope + 0.035]:
        yy = y + np.int32(np.rint(m * xx0)) + off[:, None]
        ctr = im[yy, xx]
        bg = np.minimum(im[yy - 3, xx], im[yy + 3, xx])
        s = np.mean(np.clip(bg - ctr, 0, 110), axis=1)
        s -= 0.025 * abs(off)
        i = np.argmax(s)
        if best is None or best[0] < s[i]:
            keep = abs(off - off[i]) < 2
            w = np.maximum(s[keep], 0) + 1e-7
            best = s[i], m, y + np.average(off[keep], weights=w)
    return best


def audit(n):
    r = rows[n]
    if len(r["corners"]) != 4:
        return
    A = np.asarray(Image.open(originals / r["original"]).convert("L")).astype("float32")
    p = Proj(
        proj="tmerc",
        lon_0=6 * math.floor((r["bounds"][0] + r["bounds"][2]) / 12) + 3,
        ellps="krass",
        k=1,
        x_0=500000,
    )
    cs = [*r["corners"].values(), *r.get("other_gcps", [])]
    en = np.array(p(*np.asarray([v["lonlat"] for v in cs]).T)).T
    px = np.asarray([v["pixel"] for v in cs])
    f = tps(en, px)
    g = []
    for E in np.arange(np.ceil(min(en[:, 0]) / 1000) * 1000, max(en[:, 0]), 1000):
        for N in np.arange(np.ceil(min(en[:, 1]) / 1000) * 1000, max(en[:, 1]), 1000):
            [[x, y], [xx, yy], [xx2, yy2]] = f(
                np.array([[E, N], [E + 100, N], [E, N + 100]])
            )
            lon, lat = p(E, N, inverse=True)
            w, s, e, t = r["bounds"]
            h, (iw) = A.shape
            if (
                lon < w + 0.012
                or lon > e - 0.012
                or lat < s + 0.009
                or lat > t - 0.009
                or x < 100
                or x > iw - 100
                or y < 100
                or y > h - 100
            ):
                continue
            hr, m, cy = line(A, x, y, (yy - y) / (xx - x))
            vr, q, cx = line(A.T, y, x, (xx2 - x) / (yy2 - y))
            xt = round(x)
            yt = round(y)
            u = (cx - q * yt + q * (cy - m * xt)) / (1 - m * q)
            v = cy + m * (u - xt)
            g.append({"en": [E, N], "pred": [x, y], "xy": [u, v], "strength": [hr, vr]})
    G = np.array([d["en"] for d in g])
    P = np.array([d["xy"] for d in g])
    pred = f(G)
    err = np.linalg.norm(P - pred, axis=1)
    keep = np.array([min(d["strength"]) for d in g]) > 18
    # Neighbouring independent measurements constrain isolated accidental matches to roads or line lettering.
    for i, d in enumerate(g):
        near = np.argsort(np.linalg.norm(G - G[i], axis=1))[1:11]
        consistent = (
            np.median((P - pred)[near[keep[near]]], axis=0)
            if keep[near].any()
            else np.array([0.0, 0.0])
        )
        d["ok"] = bool(keep[i] and np.linalg.norm((P - pred)[i] - consistent) < 4)
    keep = np.array([d["ok"] for d in g])
    summary = {
        "examined": len(g),
        "held": int(keep.sum()),
        "median": round(float(np.median(err[keep])), 2) if keep.any() else None,
        "p95": round(float(np.percentile(err[keep], 95)), 2) if keep.any() else None,
    }
    print(n, summary, flush=True)
    (dest / (n + ".json")).write_text(json.dumps(g, default=lambda x: float(x)))
    return g


if __name__ == "__main__":
    with ProcessPoolExecutor(3) as ex:
        list(ex.map(audit, sorted(rows)))
