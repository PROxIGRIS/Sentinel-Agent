# Debug & Profiling Tools

These scripts are strictly for development and debugging. **Do not pack these into the production PyInstaller build.**

## 	race_inject.py
A heavy sys.settrace() profiler that logs every single function call and instruction executed during the Python boot process. 
**Warning:** Injecting this into Obylon.py will artificially increase the boot time from ~3 seconds to over 3.5 minutes due to the extreme I/O overhead.

To use:
1. Copy 	race_inject.py back to the root directory.
2. Add import trace_inject at the top of Obylon.py.
3. Add inject_tracer() at the start of main().
4. Run the PyInstaller build.
5. Boot logs will be dumped to C:\ProgramData\Obylon\logs\ultra_boot_trace.log.

## Other Scripts
- patch*.py: Assorted temporary codebase regex patchers.
- 	est_*.py: Isolated API tests for Supabase, Identity hashing, and WTS functions.
