"""Anchor a faint/bowed geographic perimeter to measured native kilometre crossings while preserving named corners."""

import json
import math
import argparse
import cv2
import numpy as np
from pyproj import Proj
from measure import p, tps, rules, write_json
from refine import errors
from trace_native_border import trace

r = p / "review"


def run(n, profile):
    fn = n + ".json"
    base = json.loads((r / "adaptive-candidates" / fn).read_bytes())
    w, s, e, h = b = base["bounds"]
    pr = Proj(
        proj="tmerc",
        lon_0=6 * math.floor((w + e) / 12) + 3,
        ellps="krass",
        k=1,
        x_0=500000,
    )
    im = cv2.imread(
        str(p / "originals" / base["original"]),
        cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION,
    )
    gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    m = np.load(r / "measurements" / (n + ".npz"))["points"]
    G = m[:, :2]
    P = m[:, 2:4]
    km = np.rint(G / 1000).astype(int)
    withheld = (km[:, 0] + 2 * km[:, 1]) % 3 == 0

    def model(row):
        pts = [*row["corners"].values(), *row["other_gcps"]]
        en = np.array(pr(*np.array([q["lonlat"] for q in pts]).T)).T
        return tps(en, np.array([q["pixel"] for q in pts]))

    F = model(base)
    previous = json.loads((r / "continuous-edges" / fn).read_bytes())["edges"]
    if profile == "confirmed":
        implicated = [side for side, a in previous.items() if a["normal"][1] > 3.5]
    else:
        implicated = [side for side, a in previous.items() if a["normal"][1] >= 2.5]
    valmeta = {}
    controls = []
    erase = set()
    edge_candidates = {}
    for side in implicated:
        si, sv = ({"north": (1, h), "south": (1, s), "west": (0, w), "east": (0, e)})[
            side
        ]
        horizontal = si == 1
        stats, tr = trace(im, F, pr, b, side, profile == "converging")

        def ll(t):
            return (
                np.column_stack((w + t * (e - w), np.full_like(t, sv)))
                if horizontal
                else np.column_stack((np.full_like(t, sv), s + t * (h - s)))
            )

        def en(t):
            return np.array(pr(*ll(t).T)).T

        axis = 0 if horizontal else 1
        limits = en(np.array([0.023, 0.977]))[:, axis]
        targets = np.arange(math.ceil(min(limits) / 1000) * 1000, max(limits), 1000)
        lo = np.full_like(targets, 0.023)
        hi = np.full_like(targets, 0.977)
        for _ in range(28):
            mid = (lo + hi) / 2
            below = en(mid)[:, axis] < targets
            below = below if limits[0] < limits[1] else ~below
            lo = np.where(below, mid, lo)
            hi = np.where(below, hi, mid)
        fr = (lo + hi) / 2
        geo = en(fr)
        orig = F(geo)
        normal = np.column_stack(
            [np.interp(fr, tr["f"], tr["normal"][:, i]) for i in (0, 1)]
        )
        off = np.interp(fr, tr["f"], tr["path"])
        xy = orig + off[:, None] * normal
        dt = F(en(fr + 0.0001)) - orig
        dg = F(geo + ([0, 100] if horizontal else [100, 0])) - orig
        # A narrow normal search stays on the physical boundary selected from its two known labelled ends.
        c1, d1, s1 = rules(gray, xy, dt, reach=2)
        c2, d2, s2 = rules(gray, xy, dg, reach=14)
        dv = np.linalg.solve(
            np.stack((c1, c2), axis=1), np.column_stack((d1, d2))[:, :, None]
        ).reshape(-1, 2)
        ok = (s1 >= 6) & (s2 >= 16) & (np.abs(d2) < 12.5)
        good = np.flatnonzero(ok)
        if len(good) < (5 if profile == "confirmed" else 6):
            valmeta[side] = {"crossings": len(good), "held": 0}
            continue
        stride = 2 if profile == "confirmed" else 3
        selected = good[np.arange(len(good)) % stride != 1]
        test = good[1::stride]
        edge_candidates[side] = (geo[test], (xy + dv)[test])
        valmeta[side] = dict(crossings=len(good), held=len(test))
        erase.update(
            i
            for i, v in enumerate(base["other_gcps"])
            if abs(v["lonlat"][si] - sv) < 1e-7
        )
        for j in selected:
            controls.append(
                dict(
                    pixel=(xy[j] + dv[j]).round(2).tolist(),
                    lonlat=ll(fr)[j].round(11).tolist(),
                    method="Printed 1 km line crossing the continuously traced geographic neatline",
                )
            )
    cand = dict(
        base,
        other_gcps=[v for i, v in enumerate(base["other_gcps"]) if i not in erase]
        + controls,
    )
    F = model(cand)
    tests = {}
    for side, points in edge_candidates.items():
        g, xy = points
        valmeta[side]["error"] = errors(np.linalg.norm(F(g) - xy, axis=1))
    for side in ("north", "south", "west", "east"):
        tests[side], _ = trace(im, F, pr, b, side, profile == "converging")
    interior = errors(np.linalg.norm(F(G[withheld]) - P[withheld], axis=1))
    passed = (
        interior[1] <= 4.5
        and interior[0] <= 1.9
        and all(a["normal"][1] <= 3.5 and a["visible"] >= 72 for a in tests.values())
    )
    passed &= all(
        k in valmeta and valmeta[k].get("error", [999, 999])[1] < 4.5
        for k in implicated
    )
    meta = dict(
        id=n,
        source_sha256=base["sha256"],
        ready=bool(passed),
        stage="Held-out printed grid; traced geographic neatline",
        held=int(withheld.sum()),
        median=interior[0],
        p95=interior[1],
        edges=tests,
        withheld_boundary_crossings=valmeta,
        added_boundary_controls=len(controls),
    )
    folder = r / "traced-candidates"
    folder.mkdir(exist_ok=True)
    write_json(folder / fn, cand)
    folder = r / "traced-metrics"
    folder.mkdir(exist_ok=True)
    write_json(folder / fn, meta)
    if passed:
        cand["flags"] = []
        cand["manual_review"] = (
            (cand.get("manual_review") or "")
            + f' The accepted geographic corner pixels were held fixed. Independently held out {int(withheld.sum())} printed 1 km crossings and traced all four physical edges in {min(x["visible"] for x in tests.values())} or more native sections per side.'
        ).strip()
        write_json(r / "native" / fn, dict(meta, reason=""))
        write_json(r / "qualified" / fn, cand)
    print(
        n,
        passed,
        interior,
        [(k, v["visible"], v["normal"]) for k, v in tests.items()],
        valmeta,
        flush=True,
    )


if __name__ == "__main__":
    cv2.setNumThreads(1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", choices=["standard", "confirmed", "converging"], default="standard"
    )
    parser.add_argument("sheets", nargs="+")
    args = parser.parse_args()
    for sheet in args.sheets:
        run(sheet, args.profile)
