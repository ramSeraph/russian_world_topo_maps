
import json
import os
import requests

def download_images():
    # Create the output directory if it doesn't exist
    output_dir = 'data/raw'
    os.makedirs(output_dir, exist_ok=True)

    # Read the info.json file
    with open('info.json', 'r') as f:
        data = json.load(f)

    # Download each file
    for id, info in data.items():
        url = info['url']
        filepath = os.path.join(output_dir, f'{id}.jpg')

        if os.path.exists(filepath):
            print(f'Skipping {id}, file already exists.')
            continue

        try:
            print(f'Downloading {id} from {url}...')
            response = requests.get(url, stream=True)
            response.raise_for_status()  # Raise an exception for bad status codes

            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f'Successfully downloaded {id}.')
        except requests.exceptions.RequestException as e:
            print(f'Failed to download {id}: {e}')

if __name__ == '__main__':
    download_images()
