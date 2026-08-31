import sys, time, os

os.makedirs(r'C:\ProgramData\Obylon\logs', exist_ok=True)
_t0 = time.perf_counter()
_last_t = _t0

def _log(msg):
    try:
        with open(r'C:\ProgramData\Obylon\logs\ultra_boot_trace.log', 'a') as f:
            f.write(msg + '\n')
    except Exception: pass

_log('T+00000.00ms: trace_inject imported')

def global_tracer(frame, event, arg):
    global _last_t
    now = time.perf_counter()
    if now - _last_t > 0.5:
        # It took more than 0.5s to reach this event from the last one!
        func_name = frame.f_code.co_name
        filename = frame.f_code.co_filename
        lineno = frame.f_lineno
        _log(f'SLOW STEP: {now - _last_t:.2f}s elapsed before {filename}:{lineno} {func_name}() event={event}')
    _last_t = now
    return global_tracer

sys.settrace(global_tracer)

def inject_tracer():
    _log(f'T+{(time.perf_counter() - _t0)*1000:08.2f}ms: Entering main()')
    pass

import builtins
builtins.inject_tracer = inject_tracer
