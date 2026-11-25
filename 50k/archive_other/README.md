# General Staff 1:50,000 georeferencing

The release covers 4,387 physical scans from Archive.org and The Red Atlas. Its 83 joined scans each produce one raster. The provenance register records the source edition, native filename, published designation, original and COG URLs, and SHA-256 digests. [Release provenance](../../new/genshtab-audit/50k-provenance.csv)

## Rebuild a released COG

Run from the repository root on the build host. Use Python 3.11 or later with Pillow, NumPy, OpenCV, pyproj and Shapely, GDAL command-line tools and Python bindings. The shared builder uses the original thin-plate-spline warp, frame cutline and masked EPSG:3857 COG settings. Set `GDAL_PYTHON` if the GDAL bindings use a different interpreter from `/usr/bin/python3`.

```sh
scripts="$PWD/50k/archive_other"
builder="$PWD/100k/archive_other/build_warps.py"
controls="$PWD/new/genshtab-audit/50k-staged-frame-controls.zip"
work=/path/to/50k-staging
sheet=I37-073-2
python3 "$scripts/fetch_released.py" "$work" "$sheet"
python3 "$scripts/stage_checked_warps.py" "$controls" "$work/released" \
    --archive "$work/archive/originals" --red-atlas "$work/red-atlas/mosaics" --sheet "$sheet"
python3 "$builder" "$work/released" "$sheet"
```

The output is `$work/released/cogs/I37-073-2.tif`. Omit the sheet selections from all three commands to process the full set. The register keeps catalogue and published IDs separate for the two relabelled originals. The staging step checks the original bytes before using any control. [Released frame controls](../../new/genshtab-audit/50k-staged-frame-controls.zip)

## Repeat the corner measurements

The initial detector uses grayscale frame rules, Tesseract orientation data, and the printed crossings around each corner. It writes intermediate readings under `archive/checked` or `red-atlas/checked`. For Archive.org sheets, the native grid scripts compare the proposed frame with the two printed rules at 1 km grid intersections. The refinement fits a subset of these intersections and checks the others and the sheet edges. Run this sequence after fetching the example above.

```sh
python3 "$scripts/measure_frames.py" "$work" "$sheet"
(
    cd "$work/grid"
    python3 "$scripts/native_grid/measure.py" 1 "$sheet"
    python3 "$scripts/native_grid/refine.py" --jobs 1 --promote "$sheet"
)
```

The reviewed inputs preserve manual corner readings with their source hashes. For example, I37-073-2 uses alternative B at the northeast corner. The exact release replay above also includes the accepted readings for sheets that required denser grids, collar tracing, or individual corrections. [Archive.org readings](reviewed-controls.json) · [Final corner decisions](../../new/genshtab-audit/50k-corner-review-feedback.json)

For a Red Atlas sheet, fetch and measure it with the same commands using its sheet ID. From `$work/red-atlas`, run `python3 "$scripts/red_grid/lattice.py"` and then `python3 "$scripts/red_grid/improve.py"` to measure the printed grid and write candidate controls under `analysis/`. [Reviewed Red Atlas readings](red-atlas-reviewed-controls.json) · [Red Atlas source levels and checksums](../../new/genshtab-audit/50k-red-atlas-scan-provenance.csv)

## PMTiles

The November mosaic recipe contains the pinned version of the retile tool, its input manifests, build and packaging scripts, and verification records for all 33 parts. Its `BUILD.txt` describes the original host paths and release operations. [PMTiles recipe](../../new/genshtab-audit/50k-retile-recipe.tar.gz)
