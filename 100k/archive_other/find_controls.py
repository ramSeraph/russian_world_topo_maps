"""Stage Pulkovo grid corners for 1:100,000 and 1:50,000 scans from verified receipts."""
import argparse
import csv
import json
import math
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import re
import sys

import cv2
import numpy as np
from pyproj import Transformer
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / '200k' / 'archive_other'))
from check_orientation import check as check_orientation
from find_frames import detect
from find_inner_grid import measure, NAMES
from stage_controls import coordinates, sheet_to_bounds, NATIVE, DATUM
from sheet_to_bounds import parse_sheet_id


def shape_error(corners, bounds, sheet_id=None):
    mid = (bounds[0] + bounds[2]) / 2
    meridian = math.floor(mid / 6) * 6 + 3
    crs = f'+proj=tmerc +lon_0={meridian} +k=1 +x_0=500000 +y_0=0 {DATUM} +units=m +type=crs'
    project = Transformer.from_crs(NATIVE, crs, always_xy=True)
    metric = np.array([complex(x, -y) for x, y in
                       (project.transform(*corners[k]['lonlat']) for k in NAMES)])
    px = np.array([complex(*corners[k]['pixel']) for k in NAMES])
    metric -= metric.mean()
    px -= px.mean()
    scale = np.vdot(metric, px) / np.vdot(metric, metric)
    residual = abs(px - metric * scale)
    denominator = 100_000
    if sheet_id is not None:
        paper_scale = parse_sheet_id(sheet_id.split('_')[0])['scale']
        denominator = {'50k': 50_000, '100k': 100_000}[paper_scale]
    return round(float(max(residual)), 1), round(float(abs(scale) * (denominator * .0254)), 1)


def source_controls(path, row, expected):
    with path.open(encoding='latin1') as stream:
        lines = [line for line in csv.reader(stream) if line]
    if lines[4][0] != 'Pulkovo 1942 (2)':
        raise ValueError('Unsupported source datum')
    dims = next(line for line in lines if line[0] == 'IWH')
    w, h = int(dims[2]), int(dims[3])
    if (w, h) != (row['width'], row['height']):
        raise ValueError('Ozi image size differs from scan')
    xy = {line[1]: list(map(int, line[2:4])) for line in lines if line[0] == 'MMPXY'}
    ll = {line[1]: list(map(float, line[2:4])) for line in lines if line[0] == 'MMPLL'}
    points = []
    for line in lines:
        if not line[0].startswith('Point') or not line[2].strip():
            continue
        x, y = map(int, line[2:4])
        lat = (float(line[6]) + float(line[7]) / 60) * (-1 if line[8] == 'S' else 1)
        lon = (float(line[9]) + float(line[10]) / 60) * (-1 if line[11] == 'W' else 1)
        points.append(dict(pixel=[x, y], lonlat=[lon, lat], enabled=line[4].strip() == 'in'))
    corners, flags = {}, []
    for name, target in expected.items():
        matches = [p for p in points if math.dist(p['lonlat'], target) < 1e-5]
        if len(matches) != 1:
            raise ValueError('No unique Ozi point for ' + name)
        point = matches[0]
        x, y = point['pixel']
        if not (0 <= x <= w and 0 <= y <= h):
            raise ValueError('Nominal Ozi corner outside image')
        corroborated = any(i in ll and math.dist(ll[i], target) < 1e-5
                           and math.dist(pixel, point['pixel']) <= 1.5 for i, pixel in xy.items())
        if (x == w or y == h) and not corroborated:
            flags.append('Check image edge ' + name)
        if not point['enabled'] and not corroborated:
            flags.append('Check unused Ozi point ' + name)
        corners[name] = point
    additional = [p for p in points if p['enabled'] and p not in corners.values()
                  and 0 <= p['pixel'][0] < w and 0 <= p['pixel'][1] < h]
    return corners, additional, flags


