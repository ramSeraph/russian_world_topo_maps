"""Check the printed kilometre grid and mask in the completed Baltic COGs."""

import argparse
import csv
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.warp import transform_geom

from measure_frames import projected
from measure import rules


def check(task):
    root, fitfile = task
    cv2.setNumThreads(1)
    fit = json.loads(fitfile.read_text())
    row, checks = fit["control"], fit["checks"]
    name = row["scan_id"]
    with rasterio.open(root / "georef/cogs" / (name + ".tif")) as ds:
        if ds.crs.to_epsg() != 3857 or ds.count != 3 or not ds.overviews(1):
            raise ValueError(f"Unexpected format for {name}")
        gray = cv2.cvtColor(np.moveaxis(ds.read(), 0, 2), cv2.COLOR_RGB2GRAY)
        mask = ds.dataset_mask()
        poly = transform_geom("EPSG:4326", ds.crs, row["footprint"])
        expected = rasterize(
            [(poly, 255)], out_shape=mask.shape, transform=ds.transform
        )
        base = np.count_nonzero(expected)
        overlap = np.count_nonzero((expected > 0) & (mask > 0)) / base
        excess = np.count_nonzero((expected == 0) & (mask > 0)) / base
        ll = np.array([a["lonlat"] for a in checks["withheld"]])
        proj = projected(row["bounds"])
        en = np.column_stack(proj(*ll.T))
        tr = Transformer.from_crs(row["native_geographic_crs"], ds.crs, always_xy=True)

        def pixels(en):
            xx, yy = tr.transform(*proj(*en.T, inverse=True))
            cols, rows = ~ds.transform * (xx, yy)
            return np.column_stack((cols - 0.5, rows - 0.5))

        pos = pixels(en)
        ux, uy = pixels(en + [100, 0]) - pos, pixels(en + [0, 100]) - pos
        c1, d1, s1 = rules(gray, pos, ux, reach=15)
        c2, d2, s2 = rules(gray, pos, uy, reach=15)
        dif = np.linalg.solve(
            np.stack((c1, c2), 1), np.column_stack((d1, d2))[:, :, None]
        ).reshape(-1, 2)
        good = np.minimum(s1, s2) >= 14
        dxy = dif[good]
        lats = ll[good, 1]
        # EPSG:3857 map metres must be converted to local ground metres for the residual summary.
        ground = np.linalg.norm(dxy, axis=1) * ds.res[0] * np.cos(np.deg2rad(lats))
        if not len(ground):
            raise ValueError(f"No independent grid read from {name}")
        metrics = dict(
            sheet=name,
            year=row["year"],
            country=row["country"],
            withheld=len(pos),
            read=int(good.sum()),
            median_m=round(float(np.median(ground)), 2),
            p95_m=round(float(np.quantile(ground, 0.95)), 2),
            max_m=round(float(ground.max()), 2),
            mask_coverage=round(overlap, 7),
            mask_excess=round(excess, 7),
            source_grid_p95_px=checks["p95"],
            resolution_3857=ds.res[0],
        )
        return metrics, ground.tolist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    parser.add_argument("--jobs", type=int, default=5)
    args = parser.parse_args()
    root = args.work.resolve()
    paths = sorted((root / "fitted").glob("*.json"))
    out = []
    res = []
    with ProcessPoolExecutor(args.jobs) as pool:
        for m, g in pool.map(check, [(root, f) for f in paths]):
            out.append(m)
            res.extend(g)
    with (root / "georef/review/warp-checks.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=out[0])
        w.writeheader()
        w.writerows(out)
    summary = dict(
        sheets=len(out),
        withheld=sum(x["withheld"] for x in out),
        read=len(res),
        median_m=round(float(np.median(res)), 2),
        p95_m=round(float(np.quantile(res, 0.95)), 2),
        worst_sheet_p95_m=max(x["p95_m"] for x in out),
        min_mask_coverage=min(x["mask_coverage"] for x in out),
        max_mask_excess=max(x["mask_excess"] for x in out),
        min_read=min(x["read"] for x in out),
    )
    (root / "georef/review/verification.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    print(summary)


if __name__ == "__main__":
    main()
