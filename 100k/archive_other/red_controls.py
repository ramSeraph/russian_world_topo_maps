"""Read the printed frame of the selected Red Atlas Zoomify mosaics at their native pixel coordinates."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess

import cv2
import numpy as np

from find_controls import NAMES, coordinates, shape_error, sheet_to_bounds
from refine_frames import frame, inner_corner


def orientation(gray):
    height = gray.shape[0]
    band = max(80, height // 10)
    margins = np.vstack((gray[:band], gray[-band:]))
    result = subprocess.run(['tesseract', 'stdin', 'stdout', '--psm', '0', '--dpi', '225'],
                            input=cv2.imencode('.png', margins)[1].tobytes(), capture_output=True)
    rotation = re.search(rb'Rotate: (\d+)', result.stdout)
    confidence = re.search(rb'Orientation confidence: ([\d.]+)', result.stdout)
    return (int(rotation[1]) if rotation else None, float(confidence[1]) if confidence else 0.0)


def stage(task):
    root, path = task
    meta = json.loads(path.read_text())
    sheet = meta['sheet']
    dest = root / 'controls' / (sheet + '.json')
    if dest.exists():
        return
    cv2.setNumThreads(1)
    photo = root / 'mosaics' / (sheet + '.png')
    gray = cv2.imread(str(photo), cv2.IMREAD_GRAYSCALE)
    height, width = gray.shape
    if (width, height) != (meta['source_level_width'], meta['source_level_height']):
        raise ValueError(f'Dimension mismatch for {sheet}')
    bounds = sheet_to_bounds(sheet)
    ll = coordinates(bounds)
    scale = 300 / meta['estimated_level_dpi']
    normalized = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    factors = np.array([normalized.shape[1] / width, normalized.shape[0] / height])
    rot, confidence = orientation(gray)
    checks = []
    if rot not in (0, 180) or confidence < 3:
        checks.append('Check orientation')
    corners, measurements = {}, {}
    if rot in (None, 0, 180):
        anchors, strength = frame(normalized)
        for i, name in enumerate(NAMES):
            j = (i + (rot or 0) // 90) % 4
            reading = inner_corner(normalized, anchors, j)
            pixel = ((np.array(reading['pixel']) + .5) / factors - .5).round(2).tolist()
            corners[name] = dict(pixel=pixel, lonlat=ll[name])
            measurements[name] = reading
            if min(reading['outer_support']) < .48 or min(reading['support']) < .55 or min(reading['separation']) < .055:
                checks.append('Check ' + name)
        if min(strength) < .48:
            checks.append('Check outer frame')
    error = dpi = None
    if corners:
        error, dpi = shape_error(corners, bounds, sheet)
        if error > 25 or abs(dpi / meta['estimated_level_dpi'] - 1) > .12:
            checks.append('Check frame shape')
    row = dict(scan_id=sheet, source='The Red Atlas', year=meta['year'], original=photo.name,
               sha256=meta['mosaic_sha256'], size=[width, height], component_ids=sheet,
               bounds=bounds, method='Long frame rules', rotation=rot, orientation_confidence=confidence,
               corners=corners, other_gcps=[], measurements=measurements, normalizing_scale=scale,
               shape_error_px=error, estimated_dpi=dpi, flags=checks)
    tmp = dest.with_suffix('.tmp')
    tmp.write_text(json.dumps(row, ensure_ascii=False)+'\n')
    tmp.replace(dest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--jobs', type=int, default=3)
    args = parser.parse_args()
    root = args.root.resolve()
    (root/'controls').mkdir(exist_ok=True)
    os.environ['OMP_THREAD_LIMIT'] = '1'
    with ProcessPoolExecutor(args.jobs) as pool:
        for _ in pool.map(stage, ((root, p) for p in sorted((root/'retrieval').glob('*.json')))):
            pass


if __name__ == '__main__':
    main()
