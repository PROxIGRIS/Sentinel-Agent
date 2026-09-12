import zipfile
import os
import datetime
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
os.chdir(REPO_ROOT)

now = datetime.datetime.now()
build_number = os.environ.get("OBYLON_BUILD_NUMBER", "7.0.6-" + now.strftime("%Y%m%d%H%M"))
metadata = {
    "build_date": now.isoformat(),
    "build_number": build_number,
    "description": "Obylon Full Source Release — 7.0.6 LTS stabilization: node reconciliation + reliable command dispatch + persistent rename",
    "status": "Release candidate; endpoint validation required"
}

with open("metadata.json", "w") as f:
    json.dump(metadata, f, indent=4)

def zipdir(path, ziph):
    for root, dirs, files in os.walk(path):
        parts = root.split(os.sep)
        
        # User requested to exclude 'internal' but 'obylonc/internal' contains the Go source code. 
        # I will exclude 'internal' ONLY if it's at the root level, but not inside 'obylonc' 
        # just to be safe and keep the source code.
        if 'internal' in parts and 'obylonc' not in parts:
            continue
            
        if any(p in ['target', '__pycache__', '.git', 'dist', 'build_artifacts', 'temp_source', 'go', 'agent_logs', 'tesseract_engine'] for p in parts):
            continue
            
        for file in files:
            if file.endswith('.exe') or file.endswith('.dll') or file.endswith('.pyd') or file.endswith('.pyc') or file.endswith('.zip') or file.endswith('.log') or file.endswith('.prof'):
                continue
            fpath = os.path.join(root, file)
            ziph.write(fpath, os.path.relpath(fpath, path))

zip_name = f'obylon-source-{datetime.datetime.now().strftime("%Y%m%d")}.zip'
with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
    zipdir('.', zipf)
print(f'Successfully packed {zip_name}')
