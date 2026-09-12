import time
t0 = time.time()
def log_t(msg):
    with open(r'C:\ProgramData\Obylon\logs\time_trace.txt', 'a') as f:
        f.write(f'{time.time() - t0:.2f}s: {msg}\n')
log_t('Top of Obylon.py')
