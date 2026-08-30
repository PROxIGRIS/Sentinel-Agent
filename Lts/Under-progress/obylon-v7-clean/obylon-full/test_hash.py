import hashlib
combined = '4C4C4544-004B-5810-8032-B1C04F305633|0000_0000_0000_0000_8CE3_8E04_0400_E9F5.|3C:21:9C:1D:C7:CA'
print('PYTHON HASH:', hashlib.sha256(combined.encode('utf-8')).hexdigest())
