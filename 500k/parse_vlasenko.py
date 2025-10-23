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
import math
import json
import traceback
from pathlib import Path

from PIL import Image
from pyproj import Transformer, CRS

from topo_map_processor.processor import TopoMapProcessor

from ozi_map import ozi_reader

def get_pulkovo1942_gk_epsg(zone_number):
    """
    Returns the EPSG code for a Pulkovo 1942 / Gauss-Kruger 6-degree zone.

    Args:
        zone_number (int): The Gauss-Krüger zone number (1-60).

    Returns:
        int or None: The EPSG code, or None if the zone number is invalid.
    """
    if 1 <= zone_number <= 60:
        # The pattern for Pulkovo 1942 Gauss-Kruger 6-degree zones is 28400 + zone_number.
        return 28400 + zone_number
    else:
        return None

# Example usage:
#zone_9_epsg = get_pulkovo1942_gk_epsg(9)
#print(f"The EPSG code for Pulkovo 1942 / Gauss-Kruger zone 9 is: {zone_9_epsg}")

#zone_37_epsg = get_pulkovo1942_gk_epsg(37)
#print(f"The EPSG code for Pulkovo 1942 / Gauss-Kruger zone 37 is: {zone_37_epsg}")


def get_gk_zone(longitude):
    """
    Calculates the 6-degree Gauss-Krüger zone number from a given longitude.
    This formula is specific to the Soviet military mapping system.

    Args:
        longitude (float): The longitude in decimal degrees (e.g., 55.75).

    Returns:
        int: The Gauss-Krüger zone number.
    """
    # The Soviet Gauss-Krüger system starts zone 1 at the prime meridian.
    # Zones are 6 degrees wide.
    # The central meridian of zone 1 is 3° E.
    # Zone number = floor(longitude / 6) + 1
    
    # Handle negative longitudes correctly
    if longitude < 0:
        zone = math.floor((longitude + 180) / 6) + 1
    else:
        zone = math.floor(longitude / 6) + 1
        
    return int(zone)



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
        self.other_gcps = extra.get('other_gcps', None)
        self.cutline_override = extra.get('cutline_override', None)

    def get_id(self):
        if self.id_override is not None:
            return self.id_override
        return super().get_id()

    #def get_resolution(self):
    #    return "auto"

    def get_original_pixel_coordinate(self, p):
        return p

    def get_gcps(self, pre_rotated=False):
        if self.corner_gcps is not None:
            gcps = []
            for gcp in self.corner_gcps:
                gcps.append([(gcp['x'], gcp['y']),
                             (gcp['lon'], gcp['lat'])])
            if self.other_gcps is not None:
                for gcp in self.other_gcps:
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


    def export_bounds_file(self):
        bounds_dir = self.get_bounds_dir()

        bounds_file = bounds_dir.joinpath(f'{self.get_id()}.geojsonl')
        if bounds_file.exists():
            print(f'{bounds_file} exists.. overwriting')
            bounds_file.unlink()

        self.ensure_dir(bounds_dir)

        workdir = self.get_workdir()
        cutline_file = workdir.joinpath('cutline.geojson')
        cutline_crs = self.get_crs_proj()

        self.run_external(f'ogr2ogr -t_srs EPSG:4326 -s_srs {cutline_crs} -f GeoJSONSeq {str(bounds_file)} {cutline_file}')


    def get_same_proj_resolution(self):
        gcps = self.get_gcps()

        #crs = CRS.from_proj4(self.get_crs_proj())
        crs = CRS.from_proj4(self.get_crs_proj_real())
        geog_crs = crs.geodetic_crs
        transformer = Transformer.from_crs(geog_crs, crs, always_xy=True)
        projected_gcps = []
        for gcp in gcps:
            corner = gcp[0]
            idx    = gcp[1]
            projected_idx = transformer.transform(idx[0], idx[1])
            projected_gcps.append((corner, projected_idx))

        proj_transformer = self.get_transformer_from_gcps(projected_gcps)
        full_img = self.get_full_img()
        h, w = full_img.shape[:2]
        corners = [
            (0, 0),
            (w, 0),
            (w, h),
            (0, h)
        ]
        #pprint(corners)
        projected_corners = [proj_transformer.xy(corner[1], corner[0]) for corner in corners]
        #pprint(projected_corners)

        proj_ul = projected_corners[0]
        proj_ll = projected_corners[3]
        proj_ur = projected_corners[1]

        proj_ul_ur_xdelta_square = (proj_ul[0] - proj_ur[0])**2
        proj_ul_ur_ydelta_square = (proj_ul[1] - proj_ur[1])**2
        #print(f'{proj_ul_ur_xdelta_square=}, {proj_ul_ur_ydelta_square=}')

        proj_ul_ll_xdelta_square = (proj_ul[0] - proj_ll[0])**2
        proj_ul_ll_ydelta_square = (proj_ul[1] - proj_ll[1])**2
        #print(f'{proj_ul_ll_xdelta_square=}, {proj_ul_ll_ydelta_square=}')

        # x_res_square, y_res_square  need to be calculated where
        # (x_res_square * proj_ul_ur_xdelta_square) + (y_res_square * proj_ul_ur_ydelta_square) = w ** 2
        # (x_res_square * proj_ul_ll_xdelta_square) + (y_res_square * proj_ul_ll_ydelta_square) = h ** 2
        # solve for x_res_square, y_res_square
        # (x_res_square * proj_ul_ur_xdelta_square * proj_ul_ll_xdelta_square) + (y_res_square * proj_ul_ur_ydelta_square * proj_ul_ll_xdelta_square) = (w ** 2) * proj_ul_ll_xdelta_square
        # (x_res_square * proj_ul_ll_xdelta_square * proj_ul_ur_xdelta_square) + (y_res_square * proj_ul_ll_ydelta_square * proj_ul_ur_xdelta_square) = (h ** 2) * proj_ul_ur_xdelta_square

        above = (((w ** 2) * proj_ul_ll_xdelta_square) - ((h ** 2) * proj_ul_ur_xdelta_square)) 
        below = ((proj_ul_ur_ydelta_square * proj_ul_ll_xdelta_square) - (proj_ul_ll_ydelta_square * proj_ul_ur_xdelta_square))
        y_res_square = above / below

        x_res_square = ((w ** 2) - (y_res_square * proj_ul_ur_ydelta_square)) / proj_ul_ur_xdelta_square

        print(f'{x_res_square=}, {y_res_square=}')

        return (1/(x_res_square**0.5), 1/(y_res_square**0.5))

    def get_crs_proj(self):
        return 'EPSG:4284'

    def get_crs_proj_real(self):
        #self.process_map_file()
        ibox = self.get_sheet_ibox()
        mid_lon = (min([p[0] for p in ibox]) + max([p[0] for p in ibox])) / 2.0
        zone = get_gk_zone(mid_lon)
        zone_lat = (zone - 1) * 6 + 3
        if zone_lat > 180:
            zone_lat -= 360
        # zone 2: 2500000 zone 3: 3500000
        zone_x = zone * 1000000 + 500000
        to_wgs84 = '28,-130,-95,0,0,0,0'
        return f'+proj=tmerc +lat_0=0 +lon_0={zone_lat} +k=1 +x_0={zone_x} +y_0=0 +ellps=krass +towgs84={to_wgs84} +units=m +no_defs +type=crs'


        #epsg = get_pulkovo1942_gk_epsg(zone)
        #if epsg is None:
        #    raise ValueError(f"Invalid GK zone {zone} for mid_lon {mid_lon}")
        #print(f"Using EPSG:{epsg} for mid_lon {mid_lon} zone {zone}")
        #return f'EPSG:{epsg}'
        # copied from https://github.com/wladich/ozi_map/blob/e45c55ca9dd3a7082fe60048a304e5d48d5c2cad/ozi_map/ozi_parser.py#L123
        #return '+proj=longlat +ellps=krass +towgs84=23.9,-141.3,-80.9,0,-0.37,-0.85,-0.12 +no_defs'

    def georeference(self):
        workdir = self.get_workdir()

        georef_file = workdir.joinpath('georef.tif')
        final_file  = workdir.joinpath('final.tif')
        if georef_file.exists() or final_file.exists():
            print(f'{georef_file} or {final_file} exists.. skipping')
            return

        from_file = self.get_full_file_path()

        crs_proj = self.get_crs_proj_real()

        gcps = self.get_gcps()

        #crs = CRS.from_proj4(self.get_crs_proj())
        crs = CRS.from_proj4(self.get_crs_proj_real())

        geog_crs = crs.geodetic_crs
        transformer = Transformer.from_crs(geog_crs, crs, always_xy=True)
        projected_gcps = []
        for gcp in gcps:
            corner = gcp[0]
            idx    = gcp[1]
            projected_idx = transformer.transform(idx[0], idx[1])
            projected_gcps.append((corner, projected_idx))

        gcp_str = ''
        for gcp in projected_gcps:
            corner = gcp[0]
            idx    = gcp[1]
            gcp_str += f' -gcp {corner[0]} {corner[1]} {idx[0]} {idx[1]}'
        
        creation_options = '-co TILED=YES -co COMPRESS=DEFLATE -co PREDICTOR=2' 
        perf_options = '--config GDAL_CACHEMAX 128 --config GDAL_NUM_THREADS ALL_CPUS'

        self.ensure_dir(workdir)
        translate_cmd = f'gdal_translate {creation_options} {perf_options} {gcp_str} -a_srs "{crs_proj}" -of GTiff {str(from_file)} {str(georef_file)}' 
        self.run_external(translate_cmd)

    def first_warp(self):
        workdir = self.get_workdir()
        warped_file = workdir.joinpath('warped.tif')
        if warped_file.exists():
            print(f'{warped_file} exists.. skipping')
            return

        georef_file = workdir.joinpath('georef.tif')

        self.ensure_dir(workdir)
        img_quality_config = {
            'COMPRESS': 'DEFLATE',
            #'COMPRESS': 'JPEG',
            'PREDICTOR': '2',
            #'PHOTOMETRIC': 'YCBCR',
            #'JPEG_QUALITY': self.warp_jpeg_quality,
            'TILED': 'YES',
            'BIGTIFF': 'IF_SAFER',
        }

        warp_quality_options = ' '.join([ f'-co {k}={v}' for k,v in img_quality_config.items() ])

        #res = self.get_resolution()
        #size_options = f'-tr {res} {res}'
        res = self.get_same_proj_resolution()
        #print(res)
        #exit(0)
        crs_proj = self.get_crs_proj_real()
        FACTOR = 0.5
        size_options = f'-tr {res[0]*FACTOR} {res[1]*FACTOR}'
        #size_options = f'-tr {res/2} {res/2}'
        #size_options = '-ts 0 8000'
        #size_options = ''
        reproj_options = f'-tps {size_options} -r bilinear -t_srs "{crs_proj}" -s_srs "{crs_proj}"' 
        #nodata_options = '-dstnodata 0'
        nodata_options = '-dstalpha'
        perf_options = '-multi -wo NUM_THREADS=ALL_CPUS --config GDAL_CACHEMAX 1024 -wm 1024' 

        warp_cmd = f'gdalwarp -overwrite {perf_options} {nodata_options} {reproj_options} {warp_quality_options} {str(georef_file)} {str(warped_file)}'
        self.run_external(warp_cmd)


    def warp(self):
        workdir = self.get_workdir()

        final_file = workdir.joinpath('final.tif')
        if final_file.exists():
            print(f'{final_file} exists.. skipping')
            return

        self.first_warp()

        cutline_file = workdir.joinpath('cutline.geojson')
        warped_file = workdir.joinpath('warped.tif')

        sheet_ibox = self.get_updated_sheet_ibox()
        cutline_crs_proj = self.get_crs_proj()

        self.create_cutline(sheet_ibox, cutline_file)

        img_quality_config = {
            'COMPRESS': 'DEFLATE',
            'PREDICTOR': '2',
            #'PHOTOMETRIC': 'YCBCR',
            #'JPEG_QUALITY': self.warp_jpeg_quality,
            'TILED': 'YES',
            'BIGTIFF': 'IF_SAFER',
        }
        crs_proj = self.get_crs_proj_real()
        warp_quality_options = ' '.join([ f'-co {k}={v}' for k,v in img_quality_config.items() ])
        #res = self.get_resolution()
        #size_options = f'-tr {res} {res}'
        size_options = ''
        reproj_options = f'{size_options} -r bilinear -t_srs "EPSG:3857" -s_srs "{crs_proj}"' 
        nodata_options = '-dstalpha'
        perf_options = '-multi -wo NUM_THREADS=ALL_CPUS --config GDAL_CACHEMAX 1024 -wm 1024' 
        cutline_options = f'-cutline {str(cutline_file)} -cutline_srs "{cutline_crs_proj}" -crop_to_cutline --config GDALWARP_IGNORE_BAD_CUTLINE YES -wo CUTLINE_ALL_TOUCHED=TRUE'
        warp_cmd = f'gdalwarp -overwrite {perf_options} {nodata_options} {reproj_options} {warp_quality_options} {cutline_options} {str(warped_file)} {str(final_file)}'
        self.run_external(warp_cmd)



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
 
