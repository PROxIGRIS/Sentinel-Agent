import time
import os

t0 = time.time()
try:
    os.makedirs(r'C:\ProgramData\Obylon\logs', exist_ok=True)
    with open(r'C:\ProgramData\Obylon\logs\ultra_boot_trace.log', 'w') as f:
        f.write(f'T+0.00s: pre_boot_tracer started (Python initialized!)\n')
except: pass

import builtins
builtins._global_t0 = t0

def log_step(msg):
    try:
        with open(r'C:\ProgramData\Obylon\logs\ultra_boot_trace.log', 'a') as f:
            f.write(f'T+{time.time() - builtins._global_t0:.2f}s: {msg}\n')
    except: pass
builtins.log_step = log_step
