# General Staff 1:200,000 scan controls

The November 2026 selection comprises 544 Archive.org JPEGs and 21 Satmaps GIFs. Each row in [selected-scans.csv](selected-scans.csv) identifies one original by SHA-256. Joined scans retain their component identifiers in one row. Archive.org rows also record the ZIP member, byte range, compression method, CRC32 and filename year. Satmaps catalogue years are unknown.

Run the following from the repository root on the remote build host. The Python environment needs NumPy, OpenCV, Pillow, pyproj and Shapely. The corner measurements used OpenCV 5.0.0. Orientation checks use Tesseract with its OSD data.

```sh
scripts=200k/archive_other
job=/path/to/200k-staging
python3 "$scripts/fetch_selected.py" "$job"
python3 "$scripts/find_frames.py" "$job"
python3 "$scripts/find_inner_grid.py" "$job"
python3 "$scripts/check_orientation.py" "$job"
python3 "$scripts/stage_controls.py" "$job"
```

The fetcher checks the selected original before accepting a cached file. It saves an acquisition receipt per scan. The shared grayscale detector finds an enclosing frame. The 1:200k pass fits the thick outer rules and searches the collar for the intersecting printed parallel and meridian. Flags record ambiguous lines, weak evidence or unusual geometry. The shape check measures the maximum corner residual against a rotation and uniform-scale fit in the sheet's projected coordinate system. Scan pixels use a top-left origin.

The 17 original [Ozi calibrations](calibration/) give nine geographic controls each. [Printed controls](printed_controls.json) records native pixel readings for the other four Satmaps scans, individual reviewed corner corrections, checked text orientations, and the limits of four partly joined archive sheets. The stage preserves original pixels on upside-down scans and assigns them geographic corner names. Controls and scan footprints are written to `$job/review/`. Geographic coordinates use the Pulkovo 1942 datum supplied in the Ozi files and assumed for archive sheets.

The staged `controls.json` records the pixel coordinates and geographic coordinates of each control. For manually corrected corners it also retains the detector's original pixel reading. The accompanying `footprints.geojson` contains one feature per scan.
