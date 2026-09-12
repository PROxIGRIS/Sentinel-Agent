import zipfile
import os

def zipdir(path, ziph):
    for root, dirs, files in os.walk(path):
        parts = root.split(os.sep)
        if any(p in ['target', '__pycache__', '.git', 'dist', 'build', 'temp_source', 'go', 'agent_logs', 'tesseract_engine'] for p in parts):
            continue
        for file in files:
            if file.endswith('.exe') or file.endswith('.dll') or file.endswith('.pyd') or file.endswith('.pyc') or file.endswith('.zip') or file.endswith('.log'):
                continue
            fpath = os.path.join(root, file)
            ziph.write(fpath, os.path.relpath(fpath, path))

with zipfile.ZipFile('obylon-source.zip', 'w', zipfile.ZIP_DEFLATED) as zipf:
    zipdir('.', zipf)
print('Done!')
