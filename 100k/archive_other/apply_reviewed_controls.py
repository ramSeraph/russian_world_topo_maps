"""Apply source-pinned visual review to 1:100,000 graticule controls.

Each output is keyed by the original scan identifier so it can replace the
corresponding checked record. A cropped named sheet can carry a shorter
canonical output name and its measured geographic extent.
"""
import argparse
import json
from pathlib import Path

from find_controls import NAMES, coordinates, shape_error


def apply(row, edit):
    if row['sha256'] != edit['sha256']:
        raise ValueError(f"Reviewed pixels belong to another edition of {row['scan_id']}")
    old = row['corners']
    row['corners_before_manual_review'] = old
    row['flags_before_manual_review'] = row['flags']
    flags = list(row['flags'])
    positions = {k: v['pixel'] for k, v in old.items()}
    if 'rotation' in edit:
        rotation = edit['rotation']
        if rotation != row['rotation']:
            if row['rotation'] not in (0, 180) or rotation not in (0, 180):
                raise ValueError('Unsupported orientation correction')
            opposite = dict(zip(NAMES, NAMES[2:] + NAMES[:2]))
            positions = {k: old[opposite[k]]['pixel'] for k in NAMES}
            flags = [' '.join(opposite.get(s, s) for s in flag.split()) for flag in flags]
        row['rotation'] = rotation
        flags = [flag for flag in flags if flag != 'Check orientation']
    positions.update(edit.get('pixels', {}))
    row['bounds'] = edit.get('bounds', row['bounds'])
    expected = coordinates(row['bounds'])
    geographic = edit.get('corner_lonlat', expected)
    row['corners'] = {k: dict(pixel=positions[k], lonlat=geographic[k]) for k in NAMES}
    if 'other_gcps' in edit:
        row['other_gcps'] = edit['other_gcps']
    for key in ('year', 'canonical_id', 'component_ids', 'method', 'partial_extent', 'footprint_lonlat'):
        if key in edit:
            row[key] = edit[key]
    row['shape_error_px'], row['estimated_dpi'] = shape_error(row['corners'], row['bounds'], row['scan_id'])
    if edit.get('all_corners_checked'):
        flags = [flag for flag in flags if flag == 'Check orientation']
    row['flags'] = list(dict.fromkeys(flags + edit.get('flags', [])))
    row['manual_review'] = edit['evidence']
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checked', nargs='+', type=Path, help='Directories containing checked source JSON')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--edits', type=Path, default=Path(__file__).with_name('reviewed-controls.json'))
    args = parser.parse_args()
    args.output.mkdir(exist_ok=True, parents=True)
    edits = json.loads(args.edits.read_text())
    for sheet, edit in edits.items():
        candidates = [d/(sheet+'.json') for d in args.checked if (d/(sheet+'.json')).is_file()]
        matched = [r for p in candidates if (r := json.loads(p.read_bytes()))['sha256'] == edit['sha256']]
        if len(matched) != 1:
            raise ValueError(f'{sheet} needs exactly one checked record with the reviewed source checksum')
        out = apply(matched[0], edit)
        path = args.output/(sheet+'.json')
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(out, ensure_ascii=False)+'\n')
        tmp.replace(path)
    print('Staged', len(edits), 'source-pinned reviews', flush=True)


if __name__ == '__main__':
    main()
