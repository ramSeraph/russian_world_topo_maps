"""Assemble source and detected frame controls for the selected 1:200k scans."""
import argparse
import csv
import json
import math
from pathlib import Path
import sys

import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import Polygon, box, mapping

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]/'new'))
from sheet_to_bounds import sheet_to_bounds

NAMES = ('NW', 'NE', 'SE', 'SW')
DATUM = '+ellps=krass +towgs84=28,-130,-95,0,0,0,0'
NATIVE = CRS.from_proj4('+proj=longlat '+DATUM+' +type=crs')
WGS = Transformer.from_crs(NATIVE, 4326, always_xy=True)


def read(path):
    return json.loads(path.read_text())


def coordinates(box):
    w,s,e,n = box
    return dict(zip(NAMES, [(w,n),(e,n),(e,s),(w,s)]))


def ozi_controls(path, row, expected):
    lines = list(csv.reader(path.read_text(encoding='latin1').splitlines()))
    if lines[4][0] != 'Pulkovo 1942 (2)':
        raise ValueError('Unsupported source datum')
    dims = next(l for l in lines if l[0]=='IWH')
    if [int(x) for x in dims[2:4]] != [row['width'],row['height']]:
        raise ValueError('Ozi image size differs from scan')
    pts = []
    for line in lines:
        if not line[0].startswith('Point') or not line[2].strip():
            continue
        x,y = map(int,line[2:4])
        lat = (float(line[6])+float(line[7])/60)*(-1 if line[8]=='S' else 1)
        lon = (float(line[9])+float(line[10])/60)*(-1 if line[11]=='W' else 1)
        if not (0<=x<row['width'] and 0<=y<row['height']):
            raise ValueError('Ozi point outside original image')
        pts.append(dict(pixel=[x,y],lonlat=[lon,lat]))
    corners = {}
    for k, p in expected.items():
        matches = [c for c in pts if math.dist(c['lonlat'], p)<1e-5]
        if len(matches)!=1:
            raise ValueError(f'No unique Ozi point for {k}')
        corners[k] = matches[0]
    return corners, [c for c in pts if c not in corners.values()]


def controls(root, row, edits):
    sheet = row['scan_id']
    ids = row['component_ids'].split()
    parts = [sheet_to_bounds(i) for i in ids]
    b = [min(v[0] for v in parts),min(v[1] for v in parts),
         max(v[2] for v in parts),max(v[3] for v in parts)]
    notes = []
    for i, key in ((0,'western_limits'), (1,'southern_limits')):
        if sheet in edits[key]:
            v = edits[key][sheet]
            b[i] = v['degrees']+v['minutes']/60
            notes.append('Partial grid cell on '+('western' if i==0 else 'southern')+' edge')
    ll = coordinates(b)
    flags = []
    extra = []
    rotation = 0
    if sheet in edits['manual_corners']:
        method = 'Manual reading'
        corners = {k:dict(pixel=v,lonlat=ll[k]) for k,v in edits['manual_corners'][sheet].items()}
    elif row.get('calibration'):
        method = 'Source Ozi'
        corners,extra = ozi_controls(root/'calibration'/row['calibration'],row,ll)
    else:
        method = 'Grayscale lines'
        detected = read(root/'grid'/(sheet+'.json'))
        rot = read(root/'orientation'/(sheet+'.json'))
        rotation = edits['rotation_checks'].get(sheet,rot['rotation'])
        if rotation not in (0,180):
            raise ValueError(f'Unresolved orientation for {sheet}')
        if rotation:
            notes.append('Scan is upside down; geographic corner order corrected')
        corners = {}
        for i,k in enumerate(NAMES):
            c = detected[NAMES[(i+rotation//90)%4]]
            corners[k] = dict(pixel=c['pixel'],lonlat=ll[k],review_reasons=c['review_reasons'])
            override = edits.get('corner_overrides',{}).get(sheet,{}).get(k)
            if override is not None:
                corners[k] = dict(pixel=override, lonlat=ll[k], original_pixel=c['pixel'], method='Manual reading')
                notes.append(f'{k} corrected from the printed graticule')
            elif c['review_reasons']:
                flags.append(k)
    meridian = math.floor((b[0]+b[2])/12)*6+3
    tm = f'+proj=tmerc +lat_0=0 +lon_0={meridian} +k=1 +x_0=500000 +y_0=0 {DATUM} +units=m +type=crs'
    tr = Transformer.from_crs(NATIVE,tm,always_xy=True)
    metres = np.array([tr.transform(*c['lonlat']) for c in corners.values()])
    px = np.array([c['pixel'] for c in corners.values()])
    # Fit rotation and a uniform scale, retaining a measure of stretch/skew.
    m = metres[:,0] - 1j*metres[:,1]
    q = px[:,0] + 1j*px[:,1]
    m -= m.mean()
    q -= q.mean()
    factor = np.vdot(m,q)/np.vdot(m,m)
    residual = np.abs(q-m*factor)
    err = round(float(residual.max()),1)
    review = edits.get('frame_shape_review',{}).get(sheet)
    if review is not None:
        notes.append('All four printed intersections visually checked')
        for k in NAMES:
            if k in flags:
                flags.remove(k)
                corners[k]['initial_review_reasons'] = corners[k].pop('review_reasons')
    if err>42:
        flags.append('shape')
    # Densify the sheet boundary before conversion into WGS84.
    path = list(ll.values()) + [ll['NW']]
    ring = []
    mid = (b[0]+b[2])/2
    for a,z in zip(path,path[1:]):
        for i in range(16):
            lon,lat = WGS.transform(*(a[j]+(z[j]-a[j])*i/16 for j in (0,1)))
            ring.append([mid+(lon-mid+180)%360-180,lat])
    geom = Polygon(ring).intersection(box(-180,-90,180,90))
    if geom.is_empty or geom.geom_type!='Polygon':
        raise ValueError('Unexpected antimeridian footprint for '+sheet)
    return dict(**row, corners=corners, other_gcps=extra, method=method, rotation=rotation,
                flags=flags, notes=notes, shape_error_px=err, initial_shape_error_px=review, bounds=b, source_crs=tm,
                footprint=mapping(geom))


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    args=parser.parse_args()
    root=args.root.resolve()
    edits=read(HERE/'printed_controls.json')
    records=[controls(root,r,edits) for r in read(root/'downloaded.json')]
    review=root/'review'
    review.mkdir(exist_ok=True)
    (review/'controls.json').write_text(json.dumps(records,ensure_ascii=False,separators=(',',':')))
    feats=[dict(type='Feature',properties=dict(id=r['scan_id'],members=r['component_ids'],year=r['year'] or None,
                  source=r['source'],method=r['method'],flags=r['flags'],notes=r['notes']),
                geometry=r['footprint']) for r in records]
    (review/'footprints.geojson').write_text(json.dumps(dict(type='FeatureCollection',features=feats),separators=(',',':')))
    print(f'{len(records)} controls, {sum(bool(r["flags"]) for r in records)} flagged', flush=True)
