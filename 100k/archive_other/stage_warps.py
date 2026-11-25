"""Stage 1:100,000 checked graticules and native scans for the shared COG builder."""
import argparse
import csv
import json
import math
from pathlib import Path
import sys

from shapely.geometry import Polygon, mapping

SETTINGS = Path(__file__).resolve().parents[2] / '200k' / 'archive_other'
sys.path.insert(0, str(SETTINGS))
from stage_controls import DATUM, NAMES, WGS


def footprint(row):
    bounds = row['bounds']
    west, south, east, north = bounds
    if not -180 <= west < east <= 180 or not -85.051129 < south < north < 85.051129:
        raise ValueError('The sheet needs manual handling at the projection boundary')
    corners = row['corners']
    if 'footprint_lonlat' in row:
        outline = row['footprint_lonlat']
        if len(outline) < 4 or outline[0] != outline[-1]:
            raise ValueError('The measured native cutline must be a closed ring')
        coordinates = outline[:-1]
    else:
        coordinates = [corners[key]['lonlat'] for key in NAMES]
    reference = Polygon(coordinates)
    if not reference.is_valid or reference.area <= 0:
        raise ValueError('Invalid native cutline')
    ring = []
    for i, (x, y) in enumerate(coordinates):
        next_x, next_y = coordinates[(i+1) % len(coordinates)]
        for j in range(16):
            lon, lat = WGS.transform(x + (next_x-x)*j/16, y + (next_y-y)*j/16)
            if ring and abs(lon-ring[-1][0]) > 180:
                raise ValueError('The transformed footprint crosses the antimeridian')
            ring.append((lon, lat))
    shape = Polygon(ring)
    pixels = Polygon([corners[k]['pixel'] for k in NAMES])
    if not shape.is_valid or shape.area <= 0 or not pixels.is_valid or pixels.area <= 0:
        raise ValueError('Invalid geographic or pixel frame')
    return mapping(shape)


def prepare(control, info):
    if set(control['corners']) != set(NAMES):
        raise ValueError('Four geographical corners are required')
    if info['sha256'] != control['sha256']:
        raise ValueError('The provenance checksum differs from the corner measurement')
    width, height = control['size']
    if [int(info['width']), int(info['height'])] != [width, height]:
        raise ValueError('Provenance and corner image sizes differ')
    meridian = math.floor((control['bounds'][0]+control['bounds'][2])/12)*6+3
    crs = f'+proj=tmerc +lat_0=0 +lon_0={meridian} +k=1 +x_0=500000 +y_0=0 {DATUM} +units=m +type=crs'
    row = {k:control[k] for k in ('scan_id', 'component_ids', 'original', 'sha256', 'source',
                                 'method', 'bounds', 'corners', 'other_gcps', 'flags', 'rotation',
                                 'estimated_dpi', 'shape_error_px')}
    row['scan_id'] = info['scan_id']
    row['catalogue_scan_id'] = info.get('catalogue_scan_id') or control['scan_id']
    if control.get('manual_review'):
        row['manual_review'] = control['manual_review']
    row.update(year=info['year'], source_url=info['source_url'],
               year_basis=info['year_basis'], width=width, height=height, source_crs=crs,
               footprint=footprint(control))
    for key in ('terrain_as_of','printer_date'):
        if info.get(key):
            row[key] = info[key]
    # An Ozi calibration may include only a subset of the nine auxiliary points.
    # Check for contrary coordinates at a common source pixel before applying a TPS.
    points = {}
    for p in [*row['corners'].values(), *row['other_gcps']]:
        xy = tuple(p['pixel'])
        if xy in points and points[xy] != p['lonlat']:
            raise ValueError('A source pixel has conflicting geographic coordinates')
        points[xy] = p['lonlat']
    return row


def write_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':'))+'\n')
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--archive-satmaps', type=Path, required=True)
    parser.add_argument('--red-atlas', type=Path, required=True)
    parser.add_argument('--provenance', type=Path, required=True)
    parser.add_argument('--overrides', type=Path, help='Directory of subsequently reviewed full control records')
    parser.add_argument('--replacements', type=Path, help='Replacement root containing checked/ controls and mosaics/ originals')
    parser.add_argument('--satmaps-replacements', type=Path,
                        help='Replacement root containing checked/ controls and originals/ Satmaps scans')
    args = parser.parse_args()
    job = args.output.resolve()
    originals, review = job/'originals', job/'review'
    originals.mkdir(parents=True, exist_ok=True)
    review.mkdir(exist_ok=True)
    with args.provenance.open() as stream:
        scans = list(csv.DictReader(stream))
    info = {r['scan_id']:r for r in scans}
    if len(info) != len(scans):
        raise ValueError('Duplicate scan in the provenance register')
    # A partial or mislabelled catalogue sheet keeps its original scan filename.
    by_catalogue = {r.get('catalogue_scan_id') or r['scan_id']:r for r in scans}
    if len(by_catalogue) != len(scans):
        raise ValueError('Duplicate catalogue identity in the provenance register')
    source_sets = [(args.archive_satmaps, 'originals'), (args.red_atlas, 'mosaics')]
    if args.replacements:
        source_sets.append((args.replacements, 'mosaics'))
    if args.satmaps_replacements:
        source_sets.append((args.satmaps_replacements, 'originals'))
    candidates = {}
    for root, folder in source_sets:
        for path in sorted((root/'checked').glob('*.json')):
            record = json.loads(path.read_bytes())
            if path.stem != record['scan_id']:
                raise ValueError(f'Mismatched identity in {path}')
            candidates.setdefault(path.stem, []).append((root/folder, record))
    combined, errors = [], {}
    if set(by_catalogue) != set(candidates):
        raise ValueError(f'Provenance and checked scan IDs differ: {sorted(set(by_catalogue) ^ set(candidates))[:20]}')
    for catalogue, expected in by_catalogue.items():
        choices = [(folder, c) for folder, c in candidates[catalogue] if c['sha256'] == expected['sha256']]
        if len(choices) != 1:
            raise ValueError(f'Cannot uniquely match the selected source for {catalogue}')
        folder, c = choices[0]
        override = args.overrides/(catalogue+'.json') if args.overrides else None
        if override and override.exists():
            amendment = json.loads(override.read_bytes())
            if amendment['sha256'] == expected['sha256']:
                c = amendment
        if (c.get('canonical_id') or c['scan_id']) != expected['scan_id']:
            raise ValueError(f'Canonical identity for {catalogue} requires reviewed controls')
        image = (folder / c['original']).resolve(strict=True)
        link = originals / image.name
        if link.is_symlink() and link.resolve() != image:
            candidate = link.with_suffix(link.suffix+'.new')
            candidate.symlink_to(image)
            candidate.replace(link)
        elif not link.exists():
            link.symlink_to(image)
        try:
            combined.append(prepare(c, expected))
        except ValueError as error:
            errors[expected['scan_id']] = str(error)
    combined.sort(key=lambda r:r['scan_id'])
    write_json(review/'controls.json', combined)
    features = [dict(type='Feature', geometry=r['footprint'],
                     properties=dict(id=r['scan_id'], components=r['component_ids'], year=r['year'],
                                     source=r['source'], flags=r['flags'])) for r in combined]
    write_json(review/'footprints.geojson', dict(type='FeatureCollection', features=features))
    write_json(review/'withheld.json', errors)
    print(f'{len(combined)} staged, {len(errors)} withheld', flush=True)


if __name__ == '__main__':
    main()
