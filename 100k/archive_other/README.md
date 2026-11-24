# General Staff 1:100,000 georeferencing

Run the acquisition and raster processing on the remote build host. The working directories hold original source pixels, measured controls and draft cloud-optimized GeoTIFFs. The [source register](../../new/genshtab-audit/100k-scan-provenance.csv) identifies the selected physical scan, its component cells, edition evidence and SHA-256. The undated catalogue duplicates remain documented in the [edition comparison](../../new/genshtab-audit/100k-red-atlas-edition-comparison.csv).

## Fetch the selected originals

Use Python 3.11 or later with Pillow, NumPy, OpenCV, pyproj and Shapely. The raster build uses GDAL command-line tools and Python bindings, Tesseract with its orientation data, and dezoomify-rs for Red Atlas. The shared 1:200k fetcher verifies Archive.org ZIP-member names, byte ranges, uncompressed lengths, CRC32 values and original SHA-256 values. Satmaps scans and their OziExplorer calibrations have separate SHA-256 values. The snapshot contains the calibration files for the selected Satmaps editions.

```sh
scripts=100k/archive_other
shared=200k/archive_other
work=/path/to/100k-staging
catalogues="$work/archive-satmaps"
red="$work/red-atlas"
warps="$work/warps"
mkdir -p "$catalogues"
python3 -m zipfile -e "$scripts/calibration-snapshot.zip" "$catalogues"
python3 "$shared/fetch_selected.py" "$catalogues" --inventory-dir "$scripts" --jobs 5
python3 "$scripts/fetch_red_atlas.py" "$red" --jobs 3
```

The Red Atlas register pins one Zoomify descriptor, pyramid level, decoded RGB digest and original tile extent per selection. The levels were chosen against the printed frame density of the existing 1:100k collection, whose median is about 299 dpi. The fetcher checks the native JPEG tiles including the partial tiles along the right and bottom edges. It preserves their decoded pixels in a PNG. Pass individual sheet IDs after the output directory for a selective replay. [Selected Red Atlas scans](red-atlas.csv)

## Measure and review ground controls

```sh
python3 "$scripts/find_controls.py" "$catalogues" --jobs 4
python3 "$scripts/refine_frames.py" "$catalogues" --jobs 4
python3 "$scripts/check_crossings.py" "$catalogues" --jobs 4
python3 "$scripts/red_controls.py" "$red" --jobs 3
python3 "$scripts/check_crossings.py" "$red" --red-atlas --jobs 3
python3 "$scripts/apply_reviewed_controls.py" "$catalogues/checked" "$red/checked" --output "$work/reviewed"
```

The image detector measures dark printed lines in grayscale. It locates the outer frame, follows its sides into each corner, and looks for the printed parallel and meridian crossing the collar. A separate check measures whether each line continues beyond the map body. Source-calibrated scans use their Pulkovo 1942 Ozi points, preserving which points are enabled and comparing doubtful corners with the moving-map outline. The geometry check estimates scan density and measures distortion against the sheet's Gauss–Krüger projection. The reviewed readings identify source bytes by hash, so a correction cannot silently move to a different edition. [Initial printed readings](printed-controls.json) · [Reviewed controls and evidence](reviewed-controls.json)

## Build the COGs

```sh
python3 "$scripts/stage_warps.py" "$warps" --archive-satmaps "$catalogues" \
    --red-atlas "$red" --overrides "$work/reviewed" \
    --provenance new/genshtab-audit/100k-scan-provenance.csv
python3 "$scripts/build_warps.py" "$warps" --jobs 8
```

The stage checks source identity and writes the final per-scan controls to `review/controls.json`. The shared 1:200k builder uses exact thin-plate-spline warping in the sheet's projected coordinate system, clips to the measured frame and writes a masked EPSG:3857 COG on the Web Mercator tile grid. Set `GDAL_PYTHON` if the GDAL Python bindings are installed outside the default system interpreter. Run the same commands after revising a reading. The builder verifies hashes and reuses existing rasters when the changes affect only descriptive metadata.

Joined sheets produce one file per physical scan. A mislabelled Satmaps input listed as U37-133 through U37-136 is recorded under its original catalogue filename and staged as U37-133_U37-134, the area substantiated by the printed coordinates. Partial scans retain their measured geographic limits.

## Replay the released frames

The final register contains the native corner pixels, supplementary ground controls, source checksums and clipping footprints for all 2,667 released scans. Its decompressed SHA-256 is `6a81f3950795c5a63df40044bbc89cfdd5ea2ab58200220af268f59e2cf1a970`. The public provenance CSV also gives direct download URLs for each original and COG. Store a released original under the native filename in the register. [Final controls](../../new/genshtab-audit/100k-staged-frame-controls.json.gz) · [Release provenance](https://github.com/ramSeraph/russian_world_topo_maps/releases/download/100k-gs-orig/100k-provenance.csv)

With the source directories from the acquisition step, run the following from the repository root. The builder accepts individual published sheet IDs or the full register when the ID is omitted.

```sh
replay="$work/released"
mkdir -p "$replay/review" "$replay/originals"
ln -s "$catalogues"/originals/* "$red"/mosaics/*.png "$replay/originals/"
gzip -dc new/genshtab-audit/100k-staged-frame-controls.json.gz > "$replay/review/controls.json"
python3 "$scripts/build_warps.py" "$replay" C48-046
```

The November mosaic recipe records the exact retile inputs, rendering and packaging scripts, and public verification results. Its `BUILD.txt` describes the original host layout. [PMTiles recipe](../../new/genshtab-audit/100k-retile-recipe.tar.gz)
