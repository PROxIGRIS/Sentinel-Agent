import zipfile

zip_file = r'C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-source.zip'

size_map = {}
with zipfile.ZipFile(zip_file, 'r') as zf:
    for info in zf.infolist():
        size_map[info.filename] = info.file_size

# Print top 20 largest files
sorted_files = sorted(size_map.items(), key=lambda x: x[1], reverse=True)
for f, s in sorted_files[:20]:
    print(f"{f}: {s / (1024*1024):.2f} MB")
