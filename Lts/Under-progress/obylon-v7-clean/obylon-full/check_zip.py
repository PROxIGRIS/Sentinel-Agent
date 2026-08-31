import zipfile
import os

with zipfile.ZipFile('obylon-source.zip', 'r') as zipf:
    files = [(info.filename, info.file_size) for info in zipf.infolist()]
    
    files.sort(key=lambda x: x[1], reverse=True)
    print("Largest 20 files in zip:")
    for f, s in files[:20]:
        print(f"{s / (1024*1024):.2f} MB - {f}")
