# Reproduce the 1:500,000 frame corners

The November 2026 additions contain 232 original JPEGs. Use the released JPEGs at their native dimensions. The detector measures pixel coordinates from the centre of the upper-left pixel, with x increasing rightwards and y downwards.

From the repository root, this example reproduces the four corners on Canadian sheet `M17-3`. It requires `gh` and `uv`.

```sh
mkdir -p 500k/data/corner-replay/originals
gh release download 500k-gs-orig -p 500k-provenance.csv -D 500k/data/corner-replay
gh release download 500k-gs-orig-extra4 -p M17-3.jpg -D 500k/data/corner-replay/originals
uv run 500k/archive_other/reproduce_corners.py \
  --originals 500k/data/corner-replay/originals \
  --provenance 500k/data/corner-replay/500k-provenance.csv \
  --output 500k/data/corner-replay/results --sheet M17-3
```

To replay the complete batch, download the originals named in the register and omit `--sheet`. Each joined scan uses its full release ID as a single filename.

The runner checks the scan's SHA-256 against the provenance register and invokes the [shared grayscale detector](../../1m/archive_other/detect_corners.py). The archive member names specify 300 dpi. The Western Australian and Red Atlas runs used 200 dpi to scale the detector's search windows. The detector finds the printed frame at reduced resolution, then fits intersecting rules at each corner in the original pixels.

Each output JSON includes the raw detector result, including its review flags, and the four reviewed pixel pairs. The [manual readings](manual_corners.json) are keyed by sheet and original JPEG digest. They correct 53 archive corners and seven Red Atlas corners. The Australian sheets use all 80 detected corners. On `M17-3`, for example, the reviewed southwest corner is `[22, 3848]`.

The [published control points](https://github.com/ramSeraph/russian_world_topo_maps/releases/download/500k-gs-georef/500k-controls.json) provide an independent comparison for all 928 pixel pairs. They also contain the geographic coordinates and extra graticule controls used to warp joined sheets. The [source register](https://github.com/ramSeraph/russian_world_topo_maps/releases/download/500k-gs-orig/500k-provenance.csv) records the origins, editions and checksums.
