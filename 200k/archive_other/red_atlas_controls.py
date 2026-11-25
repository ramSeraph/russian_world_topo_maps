"""Reconstruct the 1:200k Red Atlas graticule readings from the published JPEGs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import cv2
import numpy as np



def readings():
    return json.loads(Path(__file__).with_name('red_atlas_readings.json').read_text())


def verify(path, source):
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != source['sha256']:
            raise ValueError(f'Source checksum mismatch for {path.name}')


def fetch_originals(root):
    folder = root / 'originals'
    folder.mkdir(parents=True, exist_ok=True)
    for entry in readings():
        source = entry['source']
        target = folder / source['original']
        if target.exists():
            verify(target, source)
            continue
        with tempfile.TemporaryDirectory(dir=folder) as work:
            tmp = Path(work) / target.name
            subprocess.run(['curl', '-fsSL', '--retry', '3', '--output', str(tmp), entry['original_url']], check=True)
            verify(tmp, source)
            tmp.replace(target)


def fit_line(gray, x, y, along, offsets, flank, clip, penalty):
    slopes = np.arange(-.065, .066, .005, dtype='float32')
    xs = x + offsets[:, None, None] + slopes[None, :, None] * along
    ys = np.broadcast_to(y + along, xs.shape)
    rows = np.ascontiguousarray(ys).reshape(-1, len(along))

    def sample(dx):
        columns = np.ascontiguousarray(xs + dx).reshape(-1, len(along))
        return cv2.remap(gray, columns, rows, cv2.INTER_LINEAR).reshape(xs.shape).astype(float)

    contrast = (sample(-flank) + sample(flank)) / 2 - sample(0)
    score = np.clip(contrast, *clip).mean(axis=2) - penalty * abs(offsets[:, None])
    i, j = np.unravel_index(np.argmax(score), score.shape)
    return float(offsets[i]), float(slopes[j])


def intersection(gray, seed, corner=None):
    x, y = seed
    if corner:
        # Follow each labelled line into the collar beyond the mapped area.
        along = np.arange(10, 47, dtype='float32')
        vertical = -along if corner[0] == 'N' else along
        horizontal = -along if corner[1] == 'W' else along
        search = (np.arange(-7, 7.01, .25, dtype='float32'), 2.5, (-25, 180), .4)
    else:
        # Interior crossings have visible line segments on both sides.
        vertical = horizontal = np.r_[np.arange(-34, -6), np.arange(7, 35)].astype('float32')
        search = (np.arange(-1.75, 1.76, .25, dtype='float32'), 2.75, (-20, 135), .5)
    a, m = fit_line(gray, x, y, vertical, *search)
    b, n = fit_line(gray.T, y, x, horizontal, *search)
    dx = (a + m*b) / (1 - m*n)
    return [round(x + dx, 2), round(y + b + n*dx, 2)]


def stage(root, build_controls):
    rows = []
    for entry in readings():
        source = entry['source']
        path = root / 'originals' / source['original']
        verify(path, source)
        gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION)
        if gray is None or gray.shape != (source['height'], source['width']):
            raise ValueError(f'Unexpected image dimensions for {path.name}')
        corners = entry.get('printed_corners')
        if corners is None:
            corners = {name: intersection(gray, xy, name) for name, xy in entry['corner_seeds'].items()}
        edits = dict(manual_corners={source['scan_id']: corners}, western_limits={}, southern_limits={})
        row = build_controls(root, source, edits)
        for point in entry.get('interior_seeds', []):
            row['other_gcps'].append(dict(pixel=intersection(gray, point['seed']), lonlat=point['lonlat'],
                                          method='Printed interior graticule'))
        if row['other_gcps']:
            row['notes'].append('Three printed quarter-degree intersections supplement the four printed corners.')
        rows.append(row)
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Fetch and verify the eight released Red Atlas originals')
    parser.add_argument('root', type=Path)
    fetch_originals(parser.parse_args().root)
