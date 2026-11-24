"""Stage source-hash-pinned 1:50,000 controls and originals for 100k/archive_other/build_warps.py."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile


def stage(bundle, archive, red_atlas, output, sheets):
    source_dirs = {'Archive.org': archive.resolve(), 'The Red Atlas': red_atlas.resolve()}
    review = output / 'review'
    originals = output / 'originals'
    review.mkdir(parents=True, exist_ok=True)
    originals.mkdir(parents=True, exist_ok=True)
    rows = []
    retained = set()
    with zipfile.ZipFile(bundle) as controls:
        for item in sorted(controls.infolist(), key=lambda record: record.filename):
            name = item.filename.removesuffix('.json')
            if sheets and name not in sheets:
                continue
            row = json.loads(controls.read(item))
            if name in retained or item.filename != row['scan_id'] + '.json' or Path(name).name != name:
                raise ValueError(f'Invalid or duplicate control record {item.filename}')
            if set(row['corners']) != {'NW', 'NE', 'SE', 'SW'}:
                raise ValueError(f'{name} has an incomplete native frame')
            filename = row['original']
            if Path(filename).name != filename:
                raise ValueError(f'Invalid original filename for {name}')
            # A few archive member names do not match the designation printed in the collar.
            source = source_dirs[row['source']] / filename
            with source.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != row['sha256']:
                    raise ValueError(f'Original checksum mismatch for {name}')
            link = originals / filename
            if not os.path.lexists(link):
                link.symlink_to(source)
            elif not link.exists() or not link.samefile(source):
                raise ValueError(f'{link} already refers to a different original')
            rows.append(row)
            retained.add(name)
    if sheets - retained:
        raise ValueError('Absent controls: ' + ', '.join(sorted(sheets - retained)))
    if not rows:
        raise ValueError('The controls bundle contains no selected records')
    register = review / 'controls.json'
    with tempfile.NamedTemporaryFile('w', dir=review, suffix='.json', delete=False) as stream:
        json.dump(rows, stream, separators=(',', ':'), ensure_ascii=False)
        stream.write('\n')
        temporary = Path(stream.name)
    temporary.replace(register)
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path, help='50k-staged-frame-controls.zip')
    parser.add_argument('output', type=Path, help='Staging directory for this selection')
    parser.add_argument('--archive', required=True, type=Path, help='Directory of native Archive.org JPEGs')
    parser.add_argument('--red-atlas', required=True, type=Path, help='Directory of native Red Atlas mosaics')
    parser.add_argument('--sheet', action='append', default=[], help='Stage a specific sheet; repeat as needed')
    args = parser.parse_args()
    count = stage(args.bundle, args.archive, args.red_atlas, args.output.resolve(), set(args.sheet))
    print(f'Staged {count} source-verified native frames in {args.output}')


if __name__ == '__main__':
    main()
