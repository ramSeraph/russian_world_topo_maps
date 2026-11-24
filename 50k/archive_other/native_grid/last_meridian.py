"""Use the actual printed water/collar edge and labelled horizontal kilometre rules at 128°45′ E."""

import json
import cv2
import numpy as np
from pyproj import Proj
from measure import p, write_json, tps, rules
from refine import errors
from trace_native_border import trace

r = p / "review"
n = "J52-066-3"
fn = n + ".json"
base = json.loads((r / "traced-candidates" / fn).read_bytes())
w, s, e, h = base["bounds"]
cl = base["corners"]
pr = Proj(proj="tmerc", lon_0=129, k=1, x_0=500000, ellps="krass")
im = cv2.imread(
    str(p / "originals" / base["original"]),
    cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION,
)
gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
m = np.load(r / "measurements" / (n + ".npz"))["points"]
G = m[:, :2]
P = m[:, 2:4]
km = np.rint(G / 1000).astype(int)
test_grid = (km[:, 0] + 2 * km[:, 1]) % 3 == 0
cc = [*cl.values(), *base["other_gcps"]]
F = tps(
    np.array(pr(*np.array([q["lonlat"] for q in cc]).T)).T,
    np.array([q["pixel"] for q in cc]),
)
a = np.array(cl["NE"]["pixel"])
b = np.array(cl["SE"]["pixel"])
yy = np.arange(round(a[1] + 18), round(b[1] - 17))
xc = np.rint(a[0] + (b[0] - a[0]) * (yy - a[1]) / (b[1] - a[1])).astype(int)
off = np.arange(-50, 51)
xx = xc[:, None] + off
img = im[yy[:, None], xx].astype(float)
smooth = cv2.GaussianBlur(img, (3, 15), 1, 4)
paper = np.median(smooth[:, -13:], axis=1)
difference = smooth - paper[:, None, :]
difference -= difference.mean(axis=2, keepdims=True)
colour = np.linalg.norm(difference, axis=2)
reference = np.median(colour[:, :18], axis=1)
rat = colour / np.maximum(20, reference)[:, None]
# Find the edge closest to the long true meridian within the known outer search window. Full-colour collar references come from each native row.
z = rat[:, :-1] - 0.5
cross = (z > 0) & (rat[:, 1:] <= 0.5) & (abs(off[:-1])[None, :] < 30)
px = []
for i, x in enumerate(xc):
    options = np.flatnonzero(cross[i])
    j = int(options.max()) if len(options) else None
    if j is None or reference[i] < 20:
        px.append(np.nan)
        continue
    d = (rat[i, j] - 0.5) / max(rat[i, j] - rat[i, j + 1], 1e-8)
    px.append(x + off[j] + d)
px = np.array(px)
valid = np.isfinite(px)
px = np.interp(yy, yy[valid], px[valid])


