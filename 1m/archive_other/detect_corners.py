# /// script
# dependencies = ["numpy", "opencv-python-headless>=4,<5"]
# ///

"""Locate candidate inner-frame corners on Genshtab 1:1M scans using grayscale.

Usage: uv run detect_corners.py --output results K16.jpg
       uv run detect_corners.py --output results --manifest latest_1m.json
The manifest resolves each selected scan's relative_path from its own directory.
Each input produces one JSON file with NW, NE, SE and SW candidates when found.
Coordinates are pixels in the original scan, measured from the top left.
This follows TopoMapProcessor.get_corners' coarse-contour / native-corner
workflow. Local sloping rules may be skewed or tangent to a curved parallel.
All returned locations are candidates for review, including status=candidate.
The published 1m-gs-georef release includes the reviewed corners and manual
overrides in 1m-controls.json, alongside the sheet years in 1m-provenance.csv.
"""

import argparse
import json
from pathlib import Path
import re

import cv2
import numpy as np


def coarse_frame(gray):
    """Locate the large printed enclosure. Its corners seed local searches only."""
    h, w = gray.shape
    scale = min(1, 2000 / max(w, h))
    thumb = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ink = cv2.adaptiveThreshold(
        thumb, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 6
    )
    candidates = []
    for diameter in (3, 1, 7):
        mask = cv2.morphologyEx(
            ink, cv2.MORPH_CLOSE, np.ones((diameter, diameter), np.uint8)
        )
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:15]:
            area = cv2.contourArea(contour) / mask.size
            if not 0.43 < area < 0.96:
                continue
            perimeter = cv2.arcLength(contour, True)
            for tolerance in (0.009, 0.015, 0.022):
                poly = cv2.approxPolyDP(contour, perimeter * tolerance, True).reshape(
                    -1, 2
                )
                if len(poly) == 4 and cv2.isContourConvex(poly):
                    poly = np.roll(poly, -np.argmin(poly.sum(axis=1)), axis=0)
                    if poly[1, 0] < poly[3, 0]:
                        poly = poly[[0, 3, 2, 1]]
                    candidates.append((area, poly / scale))
                    break
        if candidates:
            return max(candidates, key=lambda pair: pair[0])[1]
    raise ValueError("No large four-sided frame contour")


# In each crop the page interior is down and right. Work in 300 dpi units so
# the same line spacings apply when the filename specifies a different DPI.
OFFSET = 220
EXTENT = 550


def corner_crop(gray, anchor, direction, ratio):
    coords = np.arange(-OFFSET, EXTENT, dtype=np.float32) * ratio
    xs = anchor[0] + coords * direction[0]
    ys = anchor[1] + coords * direction[1]
    mx, my = np.meshgrid(xs, ys)
    return cv2.remap(
        gray,
        mx.astype(np.float32),
        my.astype(np.float32),
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=255,
    )


def ink_strength(gray):
    # Local luminance contrast across the rule. Coloured or faded ink can
    # register on a light or dark map background.
    paper = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, np.ones((33, 1), np.uint8))
    return np.clip((paper.astype(np.float32) - gray - 6) / 50, 0, 1)


def frame_lines(ink):
    """Find parallel, sustained ink rules with a light collar on their outside."""
    xs = np.arange(190, 431, 5)
    pivot = xs.mean()
    offsets = np.arange(-155, 236)
    candidates = []
    for slope in np.arange(-0.43, 0.431, 0.01):
        ys = offsets[:, None] + np.rint((xs - pivot) * slope).astype(int)
        profile = ink[OFFSET + ys, OFFSET + xs].mean(axis=1)
        # Use the innermost strong rule of a closely spaced pair. Coordinate
        # labels and decorative borders rarely produce the same pair of lines.
        broad = np.convolve(profile, np.ones(8) / 8, mode="same")
        peaks = (
            np.where(
                (profile[1:-1] >= profile[:-2])
                & (profile[1:-1] > profile[2:])
                & (profile[1:-1] >= 0.52)
            )[0]
            + 1
        )
        for inner in peaks:
            outer = peaks[(peaks >= inner - 19) & (peaks <= inner - 6)]
            if not len(outer):
                continue
            outer = outer[np.argmax(profile[outer])]
            collar = profile[max(0, outer - 55) : max(0, outer - 8)]
            if len(collar) < 16:
                continue
            # The coordinate band sits inside a much heavier decorative rule.
            # Require that rule outside the pair, across the mostly blank collar.
            band = broad[max(0, outer - 155) : max(0, outer - 46)]
            if len(band) == 0 or band.max() < 0.48:
                continue
            score = (
                0.47 * profile[inner]
                + 0.33 * profile[outer]
                + 0.2 * band.max()
                - 0.4 * collar.mean()
            )
            # A third sustained line immediately inward is usually the actual
            # inner edge of a subdivided minute band.
            if np.any((peaks > inner) & (peaks <= inner + 8)):
                score -= 0.16
            candidates.append((float(score), slope, offsets[inner] - slope * pivot))
    distinct = []
    for candidate in sorted(candidates, reverse=True):
        if all(
            abs((candidate[2] + pivot * candidate[1]) - (b + pivot * m)) > 5
            or abs(candidate[1] - m) > 0.055
            for _, m, b in distinct
        ):
            distinct.append(candidate)
        if len(distinct) == 5:
            break
    return distinct


def intersection(horizontal, vertical):
    mh, bh = horizontal
    mv, bv = vertical
    x = (bv + mv * bh) / (1 - mv * mh)
    return np.array([x, mh * x + bh])


