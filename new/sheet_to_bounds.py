#!/usr/bin/env python3
"""
Convert Russian topographic map sheet numbers to geographic bounds.

The Russian (Soviet) military topographic map system uses a hierarchical naming scheme:
- 1:1,000,000 (1M): Letter-Number (e.g., M-36) - 4° lat x 6° lon
- 1:500,000 (500K): Letter-Number-Quadrant (e.g., M-36-1) - 2° lat x 3° lon (quadrants 1-4)
- 1:200,000 (200K): Letter-Number-Roman (e.g., M-36-16) - 40' lat x 1° lon (36 sheets per 1M)
- 1:100,000 (100K): Letter-Number-Number (e.g., M-36-046) - 20' lat x 30' lon (144 sheets per 1M)
- 1:50,000 (50K): Letter-Number-Number-Quadrant (e.g., M-36-046-3) - 10' lat x 15' lon
- 1:25,000 (25K): Letter-Number-Number-Quadrant-Quadrant (e.g., M-36-046-3-4) - 5' lat x 7'30" lon

Latitude bands: A=0-4°, B=4-8°, C=8-12°, ... (Northern hemisphere)
                XA=0-4°S, XB=4-8°S, ... (Southern hemisphere with X prefix)
Longitude zones: 1-60, starting at 180°W, each 6° wide
                Zone 1: 180°W to 174°W
                Zone 31: 0° to 6°E (Greenwich is boundary of zones 30/31)
"""

import re
from typing import Tuple, Optional, Dict


def parse_sheet_id(sheet_id: str) -> Dict:
    """
    Parse a Russian topo map sheet ID into its components.

    Returns a dict with:
        - hemisphere: 'N' or 'S'
        - lat_band: letter (A-V)
        - lon_zone: integer (1-60)
        - scale: '1m', '500k', '200k', '100k', '50k', or '25k'
        - subdivisions: list of subdivision numbers
    """
    # Normalize the sheet ID
    sheet_id = sheet_id.upper().strip()

    # Check for southern hemisphere prefix
    hemisphere = 'N'
    if sheet_id.startswith('X'):
        hemisphere = 'S'
        sheet_id = sheet_id[1:]

    # Parse the base 1:1M sheet (Letter-Number)
    match = re.fullmatch(r'([A-V])-?(\d{1,2})((?:-\d+){0,3})', sheet_id)
    if not match:
        raise ValueError(f"Invalid sheet ID format: {sheet_id}")

    lat_band = match.group(1)
    lon_zone = int(match.group(2))
    remainder = match.group(3)

    if lon_zone < 1 or lon_zone > 60:
        raise ValueError(f"Longitude zone must be 1-60, got {lon_zone}")

    subdivisions = []
    scale = '1m'

    if remainder:
        # Remove leading dash if present
        if remainder.startswith('-'):
            remainder = remainder[1:]

        if not remainder:
            scale = '1m'
        else:
            # Parse subdivisions
            parts = remainder.split('-')

            for i, part in enumerate(parts):
                if not part:
                    continue

                # Check if this is a 3-digit number (100k scale indicator)
                is_3digit = len(part) == 3 and part.isdigit()
                sub_num = int(part)
                subdivisions.append(sub_num)

                if i == 0:
                    # First subdivision determines scale
                    if is_3digit or sub_num > 36:
                        # 100k: sheets 001-144 (3-digit format) or > 36
                        scale = '100k'
                    elif len(part) == 1 and sub_num <= 4:
                        # 500k: quadrants 1-4
                        scale = '500k'
                    else:
                        # 200k: sheets 1-36 (sometimes written as 01-36)
                        scale = '200k'
                elif i == 1:
                    if scale == '500k':
                        # After 500k quadrant, next could be 200k-style or 100k-style
                        scale = '100k' if sub_num > 36 else '200k'
                    else:
                        # 50k quadrant (1-4) after 100k or 200k
                        scale = '50k'
                elif i == 2:
                    # 25k quadrant (1-4) after 50k
                    scale = '25k'

    return {
        'hemisphere': hemisphere,
        'lat_band': lat_band,
        'lon_zone': lon_zone,
        'scale': scale,
        'subdivisions': subdivisions,
        'original': sheet_id
    }


def get_1m_bounds(lat_band: str, lon_zone: int, hemisphere: str = 'N') -> Tuple[float, float, float, float]:
    """
    Get bounds for a 1:1,000,000 scale sheet.

    Returns (min_lon, min_lat, max_lon, max_lat)
    """
    # Latitude: A=0-4, B=4-8, etc.
    band_index = ord(lat_band) - ord('A')
    min_lat = band_index * 4
    max_lat = min_lat + 4

    if hemisphere == 'S':
        min_lat, max_lat = -max_lat, -min_lat

    # Longitude: Zone 1 starts at 180°W (-180°), each zone is 6° wide
    # Zone 1: -180 to -174
    # Zone 30: -6 to 0
    # Zone 31: 0 to 6
    min_lon = -180 + (lon_zone - 1) * 6
    max_lon = min_lon + 6

    return (min_lon, min_lat, max_lon, max_lat)


