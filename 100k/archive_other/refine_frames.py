"""Refine doubtful 300 dpi readings using the four long edges of the printed frame."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import math
from pathlib import Path

import cv2
import numpy as np

from find_controls import NAMES, coordinates, shape_error
from find_inner_grid import AXES, collar_line


def line_strength(gray, samples, width):
    rows = np.rint(samples).astype(int).clip(2, gray.shape[0] - 3)
    values = sum(gray[rows + d, :width].astype(float) for d in (-2, 0, 2)) / 3
    padded = np.pad(values, ((0, 0), (10, 10)), constant_values=255)
    contrast = (padded[:, :width] + padded[:, 20:20 + width]) / 2 - values
    ink = np.clip(contrast / 125, 0, 1) * np.clip((228 - values) / 115, 0, 1)
    # Broad marginal rules score higher than thin kilometre lines.
    return .35 * ink + .65 * cv2.erode(ink, np.ones((1, 5), np.uint8))


def full_edge(gray):
    height, width = gray.shape
    samples = np.linspace(.18 * height, .82 * height, 96)
    midpoint = samples.mean()
    limit = int(width * .22)
    ink = line_strength(gray, samples, limit)
    offsets = np.arange(2, limit)
    quality = np.zeros(len(offsets))
    slopes = np.zeros(len(offsets))
    rows = np.arange(len(samples))[:, None]
    for slope in np.arange(-.045, .0451, .001):
        xx = np.rint(offsets + (samples - midpoint)[:, None] * slope).astype(int)
        score = (ink[rows, xx.clip(0, limit - 1)] * (xx >= 0) * (xx < limit)).mean(axis=0)
        better = score > quality
        quality[better] = score[better]
        slopes[better] = slope

    # The outermost sustained rule anchors the search for the inner map boundary.
    start = np.flatnonzero(quality >= quality.max() * .80)[0]
    best = start + np.argmax(quality[start:start + 10])
    offset, slope = offsets[best], slopes[best]
    for _ in range(2):
        prior = offset + (samples - midpoint) * slope
        xx = np.rint(prior[:, None] + np.arange(-6, 7)).astype(int).clip(0, limit - 1)
        values = ink[rows, xx]
        peaks = (values - .016 * abs(xx - prior[:, None])).argmax(axis=1)
        support = values[np.arange(len(samples)), peaks] > .44
        if support.sum() < 18:
            break
        measured = xx[np.arange(len(samples)), peaks]
        slope, offset = np.polyfit(samples[support] - midpoint, measured[support], 1)
    return float(offset - midpoint * slope), float(slope), float(quality[best])


def crossing(vertical, horizontal):
    a, b = vertical[:2]
    c, d = horizontal[:2]
    x = (a + b * c) / (1 - b * d)
    return x, c + d * x


def frame(gray):
    h, w = gray.shape
    left = full_edge(gray)
    right = full_edge(gray[:, ::-1])
    top = full_edge(gray.T)
    bottom = full_edge(gray[::-1, :].T)
    east = (w - 1 - right[0], -right[1])
    south = (h - 1 - bottom[0], -bottom[1])
    anchors = [crossing(left, top), crossing(east, top), crossing(east, south), crossing(left, south)]
    return np.asarray(anchors), [v[2] for v in (left, top, right, bottom)]


def local_edge(gray, across, along, corner):
    transform = np.column_stack((across, along, corner - 44 * across))
    strip = cv2.warpAffine(gray, transform, (89, 620), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                           borderMode=cv2.BORDER_CONSTANT, borderValue=255)
    samples = np.arange(45, 610, 5)
    ink = line_strength(strip, samples, 89)
    offsets = np.arange(13, 76)
    slopes = np.arange(-.035, .036, .002)
    xx = np.rint(offsets[None, :, None] + slopes[:, None, None] * (samples - 260)).astype(int)
    scores = ink[np.arange(len(samples)), xx].mean(axis=2)
    i, j = np.unravel_index(np.argmax(scores - .003 * abs(offsets - 44)), scores.shape)
    return offsets[j] - 44 - slopes[i] * 260, slopes[i], float(scores[i, j])


def inner_corner(gray, anchors, index):
    x_axis, y_axis = [anchors[j] - anchors[index] for j in AXES[index]]
    x_axis /= np.linalg.norm(x_axis)
    y_axis /= np.linalg.norm(y_axis)
    origin = anchors[index]
    vertical = local_edge(gray, x_axis, y_axis, origin)
    horizontal = local_edge(gray, y_axis, x_axis, origin)
    dx, dy = crossing(vertical, horizontal)
    origin = origin + dx * x_axis + dy * y_axis
    transform = np.column_stack((x_axis, y_axis, origin))
    crop = cv2.warpAffine(gray, transform, (390, 390), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_REPLICATE)
    a, m, qx, gapx = collar_line(crop)
    b, n, qy, gapy = collar_line(crop.T)
    x, y = crossing((a - 108 * m, m), (b - 108 * n, n))
    point = origin + x * x_axis + y * y_axis
    return dict(pixel=point.round(2).tolist(), support=[round(qx, 3), round(qy, 3)],
                separation=[round(gapx, 3), round(gapy, 3)], inset=[round(x, 1), round(y, 1)],
                outer_support=[round(vertical[2], 3), round(horizontal[2], 3)], outer=origin.round(2).tolist())


def refine(args):
    root, control = args
    original = json.loads(control.read_bytes())
    out = root / 'refined' / control.name
    if out.exists():
        return
    chosen = original
    if original['source'] == 'Archive.org' and original['flags'] and original['rotation'] in (0, 180):
        cv2.setNumThreads(1)
        photo = root / 'originals' / original['original']
        gray = cv2.imread(str(photo), cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION)
        anchors, support = frame(gray)
        ll = coordinates(original['bounds'])
        measurements = {}
        corners = {}
        flags = [v for v in original['flags'] if v == 'Check orientation']
        for i, k in enumerate(NAMES):
            j = (i + original['rotation'] // 90) % 4
            r = inner_corner(gray, anchors, j)
            measurements[k] = r
            corners[k] = dict(pixel=r['pixel'], lonlat=ll[k])
            if min(r['outer_support']) < .48 or min(r['support']) < .55 or min(r['separation']) < .055:
                flags.append('Check ' + k)
            prior = original['corners'].get(k)
            if prior and math.dist(prior['pixel'], r['pixel']) > 18:
                flags.append('Compare revised ' + k)
        err, dpi = shape_error(corners, original['bounds'], original['scan_id'])
        prior_err = original['shape_error_px']
        if min(support) >= .52 and 280 <= dpi <= 320 and err <= 45 and (prior_err is None or err <= prior_err + 2):
            if err > 30:
                flags.append('Check frame shape')
            if prior_err is None:
                flags.append('Check recovered frame')
            chosen = dict(original, corners=corners, measurements=measurements, flags=flags,
                          method='Long frame rules', previous_corners=original['corners'],
                          previous_flags=original['flags'], previous_shape_error_px=prior_err,
                          shape_error_px=err, estimated_dpi=dpi)
    tmp = out.with_suffix('.tmp')
    tmp.write_text(json.dumps(chosen, ensure_ascii=False) + '\n')
    tmp.replace(out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    root = args.root.resolve()
    (root / 'refined').mkdir(exist_ok=True)
    paths = sorted(p for p in (root / 'controls').glob('*.json') if not (root / 'refined' / p.name).exists())
    with ProcessPoolExecutor(args.jobs) as pool:
        for i, _ in enumerate(pool.map(refine, ((root, p) for p in paths)), 1):
            if i % 100 == 0:
                print('Checked', i, 'of', len(paths), flush=True)
