import csv
import json
from pathlib import Path
import re

def should_skip(fname):
    if fname.endswith('/'):
        return True
    if fname.endswith('--coverage.gif'):
        return True
    if fname.endswith('.kml'):
        return True
    if fname.endswith('.html'):
        return True
    if fname.endswith('mapstor.gif'):
        return True
    return False

def extract_year(text):
    """Extracts year or year range like (1980) or (1980-1985) from a string."""
    # For cases like (1980) or (1980-1985)
    match = re.search(r'\((\d{4}(?:-\d{4})?)\)', text)
    if match:
        return match.group(1)
    
    # For cases like _1980-1980_ or _1980_
    match = re.search(r'_(\d{4}(?:-\d{4})?)_', text)
    if match:
        return match.group(1)
    return None

# Read all file entries from the CSV
all_files = {}
with open('data/zip_files.csv', 'r') as csvfile:
    reader = csv.DictReader(csvfile)
    for row in reader:
        fname = row['filename']
        url = row['url']
        if should_skip(fname):
            continue
        all_files[fname] = { 'url': url }

by_id = {}
# Process only gif files to find the best map sheet for each ID
for fname, data in all_files.items():
    if not fname.endswith('.gif'):
        continue

    gif_filename = Path(fname).name
    
    # As per user request, split filename to find parts
    # We also consider the zip file name from the URL
    zip_filename_stem = Path(data['url']).stem
    parts = gif_filename.removesuffix('.gif').split('--') + zip_filename_stem.split('--')

    ids = []
    year = None

    # Extract IDs and Year from the parts
    for part in parts:
        if not year:
            year = extract_year(part)

        # Regex to find map IDs like 'l37-129' or 'p35-143_144'
        # This pattern must match the entire part
        if re.fullmatch(r'[a-zA-Z]\d{2}-[\d_]+', part):
            match = re.match(r'([a-zA-Z]\d{2}-)', part)
            if match:
                prefix = match.group(1).upper()
                numbers_part = part[len(prefix):]
                
                for num_str in numbers_part.split('_'):
                    if num_str.isdigit():
                        map_id = f"{prefix}{num_str}"
                        if map_id not in ids:
                            ids.append(map_id)

    if not ids:
        print(f"Skipping {gif_filename} as it has no discernible ID.")
        continue

    if not year:
        print(f"Skipping {gif_filename} as it has no year information.")
        continue

    year_parts = year.split('-')
    if len(year_parts) == 2 and year_parts[0] == year_parts[-1]:
        year = year_parts[0]

    year_for_comparison = int(year.split('-')[0])

    map_id = '_'.join(sorted(ids))
    if map_id in by_id:
        prev_year_str = by_id[map_id]['year']
        prev_year_for_comparison = int(prev_year_str.split('-')[0])
        if prev_year_for_comparison >= year_for_comparison:
            # Existing map is newer or same year, so we keep it
            continue
    
    # This is the best map for this ID so far
    by_id[map_id] = {
        'url': data['url'],
        'year': year,
        'filename': gif_filename,
        'id': map_id
    }

print(f"Found {len(by_id)} unique IDs")

# Write the result to a JSON file
Path('data/sheet_map.json').write_text(json.dumps(by_id, indent=2, sort_keys=True))
