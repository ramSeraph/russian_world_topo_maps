"""Export the verified Baltic COG inventory, review footprints and calibration archive."""

import argparse
import csv
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from pyproj import Transformer


def export(work):
    job = work / "georef"
    review = job / "review"
    with (work / "25k-selected-originals.csv").open() as stream:
        sources = {Path(row["name"]).stem: row for row in csv.DictReader(stream)}
    with (review / "warp-checks.csv").open() as stream:
        checks = {row["sheet"]: row for row in csv.DictReader(stream)}
    if set(sources) != checks.keys() or set(sources) != {
        p.stem for p in (job / "cogs").glob("*.tif")
    }:
        raise ValueError("Originals, checked warps and output TIFFs differ")
    to_wgs = Transformer.from_crs(3857, 4326, always_xy=True)
    features, inventory = [], []
    with ZipFile(
        review / "25k-staged-frame-controls.zip", "w", compression=ZIP_DEFLATED
    ) as archive:
        for sheet, source in sorted(sources.items()):
            receipt = json.loads((job / "provenance" / (sheet + ".json")).read_text())
            control = receipt["source"]
            measured = work / "fitted" / (sheet + ".json")
            if (
                json.loads(measured.read_bytes())["control"] != control
                or source["sha256"] != control["sha256"]
                or (job / "cogs" / receipt["cog"]).stat().st_size
                != receipt["output_size"]
            ):
                raise ValueError(f"Inconsistent build receipt for {sheet}")
            archive.write(measured, "frames/" + measured.name)
            xa, step, _, ya, _, ystep = receipt["geotransform"]
            width, height = receipt["dimensions"]
            west, north = to_wgs.transform(xa, ya)
            east, south = to_wgs.transform(xa + width * step, ya + height * ystep)
            check = checks[sheet]
            row = dict(
                sheet=sheet,
                country=source["country"],
                edition=int(source["edition_year"]),
                original=source["name"],
                cog=receipt["cog"],
                source_url=control["source_url"],
                member=source["member"],
                source_sha256=source["sha256"],
                cog_sha256=receipt["output_sha256"],
                bytes=receipt["output_size"],
                width=width,
                height=height,
                epsg=receipt["target_epsg"],
                zoom=receipt["zoom"],
                grid_read=int(check["read"]),
                grid_p95_m=float(check["p95_m"]),
            )
            inventory.append(row)
            props = {
                k: row[k]
                for k in (
                    "sheet",
                    "country",
                    "edition",
                    "original",
                    "cog",
                    "source_url",
                    "zoom",
                    "grid_read",
                    "grid_p95_m",
                )
            }
            props["raster_bounds"] = [[south, west], [north, east]]
            props["components"] = control["component_ids"]
            if sheet == "O34-095-3-3_O34-095-3-4":
                props["extent_note"] = (
                    "The printed frame ends at 23°09′ E. Only the western fifth of O34-095-3-4 is present."
                )
            features.append(
                dict(
                    type="Feature",
                    id=sheet,
                    geometry=control["footprint"],
                    properties=props,
                )
            )
        archive.write(work / "25k-selected-originals.csv", "25k-selected-originals.csv")
        archive.write(review / "warp-checks.csv", "warp-checks.csv")
        archive.write(review / "verification.json", "verification.json")
    with (review / "25k-staged-cogs.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=inventory[0])
        writer.writeheader()
        writer.writerows(inventory)
    geojson = dict(type="FeatureCollection", features=features)
    (review / "25k-staged-cogs.geojson").write_text(
        json.dumps(geojson, separators=(",", ":"), ensure_ascii=False) + "\n"
    )
    print(len(inventory), "checked COGs;", sum(r["bytes"] for r in inventory), "bytes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    export(parser.parse_args().work.resolve())
