# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "bs4",
# ]
# ///


import json
import os
import re
from urllib.parse import urljoin
try:
    from bs4 import BeautifulSoup
except ImportError:
    print("BeautifulSoup not found. Please install it using: pip install beautifulsoup4")
    exit()

def get_map_files():
    """Returns a set of map file names without extension."""
    map_dir = 'data/map50k'
    if not os.path.isdir(map_dir):
        return set()
    return {f.split('.')[0].lower() for f in os.listdir(map_dir) if f.endswith('.map')}

def transform_sheet_id(sheet_id_raw):
    """Transforms the raw sheet ID to the desired format."""
    
    def single_transform(sid):
        sid = sid.upper()
        parts = sid.split('-')
        if len(parts) > 1:
            first_part = parts[0] + parts[1]
            rest_parts = parts[2:]
            if rest_parts:
                return first_part + '-' + '-'.join(rest_parts)
            else:
                return first_part

        return sid

    if '_' in sheet_id_raw:
        parts = sheet_id_raw.split('_')
        base = parts[0]
        sheet_prefix = base.rsplit('-',1)[0]
        
        transformed_parts = [single_transform(base)]
        for p in parts[1:]:
            transformed_parts.append(single_transform(f"{sheet_prefix}-{p}"))
        return '_'.join(transformed_parts)
    else:
        return single_transform(sheet_id_raw)

def check_map_exists(sheet_id_raw, map_files):
    """Checks if the map file(s) exist for a given raw sheet ID."""
    if '_' in sheet_id_raw:
        # Handle cases like 'q-39-013_014'
        parts = sheet_id_raw.split('_')
        base_id = parts[0]
        prefix = base_id.rsplit('-', 1)[0]
        
        all_ids = [base_id] + [f"{prefix}-{num}" for num in parts[1:]]
        return all(f"{id.lower()}" in map_files for id in all_ids)
    else:
        # Handle cases like 'm-48-033'
        return sheet_id_raw.lower() in map_files

def main():
    """
    Parses an HTML file with map links, checks for corresponding map files,
    and writes the data to a JSON file.
    """
    map_files = get_map_files()
    base_url = 'https://maps.vlasenko.net/soviet-military-topographic-map/map50k.html'

    try:
        with open('data/map50k.html', 'r', encoding='cp1251') as f:
            html_content = f.read()
    except FileNotFoundError:
        print("Error: data/map50k.html not found.")
        return

    soup = BeautifulSoup(html_content, 'html.parser')
    links = soup.find_all('a')

    sheet_map = {}

    for link in links:
        sheet_id_raw = link.text.strip()
        relative_url = link.get('href')

        print(sheet_id_raw, relative_url)

        if not sheet_id_raw or not re.match(r'^[a-zA-Z]-\d{2}-\d{3}-\d{1}(_\d+)*$', sheet_id_raw) or not relative_url:
            continue
        print(sheet_id_raw)

        url = urljoin(base_url, relative_url)
        final_id = transform_sheet_id(sheet_id_raw)
        map_exists = check_map_exists(sheet_id_raw, map_files)

        sheet_map[final_id] = {
            'url': url,
            'map_exists': map_exists
        }

    output_path = 'data/sheet_map.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(sheet_map, f, indent=4, sort_keys=True)

    print(f"Successfully created {output_path}")

if __name__ == '__main__':
    main()
