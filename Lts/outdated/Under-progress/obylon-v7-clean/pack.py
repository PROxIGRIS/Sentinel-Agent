import os
import zipfile

source_dir = r'C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full'
zip_file = r'C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-source.zip'

exclude_exts = {'.dll', '.pyd', '.exe', '.pyc', '.o', '.obj', '.a', '.lib', '.so', '.dylib', '.pyo', '.zip', '.log', '.syso'}
exclude_dirs = {'__pycache__', 'dist', 'build', '.git', '.mypy_cache', 'target', 'node_modules', '.pytest_cache', 'go', 'temp_source', 'agent_logs'}

with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(source_dir):
        # Exclude directories in-place
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in exclude_exts:
                continue
            abs_path = os.path.join(root, file)
            rel_path = os.path.relpath(abs_path, source_dir)
            zf.write(abs_path, rel_path)

print('Zip created successfully.')
