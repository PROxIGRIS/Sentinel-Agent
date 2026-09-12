import zipfile
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
os.chdir(REPO_ROOT)

with zipfile.ZipFile('obylon-source.zip', 'r') as zipf:
    files = [(info.filename, info.file_size) for info in zipf.infolist()]
    
    files.sort(key=lambda x: x[1], reverse=True)
    print("Largest 20 files in zip:")
    for f, s in files[:20]:
        print(f"{s / (1024*1024):.2f} MB - {f}")
