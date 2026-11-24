"""Compare the printed 2 km lattice of a rectified scan with its nominal corner controls.

The tested Satmaps crops extend to the sheet edges and have been resampled along
longitude and latitude. Project the Gauss–Krüger grid into that native pixel
space and measure how far the printed rules lie from the predicted ones.
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from pyproj import Proj


def grid_pixels(row, axis):
    west, south, east, north = row['bounds']
    meridian = 6 * int(np.floor((west + east) / 12)) + 3
    projection = Proj(proj='tmerc', lon_0=meridian, ellps='krass', x_0=500000, k=1)
    gx, gy = projection([west, east, east, west], [north, north, south, south])
    across, along = (gx, gy) if axis == 0 else (gy, gx)
    lines = np.arange(2000 * np.floor(min(across) / 2000), max(across), 2000)
    a, b = np.meshgrid(lines, np.linspace(min(along), max(along), 700), indexing='ij')
    easting, northing = (a, b) if axis == 0 else (b, a)
    longitude, latitude = projection(easting, northing, inverse=True)
    u, v = (longitude - west) / (east - west), (north - latitude) / (north - south)
    inside = (u > .03) & (u < .97) & (v > .036) & (v < .964)
    u, v = u[inside], v[inside]
    points = np.array([row['corners'][k]['pixel'] for k in ('NW', 'NE', 'SE', 'SW')])
    weights = np.column_stack(((1-u)*(1-v), u*(1-v), u*v, (1-u)*v))
    x, y = (weights @ points).T
    return x, y, u, v


def check_axis(image, row, axis):
    x, y, u, v = grid_pixels(row, axis)
    offsets = np.arange(-75, 76)
    positions = np.broadcast_to(x, (len(offsets), len(x)))
    xx = np.float32(positions + (offsets[:, None] if axis == 0 else 0))
    positions = np.broadcast_to(y, (len(offsets), len(y)))
    yy = np.float32(positions + (offsets[:, None] if axis == 1 else 0))
    samples = cv2.remap(image, xx, yy, cv2.INTER_LINEAR).astype(float)
    masks = {'whole': np.ones(len(x), dtype=bool),
             'NW': (u < .5) & (v < .5), 'NE': (u >= .5) & (v < .5),
             'SE': (u >= .5) & (v >= .5), 'SW': (u < .5) & (v >= .5)}
    result = {}
    for name, mask in masks.items():
        profile = samples[:, mask].mean(axis=1).reshape(1, -1)
        # Printed lines are dark and narrow. Subtract their intensities from
        # their local background to suppress broader changes in map colour.
        contrast = (cv2.GaussianBlur(profile, (0, 0), 5)
                    - cv2.GaussianBlur(profile, (0, 0), .5)).ravel()
        i = contrast.argmax()
        result[name] = {'offset_px': int(offsets[i]), 'contrast': round(float(contrast[i]), 1)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checked_directory', type=Path)
    parser.add_argument('image_directory', type=Path)
    parser.add_argument('sheets', nargs='+')
    args = parser.parse_args()
    results = {}
    for sheet in args.sheets:
        row = json.loads((args.checked_directory / (sheet + '.json')).read_bytes())
        with Image.open(args.image_directory / row['original']) as scan:
            image = np.asarray(scan.convert('L'))
        results[sheet] = {name: check_axis(image, row, i)
                          for i, name in enumerate(('eastings', 'northings'))}
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
