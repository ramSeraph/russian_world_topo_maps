# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "bs4",
# ]
# ///


import os
from bs4 import BeautifulSoup

def get_map_files_from_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    links = soup.find_all('a')
    map_files = set()
    for link in links:
        href = link.get('href')
        if href and '.jpg' in href:
            map_files.add(os.path.splitext(os.path.basename(href))[0])
    return map_files

def get_map_files_from_directory(directory_path):
    files = os.listdir(directory_path)
    map_files = {f for f in files if f.endswith('.map')}
    map_files = {os.path.splitext(f)[0] for f in map_files}
    return map_files

def main():
    html_file_path = 'data/map100k.html'
    maps_directory = 'data/map100k'

    with open(html_file_path, 'r', encoding='cp1251') as f:
        html_content = f.read()

    html_maps = get_map_files_from_html(html_content)
    dir_maps = get_map_files_from_directory(maps_directory)

    missing_in_dir = html_maps - dir_maps
    extra_in_dir = dir_maps - html_maps

    if not missing_in_dir and not extra_in_dir:
        print("No discrepancies found.")
    else:
        if missing_in_dir:
            print("Files in HTML but not in directory:")
            for file in sorted(missing_in_dir):
                print(f"  - {file}")
            print('Number of extra files:', len(missing_in_dir))
        if extra_in_dir:
            print("Files in directory but not in HTML:")
            for file in sorted(extra_in_dir):
                print(f"  - {file}")
            print('Number of extra files:', len(extra_in_dir))

if __name__ == "__main__":
    main()

