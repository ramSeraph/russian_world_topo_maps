# General Staff 1:200,000 scan controls

The November 2026 release adds 544 Archive.org JPEGs, 21 Satmaps GIFs and eight Red Atlas JPEGs, totalling 573 scans. The Archive.org and Satmaps originals are pinned by SHA-256 in [selected-scans.csv](selected-scans.csv). Joined scans retain their component identifiers in one row. Archive.org rows also record the ZIP member, byte range, compression method, CRC32 and filename year. Satmaps catalogue years are unknown.

Run the following from the repository root on the remote build host. The Python environment needs NumPy, OpenCV, Pillow, pyproj and Shapely. The corner measurements used OpenCV 5.0.0. Orientation checks use Tesseract with its OSD data.

```sh
scripts=200k/archive_other
job=/path/to/200k-staging
python3 "$scripts/fetch_selected.py" "$job"
python3 "$scripts/find_frames.py" "$job"
python3 "$scripts/find_inner_grid.py" "$job"
python3 "$scripts/check_orientation.py" "$job"
python3 "$scripts/red_atlas_controls.py" "$job"
python3 "$scripts/stage_controls.py" "$job" --with-red-atlas
```

The fetcher checks the selected original before accepting a cached file. It saves an acquisition receipt per scan. The shared grayscale detector finds an enclosing frame. The 1:200k pass fits the thick outer rules and searches the collar for the intersecting printed parallel and meridian. Flags record ambiguous lines, weak evidence or unusual geometry. The shape check measures the maximum corner residual against a rotation and uniform-scale fit in the sheet's projected coordinate system. Scan pixels use a top-left origin.

The 17 original [Ozi calibrations](calibration/) give nine geographic controls each. [Printed controls](printed_controls.json) records native pixel readings for the other four Satmaps scans, individual reviewed corner corrections, checked text orientations, and the limits of four partly joined archive sheets. The stage preserves original pixels on upside-down scans and assigns them geographic corner names. Controls and scan footprints are written to `$job/review/`. Geographic coordinates use the Pulkovo 1942 datum supplied in the Ozi files and assumed for archive sheets.

The staged `controls.json` records the pixel coordinates and geographic coordinates of each control. For manually corrected corners it also retains the detector's original pixel reading. The accompanying `footprints.geojson` contains one feature per scan.

## Red Atlas corner measurements

The Red Atlas step fetches the eight original JPEGs from the GitHub release and checks each SHA-256 before measuring it. The four British sheets use visually identified seed pixels. The grayscale fitter follows each printed line into the map collar and intersects the fitted parallel and meridian. The four US sheets retain the final readings made directly on the labelled intersections. Baltimore and Boston also use three fitted interior graticule crossings each. The source hash, seed coordinates, manual readings and print edition are recorded per sheet. [Red Atlas readings](red_atlas_readings.json)

Omit the Red Atlas fetch and the `--with-red-atlas` flag to reproduce the first 565 sheets. The verifier compares source checksums, control coordinates, rotations, sheet limits and CRS by sheet ID. It allows a footprint difference of up to 10⁻¹¹ degrees across PROJ and GEOS versions.

```sh
curl -fL https://github.com/ramSeraph/russian_world_topo_maps/releases/download/200k-gs-georef/200k-controls.json -o "$job/released-controls.json"
python3 "$scripts/verify_controls.py" "$job/review/controls.json" "$job/released-controls.json"
```

## Full-resolution georeferencing

After staging the reviewed controls, build the cloud-optimized GeoTIFFs on the processing host with GDAL's command-line tools, the GDAL Python bindings and Pillow installed.

```sh
python3 200k/archive_other/build_cogs.py "$job" --jobs 6
```

The builder validates each original's SHA-256, expands indexed and grayscale images to RGB, and fits a thin-plate spline to the reviewed control points in the sheet's Gauss–Krüger zone. It clips to the staged WGS 84 frame and writes masked, JPEG-compressed EPSG:3857 COGs on the Google Maps tile grid. It checks the centre and four inset corners against the mask, validates the COG layout, and saves the output hash and GDAL header alongside each result. Original scans, including upside-down sheets, retain their native pixels.

The published provenance register records the edition, source, original and COG checksums. For Zoomify scans it also records the viewer, source level and terms. [Release provenance](https://github.com/ramSeraph/russian_world_topo_maps/releases/download/200k-gs-orig/200k-provenance.csv)
