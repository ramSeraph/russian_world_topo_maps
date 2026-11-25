"""Find the two graticule lines crossing inside a Soviet 1:200k marginal collar.

The coarse enclosure and the original paired-rule results come from find_frames.py.
This pass uses grayscale line contrast on both sides of the map-content boundary.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import math
from pathlib import Path

import cv2
import numpy as np

NAMES = ('NW', 'NE', 'SE', 'SW')
AXES = ((1, 3), (0, 2), (3, 1), (2, 0))


def collar_line(tile):
    # At 300 dpi the intersection normally lies about 105 px inside the outer rule.
    # A physical map line crosses both the unprinted collar and the map content.
    blur = cv2.GaussianBlur(tile.astype('float32'), (3, 1), 0.6)
    strength = np.maximum(0, (np.roll(blur, 5, 1) + np.roll(blur, -5, 1)) / 2 - blur)
    strength = cv2.dilate(np.minimum(1, strength/50), np.ones((1, 3), np.uint8))
    ys = np.arange(30, 385, 2)
    offsets = np.arange(60, 155)
    slopes = np.linspace(-0.05, 0.05, 33)
    xs = offsets[None, :, None] + slopes[:, None, None] * (ys - 108)
    samples = strength[ys, np.rint(xs).astype(int)]
    collar = samples[:, :, ys < 84].mean(axis=2)
    inside = samples[:, :, ys > 145].mean(axis=2)
    # Inside the frame a white sea or pale print can still carry a long faint rule.
    quality = .45*collar + .55*inside
    key = quality - 0.003*np.abs(offsets - 106)
    i, j = np.unravel_index(np.argmax(key), key.shape)
    second = key[:, np.abs(offsets-offsets[j]) > 8].max()
    return float(offsets[j]), float(slopes[i]), float(quality[i,j]), float(key[i,j]-second)


def outer_rule(strip):
    # The thick outer rule persists for hundreds of pixels. A colour key or a
    # margin note touching it can pull a contour vertex away from the frame.
    pixels = strip.astype(np.float32)
    dark = cv2.blur(pixels, (5, 1))
    contrast = (np.roll(dark, 13, 1) + np.roll(dark, -13, 1))/2 - dark
    weight = np.clip(contrast/115, 0, 1) * np.clip((215-dark)/120, 0, 1)
    ys = np.arange(90, 730, 6)
    slopes = np.arange(-.075, .076, .003)
    offsets = np.arange(12, 449)
    xx = np.rint(offsets[None,:,None] + slopes[:,None,None]*(ys-380)).astype(int)
    samples = weight[ys, np.clip(xx, 0, strip.shape[1]-1)]
    support = samples.mean(axis=2)
    i,j = np.unravel_index(np.argmax(support - .00005*abs(offsets-230)), support.shape)
    return offsets[j]-230-slopes[i]*380, slopes[i], float(support[i,j])


def measure(gray, anchors, index):
    x_axis, y_axis = [anchors[i] - anchors[index] for i in AXES[index]]
    x_axis /= np.linalg.norm(x_axis)
    y_axis /= np.linalg.norm(y_axis)
    origin = anchors[index]
    # Extract each side separately to avoid allocating a full-resolution rectified scan.
    def strip(across, along):
        matrix = np.column_stack((across, along, origin - 230*across))
        return cv2.warpAffine(gray, matrix, (460, 730), flags=cv2.INTER_LINEAR|cv2.WARP_INVERSE_MAP,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=255)
    ax, mx, sx = outer_rule(strip(x_axis, y_axis))
    ay, my, sy = outer_rule(strip(y_axis, x_axis))
    ox = (ax + mx*ay)/(1-mx*my)
    oy = ay + my*ox
    if min(sx, sy) >= .48:
        origin = origin + x_axis*ox + y_axis*oy
    matrix = np.column_stack((x_axis, y_axis, origin))
    tile = cv2.warpAffine(gray, matrix, (390, 390), flags=cv2.INTER_LINEAR|cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_REPLICATE)
    a, m, qx, dx = collar_line(tile)
    b, n, qy, dy = collar_line(tile.T)
    x = (a + m*(b-108) - m*n*108)/(1-m*n)
    y = b + n*(x-108)
    xy = origin + x_axis*x + y_axis*y
    reasons = []
    if min(sx, sy) < .48:
        reasons.append('outer frame unclear')
    if min(qx, qy) < 0.55:
        reasons.append('weak graticule line')
    if min(dx, dy) < 0.055:
        reasons.append('competing graticule lines')
    if min(x, y) < 69 or max(x, y) > 147:
        reasons.append('unusual collar width')
    return dict(pixel=xy.round(2).tolist(), outer=origin.round(2).tolist(), support=[round(qx, 3), round(qy, 3)],
                separation=[round(dx, 3), round(dy, 3)], inset=[round(x,1), round(y,1)],
                review_reasons=reasons)


def run(arg):
    root, path = arg
    dest = root / 'grid' / (path.stem+'.json')
    raw = json.loads((root/'corners'/(path.stem+'.json')).read_text())
    out = {}
    if all(raw['corners'].get(k, {}).get('search_anchor') for k in NAMES):
        anchors = np.array([raw['corners'][k]['search_anchor'] for k in NAMES], dtype=float)
        gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE|cv2.IMREAD_IGNORE_ORIENTATION)
        for i, k in enumerate(NAMES):
            c = measure(gray, anchors, i)
            prior = raw['corners'][k].get('pixel')
            if prior:
                c['paired_rule_distance'] = round(math.dist(prior,c['pixel']), 2)
            out[k] = c
    tmp = dest.with_suffix('.tmp')
    tmp.write_text(json.dumps(out, indent=2)+'\n')
    tmp.replace(dest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('ids', nargs='*')
    args = parser.parse_args()
    root = args.root.resolve()
    (root/'grid').mkdir(exist_ok=True)
    cv2.setNumThreads(1)
    files = sorted((root/'originals').glob('*.jpg'))
    plan_path = root/'plan.json'
    if plan_path.is_file():
        planned = {r['scan_id'] for r in json.loads(plan_path.read_text())}
        files = [f for f in files if f.stem in planned]
    with ProcessPoolExecutor(4) as pool:
        list(pool.map(run, ((root, f) for f in files if not args.ids or f.stem in args.ids)))
