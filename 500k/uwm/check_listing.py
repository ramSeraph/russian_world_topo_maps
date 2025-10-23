import json
import csv
import os

def check_existing_sheets():
    # Construct absolute paths
    base_dir = os.path.dirname(os.path.abspath(__file__))
    info_json_path = os.path.join(base_dir, 'info.json')
    listing_csv_path = os.path.join(base_dir, '..', 'listing_files.csv')

    # Read sheet IDs from uwm/info.json
    with open(info_json_path, 'r') as f:
        uwm_data = json.load(f)
    uwm_sheet_ids = set(uwm_data.keys())

    # Read sheet IDs from listing_files.csv
    existing_sheet_ids = set()
    with open(listing_csv_path, 'r') as f:
        reader = csv.reader(f)
        next(reader)  # Skip header
        for row in reader:
            # Extract sheet ID from filename (e.g., "A21-1.tif" -> "A21-1")
            sheet_id = os.path.splitext(row[0])[0]
            existing_sheet_ids.add(sheet_id)

    # Find and print matches
    print("Sheets from uwm/info.json already in listing_files.csv:")
    for sheet_id in sorted(uwm_sheet_ids.intersection(existing_sheet_ids)):
        print(sheet_id)

if __name__ == "__main__":
    check_existing_sheets()
