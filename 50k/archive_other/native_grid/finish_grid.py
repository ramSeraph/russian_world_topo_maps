"""Use a held-back third of the 1km grid to validate adaptive interior paper corrections."""

import cv2
import json
import math
import sys
import numpy as np
from itertools import product
from pyproj import Proj
from measure import p, tps, write_json
from refine import borders, errors

root = p / "review"


def fit_sheet(n):
    fn = n + ".json"
    cand = root / "refinement-candidates" / fn
    if not cand.exists():
        return
    r = json.loads(cand.read_bytes())
    m = np.load(root / "measurements" / (n + ".npz"))["points"]
    G = m[:, :2]
    P = m[:, 2:4]
    strength = m[:, 4]
    w, s, e, h = r["bounds"]
    pr = Proj(
        proj="tmerc",
        lon_0=6 * math.floor((w + e) / 12) + 3,
        ellps="krass",
        k=1,
        x_0=500000,
    )
    # Full columns/rows of source km crosses remain in every third of the grid; test points cannot be selected.
    kms = np.rint(G / 1000).astype(int)
    validation = (kms[:, 0] + 2 * kms[:, 1]) % 3 == 0
    ix = np.flatnonzero(~validation)
    vv = np.flatnonzero(validation)
    evalid = G[vv]
    pvalid = P[vv]
    angle = np.array(pr(*evalid.T, inverse=True)).T
    quad = np.bincount(
        (angle[:, 0] > (w + e) / 2).astype(int)
        + 2 * (angle[:, 1] > (s + h) / 2).astype(int),
        minlength=4,
    ).tolist()
    assert min(quad) >= 4, (n, quad)
    base = [
        *r["corners"].values(),
        *[
            a
            for a in r["other_gcps"]
            if a.get("method") != "Printed 1 km grid intersection"
        ],
    ]
    baseg = np.array(pr(*np.array([q["lonlat"] for q in base]).T)).T
    basep = np.array([q["pixel"] for q in base])
    picked = []
    for u, v in product(np.linspace(0.08, 0.92, 5), repeat=2):
        pt = np.array(pr(w + u * (e - w), s + v * (h - s)))
        scores = np.linalg.norm(G[ix] - pt, axis=1) + 10 * np.maximum(
            0, 45 - strength[ix]
        )
        scores[np.isin(ix, picked)] = np.inf
        picked.append(int(ix[scores.argmin()]))
    # Place extra control only where an observed displacement is also supported by nearby print.
    dist = np.linalg.norm(G[:, None, :] - G[None, :, :], axis=2)
    neighbours = np.argsort(dist[:, ix], axis=1)[:, 1:5]
    strong = strength >= 22
    for j in range(65):
        F = tps(np.vstack([baseg, G[picked]]), np.vstack([basep, P[picked]]))
        res = P - F(G)
        mag = np.linalg.norm(res, axis=1)
        adj = np.median(res[ix][neighbours], axis=1)
        agreement = np.linalg.norm(res - adj, axis=1)
        z = mag[ix] / (1 + 0.15 * np.maximum(0, agreement[ix] - 1))
        z *= np.where(strong[ix], 1, 0.8)
        z[np.isin(ix, picked)] = -np.inf
        if np.quantile(mag[ix], 0.95) < 1.35 or len(picked) >= 85:
            break
        i = int(ix[z.argmax()])
        picked.append(i)
    # Refit if the cap was reached after appending a final training crossing.
    F = tps(np.vstack([baseg, G[picked]]), np.vstack([basep, P[picked]]))
    val = errors(np.linalg.norm(F(evalid) - pvalid, axis=1))
    im = cv2.imread(
        str(p / "originals" / r["original"]),
        cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION,
    )
    edges, aux = borders(pr, r, F, im)
    r["other_gcps"] = [
        q
        for q in r["other_gcps"]
        if q.get("method") != "Printed 1 km grid intersection"
    ] + [
        dict(
            pixel=P[i].round(2).tolist(),
            lonlat=np.round(pr(*G[i], inverse=True), 11).tolist(),
            method="Printed 1 km grid intersection",
        )
        for i in picked
    ]
    current = json.loads((root / "native" / fn).read_bytes())
    meta = dict(
        id=n,
        source_sha256=r["sha256"],
        stage="independent adaptive printed grid",
        median=val[0],
        p95=val[1],
        held=len(vv),
        quadrants=quad,
        training=len(picked),
        edges=edges,
        ready=False,
    )
    failures = []
    if val[1] > 4.5 or val[0] > 1.9:
        failures.append("Interior grid")
    if any(
        a["read"] < max(5, a["possible"] * 0.43)
        or a["normal"][1] is None
        or a["normal"][1] > 3.5
        for a in edges.values()
    ):
        failures.append("Native neatline")
    meta["reason"] = " | ".join(failures)
    meta["ready"] = not failures
    out = root / "adaptive"
    out.mkdir(exist_ok=True)
    write_json(out / fn, meta)
    out = root / "adaptive-candidates"
    out.mkdir(exist_ok=True)
    write_json(out / fn, r)
    if not failures:
        r["flags"] = []
        r["manual_review"] = (
            (r.get("manual_review") or "")
            + f" Adaptive paper correction uses {len(picked)} training intersections; {len(vv)} spatially interleaved, unused 1 km crosses agree to median {val[0]} and p95 {val[1]} native pixels."
        ).strip()
        write_json(root / "native" / fn, dict(current, **meta))
        write_json(root / "qualified" / fn, r)
    print(n, meta["held"], val, meta["reason"], flush=True)


if __name__ == "__main__":
    ids = sys.argv[1:] or json.loads((root / "priority.json").read_bytes())
    cv2.setNumThreads(1)
    for n in ids:
        if not (root / "qualified" / (n + ".json")).exists():
            fit_sheet(n)
