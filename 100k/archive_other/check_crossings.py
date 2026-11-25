"""Cross-check proposed coordinates against the two printed lines through the map collar."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import math
from pathlib import Path

import cv2
import numpy as np

from find_controls import NAMES, shape_error


def scan_axis(gray, point, across, along, dpi):
    # The graticule crosses the blank collar and continues into the map. Interior
    # kilometre lines can be darker, but usually stop at the edge of the collar.
    ratio = dpi / 300
    offsets = np.arange(-48 * ratio, 48 * ratio + .01, .5)
    samples = np.r_[np.linspace(-66, -14, 29), np.linspace(12, 99, 39)] * ratio
    positions = point + offsets[:, None, None] * across + samples[None, :, None] * along

    def sample(delta):
        xy = (positions + delta * across).astype('float32')
        return cv2.remap(gray, xy, None, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).astype(float)
    center = sample(0)
    flank = (sample(-3.8 * ratio) + sample(3.8 * ratio)) / 2
    ink = np.clip((flank - center) / 88, 0, 1)
    exterior = np.mean(ink[:, :29], axis=1)
    interior = np.mean(ink[:, 29:], axis=1)
    scores = .63 * exterior + .37 * interior - .0012 * abs(offsets) / ratio
    best = np.argmax(scores)
    alternate = max(scores[abs(offsets - offsets[best]) > 7 * ratio])
    return dict(offset=round(float(offsets[best]), 2),
                outside=round(float(exterior[best]), 3), inside=round(float(interior[best]), 3),
                separation=round(float(scores[best] - alternate), 3))


def check(task):
    root, source, dest, item = task
    out = dest / item.name
    if out.exists():
        return
    r = json.loads(item.read_bytes())
    if r['source'] != 'Satmaps' and len(r['corners']) == 4 and r['flags'] and 90 < (r['estimated_dpi'] or 0) < 420:
        cv2.setNumThreads(1)
        im = cv2.imread(str(root/source/r['original']), cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION)
        points = np.array([r['corners'][k]['pixel'] for k in NAMES])
        candidates, clear, readings = {}, [], {}
        for i, name in enumerate(NAMES):
            v = points[i ^ 1] - points[i]
            h = points[3-i] - points[i]
            a, b = v / np.linalg.norm(v), h / np.linalg.norm(h)
            x = scan_axis(im, points[i], a, b, r['estimated_dpi'])
            y = scan_axis(im, points[i], b, a, r['estimated_dpi'])
            readings[name] = [x, y]
            if all(q['outside'] >= .53 and q['inside'] >= .39 and q['separation'] >= .085 for q in (x, y)):
                candidates[name] = (points[i] + a*x['offset'] + b*y['offset']).round(2).tolist()
                clear.append(name)
        if candidates:
            prior = r['corners']
            proposals = {k: dict(v, pixel=candidates.get(k, v['pixel'])) for k, v in prior.items()}
            error, dpi = shape_error(proposals, r['bounds'], r['scan_id'])
            if error <= r['shape_error_px'] + 2:
                r['corners_before_line_check'] = prior
                r.update(corners=proposals, shape_error_px=error, estimated_dpi=dpi)
                for k in clear:
                    changed = math.dist(prior[k]['pixel'], candidates[k])
                    if error <= 18 and changed <= 4:
                        r['flags'] = [f for f in r['flags'] if f not in ('Check '+k, 'Compare revised '+k, k+' line disagreement')]
                    if changed >= 6 and 'Check '+k not in r['flags']:
                        r['flags'].append('Check '+k)
                if len(clear) == 4 and error <= 12:
                    r['flags'] = [f for f in r['flags'] if f != 'Check frame shape']
        r['crossing_readings'] = readings
    tmp = out.with_suffix('.tmp')
    tmp.write_text(json.dumps(r, ensure_ascii=False)+'\n')
    tmp.replace(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--red-atlas', action='store_true')
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    root = args.root.resolve()
    source, controls = ('mosaics', 'controls') if args.red_atlas else ('originals', 'refined')
    dest = root / 'checked'
    dest.mkdir(exist_ok=True)
    with ProcessPoolExecutor(args.jobs) as pool:
        for _ in pool.map(check, ((root, source, dest, f) for f in sorted((root/controls).glob('*.json')))):
            pass


if __name__ == '__main__':
    main()
