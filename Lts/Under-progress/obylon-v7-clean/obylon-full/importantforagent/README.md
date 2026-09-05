# Obylon Agent: Boot Issue Documentation

## For AI Agents Working on This Codebase

This document explains the critical boot-time performance issues encountered,
their root causes, and the architectural decisions made to solve them.

---

## Issue 1: PyInstaller `--onefile` vs `--onedir` Boot Delay

### Symptom
The agent took **10–30 seconds** to show any signs of life after execution.
No logs, no errors — just a frozen process.

### Root Cause
PyInstaller's `--onefile` mode bundles the **entire Python runtime, all DLLs,
and all data files** into a single `.exe`. At runtime, a C bootloader silently
extracts this archive to `%LocalAppData%\Temp\_MEIxxxxxx` before Python
even starts. For Obylon (with PIL, pytesseract, numpy, websockets, nacl, etc.)
this extraction is massive.

### Fix
**Use `--onedir` mode exclusively.** The `obylon.spec` uses `COLLECT()` to
produce a `dist/obylon/` directory where all files are pre-extracted at
install time. The InnoSetup installer packages this directory — extraction
cost is paid **once during installation**, not on every boot.

### Rule for Agents
- **NEVER** change the spec to use `--onefile`.
- **NEVER** pass `--onefile` to PyInstaller.
- The `obylon.spec` file's `COLLECT(...)` block is the authoritative config.

---

## Issue 2: Windows Defender "Block at First Sight" (BAFS)

### Symptom
After a fresh compile, the **very first execution** of the new binary freezes
for up to **5 minutes**. Subsequent executions are instant. This only happens
once per unique binary hash.

### Root Cause
Windows Defender's cloud-protection feature ("Block at First Sight") intercepts
any newly-seen, unsigned executable. It pauses the process, uploads a sample
to Microsoft's cloud for analysis, and waits for the verdict. This is invisible
to the user — no UI, no error, just a frozen process.

### Fix
**Pre-cache Defender analysis during installation.** The installer runs
`obylon.exe --warmup` after file extraction. This forces Defender to analyze
the binary during the install phase (when the admin expects waiting) rather
than during the first boot (when the user expects instant startup).

### Implementation
1. **Python side (`Obylon.py`):** The `--warmup` flag is handled inside
   `if __name__ == "__main__":`. It initializes all expensive runtime
   components (PIL, pytesseract, pynput, websockets, psutil, win32api, etc.)
   then writes `warmup.lock` next to the executable. On failure, it exits
   with code 1 and does NOT create the lock file.

2. **Installer side (`obylon-setup.iss`):** After file extraction, the
   `WarmupPythonRuntime` procedure launches `obylon.exe --warmup` directly
   (no cmd.exe wrapper), then polls for `warmup.lock` with a 300-second
   timeout. If the lock appears, warmup succeeded. If timeout expires,
   the installer continues but clearly indicates degraded status.

### Critical Path Constraint: `sys.executable` vs `__file__`
In PyInstaller `--onedir` mode:
- `__file__` resolves to `dist/obylon/_internal/Obylon.pyc`
- `sys.executable` resolves to `dist/obylon/obylon.exe`

The warmup lock **MUST** be written relative to `os.path.dirname(sys.executable)`,
not `__file__`. Otherwise the lock file gets hidden inside `_internal/` and
the installer will never find it — causing an infinite wait loop.

---

## Issue 3: Offline UUID Leaking into Supabase Queries

### Symptom
Repeated `22P02` Postgres errors:
```
invalid input syntax for type uuid: "offline-08ad41d0-..."
```

### Root Cause
When the agent boots before the network adapter is ready, `register_workstation()`
returns `f"offline-{HARDWARE_UUID}"` as a fallback identity. This string is NOT
a valid Postgres UUID. When background threads (heartbeat, C2 config, actions)
later try to use this ID in Supabase queries, Postgres rejects it.

### Fix
Added `resolve_offline_wid()` — a self-healing function that runs at the top of
every critical loop. If the agent still holds an `offline-` ID and the network
is now available, it re-registers with Supabase and swaps in a real UUID
seamlessly, without requiring a restart.

---

## How to Build the Agent Correctly

```powershell
# 1. Build the onedir Python distribution
python -m PyInstaller -y obylon.spec

# 2. Compile the InnoSetup installer
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" obylon-setup.iss

# 3. The output is at dist/obylon-setup.exe
```

### Checklist Before Shipping
- [ ] `obylon.spec` uses `COLLECT()` (onedir mode)
- [ ] `good_vocab.txt` is in the `datas` array
- [ ] `icon.ico` is set in the `EXE()` block
- [ ] `obylon-setup.iss` launches warmup via `obylon.exe --warmup` directly
- [ ] No `--onefile` flag anywhere in the build chain
- [ ] Test `obylon.exe --warmup` manually before packaging
