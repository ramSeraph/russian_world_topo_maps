
import os
import subprocess
import shutil

def tile_tiffs():
    gtiffs_dir = 'export/gtiffs'
    temp_dir = 'temp'
    tiles_dir = 'data/25k/export/tiles'
    
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    tiffs = [f for f in os.listdir(gtiffs_dir) if f.endswith('.tif')]
    total_tiffs = len(tiffs)
    successful_count = 0
    failed_sheets = []

    for i, tiff_file in enumerate(tiffs):
        sheet_no = os.path.splitext(tiff_file)[0]
        sheet_temp_dir = os.path.join(temp_dir, sheet_no)
        
        if not os.path.exists(sheet_temp_dir):
            os.makedirs(sheet_temp_dir)

        try:
            shutil.copy(os.path.join(gtiffs_dir, tiff_file), sheet_temp_dir)
            
            command = [
                'uv', 'run', 'tile',
                '--tiles-dir', tiles_dir,
                '--tiffs-dir', sheet_temp_dir,
                '--name', sheet_no,
                '--description', sheet_no,
                '--attribution', 'Russian Topo Maps',
                '--max-zoom', '15',
                '--min-zoom', '15'
            ]
            
            result = subprocess.run(command, capture_output=True, text=True)
            
            if result.returncode == 0:
                successful_count += 1
                shutil.rmtree(sheet_temp_dir)
            else:
                failed_sheets.append(sheet_no)
                print(f"Failed to tile {sheet_no}: {result.stderr}")

        except Exception as e:
            failed_sheets.append(sheet_no)
            print(f"An error occurred while processing {sheet_no}: {e}")

        progress = (i + 1) / total_tiffs * 100
        print(f"Progress: {progress:.2f}% ({i + 1}/{total_tiffs})")

    print("\nTiling complete.")
    print(f"Successful sheets: {successful_count}")
    print(f"Failed sheets: {len(failed_sheets)}")
    if failed_sheets:
        print("Failed sheet numbers:")
        for sheet in failed_sheets:
            print(sheet)

if __name__ == '__main__':
    tile_tiffs()
