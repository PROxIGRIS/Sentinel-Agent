# Obylon Sentinel 7.0.5-LTS — Windows Production Validation

## Purpose

This package must be validated on a real Windows endpoint before calling the build production-ready.
The goal is not to make the software look healthy. The goal is to **find every failure, inconsistency,
warning, misleading success, lifecycle fault, performance problem, installer problem, or security regression
that can be demonstrated on the endpoint**.

Be hostile to the build. A clean report is only useful if it is earned.

## Rules for the validation agent

1. Run the supplied `validate_windows.ps1` from this package in PowerShell as Administrator.
2. Validate the **exact 7.0.5 build being considered for release**, not an older installation.
3. Do not modify source code or silently "fix" anything. Report it first.
4. Do not delete logs, vaults, captures, identities, scheduled tasks, or program files.
5. Do not run destructive commands (`deactivate`, `reset-identity`, boot disable, credential logout, or anything equivalent) unless the operator explicitly authorizes a separate test.
6. Do not expose tokens, license keys, refresh tokens, device codes, private keys, or other secrets in the report. Redact them.
7. Do not treat "process exists" as proof that the subsystem works. Gather evidence from commands, logs, scheduled-task definition, timestamps, and cross-process behavior.
8. If a test cannot be performed, mark it **NOT TESTED** and explain exactly why. Never convert missing evidence into PASS.
9. Record exact versions, build numbers, file paths, timestamps, exit codes, and relevant error text.
10. Test both the normal installed path and, where safe, the actual built artifacts.

## Automated validation

Run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\tools\validation\validate_windows.ps1
```

The script writes a timestamped report under `%PROGRAMDATA%\Obylon\validation\` and prints a summary.

## Required manual/runtime validation

The validation agent/operator must also verify the following because some behaviors are not safe to trigger automatically:

### A. Fresh install / upgrade

- Install the exact candidate build on a clean Windows VM or a clean endpoint.
- Record installer exit code.
- Confirm installed files are present and the versions match 7.0.5-LTS / build `7.0.5-202609061200`.
- Reboot.
- Verify the boot sequence completes without an abnormal delay.

### B. Runtime chain

Confirm, with evidence, the expected runtime chain is alive:

```text
Task Scheduler → ObylonBroker.exe → ObylonCore.exe → obylon.exe / Brain → Warden
```

Do not rely only on Task Manager. Cross-check recent log timestamps and process start times.

### C. Functional smoke tests

Use an approved test endpoint/session and verify:

- CLI authentication / device authorization
- license status/heartbeat
- classroom focus
- freeze
- unfreeze
- Warden enforcement path
- CLI status/diagnose/doctor
- offline/reconnect behavior where safe
- reboot/login-session transition

Record exact observed result and timing for each.

### D. Negative/failure-path tests

Where safe in the test environment, verify that:

- a stale/expired auth session recovers rather than looping forever;
- temporary network loss does not crash the Brain/Core/Broker chain;
- a malformed or unavailable fingerprint does not become a silently trusted identity;
- a corrupted vault fails safely and is not silently destroyed;
- stale capture files are diagnosed as leftovers rather than treated as current evidence;
- an unavailable performance snapshot does not produce a false healthy result;
- a missing process is reported honestly.

### E. Installer/UI

Inspect the actual installer visually and functionally:

- no overlapping text;
- no clipped controls;
- no broken stage indicators;
- readable on the supported Windows display scale;
- license page scrolls;
- completion page is aligned;
- install/repair/uninstall behavior is sane.

### F. CLI UI

Run at minimum:

```text
obylonc
obylonc --help
obylonc -v
obylonc version
obylonc login status
obylonc status
obylonc diagnose
obylonc doctor
obylonc boot status
obylonc logs -n 30
```

Check for clipped output, broken ANSI rendering, misleading status, incorrect version/build metadata,
awkward alignment, stack traces, and contradictory claims.

## Brutal reporting standard

The final report must contain:

1. **Executive verdict:** SHIP / SHIP WITH CONDITIONS / NO-SHIP.
2. **Release identity:** exact versions and hashes of the tested binaries.
3. **PASS table:** every verified test with evidence.
4. **FAIL table:** every deterministic defect, including low-severity defects.
5. **WARNINGS:** suspicious behavior or reliability concerns that did not fail a hard gate.
6. **NOT TESTED:** every requested item that could not be validated.
7. **Logs:** any error/warning/exception/panic/traceback or suspicious repeated message, with timestamps.
8. **Lifecycle timings:** install → boot → Broker → Core → Brain → ready, plus reboot/session transition timing.
9. **Security findings:** authentication, vault, identity, IPC, scheduled task, permissions, update behavior.
10. **Performance findings:** CPU, memory, scan pressure, log rate, repeated retry behavior, hot loops.
11. **UX findings:** CLI and installer issues, even if the software functionally works.
12. **Release blockers:** anything that should stop shipment.
13. **Recommended fixes:** specific, minimal fixes, not feature creep.

### Severity

- **P0 — Critical:** data loss, credential exposure, enforcement bypass, broken boot/security boundary, unsafe fail-open behavior, or a release-blocking crash.
- **P1 — High:** major functionality unavailable, unreliable startup, auth/recovery failure, serious installer/update failure, repeated crash/loop.
- **P2 — Medium:** correctness bug, misleading state, degraded recovery, significant UX/performance problem.
- **P3 — Low:** cosmetic inconsistency, wording, minor CLI ergonomics, non-blocking diagnostics issue.

### Final instruction

Do not grade on intentions. Grade on observed behavior.

A PASS requires evidence.
A NOT TESTED result is not a PASS.
A clean log is not proof that an untested path works.
A running process is not proof that its dependency chain is healthy.
A successful command is not proof that the underlying security invariant is correct.

Be brutal.
