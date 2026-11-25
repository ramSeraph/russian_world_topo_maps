"""Check scan orientation using text along the upper and lower margins."""
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import cv2
import numpy as np


def check(path):
    dest = path.parents[1] / 'orientation' / (path.stem + '.json')
    if dest.exists():
        return
    gray = cv2.imread(str(path), cv2.IMREAD_REDUCED_GRAYSCALE_2)
    h, w = gray.shape
    band = max(90, h // 9)
    border = np.vstack((gray[:band], gray[-band:]))
    result = subprocess.run(['tesseract', 'stdin', 'stdout', '--psm', '0', '--dpi', '150'],
                            input=cv2.imencode('.png', border)[1].tobytes(), capture_output=True)
    output = result.stdout.decode()
    rotate = re.search(r'Rotate: (\d+)', output)
    score = re.search(r'Orientation confidence: ([\d.]+)', output)
    dest.write_text(json.dumps(dict(rotation=int(rotate[1]) if rotate else None,
                                    confidence=float(score[1]) if score else None)))


if __name__ == '__main__':
    root = Path(sys.argv[1]).resolve()
    (root/'orientation').mkdir(exist_ok=True)
    os.environ['OMP_THREAD_LIMIT'] = '1'
    cv2.setNumThreads(1)
    with ProcessPoolExecutor(5) as pool:
        list(pool.map(check, sorted((root/'originals').glob('*.jpg'))))