def refine(ink, line, start):
    """Refit to grayscale stroke centres on the inward arm near the intersection."""
    m, b = line
    xs = start + np.arange(6, 182, 2)
    xi = np.rint(xs).astype(int)
    predicted = m * xi + b
    base = np.rint(predicted).astype(int)
    offsets = np.arange(-7, 8)
    ys = base[:, None] + offsets
    if (
        (OFFSET + xi).min() < 0
        or (OFFSET + xi).max() >= ink.shape[1]
        or (OFFSET + ys).min() < 0
        or (OFFSET + ys).max() >= ink.shape[0]
    ):
        raise ValueError("Corner outside local search window")
    samples = ink[OFFSET + ys, OFFSET + xi[:, None]]
    # Select the nearest dark stroke, then use its local centre of mass.
    indices = (samples - 0.045 * np.abs(ys - predicted[:, None])).argmax(axis=1)
    strong = samples[np.arange(len(xs)), indices] > 0.42
    weights = np.maximum(samples - 0.18, 0) * (
        np.abs(np.arange(len(offsets)) - indices[:, None]) <= 2
    )
    observations = (ys * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1e-5)
    keep = strong
    if keep.mean() < 0.64:
        raise ValueError("Weak support on inward arm")
    m, b = np.polyfit(xi[keep], observations[keep], 1)
    keep = strong & (np.abs(observations - (m * xi + b)) < 2.8)
    if keep.mean() < 0.60 or keep[:18].mean() < 0.5:
        raise ValueError("Fragmented inward arm")
    return np.polyfit(xi[keep], observations[keep], 1), float(keep.mean())


def detect_corner(gray, anchor, direction, ratio):
    patch = corner_crop(gray, anchor, direction, ratio)
    horizontal, vertical = ink_strength(patch), ink_strength(patch.T)
    hs, vs = frame_lines(horizontal), frame_lines(vertical)
    if not hs or not vs:
        raise ValueError("No paired rules in both directions")
    solutions = []
    for sh, mh, bh in hs:
        for sv, mv, bv in vs:
            initial = intersection((mh, bh), (mv, bv))
            try:
                hline, hsupport = refine(horizontal, (mh, bh), initial[0])
                vline, vsupport = refine(vertical, (mv, bv), initial[1])
            except ValueError:
                continue
            point = intersection(hline, vline)
            support = min(hsupport, vsupport)
            score = min(sh, sv) + 0.18 * support
            solutions.append(
                (score, point, support, min(sh, sv), np.linalg.norm(initial - point))
            )
    if not solutions:
        raise ValueError("No crossing with two supported inward arms")
    solutions.sort(key=lambda v: v[0], reverse=True)
    score, point, support, pair_score, shift = solutions[0]
    reasons = []
    if pair_score < 0.69:
        reasons.append("weak paired rules")
    if any(
        score - other[0] < 0.045 and np.linalg.norm(point - other[1]) > 7
        for other in solutions[1:]
    ):
        reasons.append("competing frame intersections")
    if shift > 8:
        reasons.append("local and extended line fits disagree")
    xy = anchor + np.array(direction) * point * ratio
    if not (0 <= xy[0] < gray.shape[1] and 0 <= xy[1] < gray.shape[0]):
        raise ValueError("Intersection outside scan")
    return dict(
        pixel=np.round(xy, 2).tolist(),
        support=round(support, 2),
        pair_score=round(pair_score, 2),
        review_reasons=reasons,
    )


def detect(path):
    gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION)
    if gray is None:
        raise ValueError("Unreadable scan")
    dpi = re.search(r"_(\d+)dpi", path.name, re.IGNORECASE)
    ratio = int(dpi[1]) / 300 if dpi else 1
    corners = {}
    try:
        frame = coarse_frame(gray)
    except ValueError as error:
        return dict(
            scan=path.name,
            status="review",
            width=gray.shape[1],
            height=gray.shape[0],
            reason=str(error),
            corners={},
        )
    positions = [("NW", (1, 1)), ("NE", (-1, 1)), ("SE", (-1, -1)), ("SW", (1, -1))]
    for anchor, (name, direction) in zip(frame, positions):
        try:
            corners[name] = detect_corner(gray, anchor, direction, ratio)
        except ValueError as error:
            corners[name] = dict(pixel=None, review_reasons=[str(error)])
        corners[name]["search_anchor"] = np.rint(anchor).astype(int).tolist()
    status = (
        "review" if any(c["review_reasons"] for c in corners.values()) else "candidate"
    )
    return dict(
        scan=path.name,
        status=status,
        width=gray.shape[1],
        height=gray.shape[0],
        corners=corners,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", type=Path, help="Process the selected editions in a download manifest")
    parser.add_argument("scans", type=Path, nargs="*")
    args = parser.parse_args()
    if bool(args.manifest) == bool(args.scans):
        parser.error("Supply either --manifest or one or more scan paths")
    if args.manifest:
        inventory = json.loads(args.manifest.read_text())
        args.scans = [
            args.manifest.parent / row["relative_path"]
            for row in inventory["scans"] if row["preferred_for"]
        ]
        if not args.scans:
            parser.error("The manifest contains no selected scans")
    if len({scan.stem for scan in args.scans}) != len(args.scans):
        parser.error(
            "Input scans must have distinct basenames in a shared output directory"
        )
    args.output.mkdir(exist_ok=True, parents=True)
    cv2.setNumThreads(1)
    for scan in args.scans:
        result = detect(scan)
        (args.output / (scan.stem + ".json")).write_text(
            json.dumps(result, indent=2) + "\n"
        )
        print(scan.name, result["status"], flush=True)


if __name__ == "__main__":
    main()
