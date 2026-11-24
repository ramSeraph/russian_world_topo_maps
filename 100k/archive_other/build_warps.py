"""Build or resume the selected 1:100,000 COGs using the exact 1:200,000 TPS workflow."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import redirect_stdout
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '200k' / 'archive_other'))
import build_cogs


def geometry(row):
    return (row['sha256'], row['width'], row['height'], row['source_crs'], row['bounds'], row['footprint'],
            [(p['pixel'],p['lonlat']) for p in [*row['corners'].values(), *row['other_gcps']]])


def fingerprint(module_hash, row):
    return hashlib.sha256((module_hash + json.dumps(row, sort_keys=True)).encode()).hexdigest()


def build_record(row, job, module_hash):
    sheet = row['scan_id']
    output, receipt, header = (job/'cogs'/(sheet+'.tif'), job/'provenance'/(sheet+'.json'),
                               job/'headers'/(sheet+'.json'))
    if output.exists() and receipt.exists() and header.exists():
        prior = json.loads(receipt.read_bytes())
        # A review note or newly read edition can change independently of every raster pixel.
        if (geometry(row) == geometry(prior['source']) and
                prior['build_fingerprint'] == fingerprint(module_hash, prior['source']) and
                prior['output_sha256'] == build_cogs.digest(output) and
                row['sha256'] == build_cogs.digest(job/'originals'/row['original'])):
            if prior['source'] != row:
                prior.update(source=row, build_fingerprint=fingerprint(module_hash, row))
                tmp = receipt.with_suffix('.tmp')
                tmp.write_text(json.dumps(prior,indent=2)+'\n')
                tmp.replace(receipt)
            return 'reused'
    with open(os.devnull,'w') as quiet, redirect_stdout(quiet):
        build_cogs.build(row, job)
    return 'built'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path)
    p.add_argument('sheets', nargs='*')
    p.add_argument('--jobs', type=int, default=6)
    args = p.parse_args()
    root = args.root.resolve()
    os.environ.update(GDAL_PAM_ENABLED='NO',PYTHONWARNINGS='ignore::FutureWarning')
    for folder in ('cogs', 'provenance', 'headers'):
        (root/folder).mkdir(exist_ok=True)
    with (root/'build.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        rows = json.loads((root/'review/controls.json').read_text())
        wanted = set(args.sheets)
        if wanted:
            rows = [r for r in rows if r['scan_id'] in wanted]
            if len(rows) != len(wanted):
                p.error('A requested sheet is absent from the staged controls')
        # Show corrected warps early, and then build the rest in source ID order.
        rows.sort(key=lambda r:(not r.get('manual_review') and r['source']!='The Red Atlas',r['scan_id']))
        module_hash = build_cogs.digest(Path(build_cogs.__file__))
        failures = {}
        counts = {'built':0, 'reused':0}
        with ProcessPoolExecutor(args.jobs) as workers:
            tasks = {workers.submit(build_record,r,root,module_hash):r['scan_id'] for r in rows}
            for i, task in enumerate(as_completed(tasks),1):
                sheet = tasks[task]
                try:
                    counts[task.result()] += 1
                except Exception as exc:
                    failures[sheet] = str(exc)
                    print(sheet,exc,flush=True)
                if i % 25 == 0 or i == len(rows):
                    print(f'{i}/{len(rows)} checked, {counts["built"]} built, {counts["reused"]} reused, {len(failures)} failed',flush=True)
        if not wanted:
            temp = root/'build-errors.tmp'
            temp.write_text(json.dumps(failures,indent=2)+'\n')
            temp.replace(root/'build-errors.json')
        if failures:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