def get_500k_bounds(lat_band: str, lon_zone: int, quadrant: int, hemisphere: str = 'N') -> Tuple[float, float, float, float]:
    """
    Get bounds for a 1:500,000 scale sheet.

    Quadrants are arranged:
        1 | 2
        -----
        3 | 4

    Each quadrant is 2° lat x 3° lon.
    Returns (min_lon, min_lat, max_lon, max_lat)
    """
    base_bounds = get_1m_bounds(lat_band, lon_zone, hemisphere)
    return subdivide_quadrant(base_bounds, quadrant)


def get_200k_bounds(lat_band: str, lon_zone: int, sheet_num: int, hemisphere: str = 'N') -> Tuple[float, float, float, float]:
    """
    Get bounds for a 1:200,000 scale sheet.

    36 sheets per 1M sheet, arranged 6 columns x 6 rows.
    Each sheet is 40' lat x 1° lon.
    Numbered 1-36 from top-left to bottom-right, row by row.

    Returns (min_lon, min_lat, max_lon, max_lat)
    """
    if sheet_num < 1 or sheet_num > 36:
        raise ValueError(f"200k sheet number must be 1-36, got {sheet_num}")

    base_bounds = get_1m_bounds(lat_band, lon_zone, hemisphere)
    base_min_lon, base_min_lat, base_max_lon, base_max_lat = base_bounds

    # 40 minutes = 2/3 degree
    lat_size = 2/3  # 40' in degrees
    lon_size = 1    # 1° per sheet

    # Sheet numbering: 1-6 in first row (top), 7-12 in second row, etc.
    row = (sheet_num - 1) // 6  # 0-5, top to bottom
    col = (sheet_num - 1) % 6   # 0-5, left to right

    min_lon = base_min_lon + col * lon_size
    max_lon = min_lon + lon_size

    max_lat = base_max_lat - row * lat_size
    min_lat = max_lat - lat_size

    return (min_lon, min_lat, max_lon, max_lat)


def get_100k_bounds(lat_band: str, lon_zone: int, sheet_num: int, hemisphere: str = 'N') -> Tuple[float, float, float, float]:
    """
    Get bounds for a 1:100,000 scale sheet.

    144 sheets per 1M sheet, arranged 12 columns x 12 rows.
    Each sheet is 20' lat x 30' lon.
    Numbered 1-144 (or 001-144) from top-left to bottom-right, row by row.

    Returns (min_lon, min_lat, max_lon, max_lat)
    """
    if sheet_num < 1 or sheet_num > 144:
        raise ValueError(f"100k sheet number must be 1-144, got {sheet_num}")

    base_bounds = get_1m_bounds(lat_band, lon_zone, hemisphere)
    base_min_lon, base_min_lat, base_max_lon, base_max_lat = base_bounds

    # 20 minutes = 1/3 degree
    lat_size = 1/3  # 20' in degrees
    lon_size = 0.5  # 30' in degrees

    # Sheet numbering: 1-12 in first row (top), 13-24 in second row, etc.
    row = (sheet_num - 1) // 12  # 0-11, top to bottom
    col = (sheet_num - 1) % 12   # 0-11, left to right

    min_lon = base_min_lon + col * lon_size
    max_lon = min_lon + lon_size

    max_lat = base_max_lat - row * lat_size
    min_lat = max_lat - lat_size

    return (min_lon, min_lat, max_lon, max_lat)


def subdivide_quadrant(bounds: Tuple[float, float, float, float], quadrant: int, hemisphere: str = 'N') -> Tuple[float, float, float, float]:
    """
    Subdivide bounds into quadrants (used for 50k and 25k).

    Quadrants are arranged:
        1 | 2
        -----
        3 | 4

    Returns (min_lon, min_lat, max_lon, max_lat)
    """
    min_lon, min_lat, max_lon, max_lat = bounds

    mid_lon = (min_lon + max_lon) / 2
    mid_lat = (min_lat + max_lat) / 2

    if quadrant == 1:
        return (min_lon, mid_lat, mid_lon, max_lat)
    elif quadrant == 2:
        return (mid_lon, mid_lat, max_lon, max_lat)
    elif quadrant == 3:
        return (min_lon, min_lat, mid_lon, mid_lat)
    elif quadrant == 4:
        return (mid_lon, min_lat, max_lon, mid_lat)
    else:
        raise ValueError(f"Quadrant must be 1-4, got {quadrant}")


