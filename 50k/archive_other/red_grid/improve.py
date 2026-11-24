from pathlib import Path
from itertools import product
import json
import math
import numpy as np
from pyproj import Proj
from lattice import tps

p = Path.cwd()
src = p
out = p / "analysis"
edits = {}
summary = []


def metrics(dist):
    return [round(float(q), 2) for q in np.quantile(dist, [0.5, 0.95, 1])]


for f in sorted((src / "checked").glob("*.json")):
    r = json.loads(f.read_bytes())
    n = r["scan_id"]
    w, s, e, h = r["bounds"]
    pr = Proj(
        proj="tmerc",
        lon_0=6 * math.floor((w + e) / 12) + 3,
        ellps="krass",
        k=1,
        x_0=500000,
    )
    corners = list(r["corners"].values())
    en = np.array(pr(*np.asarray([v["lonlat"] for v in corners]).T)).T
    xy = np.array([v["pixel"] for v in corners])
    g = [x for x in json.loads((out / "grid" / f.name).read_bytes()) if x["ok"]]
    G = np.array([a["en"] for a in g])
    P = np.array([a["xy"] for a in g])
    stren = np.array([min(a["strength"]) for a in g])
    prev = tps(en, xy)
    prior = np.linalg.norm(prev(G) - P, axis=1)
    record = dict(
        id=n,
        qualified=len(g),
        baseline=metrics(prior),
        held=len(g),
        final=metrics(prior),
        added=0,
    )
    edit = None
    if metrics(prior)[1] > 2.5:
        chosen = []
        fracs = np.linspace(0.06, 0.94, 5 if metrics(prior)[1] > 5 else 4)
        for u, v in product(fracs, fracs):
            target = np.array(pr(w + u * (e - w), s + v * (h - s)))
            dist = np.linalg.norm(G - target, axis=1) + 12 * np.maximum(0, 50 - stren)
            if chosen:
                dist[chosen] = np.inf
            chosen.append(int(np.argmin(dist)))
        F = tps(np.vstack([en, G[chosen]]), np.vstack([xy, P[chosen]]))
        held = np.ones(len(G), dtype=bool)
        held[chosen] = False
        before = metrics(prior[held])
        after = metrics(np.linalg.norm(F(G[held]) - P[held], axis=1))
        if after[0] < before[0] and after[1] < before[1]:
            points = [
                dict(
                    pixel=P[i].round(2).tolist(),
                    lonlat=np.round(pr(*G[i], inverse=True), 11).tolist(),
                    native_grid_m=G[i].astype(int).tolist(),
                    method="Printed 1 km grid intersection",
                )
                for i in chosen
            ]
            edit = dict(
                sha256=r["sha256"],
                other_gcps=points,
                evidence=f"{len(points)} spatially distributed printed 1 km grid intersections constrain the interior. On {sum(held)} other printed crossings the 95th-percentile discrepancy improved from {before[1]:.2f} to {after[1]:.2f} native pixels.",
            )
            record.update(
                held=int(held.sum()), baseline=before, final=after, added=len(points)
            )
    if edit:
        edits[n] = edit
    summary.append(record)
(out / "grid-candidates.json").write_text(
    json.dumps(edits, ensure_ascii=False, indent=2) + "\n"
)
(out / "lattice-results.json").write_text(json.dumps(summary, indent=2) + "\n")
print([(r["id"], r["added"], r["baseline"], r["final"]) for r in summary if r["added"]])