def median_filter(a, size, mode="nearest"):
    return np.median(
        np.lib.stride_tricks.sliding_window_view(
            np.pad(a, size // 2, mode="edge"), size
        ),
        axis=1,
    )


# Horizontal black kilometre rules cross the colour edge and extend across the collar. Remove their short-lived excursions using neighbouring rows.
resid = px - xc
reference_edge = median_filter(resid, size=65, mode="nearest")
credible = abs(resid - reference_edge) < 2.0
valid &= credible
px[~credible] = xc[~credible] + reference_edge[~credible]
px = median_filter(px, size=5, mode="nearest")
# Check for the thin ink rule against the adjacent clean paper. Use its offset where it is visible.
positions = np.column_stack((px, yy))
direction = np.tile([0, 1.0], (len(yy), 1))
norm, delta, scores = rules(gray, positions, direction, reach=3)
est = px + norm[:, 0] * delta
strong = scores >= 7
delta = est - px
shift = float(np.median(delta[strong]))
inkpx = px + shift
print(
    "edge rows",
    len(yy),
    "color",
    valid.sum(),
    "thin ink",
    strong.sum(),
    "ink offset",
    shift,
    "offset at labelled endpoints",
    inkpx[0] - xc[0],
    inkpx[-1] - xc[-1],
    flush=True,
)


def at_y(y):
    return np.interp(y, yy, inkpx)


def ground(f):
    return np.array(pr(np.full_like(f, e), s + f * (h - s))).T


limits = ground(np.array([0.022, 0.978]))[:, 1]
goals = np.arange(np.ceil(min(limits) / 1000) * 1000, max(limits), 1000)
lo = np.zeros(len(goals))
hi = np.ones(len(goals))
for i in range(32):
    mid = (hi + lo) / 2
    less = ground(mid)[:, 1] < goals
    lo = np.where(less, mid, lo)
    hi = np.where(less, hi, mid)
frac = (lo + hi) / 2
earth = ground(frac)
first = F(earth)
xy = np.column_stack((at_y(first[:, 1]), first[:, 1]))
axis = F(earth + [100, 0]) - first
nc, change, sig = rules(gray, xy, axis, reach=15)
measured = xy + nc * change[:, None]
measured[:, 0] = at_y(measured[:, 1])
keep = (sig >= 16) & (abs(change) < 14)
print(
    "Reliable projected northing rules",
    int(keep.sum()),
    "of",
    len(keep),
    "strength/offset",
    list(zip(sig.round(1), change.round(1))),
    flush=True,
)
indices = np.flatnonzero(keep)
training = indices[::2]
testing = indices[1::2]
keeppts = [q for q in base["other_gcps"] if abs(q["lonlat"][0] - e) > 1e-8]
for i in training:
    keeppts.append(
        dict(
            lonlat=[e, round(float(s + frac[i] * (h - s)), 11)],
            pixel=measured[i].round(2).tolist(),
            method="Projected 1 km northing crossing the independently traced eastern 128°45′ meridian",
        )
    )
cand = dict(base, other_gcps=keeppts)
cc = [*cl.values(), *cand["other_gcps"]]
F = tps(
    np.array(pr(*np.array([q["lonlat"] for q in cc]).T)).T,
    np.array([q["pixel"] for q in cc]),
)
edge_test = errors(np.linalg.norm(F(earth[testing]) - measured[testing], axis=1))
interior = errors(np.linalg.norm(F(G[test_grid]) - P[test_grid], axis=1))
fra = np.linspace(0.009, 0.991, 401)
pred = F(ground(fra))
dx = abs(pred[:, 0] - at_y(pred[:, 1]))
inside = np.min(abs(fra[:, None] - frac[training]), axis=1) > 0.005
edge = errors(dx[inside])
print(
    "unused km grid",
    len(testing),
    edge_test,
    "independent boundary profiles",
    sum(inside),
    edge,
    "internal",
    interior,
    flush=True,
)
stats = {}
ok = True
for side in ["north", "south", "west"]:
    stats[side], _ = trace(im, F, pr, cand["bounds"], side)
    ok &= stats[side]["normal"][1] <= 3.5
stats["east"] = dict(
    visible=int(valid.sum()),
    visible_ink=int(strong.sum()),
    held_out_profiles=int(inside.sum()),
    normal=edge,
    held_out_projected_crossings=len(testing),
    crossing_error=edge_test,
)
ok = bool(
    ok
    and edge[1] <= 3
    and edge_test[1] <= 4.5
    and interior[1] <= 4.5
    and len(testing) >= 5
)
m = dict(
    id=n,
    source_sha256=cand["sha256"],
    ready=ok,
    stage="Independent collar trace, graticule and unused 1 km crossings",
    held=int(test_grid.sum()),
    median=interior[0],
    p95=interior[1],
    edges=stats,
)
write_json(r / "traced-metrics" / fn, m)
write_json(r / "traced-candidates" / fn, cand)
if ok:
    cand["flags"] = []
    cand["manual_review"] = (
        (cand.get("manual_review") or "")
        + " The 128°45′ eastern meridian was traced directly at the colour transition to the paper collar. The nearby projected vertical grid line is independently visible. Alternating measured kilometre crossings constrained the eastern boundary; the four labelled geographic corners were preserved."
    ).strip()
    write_json(r / "native" / fn, dict(m, reason=""))
    write_json(r / "qualified" / fn, cand)
print(
    "crossings f; measured minus linear; F minus measured",
    [
        (
            round(float(fi), 3),
            round(
                float(q[0] - (a[0] + (b[0] - a[0]) * (q[1] - a[1]) / (b[1] - a[1]))), 2
            ),
            diff.round(1).tolist(),
        )
        for fi, q, diff in zip(frac, measured, F(earth) - measured)
    ],
    flush=True,
)
print(
    "bad gradients where valid",
    [
        (round(i / len(yy), 2), round(float(inkpx[i] - xc[i]), 2))
        for i in range(0, len(yy), 200)
    ],
    flush=True,
)
print("PASS", ok, flush=True)