def sheet_to_bounds(sheet_id: str) -> Tuple[float, float, float, float]:
    """
    Convert a Russian topo map sheet ID to geographic bounds.

    Args:
        sheet_id: Sheet identifier (e.g., "M-36", "M-36-1", "M-36-046", "M-36-046-3")

    Returns:
        Tuple of (min_lon, min_lat, max_lon, max_lat) in decimal degrees

    Examples:
        >>> sheet_to_bounds("M-36")
        (30, 48, 36, 52)
        >>> sheet_to_bounds("A-48")
        (102, 0, 108, 4)
        >>> sheet_to_bounds("XC21-1") == (-60, -10, -57, -8)
        True
        >>> tuple(round(edge, 6) for edge in sheet_to_bounds("XE19-01"))
        (-72, -16.666667, -71, -16.0)
    """
    parsed = parse_sheet_id(sheet_id)

    hemisphere = parsed['hemisphere']
    lat_band = parsed['lat_band']
    lon_zone = parsed['lon_zone']
    scale = parsed['scale']
    subdivisions = parsed['subdivisions']

    if scale == '1m':
        return get_1m_bounds(lat_band, lon_zone, hemisphere)

    elif scale == '500k':
        return get_500k_bounds(lat_band, lon_zone, subdivisions[0], hemisphere)

    elif scale == '200k':
        return get_200k_bounds(lat_band, lon_zone, subdivisions[0], hemisphere)

    elif scale == '100k':
        return get_100k_bounds(lat_band, lon_zone, subdivisions[0], hemisphere)

    elif scale == '50k':
        # Get 100k bounds first, then subdivide
        bounds = get_100k_bounds(lat_band, lon_zone, subdivisions[0], hemisphere)
        return subdivide_quadrant(bounds, subdivisions[1], hemisphere)

    elif scale == '25k':
        # Get 100k bounds, subdivide to 50k, then subdivide again
        bounds = get_100k_bounds(lat_band, lon_zone, subdivisions[0], hemisphere)
        bounds = subdivide_quadrant(bounds, subdivisions[1], hemisphere)
        return subdivide_quadrant(bounds, subdivisions[2], hemisphere)

    else:
        raise ValueError(f"Unknown scale: {scale}")


def bounds_to_geojson(bounds: Tuple[float, float, float, float], sheet_id: str = None) -> dict:
    """
    Convert bounds to a GeoJSON Feature with a Polygon geometry.

    Args:
        bounds: (min_lon, min_lat, max_lon, max_lat)
        sheet_id: Optional sheet ID to include in properties

    Returns:
        GeoJSON Feature dict
    """
    min_lon, min_lat, max_lon, max_lat = bounds

    coordinates = [[
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lon, max_lat],
        [min_lon, min_lat]
    ]]

    properties = {}
    if sheet_id:
        properties['sheet_id'] = sheet_id

    return {
        "type": "Feature",
        "properties": properties,
        "geometry": {
            "type": "Polygon",
            "coordinates": coordinates
        }
    }


# For convenience, export main function
def get_bounds(sheet_id: str) -> dict:
    """
    Get bounds and metadata for a sheet ID.

    Returns dict with:
        - bounds: (min_lon, min_lat, max_lon, max_lat)
        - parsed: parsed sheet info
        - geojson: GeoJSON Feature
    """
    parsed = parse_sheet_id(sheet_id)
    bounds = sheet_to_bounds(sheet_id)
    geojson = bounds_to_geojson(bounds, sheet_id)

    return {
        'sheet_id': sheet_id,
        'bounds': bounds,
        'parsed': parsed,
        'geojson': geojson
    }


if __name__ == '__main__':
    import sys
    import json

    # Test cases
    test_sheets = [
        # 1:1M
        "A-48",
        "M-36",
        "B-16",
        # 1:500K
        "A-48-3",
        "G-14-1",
        "G-14-2",
        # 1:200K
        "A-38-16",
        "A-47-06",
        # 1:100K
        "C-48-046",
        "D-38-002",
        # 1:50K
        "H-36-011-3",
        "I-36-107-4",
        # 1:25K
        "C-48-27-3-4",
        "C-48-28-1-1",
    ]

    if len(sys.argv) > 1:
        # Process command line arguments
        for sheet_id in sys.argv[1:]:
            try:
                result = get_bounds(sheet_id)
                print(f"{sheet_id}: {result['bounds']}")
                print(f"  Scale: {result['parsed']['scale']}")
            except Exception as e:
                print(f"{sheet_id}: Error - {e}")
    else:
        # Run test cases
        print("Testing Russian Topo Map Sheet to Bounds Converter\n")
        print("=" * 60)

        for sheet_id in test_sheets:
            try:
                result = get_bounds(sheet_id)
                bounds = result['bounds']
                parsed = result['parsed']
                print(f"\n{sheet_id}:")
                print(f"  Scale: 1:{parsed['scale']}")
                print(f"  Bounds: ({bounds[0]:.4f}, {bounds[1]:.4f}, {bounds[2]:.4f}, {bounds[3]:.4f})")
                print(f"  (min_lon, min_lat, max_lon, max_lat)")
            except Exception as e:
                print(f"\n{sheet_id}: Error - {e}")

        print("\n" + "=" * 60)
        print("\nGeoJSON example for M-36:")
        result = get_bounds("M-36")
        print(json.dumps(result['geojson'], indent=2))
