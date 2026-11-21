"""Fetch selected Archive.org ZIP ranges and Satmaps scans on the build host."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import zlib

from PIL import Image


HERE = Path(__file__).resolve().parent


def selected_scans():
    mirrors = json.loads((HERE/'archive-mirrors.json').read_text())
    with (HERE/'selected-scans.csv').open() as stream:
        rows = list(csv.DictReader(stream))
    for r in rows:
        if r['source'] == 'Archive.org':
            for k in ('offset', 'end', 'compressed', 'method', 'flags'):
                r[k] = int(r[k])
            r.update(size=int(r['archive_bytes']), mirrors=mirrors[r['source_url']])
    return rows


def fetch(url, *, referer=None, span=None, limit):
    args = ['curl', '-4', '-fsSL', '--retry', '2', '--retry-all-errors', '--connect-timeout', '10',
            '--max-time', '75', '--max-filesize', str(limit)]
    if referer:
        args.extend(['--referer', referer, '--user-agent', 'Mozilla/5.0'])
    if span:
        args.extend(['--range', span])
    return subprocess.check_output([*args, url])


def archive_member(row):
    length = row['end'] - row['offset']
    span = f"{row['offset']}-{row['end'] - 1}"
    for mirror in row['mirrors']:
        try:
            packet = fetch(mirror + '?sheet_range=' + span, span=span, limit=length)
            if len(packet) != length or packet[:4] != b'PK\x03\x04':
                raise ValueError('Incomplete ZIP range')
            name_len, extra = struct.unpack_from('<HH', packet, 26)
            name = packet[30:30 + name_len].decode('utf8' if row['flags'] & 2048 else 'cp437')
            if name != row['archive_member']:
                raise ValueError('ZIP member identity mismatch')
            start = 30 + name_len + extra
            compressed = packet[start:start + row['compressed']]
            data = zlib.decompress(compressed, -15) if row['method'] == 8 else compressed
            if len(data) != row['size'] or f'{zlib.crc32(data):08x}' != row['archive_crc32']:
                raise ValueError('ZIP member size or CRC32 mismatch')
            return data
        except (subprocess.CalledProcessError, ValueError, zlib.error) as error:
            last_error = error
    raise RuntimeError(row['archive_member']) from last_error


def save(path, data):
    partial = path.with_suffix(path.suffix + '.partial')
    partial.write_bytes(data)
    partial.replace(path)


def satmaps_file(row, key, signature, limit):
    for suffix in ('', '&audit=200k', '&sheets=1', '&edition=200k'):
        try:
            data = fetch(row[key] + suffix, referer=row['source_url'], limit=limit)
            if data.startswith(signature):
                return data
            last_error = ValueError('Response contains no matching file')
        except subprocess.CalledProcessError as error:
            last_error = error
    raise ValueError(f"{row['scan_id']}: {key} unavailable") from last_error


def retrieve(root, row):
    sheet = row['scan_id']
    archive = row['source'] == 'Archive.org'
    path = root / 'originals' / (sheet + ('.jpg' if archive else '.gif'))
    receipt = root / 'receipts' / (sheet + '.json')
    data = path.read_bytes() if path.exists() else (
        archive_member(row) if archive else satmaps_file(row, 'satmaps_scan', (b'GIF87a', b'GIF89a'), 65_000_000)
    )
    if archive and (len(data) != int(row['archive_bytes']) or f'{zlib.crc32(data):08x}' != row['archive_crc32']):
        raise ValueError(f'Invalid archive member for {sheet}')
    sha = hashlib.sha256(data).hexdigest()
    if row.get('sha256') and sha != row['sha256']:
        raise ValueError(f'Scan differs from the selected edition for {sheet}')
    with Image.open(io.BytesIO(data)) as im:
        if im.format != ('JPEG' if archive else 'GIF'):
            raise ValueError(f'{sheet} returned {im.format}')
        im.load()
        width, height = im.size
    if not path.exists():
        save(path, data)
    record = {k: v for k, v in row.items() if k not in ('offset','end','compressed','flags','mirrors','method','size','crc32')}
    record.update(original=path.name, bytes=len(data), sha256=sha, width=width, height=height)
    if not archive:
        calibration = root / 'calibration' / (sheet + '.map')
        try:
            snapshot = HERE/'calibration'/calibration.name
            if calibration.exists() or snapshot.exists():
                ozi = (calibration if calibration.exists() else snapshot).read_bytes()
            else:
                ozi = satmaps_file(row, 'satmaps_ozi', b'OziExplorer Map Data File', 2_000_000)
        except ValueError as error:
            record['calibration_issue'] = str(error)
        else:
            if not calibration.exists():
                save(calibration, ozi)
            record.update(calibration=calibration.name, calibration_sha256=hashlib.sha256(ozi).hexdigest())
    save(receipt, (json.dumps(record, indent=2, ensure_ascii=False) + '\n').encode())
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--jobs', type=int, default=5)
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(exist_ok=True, parents=True)
    plan = selected_scans()
    save(root/'plan.json', json.dumps(plan, ensure_ascii=False).encode())
    for folder in ('originals', 'calibration', 'receipts'):
        (root/folder).mkdir(exist_ok=True)
    # Start the calibrated source early so its Ozi files can be assessed during transfer.
    plan.sort(key=lambda r: r['source'] != 'Satmaps')
    result, failures = [], {}
    with ThreadPoolExecutor(args.jobs) as workers:
        futures = {workers.submit(retrieve, root, r): r['scan_id'] for r in plan}
        for future in as_completed(futures):
            try:
                result.append(future.result())
            except Exception as error:
                failures[futures[future]] = repr(error)
                print(futures[future], repr(error), flush=True)
            if (len(result) + len(failures)) % 25 == 0:
                print(len(result), 'verified;', len(failures), 'pending', flush=True)
    save(root/'downloaded.json', json.dumps(sorted(result, key=lambda r: r['scan_id']), ensure_ascii=False, indent=2).encode())
    save(root/'pending.json', json.dumps(failures, indent=2).encode())
    print('Verified', len(result), 'of', len(plan), 'scans', flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
