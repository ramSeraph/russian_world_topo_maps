# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "topo-map-processor[parse]",
#     "ozi-map",
# ]
#
# [tool.uv.sources]
# ozi-map = { git = "https://github.com/wladich/ozi_map.git" }
# topo-map-processor = { path = "../../topo_map_processor", editable = true }
# ///


import os
import json
import traceback
from pathlib import Path

from PIL import Image

from topo_map_processor.processor import TopoMapProcessor

from ozi_map import ozi_reader

class GSMapstorProcessor(TopoMapProcessor):

    def __init__(self, filepath, extra, index_box, index_properties, id_override=None):
        super().__init__(filepath, extra, index_box, index_properties)
        self.id_override = id_override
        self.mapfile_processed = False
        self.mapfile_title = None
        self.crs_proj = None
        self.ozi_gcps = None
        self.ozi_cutline = None
        self.ozi_cutline_pixels = None
        self.jpeg_export_quality = extra.get('jpeg_export_quality', 50)
        self.warp_jpeg_quality = 100
        self.corner_gcps = extra.get('corner_gcps', None)
        self.cutline_override = extra.get('cutline_override', None)

    def get_id(self):
        if self.id_override is not None:
            return self.id_override
        return super().get_id()

    def get_resolution(self):
        return "auto"

    def get_original_pixel_coordinate(self, p):
        return p

    def get_gcps(self, pre_rotated=False):
        if self.corner_gcps is not None:
            gcps = []
            for gcp in self.corner_gcps:
                gcps.append([(gcp['x'], gcp['y']),
                             (gcp['lon'], gcp['lat'])])
            return gcps

        self.process_map_file()
        if self.ozi_gcps is None:
            raise ValueError("GCPs not available")

        gcps = []
        for ozi_gcp in self.ozi_gcps:
            if ozi_gcp['type'] != 'latlon':
                raise ValueError(f"Unsupported GCP type: {ozi_gcp['type']}")

            pixel = ozi_gcp['pixel']
            ref = ozi_gcp['ref']
            gcps.append([(pixel['x'], pixel['y']),
                         (ref['x'], ref['y'])])
        return gcps

    def get_sheet_ibox(self):
        if self.cutline_override is not None:
            return self.cutline_override

        if self.corner_gcps is not None:
            corners = []
            for gcp in self.corner_gcps:
                corners.append((gcp['lon'], gcp['lat']))
            corners = corners + [corners[0]]
            return corners

        self.process_map_file()
        return self.ozi_cutline + [
            self.ozi_cutline[0]  # Close the polygon
        ]

    def get_corners(self, pre_rotated=False):
        if self.cutline_override is not None:
            gcps = self.get_gcps()
            transformer = self.get_transformer_from_gcps(gcps)
            corners = []
            for corner in self.cutline_override:
                x, y = transformer.rowcol(corner[0], corner[1])
                corners.append((x, y))
            return corners[:-1]

        if self.corner_gcps is not None:
            corners = []
            for gcp in self.corner_gcps:
                corners.append((gcp['x'], gcp['y']))
            return corners

        self.process_map_file()
        corners = self.ozi_cutline_pixels
        return corners

    def process_map_file(self):
        if self.mapfile_processed:
            return
        map_filepath = self.filepath.with_suffix('.map')
        map_data = ozi_reader.read_ozi_map(open(map_filepath, 'rb'))

        self.index_properties['maptitle'] = map_data.get('title', '')

        datum = map_data['datum']
        if datum != 'Pulkovo 1942 (1)':
            raise ValueError(f"Unsupported datum: {datum}")

        self.ozi_gcps = map_data['gcps']

        self.ozi_cutline = map_data['cutline']
        print(f"Cutline: {self.ozi_cutline}")
        self.ozi_cutline_pixels = map_data['cutline_pixels']

        self.mapfile_processed = True

    def rotate(self):

        # no rotation.. only convert

        workdir = self.get_workdir()

        full_img_path = workdir / 'full.jpg'

        if full_img_path.exists():
            return

        self.ensure_dir(workdir)

        img = Image.open(self.filepath)
        rgb_img = img.convert('RGB')
        rgb_img.save(full_img_path, format='JPEG', subsampling=0, quality=100)


    def get_crs_proj(self):
        #self.process_map_file()

        return 'EPSG:4284'
        # copied from https://github.com/wladich/ozi_map/blob/e45c55ca9dd3a7082fe60048a304e5d48d5c2cad/ozi_map/ozi_parser.py#L123
        #return '+proj=longlat +ellps=krass +towgs84=23.9,-141.3,-80.9,0,-0.37,-0.85,-0.12 +no_defs'


def get_sheetmap():
    with open('vlasenko/data/sheet_map.json', 'r') as f:
        sheet_map = json.load(f)
    return sheet_map

def get_bad_sheet_ids():
    bad_sheets_file = Path('vlasenko/bad_sheets.txt')
    if not bad_sheets_file.exists():
        return []
    with open(bad_sheets_file, 'r') as f:
        bad_sheet_ids = [ line.strip() for line in f.readlines() if line.strip() != '' ]
    return bad_sheet_ids

def process_files():
    
    data_dir = Path('vlasenko/data/raw')
    
    from_list_file = os.environ.get('FROM_LIST', None)
    if from_list_file is not None:
        fnames = Path(from_list_file).read_text().split('\n')
        image_files = [ Path(f'{data_dir}/{f.strip()}') for f in fnames if f.strip() != '']
    else:
        # Find all jpg files
        print(f"Finding jpg files in {data_dir}")
        image_files = list(data_dir.glob("**/*.jpg"))

    print(f"Found {len(image_files)} jpg files")

    special_cases_file = Path(__file__).parent / 'vlasenko'/ 'special_cases.json'

    special_cases = {}
    if special_cases_file.exists():
        special_cases = json.loads(special_cases_file.read_text())

    sheet_map = get_sheetmap()

    bad_sheet_ids = get_bad_sheet_ids()

    total = len(image_files)
    processed_count = 0
    failed_count = 0
    success_count = 0
    # Process each file
    for filepath in image_files:
        print(f'==========  Processed: {processed_count}/{total} Success: {success_count} Failed: {failed_count} processing {filepath.name} ==========')
        extra = special_cases.get(filepath.name, {})
        id = filepath.name.replace('.jpg', '')
        if id in bad_sheet_ids:
            continue
        sheet_props = sheet_map[id]
        sheet_props['source_type'] = 'vlasenko'

        subs = []
        if 'parts' not in extra:
            subs.append([id, extra])
        else:
            for i, part in enumerate(extra['parts']):
                subs.append([f'{id}-part{i}', part])

        for subid, subextra in subs:
            try:
                processor = GSMapstorProcessor(filepath, subextra, [], sheet_props, id_override=subid)
                processor.process()
                exit(0)

                #filepath.unlink()
                #filepath.with_suffix('.map').unlink()
                success_count += 1
            except Exception as ex:
                print(f'parsing {filepath} failed with exception: {ex}')
                failed_count += 1
                traceback.print_exc()
                raise
                processor.prompt()
            processed_count += 1

    print(f"Processed {processed_count} images, failed_count {failed_count}, success_count {success_count}")


if __name__ == "__main__":
    import os
    os.environ['GDAL_PAM_ENABLED'] = 'NO'
    process_files()
 