def stage(args):
    root, receipt = args
    row = json.loads(receipt.read_bytes())
    sheet = row['scan_id']
    dest = root / 'controls' / receipt.name
    if dest.exists():
        return
    parts = np.array([sheet_to_bounds(s) for s in row['component_ids'].split()])
    bounds = [parts[:, 0].min(), parts[:, 1].min(), parts[:, 2].max(), parts[:, 3].max()]
    geographic = coordinates(bounds)
    source = root / 'originals' / row['original']
    flags, corners, additional = [], {}, []
    method, rotation = 'Source Ozi', None
    measured = {}
    cv2.setNumThreads(1)
    printed = json.loads(Path(__file__).with_name('printed-controls.json').read_text()).get(sheet)
    if printed:
        if printed['sha256'] != row['sha256']:
            raise ValueError(f'Printed controls correspond to a different scan of {sheet}')
        corners = {name: dict(pixel=px, lonlat=geographic[name]) for name, px in printed['corners'].items()}
        method, rotation = 'Printed graticule', 0
        row['year'] = printed['year']
    elif row.get('calibration'):
        try:
            corners, additional, flags = source_controls(root / 'calibration' / row['calibration'], row, geographic)
        except (ValueError, IndexError, StopIteration) as error:
            flags.append('Calibration: ' + str(error))
    if not corners:
        method = 'Grayscale lines'
        dpi = re.search(r'_(\d+)dpi', row['archive_member'], re.I)
        if dpi is None:
            flags.append('Check scan resolution')
        gray = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION)
        if gray is None:
            # Older OpenCV builds lack GIF input support. The PNG preserves pixel coordinates.
            with Image.open(source) as image:
                gray = np.array(image.convert('L'))
            source = root / 'analysis-images' / (sheet + '.png')
            source.parent.mkdir(exist_ok=True)
            Image.fromarray(gray).save(source)
        raw = detect(source, dpi=int(dpi[1]) if dpi else 200)
        # OSD reads the sheet margins. Preserve a low-confidence or unknown result for review.
        check_orientation(source)
        orientation = json.loads((root / 'orientation' / receipt.name).read_bytes())
        rotation = orientation['rotation']
        if rotation not in (0, 180) or (orientation['confidence'] or 0) < 3:
            flags.append('Check orientation')
        if all(raw['corners'].get(k, {}).get('search_anchor') for k in NAMES) and rotation in (0, 180):
            anchors = np.array([raw['corners'][k]['search_anchor'] for k in NAMES], dtype=float)
            for i, k in enumerate(NAMES):
                j = (i + rotation // 90) % 4
                coarse = raw['corners'][NAMES[j]]
                # The collar model uses a 300 dpi working scale. Keep other sizes in the
                # paired-rule detector, which normalizes its measurement to the scan DPI.
                reading = measure(gray, anchors, j) if dpi and int(dpi[1]) == 300 else coarse
                measured[k] = dict(reading)
                if reading.get('pixel') is None:
                    flags.append(k + ' unplaced')
                    continue
                corners[k] = dict(pixel=reading['pixel'], lonlat=geographic[k])
                if reading.get('review_reasons'):
                    flags.append('Check ' + k)
                if reading is not coarse and coarse.get('pixel'):
                    distance = math.dist(reading['pixel'], coarse['pixel'])
                    measured[k]['detector_difference_px'] = round(distance, 1)
                    if distance > 12 and not coarse.get('review_reasons'):
                        flags.append(k + ' line disagreement')
        else:
            flags.append(raw.get('reason') or 'Frame or orientation unresolved')
    err = dpi_estimate = None
    if len(corners) == 4:
        err, dpi_estimate = shape_error(corners, bounds, sheet)
        if err > 30:
            flags.append('Check frame shape')
        if method == 'Grayscale lines' and dpi and abs(dpi_estimate - int(dpi[1])) > int(dpi[1]) * .12:
            flags.append('Check printed extent or resolution')
    out = dict(scan_id=sheet, source=row['source'], year=row['year'], original=row['original'],
               sha256=row['sha256'], size=[row['width'], row['height']], component_ids=row['component_ids'],
               bounds=bounds, method=method, rotation=rotation, corners=corners, other_gcps=additional,
               measurements=measured, shape_error_px=err, estimated_dpi=dpi_estimate, flags=flags)
    tmp = dest.with_suffix('.tmp')
    tmp.write_text(json.dumps(out, ensure_ascii=False) + '\n')
    tmp.replace(dest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    root = args.root.resolve()
    os.environ['OMP_THREAD_LIMIT'] = '1'
    for directory in ('orientation', 'controls'):
        (root / directory).mkdir(exist_ok=True)
    receipts = sorted(f for f in (root / 'receipts').glob('*.json') if not (root / 'controls' / f.name).exists())
    with ProcessPoolExecutor(args.jobs) as pool:
        list(pool.map(stage, ((root, f) for f in receipts)))


if __name__ == '__main__':
    main()
