"""Check outer graticules and refine bent paper using independent printed grid crossings."""

import argparse
import json
import math
from concurrent.futures import ProcessPoolExecutor
import cv2
import numpy as np
from pyproj import Proj
from measure import tps, rules, p, write_json
from check_crossings import scan_axis

NAMES = ["NW", "NE", "SE", "SW"]


def errors(d):
    return np.quantile(d, [0.5, 0.95]).round(2).tolist()


def borders(pr, r, F, im):
    w, s, e, n = r["bounds"]
    stats = {}
    controls = []
    for side in ("north", "south", "west", "east"):
        horiz = side in ("north", "south")

        def ll(f):
            return (
                (w + (e - w) * f, np.full_like(f, n if side == "north" else s))
                if horiz
                else (np.full_like(f, w if side == "west" else e), s + (n - s) * f)
            )

        def grid(f):
            return np.array(pr(*ll(f))).T

        axis = 0 if horiz else 1
        limit = grid(np.array([0.022, 0.978]))[:, axis]
        targets = np.arange(math.ceil(min(limit) / 1000) * 1000, max(limit), 1000.0)
        lo = np.full_like(targets, 0.022)
        hi = np.full_like(targets, 0.978)
        for _ in range(26):
            middle = (lo + hi) / 2
            below = grid(middle)[:, axis] < targets
            below = below if limit[0] < limit[1] else ~below
            lo = np.where(below, middle, lo)
            hi = np.where(below, hi, middle)
        f = (hi + lo) / 2
        lls = np.array(ll(f)).T
        en = grid(f)
        xy = F(en)
        dt = F(grid(f + 0.0001)) - xy
        dg = F(en + ([0, 100] if horiz else [100, 0])) - xy
        c1, off1, s1 = rules(im, xy, dt, reach=18)
        c2, off2, s2 = rules(im, xy, dg, reach=18)
        diff = np.linalg.solve(
            np.stack((c1, c2), 1), np.column_stack((off1, off2))[:, :, None]
        ).reshape(-1, 2)
        # Use a high-contrast two-direction crossing for a control; use the whole visible line for independent edge checking.
        good = s1 >= 22
        near = np.abs(np.arange(len(f))[:, None] - np.arange(len(f))) <= 3
        np.fill_diagonal(near, False)
        consistent = []
        for i in range(len(f)):
            others = good & near[i]
            consistent.append(
                others.sum() >= 1 and abs(off1[i] - np.median(off1[others])) < 3.5
            )
        good &= np.array(consistent)
        stats[side] = {
            "read": int(good.sum()),
            "possible": len(f),
            "normal": errors(abs(off1[good])) if good.any() else [None, None],
        }
        g2 = good & (s2 >= 26)
        for i in np.flatnonzero(g2):
            others = g2 & near[i]
            if (
                others.sum() < 1
                or np.linalg.norm(diff[i] - np.median(diff[others], axis=0)) > 4
            ):
                continue
            controls.append(
                dict(
                    side=side,
                    f=float(f[i]),
                    ll=lls[i],
                    en=en[i],
                    xy=xy[i] + diff[i],
                    strength=min(s1[i], s2[i]),
                    displacement=float(off1[i]),
                )
            )
    return stats, controls


def near_corners(r, pr, G, P, im):
    cps = [r["corners"][k] for k in NAMES]
    pixels = np.array([c["pixel"] for c in cps])
    gc = np.array(pr(*np.array([c["lonlat"] for c in cps]).T)).T
    result = pixels.copy()
    log = {}
    for i, k in enumerate(NAMES):
        distances = np.linalg.norm(G - gc[i], axis=1)
        ix = np.argsort(distances)[:48]
        if distances[ix[7]] > 6500 or len(ix) < 20:
            continue
        ux, uy = ((G[ix] - gc[i]) / 4000).T
        x = np.column_stack([np.ones(len(ix)), ux, uy, ux**2, ux * uy, uy**2])
        wt = 1 / (1 + distances[ix] / 2500) ** 2
        for _ in range(3):
            fit = np.linalg.lstsq(x * wt[:, None], P[ix] * wt[:, None], rcond=None)[0]
            fiterr = np.linalg.norm(x @ fit - P[ix], axis=1)
            wt = 1 / (1 + distances[ix] / 2500) ** 2 / np.maximum(1, fiterr / 2.5)
        pred = fit[0]
        base = pixels[i]
        delta = np.linalg.norm(pred - base)
        if delta < 4:
            continue
        a = pixels[i ^ 1] - base
        b = pixels[3 - i] - base
        a /= np.linalg.norm(a)
        b /= np.linalg.norm(b)
        # The ink crossing is searched near the interior-grid extrapolation, which can recover a bad original control.
        sa = scan_axis(im, pred, a, b, r["estimated_dpi"])
        sb = scan_axis(im, pred, b, a, r["estimated_dpi"])
        point = pred + a * sa["offset"] + b * sb["offset"]
        dist = np.linalg.norm(point - pred)
        if (
            dist < max(7, min(13, delta * 0.40))
            and min(sa["outside"], sb["outside"]) > 0.42
            and min(sa["inside"], sb["inside"]) > 0.32
            and min(sa["separation"], sb["separation"]) > 0.035
            and np.linalg.norm(point - base) > 2
        ):
            result[i] = point
            log[k] = {
                "old": base.round(2).tolist(),
                "pixel": point.round(2).tolist(),
                "grid_extrapolation_px": round(dist, 2),
            }
    return gc, result, log


