"""Reassemble the selected public Zoomify levels from the Red Atlas sheet inventory."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
from urllib.request import urlopen
from xml.etree import ElementTree

from PIL import Image


def pixel_digest(image):
    digest = hashlib.sha256()
    for y in range(0, image.height, 128):
        digest.update(image.crop((0, y, image.width, min(y + 128, image.height))).convert('RGB').tobytes())
    return digest.hexdigest()


def save_receipt(output, record, row):
    with output.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    data = dict(row, source_level_width=int(row['source_level_width']),
                source_level_height=int(row['source_level_height']),
                estimated_level_dpi=float(row['estimated_level_dpi']), mosaic_sha256=checksum)
    tmp = record.with_suffix('.tmp')
    tmp.write_text(json.dumps(data)+'\n')
    tmp.replace(record)


def fetch(task):
    root, command, row = task
    sheet = row['sheet']
    output = root / 'mosaics' / (sheet + '.png')
    record = root / 'retrieval' / (sheet + '.json')
    if output.exists():
        with Image.open(output) as image:
            if (image.size != (int(row['source_level_width']), int(row['source_level_height']))
                    or pixel_digest(image) != row['rgb_sha256']):
                raise ValueError(f'{sheet} local scan checksum differs')
        save_receipt(output, record, row)
        return
    with urlopen(row['zoomify_descriptor'], timeout=45) as response:
        xml = response.read()
    if hashlib.sha256(xml).hexdigest() != row['descriptor_sha256']:
        raise ValueError(f'{sheet} descriptor has changed')
    props = ElementTree.fromstring(xml).attrib
    tile_size = int(props['TILESIZE'])
    width, height, level = (int(row[k]) for k in ('source_level_width', 'source_level_height', 'source_level'))
    cache = root / 'cache' / sheet
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as work:
        result = Path(work) / (sheet + '.png')
        subprocess.run(command + ['--dezoomer', 'zoomify', '--zoom-level', str(level),
                       '--parallelism', '8', '--min-interval', '30ms', '--retries', '4',
                       '--timeout', '40s', '--tile-cache', str(cache),
                       row['zoomify_descriptor'], str(result)], check=True, timeout=1200)
        coordinates = {}
        for entry in cache.rglob('*'):
            if not entry.is_file():
                continue
            match = re.search(r'_TileGroup\d+_(\d+)-(\d+)-(\d+)\.jpg-', entry.name, re.I)
            if not match or int(match[1]) != level:
                raise ValueError(f'{sheet} unexpected tile {entry.name}')
            xy = int(match[2]), int(match[3])
            if xy in coordinates:
                raise ValueError(f'{sheet} duplicate tile {xy}')
            coordinates[xy] = entry
        grid = {(x, y) for x in range(math.ceil(width/tile_size)) for y in range(math.ceil(height/tile_size))}
        if grid != coordinates.keys() or len(grid) != int(row['tiles_verified']):
            raise ValueError(f'{sheet} tile grid differs from the selected edition')
        # The last source JPEG can extend a pixel beyond the rounded descriptor dimensions.
        with Image.new('RGB', (width, height)) as mosaic:
            for (x, y), path in coordinates.items():
                with Image.open(path) as tile:
                    left, top = x * tile_size, y * tile_size
                    if tile.size != (min(tile_size, width-left), min(tile_size, height-top)):
                        raise ValueError(f'{sheet} tile {(x, y)} has the wrong dimensions')
                    mosaic.paste(tile, (left, top))
            if pixel_digest(mosaic) != row['rgb_sha256']:
                raise ValueError(f'{sheet} source pixels have changed')
            mosaic.save(result, compress_level=1)
        result.replace(output)
    save_receipt(output, record, row)
    shutil.rmtree(cache)
    print(sheet, 'verified', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('sheets', nargs='*', help='Optional sheet IDs to fetch or verify')
    parser.add_argument('--jobs', type=int, default=3)
    parser.add_argument('--dezoomify-command', default='dezoomify-rs')
    args = parser.parse_args()
    root = args.root.resolve()
    for subdir in ('mosaics', 'cache', 'retrieval'):
        (root / subdir).mkdir(exist_ok=True, parents=True)
    with Path(__file__).with_name('red-atlas.csv').open() as stream:
        rows = list(csv.DictReader(stream))
    if args.sheets:
        selected = set(args.sheets)
        rows = [row for row in rows if row['sheet'] in selected]
        if {row['sheet'] for row in rows} != selected:
            parser.error('Unknown Red Atlas sheet ID')
    with ThreadPoolExecutor(args.jobs) as pool:
        list(pool.map(fetch, ((root, shlex.split(args.dezoomify_command), row) for row in rows)))


if __name__ == '__main__':
    main()
