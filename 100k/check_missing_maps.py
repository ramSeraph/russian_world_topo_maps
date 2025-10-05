
import json

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

    all_vlasenko_keys = []
    for k in vlasenko_data.keys():
        all_vlasenko_keys.extend(k.split('_'))
    all_mapstor_keys = []
    for k in mapstor_data.keys():
        all_mapstor_keys.extend(k.split('_'))
    vlasenko_keys = set(all_vlasenko_keys)
    mapstor_keys = set(all_mapstor_keys)

    missing_keys = vlasenko_keys - mapstor_keys

    if not missing_keys:
        print("No keys from vlasenko/data/sheet_map.json are missing in mapstor/data/sheet_map.json.")
        return

    print("Keys in vlasenko/data/sheet_map.json but not in mapstor/data/sheet_map.json:")
    for key in sorted(list(missing_keys)):
        map_info = vlasenko_data.get(key, {})
        map_exists = map_info.get('map_exists', 'N/A')
        print(f"- {key}: map_exists is {map_exists}")

if __name__ == "__main__":
    check_missing_maps()
