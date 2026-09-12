import zipfile
import shutil
import os

zip_path = r'C:\Users\rajiv\Downloads\obylon-full (1).zip'
target_dir = r'C:\Sentinel-Agent\Lts\Under-progress\obylon-full'

print('Extracting...')
with zipfile.ZipFile(zip_path, 'r') as zf:
    zf.extractall('temp_extract')

src_dir = os.path.join('temp_extract', 'obylon-full')

print('Copying files...')
for item in os.listdir(src_dir):
    s = os.path.join(src_dir, item)
    d = os.path.join(target_dir, item)
    if os.path.isdir(s):
        shutil.copytree(s, d, dirs_exist_ok=True)
    else:
        shutil.copy2(s, d)

print('Cleaning up...')
shutil.rmtree('temp_extract')
print('Done!')
