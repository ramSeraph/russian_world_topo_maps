"""Build the selected 1:200,000 Genshtab COGs on a host with GDAL CLI and pyproj."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile

from pyproj import CRS, Transformer
from PIL import Image


DATUM = "+ellps=krass +towgs84=28,-130,-95,0,0,0,0"
WEB_PIXEL = 156543.03392804097  # metres per GoogleMapsCompatible pixel at zoom 0


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(*args):
    return subprocess.check_output([str(arg) for arg in args], text=True)


def build(row, root):
    sheet = row["scan_id"]
    source = root / "originals" / row["original"]
    output = root / "cogs" / (sheet + ".tif")
    receipt = root / "provenance" / (sheet + ".json")
    if digest(source) != row["sha256"]:
        raise ValueError(f"Source checksum mismatch: {sheet}")
    fingerprint = hashlib.sha256((digest(Path(__file__)) + json.dumps(row, sort_keys=True)).encode()).hexdigest()
    header = root / "headers" / (sheet + ".json")
    if output.exists() and receipt.exists() and header.exists():
        record = json.loads(receipt.read_text())
        if record["build_fingerprint"] == fingerprint and record["output_sha256"] == digest(output):
            return record

    w, s, e, n = row["bounds"]
    mid = (w + e) / 2
    tm = row["source_crs"]
    native_geo = CRS.from_proj4("+proj=longlat " + DATUM + " +type=crs")
    to_tm = Transformer.from_crs(native_geo, tm, always_xy=True)
    to_web = Transformer.from_crs(native_geo, 3857, always_xy=True)
    corners = row["corners"]
    gcp_args = []
    for c in [*corners.values(), *row["other_gcps"]]:
        # Source coordinates identify pixel centres. GDAL uses the upper-left pixel edge as zero.
        x, y = c["pixel"]
        gcp_args.extend(["-gcp", x + 0.5, y + 0.5, *to_tm.transform(*c["lonlat"])])
    coords = [corners[k]["lonlat"] for k in ("NW", "NE", "SE", "SW", "NW")]
    ring = row["footprint"]["coordinates"][0]
    south_mid = to_web.transform(mid, s)
    north_mid = to_web.transform(mid, n)
    px_height = sum(math.dist(corners[a]["pixel"], corners[b]["pixel"])
                    for a, b in (("NW", "SW"), ("NE", "SE"))) / 2
    target_res = 0.8 * math.dist(south_mid, north_mid) / px_height
    zoom = round(math.log2(WEB_PIXEL / target_res))
    res = WEB_PIXEL / 2**zoom

    with tempfile.TemporaryDirectory(dir=root / "cogs", prefix=sheet + "-") as tmp:
        tmp = Path(tmp)
        cutline = tmp / "cutline.geojson"
        cutline.write_text(json.dumps({"type": "Polygon", "coordinates": [ring]}))
        georef, warped, cog = tmp/"source.tif", tmp/"warped.vrt", tmp/"out.tif"
        with Image.open(source) as image:
            if image.mode == "P":
                bands = ["-expand", "rgb"]
            elif image.mode in ("L", "1"):
                bands = ["-b", "1", "-b", "1", "-b", "1"]
            elif image.mode in ("RGB", "RGBA"):
                bands = ["-b", "1", "-b", "2", "-b", "3"]
            else:
                raise ValueError(f"Unsupported source mode {image.mode} on {sheet}")
        run("gdal_translate", "-q", "-of", "GTiff", "-co", "TILED=YES",
            *bands, "-a_srs", tm, *gcp_args, source, georef)
        run("gdalwarp", "-q", "-of", "VRT", "-tps", "-et", "0", "-r", "bilinear",
            "-t_srs", "EPSG:3857", "-tr", res, res, "-tap", "-dstalpha",
            "-cutline", cutline, "-crop_to_cutline", "-wo", "CUTLINE_ALL_TOUCHED=TRUE", georef, warped)
        run("gdal_translate", "-q", "-of", "COG", "-b", "1", "-b", "2", "-b", "3", "-mask", "4",
            "-co", "TILING_SCHEME=GoogleMapsCompatible", "-co", f"ZOOM_LEVEL={zoom}",
            "-co", "COMPRESS=JPEG", "-co", "QUALITY=50", "-co", "NUM_THREADS=2", "-r", "nearest",
            "--config", "GDAL_TIFF_INTERNAL_MASK", "YES", "--config", "GDAL_CACHEMAX", "256", warped, cog)
        info = json.loads(run("gdalinfo", "-json", cog))
        structure = info["metadata"]["IMAGE_STRUCTURE"]
        if max(info["size"]) > max(row["width"], row["height"]) * 5:
            raise ValueError(f"Unreasonable raster dimensions for {sheet}: {info['size']}")
        bands = info["bands"]
        if (structure.get("LAYOUT") != "COG" or "JPEG" not in structure.get("COMPRESSION", "")
            or len(bands) != 3 or not bands[0].get("overviews")
            or "PER_DATASET" not in bands[0]["mask"]["flags"]
            or CRS.from_wkt(info["coordinateSystem"]["wkt"]).to_epsg() != 3857):
            raise ValueError(f"Invalid COG encoding: {sheet}")
        # Check the centre and four inset controls in the actual dataset mask.
        gt = info["geoTransform"]
        checks = []
        for lon, lat in [(mid, (s+n)/2), *((x*0.98+mid*0.02, y*0.98+(s+n)/2*0.02) for x,y in coords[:4])]:
            x, y = to_web.transform(lon, lat)
            col, line = int((x-gt[0])/gt[1]), int((y-gt[3])/gt[5])
            if not (0 <= col < info["size"][0] and 0 <= line < info["size"][1]):
                raise ValueError(f"Sheet control lies outside {sheet} COG")
            checks.append([col, line])
        gdal_python = os.environ.get("GDAL_PYTHON", "/usr/bin/python3")
        run(gdal_python, "-c",
            "import sys,json; from osgeo import gdal; ds=gdal.Open(sys.argv[1]); "
            "mask=ds.GetRasterBand(1).GetMaskBand(); "
            "assert all(mask.ReadRaster(x,y,1,1)==bytes([255]) for x,y in json.loads(sys.argv[2]))",
            cog, json.dumps(checks))
        run(gdal_python, "-m", "osgeo_utils.samples.validate_cloud_optimized_geotiff", cog)
        record = dict(id=sheet, original=source.name, cog=output.name, source=row,
                      source_crs=tm, target_epsg=3857, longitude_latitude_datum="Pulkovo 1942",
                      output_size=cog.stat().st_size, output_sha256=digest(cog), dimensions=info["size"],
                      geotransform=gt, zoom=zoom, footprint_wgs84=ring, build_fingerprint=fingerprint)
        (tmp/"receipt.json").write_text(json.dumps(record, indent=2) + "\n")
        (tmp/"header.json").write_text(json.dumps(info, separators=(",", ":")) + "\n")
        cog.replace(output)
        (tmp/"header.json").replace(header)
        (tmp/"receipt.json").replace(receipt)
    print(f"{sheet}  {record['dimensions']}  {record['output_size']:,} bytes", flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Dataset directory containing originals/ and review/controls.json")
    parser.add_argument("sheets", nargs="*")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    root = args.root.resolve()
    os.environ["GDAL_PAM_ENABLED"] = "NO"
    for folder in ("cogs", "provenance", "headers"):
        (root/folder).mkdir(exist_ok=True)
    rows = json.loads((root/"review"/"controls.json").read_text())
    if args.sheets:
        rows = [r for r in rows if r["scan_id"] in args.sheets]
        if {r["scan_id"] for r in rows} != set(args.sheets):
            parser.error("Unknown sheet in request")
    if len({r["scan_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate output sheet name")
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        records = list(pool.map(build, rows, [root]*len(rows)))
    print(f"Verified {len(records)} COGs totalling {sum(r['output_size'] for r in records):,} bytes", flush=True)


if __name__ == "__main__":
    main()
