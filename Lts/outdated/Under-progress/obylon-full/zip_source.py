import os
import zipfile
from pathlib import Path

src_dir = r"C:\Sentinel-Agent\Lts\Under-progress\obylon-full"
out_zip = r"C:\Users\rajiv\.gemini\antigravity-cli\brain\7d1e8d75-cc68-44ec-8d14-d9534cba5880\obylon_source_review_clean.zip"

EXCLUDE_DIRS = {'.git', '__pycache__', 'dist', 'build', 'target', 'venv', 'env', '.pytest_cache', '.idea', '.vscode'}
EXCLUDE_EXTS = {'.exe', '.dll', '.pdb', '.obj', '.pyc', '.pyd', '.lib', '.a', '.so', '.sys', '.log', '.jsonl', '.zip', '.msi', '.tar', '.gz'}

with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(src_dir):
        # Filter directories
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('.')]
        
        for f in files:
            ext = Path(f).suffix.lower()
            if ext in EXCLUDE_EXTS:
                continue
                
            abs_path = os.path.join(root, f)
            rel_path = os.path.relpath(abs_path, src_dir)
            zf.write(abs_path, rel_path)

print(f"Successfully created: {out_zip}")
