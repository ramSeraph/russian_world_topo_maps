
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pyproj",
#     "shapely",
#     "ozi-map",
# ]
#
# [tool.uv.sources]
# ozi-map = { git = "https://github.com/wladich/ozi_map.git" }
# ///

import json
from pathlib import Path
from pyproj import Transformer
from shapely.geometry import Polygon, MultiPolygon, LineString, mapping
from shapely.ops import split
import ozi_map.ozi_reader as ozi_reader
import sys

base_dir = Path('mapstor/data/raw')
def get_cutline_from_map_file(map_file_path):
    try:
        map_data = ozi_reader.read_ozi_map(open(map_file_path, 'rb'))
        return map_data.get('cutline')
    except Exception as e:
        print(f"Error reading map file {map_file_path}: {e}", file=sys.stderr)
        return None

def process_antimeridian(gif_files):
    output_data = {}

    transformer_to_4326 = Transformer.from_crs("EPSG:4284", "EPSG:4326", always_xy=True)
    transformer_to_4284 = Transformer.from_crs("EPSG:4326", "EPSG:4284", always_xy=True)

    antimeridian_splitter = LineString([(180, -90), (180, 90)])

    for gif_file in gif_files:
        if not gif_file.strip():
            continue
        gif_path = base_dir / gif_file
        map_path = gif_path.with_suffix('.map')

        if not map_path.exists():
            print(f"Warning: Map file not found for {gif_file}", file=sys.stderr)
            continue

        cutline_4284 = get_cutline_from_map_file(map_path)
        if not cutline_4284:
            continue

        cutline_4326 = [transformer_to_4326.transform(lon, lat) for lon, lat in cutline_4284]

        # Normalize longitudes to [0, 360] to handle antimeridian crossing
        cutline_360 = []
        for lon, lat in cutline_4326:
            if lon < 0:
                cutline_360.append((lon + 360, lat))
            else:
                cutline_360.append((lon, lat))
        
        polygon_360 = Polygon(cutline_360)

        # A polygon is invalid if it crosses itself, which can happen with the normalization
        if not polygon_360.is_valid:
            print(f"Warning: Invalid polygon for {gif_file} after longitude normalization. Skipping split.", file=sys.stderr)
            continue

        split_result = split(polygon_360, antimeridian_splitter)
        
        split_polygons = []
        if isinstance(split_result, MultiPolygon) or (hasattr(split_result, 'geoms') and len(split_result.geoms) > 1):
            split_polygons.extend(split_result.geoms)
        else:
            split_polygons.append(split_result)

        parts = []
        for poly_360 in split_polygons:
            # Denormalize longitudes back to [-180, 180]
            cutline_4326_part = []
            for lon, lat in poly_360.exterior.coords:
                if lon > 180:
                    cutline_4326_part.append((lon - 360, lat))
                else:
                    cutline_4326_part.append((lon, lat))
            
            # Shapely polygon exterior is already anticlockwise. We just need to set the start point.
            # Remove closing point for reordering.
            unique_coords = cutline_4326_part[:-1]
            if not unique_coords:
                continue

            # Find top-left point (max-lat, min-lon) and reorder
            start_index = max(range(len(unique_coords)), key=lambda i: (unique_coords[i][1], -unique_coords[i][0]))
            reordered_coords = unique_coords[start_index:] + unique_coords[:start_index]
            reordered_coords.append(reordered_coords[0]) # close polygon

            # Transform back to EPSG:4284
            cutline_4284_part = [transformer_to_4284.transform(lon, lat) for lon, lat in reordered_coords]
            parts.append({"cutline_override": cutline_4284_part})
        
        output_data[gif_path.name] = {"parts": parts}

    return output_data

def main():
    if len(sys.argv) < 2:
        print("Usage: python process_antimeridian.py <list_of_gif_files.txt>", file=sys.stderr)
        sys.exit(1)
    
    gif_list_file = sys.argv[1]
    with open(gif_list_file, 'r') as f:
        gif_files = f.read().splitlines()

    result = process_antimeridian(gif_files)
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