def controls_out(pr, points):
    return [
        dict(
            pixel=np.round(xy, 2).tolist(),
            lonlat=np.round(ll, 11).tolist(),
            method=kind,
        )
        for ll, xy, kind in points
    ]


def run(task):
    cv2.setNumThreads(1)
    n, force, promote, deep, mesh = task
    fn = n + ".json"
    target = p / "review/refinement" / fn
    if target.exists() and not force:
        return
    old = json.loads((p / "review/native" / fn).read_bytes())
    a = p / "review/amended" / fn
    if not a.exists():
        a = p / "review/proposed" / fn
    mf = p / "review/measurements" / (n + ".npz")
    if not a.exists() or not mf.exists():
        return
    r = json.loads(a.read_bytes())
    m = np.load(mf)["points"]
    summary = dict(
        id=n,
        source_sha256=r["sha256"],
        initial_flags=r["flags"],
        joined="_" in n,
        ready=False,
    )
    if len(m) < 68:
        write_json(target, dict(summary, reason="Sparse printed grid", held=len(m)))
        return
    im = cv2.imread(
        str(p / "originals" / r["original"]),
        cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION,
    )
    G = m[:, :2]
    P = m[:, 2:4]
    strength = m[:, 4]
    w, s, e, north = r["bounds"]
    pr = Proj(
        proj="tmerc",
        k=1,
        x_0=500000,
        lon_0=6 * math.floor((w + e) / 12) + 3,
        ellps="krass",
    )
    gc, pc, fix = near_corners(r, pr, G, P, im)
    if (p / "review/gallery-accepted" / fn).exists():
        accepted = json.loads((p / "review/gallery-accepted" / fn).read_bytes())
        if accepted["sha256"] != r["sha256"]:
            raise ValueError("Reviewed source changed")
        for k, xy in accepted["pixels"].items():
            pc[NAMES.index(k)] = xy
            fix.pop(k, None)
    if (p / "review/manually-confirmed" / fn).exists():
        fixed = json.loads((p / "review/manually-confirmed" / fn).read_bytes())
        for k in fixed["pixels"]:
            pc[NAMES.index(k)] = r["corners"][k]["pixel"]
            fix.pop(k, None)
    extra = r["other_gcps"]
    gc = np.vstack([gc, *[pr(*t["lonlat"]) for t in extra]])
    pc = np.vstack([pc, *[t["pixel"] for t in extra]])
    base = tps(gc, pc)
    prior = errors(np.linalg.norm(base(G) - P, axis=1))
    summary.update(
        original=prior, corner_edits=fix, grid_order="dense" if deep else "standard"
    )
    num = mesh or ((6 if prior[1] < 8 else 7) if deep else (4 if prior[1] < 7 else 5))
    chosen = []
    for u in np.linspace(0.08, 0.92, num):
        for v in np.linspace(0.08, 0.92, num):
            pos = np.array(pr(w + u * (e - w), s + v * (north - s)))
            dist = np.linalg.norm(G - pos, axis=1) + 9 * np.maximum(0, 48 - strength)
            if chosen:
                dist[chosen] = np.inf
            chosen.append(dist.argmin())
    kept = np.ones(len(G), bool)
    kept[chosen] = False
    vG = G[kept]
    vP = P[kept]
    lo, la = pr(*vG.T, inverse=True)
    quad = (lo > (w + e) / 2).astype(int) + 2 * (la > (s + north) / 2).astype(int)
    quad = np.bincount(quad, minlength=4).tolist()
    interior = [
        (pr(*G[i], inverse=True), P[i], "Printed 1 km grid intersection")
        for i in chosen
    ]
    sg = np.vstack([gc, G[chosen]])
    sp = np.vstack([pc, P[chosen]])
    F = tps(sg, sp)
    ed, bx = borders(pr, r, F, im)
    selected = []
    edge_indices = []
    baseedge = ed
    for side in ed:
        vals = [j for j, q in enumerate(bx) if q["side"] == side]
        if not vals or (ed[side]["normal"][1] or 0) < 1.6:
            continue
        avail = set(vals)
        for frac in (0.12, 0.34, 0.56, 0.78, 0.94):
            if not avail:
                break
            j = min(
                avail,
                key=lambda i: abs(bx[i]["f"] - frac)
                + 0.0007 * max(0, 45 - bx[i]["strength"]),
            )
            if abs(bx[j]["f"] - frac) > 0.11:
                continue
            avail.remove(j)
            edge_indices.append(j)
            selected.append(
                (
                    bx[j]["ll"],
                    bx[j]["xy"],
                    "Printed geographic neatline and 1 km grid crossing",
                )
            )
    if selected:
        F = tps(
            np.vstack([sg, [bx[j]["en"] for j in edge_indices]]),
            np.vstack([sp, [bx[j]["xy"] for j in edge_indices]]),
        )
        ed, bx2 = borders(pr, r, F, im)
        # Exclude training positions in the independent, native border check.
        for side in ed:
            targetf = [bx[j]["f"] for j in edge_indices if bx[j]["side"] == side]
            withheld = [
                abs(q["displacement"])
                for q in bx2
                if q["side"] == side and all(abs(q["f"] - t) > 0.002 for t in targetf)
            ]
            if withheld:
                ed[side]["withheld"] = dict(
                    count=len(withheld), normal=errors(withheld)
                )
    after = errors(np.linalg.norm(F(vG) - vP, axis=1))
    summary.update(
        held=len(vG),
        quadrants=quad,
        median=after[0],
        p95=after[1],
        edges_before=baseedge,
        edges=ed,
        added=len(interior) + len(selected),
    )
    why = []
    if min(quad) < 7 or after[1] > 3.75 or after[0] > 1.9:
        why.append("Interior grid")
    if any(
        q["read"] < max(5, q["possible"] * 0.43)
        or q["normal"][1] is None
        or q["normal"][1] > 3.5
        for q in ed.values()
    ):
        why.append("Native neatline")
    if selected and any(
        q.get("withheld", {}).get("count", 0) < 3 or q["withheld"]["normal"][1] > 3.5
        for side, q in ed.items()
        if any(bx[j]["side"] == side for j in edge_indices)
    ):
        why.append("Withheld edge crossings")
    summary["ready"] = not why
    summary["reason"] = " | ".join(why)
    for k, q in fix.items():
        r["corners"][k]["pixel"] = q["pixel"]
    r["other_gcps"] = r["other_gcps"] + controls_out(pr, interior + selected)
    (p / "review/refinement-candidates").mkdir(exist_ok=True)
    write_json(p / "review/refinement-candidates" / fn, r)
    if not why and promote:
        r["flags"] = []
        r["manual_review"] = (
            (r.get("manual_review") or "")
            + f" Native grid verification: {len(vG)} withheld two-axis printed intersections, median {after[0]} px and 95th percentile {after[1]} px. All four printed neatlines independently traced."
        ).strip()
        write_json(p / "review/qualified" / fn, r)
        write_json(
            p / "review/native" / fn,
            dict(
                old,
                ready=True,
                reason="",
                held=len(vG),
                quadrants=quad,
                p95=after[1],
                median=after[0],
                stage="withheld-grid-and-edges",
            ),
        )
    write_json(target, summary)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--deep", action="store_true")
    ap.add_argument("--mesh", type=int)
    ap.add_argument("--promote", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("names", nargs="*")
    args = ap.parse_args()
    out = p / "review/refinement"
    out.mkdir(exist_ok=True)
    ids = args.names or [
        n
        for n in json.loads((p / "review/priority.json").read_bytes())
        if not json.loads((p / "review/native" / (n + ".json")).read_bytes()).get(
            "ready"
        )
    ]
    if args.limit:
        ids = ids[: args.limit]
    with ProcessPoolExecutor(args.jobs) as pool:
        for i, _ in enumerate(
            pool.map(
                run, ((n, args.force, args.promote, args.deep, args.mesh) for n in ids)
            ),
            1,
        ):
            if i % 100 == 0 or i == len(ids):
                print(i, "/", len(ids), flush=True)
