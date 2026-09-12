import zipfile
import os
import datetime
import json

metadata = {
    "build_date": datetime.datetime.now().isoformat(),
    "build_number": "7.0.0-" + datetime.datetime.now().strftime("%Y%m%d%H%M"),
    "description": "Obylon Full Source Release",
    "status": "Stable"
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
            
        if any(p in ['target', '__pycache__', '.git', 'dist', 'build', 'temp_source', 'go', 'agent_logs', 'tesseract_engine'] for p in parts):
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
