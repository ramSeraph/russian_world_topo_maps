
import json
from pathlib import Path

def check_missing_maps():
    try:
        with open('vlasenko/data/sheet_map.json', 'r') as f:
            vlasenko_data = json.load(f)
    except FileNotFoundError:
        print("Error: vlasenko/data/sheet_map.json not found.")
        return

    try:
        with open('mapstor/data/sheet_map.json', 'r') as f:
            mapstor_data = json.load(f)
    except FileNotFoundError:
        print("Error: mapstor/data/sheet_map.json not found.")
        return

    #mapstor_bad_sheets = Path('mapstor/bad_sheets.txt').read_text().splitlines()
    #mapstor_bad_sheets = [line.strip() for line in mapstor_bad_sheets if line.strip()]
    #mapstor_bad_sheets = set([line.replace('.gif', '') for line in mapstor_bad_sheets])
    mapstor_bad_sheets = set()

    all_vlasenko_map = {}
    all_vlasenko_keys = []
    for k in vlasenko_data.keys():
        all_vlasenko_keys.extend(k.split('_'))
        for p in k.split('_'):
            all_vlasenko_map[p] = k
    all_mapstor_keys = []
    for k in mapstor_data.keys():
        if k in mapstor_bad_sheets:
            continue
        all_mapstor_keys.extend(k.split('_'))
    vlasenko_keys = set(all_vlasenko_keys)
    mapstor_keys = set(all_mapstor_keys)

    missing_keys = vlasenko_keys - mapstor_keys

    if not missing_keys:
        print("No keys from vlasenko/data/sheet_map.json are missing in mapstor/data/sheet_map.json.")
        return

    print("Keys in vlasenko/data/sheet_map.json but not in mapstor/data/sheet_map.json:")
    for key in sorted(list(missing_keys)):
        sheet = all_vlasenko_map[key]
        map_info = vlasenko_data.get(sheet, {})
        map_exists = map_info.get('map_exists', 'N/A')
        print(f"- {sheet}: map_exists is {map_exists}")

if __name__ == "__main__":
    check_missing_maps()
