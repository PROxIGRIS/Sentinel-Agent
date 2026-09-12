# How to assemble Obylon Sentinel on Windows

This is a from-scratch build/verify/package guide — written so a coding
agent with no memory of prior sessions can execute it correctly. Read the
whole thing before running anything; the scope section at the bottom
matters as much as the build steps.

## What you're building

Four artifacts that all install to the same folder
(`C:\Program Files\Obylon\`):

| Artifact | Language | Role |
|---|---|---|
| `ObylonBroker.exe` | Rust | Session 0, SYSTEM. Summons the interactive session and spawns Core into it. |
| `ObylonCore.exe` | Rust | Runs in the interactive session. Hooks, freeze, overlay, keylog, screenshot, webcam, the fast lane, spawns Brain. |
| `obylon.exe` | Python (PyInstaller) | The "brain" — threat scoring, Supabase sync, OCR, FSM. IPC client to Core. |
| `obylonc.exe` | Go | CLI: activate, status, diagnose, doctor, boot, logs, ai, support-bundle, reset-identity, deactivate, version. |

## Environment you need

- **Windows 10/11**, real hardware or a VM — several fixes in this build
  (DPI awareness, multi-monitor capture, low-level input hooks, Media
  Foundation webcam) cannot be meaningfully validated any other way.
- **Rust via `rustup`**, not a distro package manager — `rustc 1.82+`.
  `windows-core` (a transitive dependency) requires it.
- **Go 1.21+** — pure stdlib in this project, no `go mod download` needed
  beyond what's already in `go.sum`.
- **Python 3.11+** with `pip install supabase psutil pillow pywin32
  structlog httpx certifi pyinstaller`.
- **Tesseract OCR** — the `tesseract_engine/` folder (binary + tessdata)
  must sit alongside the built `obylon.exe`; it's not bundled by
  PyInstaller automatically. Copy it from wherever the existing build
  process keeps it.

## Build order

Build in this order — earlier artifacts don't depend on later ones, but
verifying each independently before moving on catches problems while
they're still cheap to find.

### 1. Go CLI

```
cd obylonc
go build -o obylonc.exe .
go vet ./...
gofmt -l .          # should print nothing
```

Confirm it's a real binary and runs: `.\obylonc.exe version`,
`.\obylonc.exe doctor` (expect every process to show "not running" at
this point — nothing else is built yet, that's correct).

### 2. Rust — `common` first, then `broker`, then `core`

```
cd rust
cargo test -p obylon-common     # pure logic, no Windows deps — should just pass
cargo build -p obylon-broker --release
cargo build -p obylon-core --release
cargo build --release            # full workspace, once both build individually
```

If `core` fails on Media Foundation or WinHTTP specifically, that's the
known-highest-risk part of this codebase (documented in the file's own
comments) — don't let it block validating everything else. Temporarily
stub the `CaptureWebcam` match arm to return an error and come back to it
once hooks/freeze/overlay/screenshot/fast-lane are confirmed working.

### 3. Python agent

```
python -m py_compile Obylon.py    # syntax only — see the note below on why this isn't enough
pyinstaller --onefile --noconsole --name obylon Obylon.py
```

**`py_compile` passing is not sufficient verification for this file.**
The bug this exact build fixes (see below) was a `NameError` that only
manifests at runtime, under specific thread-scheduling conditions —
`py_compile` reported clean the whole time it was broken. After building,
actually run the exe (see Phase 2 below) and watch the log, not just the
compiler.

### 4. Assemble the install directory

```
C:\Program Files\Obylon\
├── ObylonBroker.exe
├── ObylonCore.exe
├── obylon.exe
├── obylonc.exe
└── tesseract_engine\
    ├── tesseract.exe
    └── tessdata\...
```

Then register the boot task: `.\obylonc.exe boot enable` (this targets
`ObylonBroker.exe` — if it targets `obylon.exe host`, something reverted
to a pre-Rust-split state; don't proceed until `obylonc doctor` confirms
the boot task target is correct).

---

## The bug this exact pass fixes — read this before assuming anything else is wrong

**Symptom:** agent builds and runs manually without issue, but fails at
boot — specifically, terminates before ever reaching Supabase/DB
connection code, with a `NameError` in `brain_stdout.log` pointing at
`_compute_hardware_fingerprint_async`.

**Root cause:** a genuine race condition, not a database or networking
problem. `Obylon.py` used to start a background thread
(`_compute_hardware_fingerprint_async`, computing the anti-clone hardware
fingerprint concurrently with the rest of boot) at raw module-import
time — a bare, unindented `threading.Thread(...).start()` call sitting
at column 0. That thread's first action was to call
`_name_current_thread(...)`, a function defined ~185 lines *further down*
the same file. Under light load (running manually, system idle), the
main thread reliably finished parsing those 185 lines before the OS ever
scheduled the new thread — race never lost, bug invisible. Under real
boot load (OS busy, more threads competing for scheduling), the new
thread could get scheduled first, hit `NameError` on a name that didn't
exist yet, and die.

**The domino effect:** because `_name_current_thread(...)` was called
*outside* that function's own `try/except`, the exception bypassed the
`finally:` block too — meaning `_hardware_fingerprint_ready` (a
`threading.Event`) never got set. The next thing that calls
`get_hardware_fingerprint_blocking()` doesn't fail fast; it blocks for
its full 10-second timeout, *then* falls through to a fingerprint value
of `"unknown"`. That gets compared against the real hardware ID stored in
the vault, reads as a mismatch, and the agent's anti-clone-detection logic
correctly (given the corrupted input) concludes the machine might be an
illegal image and calls `sys.exit(1)` — **before the agent ever reaches
its Supabase connection code.** The DB was never the problem; a
background thread for something else entirely crashed the whole process
first.

**The fix, in two parts:**
1. The thread is no longer started at module-import time at all. The
   `.start()` call moved to the very top of `if __name__ == "__main__":`
   — the one point in the file *structurally guaranteed* to run only
   after every function above it has already been defined (since Python
   fully parses a module top-to-bottom before any `if __name__` code
   runs at all). This makes the exact race that occurred impossible, not
   just unlikely — no timing-dependent fix, no added delay, no retry
   logic. It still starts as early as possible for maximum overlap with
   the rest of boot; it just starts at the *first safe point* instead of
   the *first possible point*.
2. Defense in depth: `_name_current_thread(...)` moved *inside* the
   function's own `try/except/finally`, so if this class of bug ever
   recurs for a different reason, the thread fails fast (sets the ready
   event immediately, logs the error, returns `"unknown"` without a
   10-second hang) instead of silently corrupting the boot sequence's
   timing again.

**If you're debugging something that looks similar:** search for any
other bare, module-level (unindented) `threading.Thread(...).start()`
calls anywhere in `Obylon.py` — this exact pattern is the failure mode
to watch for. As of this pass there are none (verified via a direct grep
for `^threading\.Thread\(`), but if a future change reintroduces one,
this is the bug class it risks recreating.

---

## Verification checklist (do all of this before considering the build done)

- [ ] `obylonc version`, `obylonc doctor` (no flags) run without error
- [ ] All three binaries (`ObylonBroker.exe`, `ObylonCore.exe`,
      `obylon.exe`) show as running in `obylonc doctor`'s process check,
      after a real reboot — not just a manual launch
- [ ] `core.log` shows `"hooks installed"` and `"fast lane armed"`
- [ ] `obylon.log` shows the Supabase identity check completing, with a
      real (non-`offline-`) workstation ID
- [ ] Trigger a fast-lane violation (a process name from
      `fastlane_rules.json`) — confirm freeze happens with **no** overlay
- [ ] Trigger classroom focus — confirm overlay appears (large text),
      freeze is in effect
- [ ] Take a screenshot on a scaled display (125%/150%) — confirm it's
      full resolution, not cropped
- [ ] `obylonc doctor --profile 60s` — confirm real, non-zero CPU numbers
      for both Python Brain and Rust Core, not an empty/idle report
- [ ] Reboot the test machine at least once and re-run the process check
      — the bug this pass fixes only manifested under real boot load, so
      a manual launch passing is not sufficient evidence it's fixed

---

## HARD OUT OF SCOPE — do not do these

- **Don't rewrite the DB/Supabase layer in another language.** Every bug
  found across this project's history — including the one this pass
  fixes — has been a process-orchestration or Windows-native-API
  interop bug (GIL contention from COM/WMI, thread-start ordering), never
  a database-client bug. `supabase-py`/`httpx` have not been the source
  of a single defect. Switching languages here would carry real risk
  (reimplementing auth/token-refresh/Realtime-reconnect logic that's
  already correctly working) to fix a class of bug that has nothing to
  do with the database layer.
- **Don't add retry loops or longer timeouts as a substitute for finding
  a real root cause**, the way the bug this pass fixes could easily have
  been "fixed" by just increasing the fingerprint timeout or adding a
  sleep before starting that thread — that would have made the race
  *less likely*, not impossible, and it would resurface eventually.
- **Don't make freeze show an overlay again**, or **make the overlay
  smaller**, or **revert screenshot capture to primary-monitor-only
  metrics** — all three are explicit, already-made product decisions
  from prior passes, not oversights.
- **Don't touch the IPC schema, PID-based pipe authentication, or split
  `core/src/main.rs` into multiple files** — none of that relates to
  this bug.
- **Don't declare anything fixed without a real reboot test.** This
  exact bug passed every manual test and `py_compile` check while
  broken — "it compiles" and "it ran once when I tried it" are not
  evidence here.
