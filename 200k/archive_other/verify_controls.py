"""Compare reproduced 1:200k ground controls with a released control register."""
import argparse
import json
from pathlib import Path

from shapely.geometry import shape


def by_sheet(path):
    rows = json.loads(path.read_text())
    indexed = {r['scan_id']: r for r in rows}
    if len(rows) != len(indexed):
        raise ValueError(f'Duplicate sheet identifiers in {path}')
    return indexed


def verify(actual, reference):
    if not actual or actual.keys() != reference.keys():
        raise ValueError(f'Sheet register differs: {sorted(actual.keys() ^ reference.keys())}')
    fields = ('sha256', 'bounds', 'source_crs', 'rotation', 'corners', 'other_gcps')
    max_distance = 0
    for sheet, row in actual.items():
        expected = reference[sheet]
        for field in fields:
            if row[field] != expected[field]:
                raise ValueError(f'{sheet}: {field} differs from the release')
        a, b = shape(row['footprint']), shape(expected['footprint'])
        if not (a.is_valid and b.is_valid and not a.is_empty and not b.is_empty):
            raise ValueError(f'{sheet}: invalid footprint')
        # PROJ and GEOS versions can differ in the final decimal places or ring start.
        distance = a.hausdorff_distance(b)
        if distance > 1e-11:
            raise ValueError(f'{sheet}: footprint differs by {distance:g} degrees')
        max_distance = max(max_distance, distance)
    corners = sum(len(r['corners']) for r in actual.values())
    interior = sum(len(r['other_gcps']) for r in actual.values())
    print(f'Matched {len(actual)} sheets, {corners} corners and {interior} additional control points.')
    print(f'Maximum footprint difference: {max_distance:.3g} degrees.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reproduced', type=Path)
    parser.add_argument('released', type=Path)
    args = parser.parse_args()
    verify(by_sheet(args.reproduced), by_sheet(args.released))
