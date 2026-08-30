import hashlib
print('NO MAC:', hashlib.sha256('4C4C4544-004B-5810-8032-B1C04F305633|0000_0000_0000_0000_8CE3_8E04_0400_E9F5.|unknown'.encode('utf-8')).hexdigest())
print('NO DISK:', hashlib.sha256('4C4C4544-004B-5810-8032-B1C04F305633|unknown|3C:21:9C:1D:C7:CA'.encode('utf-8')).hexdigest())
print('ALL UNKNOWN:', hashlib.sha256('unknown|unknown|unknown'.encode('utf-8')).hexdigest())
