"""Run the shared grayscale neatline detector at the scan's native resolution."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import re
import sys

import cv2

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / '1m' / 'archive_other'))
from detect_corners import detect


def process(args):
    root, row = args
    sheet = row['scan_id']
    source = root / 'originals' / (sheet + ('.jpg' if row['source'] == 'Archive.org' else '.gif'))
    dest = root / 'corners' / (sheet + '.json')
    if dest.exists() or not source.is_file():
        return
    match = re.search(r'_(\d+)dpi', row['archive_member'], re.I)
    dpi = int(match[1]) if match else (200 if source.suffix == '.gif' else 300)
    cv2.setNumThreads(1)
    try:
        result = detect(source, dpi=dpi)
    except (ValueError, cv2.error) as error:
        result = dict(scan=source.name, status='review', reason=str(error), corners={})
    result['dpi_used'] = dpi
    temp = dest.with_suffix('.tmp')
    temp.write_text(json.dumps(result, indent=2) + '\n')
    temp.replace(dest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    root = args.root.resolve()
    (root/'corners').mkdir(exist_ok=True)
    plan = json.loads((root/'plan.json').read_text())
    with ProcessPoolExecutor(args.jobs) as pool:
        list(pool.map(process, ((root, row) for row in plan)))
