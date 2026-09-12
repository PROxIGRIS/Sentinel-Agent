import time, platform, os
from pathlib import Path
t0 = time.time()
print('Starting WTS test...')
try:
    import win32ts as _w32ts
    import win32api as _w32api
    import win32profile as _w32prof
    sid = _w32ts.WTSGetActiveConsoleSessionId()
    if sid not in (0xFFFFFFFF, None):
        print('Querying token for SID:', sid)
        tok = _w32ts.WTSQueryUserToken(sid)
        print('Token acquired!', tok)
except Exception as e:
    print('Failed:', e)
print('Done in', time.time() - t0, 'seconds')
