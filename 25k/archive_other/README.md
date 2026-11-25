# Baltic General Staff sheets at 1:25,000

The release contains 291 physical scans from Latvia and Estonia. Each entry in the [provenance register](../../new/genshtab-audit/25k-provenance.csv) gives the printed edition, original ZIP member, release URLs and SHA-256 for the JPEG and COG. Use the intact repository tree for the shared frame detector, Gauss–Krüger grid reader and COG builder.

## Rebuild from the printed frames

Run the commands from the repository root on the build host. Use a fresh work directory for each selection. To rebuild an individual sheet, append its physical ID to the `prepare_originals.py` command. The processing environment uses Python 3.12, NumPy, OpenCV, Pillow, pyproj, rasterio, Shapely and GDAL 3.8 command-line programs. The COG builder also uses the system Python with GDAL bindings and its COG validator.

```sh
work=/path/to/baltic-build
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python 25k/archive_other/prepare_originals.py "$work"
python 25k/archive_other/measure_frames.py "$work" --jobs 8
python 25k/archive_other/fit_grid.py "$work" --jobs 8
python 25k/archive_other/stage_warps.py "$work"
python 100k/archive_other/build_warps.py "$work/georef" --jobs 8
python 25k/archive_other/check_warps.py "$work" --jobs 4
python 25k/archive_other/export_georef.py "$work"
```

The detector measures the four printed neatlines in grayscale and measures the two ink rules at each expected 1 km grid intersection. The thin-plate spline uses the four corners, 16 distributed interior crossings and accepted grid intersections on the frame. The remaining interior crossings are withheld for verification. The joined Mērsrags scan prints 23°09′ E at both eastern corners. Its checksum identifies the edition to which that shorter frame applies.

The geographic controls are in Pulkovo 1942. The warp uses the sheet's six-degree Gauss–Krüger zone on the Krassovsky ellipsoid. Regional translations to WGS 84 are (22, −126, −85) metres for Estonia and (24, −124, −82) for Latvia. Output is a GoogleMapsCompatible EPSG:3857 COG with JPEG quality 50, an internal neatline mask and overviews. GDAL's warp approximation tolerance is 0.025 source pixels.

The verification step measures withheld printed grid crossings in the finished RGB rasters and compares each internal mask against the geographic footprint. Reported residuals are in local ground metres. The outputs are in `georef/cogs/`, with per-sheet receipts and GDAL metadata in `georef/provenance/` and `georef/headers/`. The inventory, footprints, verification results and zipped source-pixel control records are in `georef/review/`.

## Replay the released controls

For a single sheet, these commands fetch the published JPEG, restore its measured corners and grid readings, then build and check its COG. The joined Mērsrags original keeps its two-part ID throughout.

```sh
work=/path/to/baltic-replay
sheet=O34-095-3-3_O34-095-3-4
python 25k/archive_other/prepare_originals.py "$work" "$sheet"
unzip -j new/genshtab-audit/25k-staged-frame-controls.zip "frames/$sheet.json" -d "$work/fitted"
python 25k/archive_other/stage_warps.py "$work"
python 100k/archive_other/build_warps.py "$work/georef" "$sheet"
python 25k/archive_other/check_warps.py "$work" --jobs 1
```

The resulting TIFF is in `$work/georef/cogs/`. For the full release, omit the sheet arguments and extract `'frames/*.json'`. [Released controls](../../new/genshtab-audit/25k-staged-frame-controls.zip)

## PMTiles

The recipe includes the pinned retile tool, baseline descriptor, part builder, shared-boundary correction and verification records. Extract it into a build directory and follow `pmtiles/BUILD.txt`. [PMTiles recipe](../../new/genshtab-audit/25k-retile-recipe.tar.gz)
