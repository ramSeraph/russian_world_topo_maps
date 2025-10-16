import csv
import os

def check_map_files(csv_path):
    gif_files = set()
    map_files = set()

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader)  # Skip header
        for row in reader:
            if not row:
                continue
            filename = row[1]
            if "mapstor" in filename or "coverage" in filename:
                continue
            if filename.endswith('.gif'):
                base, _ = os.path.splitext(filename)
                # The files are in "maps" and "html" directories, so we should only consider the filename itself
                base = base.split('/')[-1]
                gif_files.add(base)
            elif filename.endswith('.map'):
                base, _ = os.path.splitext(filename)
                base = base.split('/')[-1]
                map_files.add(base)

    missing_maps = gif_files - map_files
    if not missing_maps:
        print("No missing map files found.")
    else:
        print("Missing map files for the following gifs:")
        for missing in sorted(list(missing_maps)):
            print(missing)

if __name__ == "__main__":
    check_map_files('data/zip_files.csv')