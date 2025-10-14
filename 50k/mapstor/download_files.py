# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "remotezip",
# ]
# ///

import json
import remotezip
from pathlib import Path

def replace_fname(content, fname, replacement):
    txt = content.decode('cp1251')
    txt = txt.replace(fname, replacement)
    return txt.encode('cp1251')


def main():
    data = json.loads(Path('data/sheet_map.json').read_text())
    for k, item in data.items():
        url = item.get('url')
        if not url:
            continue
        gif_fname = item.get('filename')
        map_fname = gif_fname.replace('.gif', '.map')

        out_gif_path = Path('data/raw') / f'{k}.gif'
        out_map_path = Path('data/raw') / f'{k}.map'

        if out_gif_path.exists() and out_map_path.exists():
            print(f"Skipping {k} from {url}, all files already exist.")
            continue

        try:
            with remotezip.RemoteZip(url) as zip_file:
                files_to_process = [
                    (gif_fname, out_gif_path, False),
                    (map_fname, out_map_path, True)
                ]
                # extract just fname file from archive
                for fname, output_path, is_map in files_to_process:
                    if output_path.exists():
                        print(f"Skipping {fname} from {url}, already exists at {output_path}")
                        continue

                    fname_full = f"maps/{fname}"
                    if fname_full in zip_file.namelist():
                        with zip_file.open(fname_full) as file:
                            content = file.read()
                            # Save the content to a local file
                            output_path.parent.mkdir(parents=True, exist_ok=True)
                            if is_map:
                                content = replace_fname(content, gif_fname, f'{k}.gif')
                            output_path.write_bytes(content)
                            print(f"Downloaded {fname} from {url} to {output_path}")
                    else:
                        print(f"{fname} not found in {url}")
        except Exception as e:
            print(f"Error processing {k} from {url}: {e}")


if __name__ == "__main__":
    main()