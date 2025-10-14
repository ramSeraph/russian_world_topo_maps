import os
import re
import sys
import requests
import shutil
from bs4 import BeautifulSoup
from pathlib import Path

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


def download_jpgs(jpg_list_file, html_file, download_dir):
    """
    Parses an HTML file to find and download GIF files listed in a text file.

    Args:
        jpg_list_file (str): Path to the text file containing the list of GIF filenames.
        html_file (str): Path to the HTML file to parse for download links.
        download_dir (str): Directory to save the downloaded GIFs.
    """
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    with open(jpg_list_file, 'r') as f:
        jpg_files = [line.strip() for line in f.readlines()]

    print(jpg_files)
    
    with open(html_file, 'r', encoding='cp1251') as f:
        html_content = f.read()

    soup = BeautifulSoup(html_content, 'html.parser')
    
    base_url = "https://maps.vlasenko.net"

    for a_tag in soup.find_all('a'):
        if not a_tag['href'].lower().endswith('.jpg'):
            continue
        full_url = base_url + a_tag['href'] 

        sheet_id = a_tag.get_text().strip()
        transformed_id = transform_sheet_id(sheet_id)
        print(f"Transformed ID: {transformed_id}")
        if transformed_id + '.jpg' not in jpg_files:
            continue

        source_map_file = Path(f'data/map100k/{sheet_id}.map')
        if source_map_file.exists():
            shutil.copy(source_map_file, Path(download_dir, f"{transformed_id}.map"))

        target_path = Path(download_dir, f"{transformed_id}.jpg")
        if target_path.exists():
            continue

        print(transformed_id)
        resp = requests.get(full_url)
        if resp.status_code != 200:
            print(f"Failed to retrieve page for {transformed_id}")
            continue
        target_path.write_bytes(resp.content)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python download_jpgs.py <jpg_list_file>")
        sys.exit(1)

    jpg_list_file = sys.argv[1]
    html_file = 'data/map50k.html'
    download_dir = 'data/raw'
    
    download_jpgs(jpg_list_file, html_file, download_dir)
