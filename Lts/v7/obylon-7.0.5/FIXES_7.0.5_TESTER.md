# Obylon 7.0.5 LTS Tester Fixes

This revision keeps the release version at **7.0.5-LTS** and fixes two tester-reported failures.

## 1. Brain missing on the first reboot after rename

### Observed
After renaming the Windows PC, the first reboot could leave `ObylonBroker.exe` and `ObylonCore.exe` running while the Python Brain was absent. Later reboots worked.

### Root cause
The Brain's security gate depended on a Windows hardware fingerprint collected through the colocated management helper (WMI/CIM-backed motherboard UUID, disk serial, and physical NIC identity). During a cold/early boot, that helper could temporarily return no usable fingerprint. The previous path could treat that single unavailable observation as a terminal boot failure (`exit 78`), and Core intentionally did not restart a Brain that exited with that terminal code.

The Windows computer name itself is **not** part of the hardware fingerprint, so the rename is not treated as identity material.

### Fix
- Hardware fingerprint collection is started after the Python module has fully loaded, eliminating a thread-start/order race.
- Boot now uses `get_verified_hardware_fingerprint()`.
- It accepts the first valid fingerprint immediately.
- If Windows identity services are temporarily unavailable, it retries in a bounded window (6 attempts, 2 seconds apart) instead of killing the Brain on a transient unavailable observation.
- A confirmed fingerprint mismatch still fails closed. This does **not** weaken clone/mismatch protection.
- Core continues supervising the Brain normally once the process is healthy.

## 2. Shutdown taking 20+ seconds

### Observed
Remote shutdown used Realtime C2 but could take 20+ seconds. Other commands were delayed, but shutdown was much worse.

### Root cause
The Realtime path was already being used. The problem was inside the `terminate` handler: after starting evidence capture, `controlled_shutdown()` deliberately slept for `TERMINATE_GRACE_SEC = 10` seconds before invoking Windows shutdown. That artificial grace period was followed by synchronous shell/process handling, so the command had a built-in multi-second floor before Windows could even begin shutdown.

### Fix
- Removed the artificial shutdown grace sleep from the command-control path.
- Added a dedicated `shutdown` IPC request to ObylonCore.
- Core invokes `shutdown.exe /s /f /t 0` directly and returns immediately after accepting the request.
- Brain first uses the Core IPC path, with an immediate `shutdown.exe` `Popen()` fallback if Core is unavailable.
- Evidence capture remains best-effort and runs independently, so it cannot hold the shutdown command hostage.
- Realtime dispatch now records success/failure from the actual shutdown request rather than acknowledging it before dispatch.

## Additional latency/reliability hardening retained in this build

- Exact Brain PID authorization replaced per-command full process-tree snapshots in Core IPC.
- Named-pipe busy retry was reduced from a 1000 ms wait to 100 ms, with shorter fallback sleeps.
- IPC deadlines use `time.monotonic()`.
- Foreground telemetry is change-driven instead of writing the same window/process to the database every scan tick.
- Remote configuration polling is 10 seconds; the **security detection scan remains 1 second**.
- Admin action claims have a 30-second lease so a crashed dispatch worker cannot permanently block the same action.

## Validation performed in source environment

- Python tests: **37 passed**
- Python compileall: **pass**
- Python AST parse: **pass**
- Rust source was not compiled in this container because Cargo is not installed.

The package must therefore be rebuilt into the final Windows binaries/installer before deployment. The release version remains 7.0.5-LTS.
