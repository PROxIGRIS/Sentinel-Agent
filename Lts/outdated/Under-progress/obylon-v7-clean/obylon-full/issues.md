# Obylon EDR — Boot Reliability and Security Handoff

**Updated:** 2026-08-30  
**Current decision:** **not production-ready**. This document distinguishes
evidence-backed findings from source changes that still need endpoint testing.

## What was investigated

- Raw launch, Core, Broker, and Brain logs in `agent_logs/`.
- The complete startup chain: Task Scheduler -> Broker -> Core -> Brain ->
  vault/signature verification -> clone validation -> IPC.
- Current source in `Obylon.py`, `rust/broker`, `rust/core`, and `obylonc`.
- The prior Codex hotfixes already present in the working tree.

## Confirmed problems

### 1. Cached-vault signatures become inconsistent after a boot heartbeat

The signed payload contains `license_id`, `node_id`, the local
`hardware_uuid`, `expires_at`, `issued_at`, and `status`. The boot-time
heartbeat verified the server response, then persisted new `issued_at`,
`status`, expiry, and grace fields **without persisting that response's
`server_sig`**. On the next process start, `ObylonVault.load()` verified the
new fields against the old signature and correctly rejected them.

Raw Brain logs repeatedly show the direct result:

```text
Signature verify failed: Signature was forged or corrupt
Cached vault signature invalid — possible tampering
Vault incomplete or missing session
```

This is a state-consistency bug, not evidence that the endpoint was cloned.

### 2. The existing logs prove repeated Core creation, not merely a decision

`broker.log` writes `core spawned into interactive session` only after the
Broker's `CreateProcessAsUserW` call succeeds. Its historical entries with
different Core PIDs therefore prove that multiple Core processes were created.

The old Broker had no instance mutex and only checked whether its last Core PID
could be opened with `PROCESS_QUERY_LIMITED_INFORMATION`. That is a liveness
probe, not a readiness check. It cannot detect a Core that is alive but whose
Brain or security startup has failed.

The old Core also had no singleton mutex. Competing Cores fought over the
global `\\.\pipe\ObylonCore` pipe, matching the raw log entries that rejected
clients whose PIDs belonged to another Core/Brain pair.

### 3. Security-failed Brains enter a restart storm

The raw Core log shows the same Core supervising repeated Brain exits with
exponential delays up to 32 seconds. In the signature-failure period the Brain
exited immediately and the Core retried it; this was not a healthy Brain and
was not a new successful boot.

The current supervisor still treats generic non-zero exits (including a vault
signature rejection) as retryable. This remains incomplete: a confirmed
security failure must stop automated respawning and leave an explicit blocked
state until an authenticated repair or operator action occurs.

### 4. The fingerprint helper has a contradictory timeout contract

The Brain gives `obylonc.exe internal-fingerprint` 15 seconds. The Go helper
allowed its PowerShell/CIM child 60 seconds. Consequently the parent could kill
the helper before the helper's own timeout completed, producing the raw-log
messages:

```text
hardware fingerprint helper timed out
hardware fingerprint unavailable during boot; clone validation deferred
```

The prior hotfix then allowed this unavailable evidence to proceed to ready
state. That is not acceptable: a slow helper is **not** clone proof, but an
agent with an activation-time hardware binding must not become ready until the
binding is checked.

### 5. The original boot-time false clone was a separate race

The historical failure described in `howtoassemble.md` was an import/thread
ordering race. The early fingerprint worker could run before
`_name_current_thread` existed, then produced an `unknown` fingerprint that
was incorrectly treated as a clone mismatch. This is distinct from the later
signature-failure storm in the supplied logs.

### 6. The reported four-to-seven-minute delay is not a single measured boot

From the supplied `obylon.log`, 19 successful Brain starts took roughly 3 to
29 seconds. There is no successful startup record lasting 240–420 seconds.

The raw history does show long failure windows, including signature failures
from approximately 18:40 to 19:14 and the next successful record around 19:23.
The bundle has no timestamped activation or vault-repair event, so the exact
source of that later recovery cannot be proven from these logs alone. The
five-minute normal heartbeat cadence and repeated supervisor retries are
plausible contributors, but are **not recorded as the root cause**.

## Changes made in the working tree

The Broker, Core, and CLI source changes have fresh release binaries. The
modified Python Brain has not been rebuilt, and no complete package has been
installed or validated by a real reboot.

| Area | Change | Status |
| --- | --- | --- |
| Vault verifier | Missing PyNaCl/verifier now rejects the state instead of returning success. | Implemented; runtime test pending |
| Vault updates | Activation, boot heartbeat, periodic heartbeat, and repair now use one complete signed-state validation path. | Implemented; end-to-end signature test pending |
| Vault persistence | Writes now flush a same-directory temporary encrypted file and atomically replace the vault. Corrupt files are preserved for investigation rather than deleted. | Implemented; crash-recovery test pending |
| Online repair | A signature-invalid cached vault may use its retained token only to request a fresh, hardware-bound, cryptographically verified heartbeat response. Invalid, offline, and corrupt states remain blocked. | Implemented; endpoint test pending |
| Vault load | Missing or invalid signatures fail closed; unreachable duplicate load/verification code was removed. | Implemented |
| Fingerprint timeout | Go helper deadline reduced from 60 seconds to 12 seconds, below the Brain's 15-second child deadline. | Implemented; real CIM test pending |
| Identity result | Replaced boolean/deferred clone handling with explicit `verified`, `legacy`, `unavailable`, `mismatch`, and `corrupt` results. | Implemented |
| Identity pending | Unavailable fingerprint evidence keeps the Brain out of ready state for six bounded checks, then exits in a terminal security-blocked state. | Implemented; endpoint test pending |
| Security exits | Clone mismatch, missing/invalid vault, invalid server signature, rollback, expired offline grace, and unresolved identity use code 78. Core stops automatic Brain restarts for that code. | Implemented; endpoint test pending |
| Broker singleton | Added `Global\\ObylonBrokerMutex`. | Implemented; reboot test pending |
| Core singleton | Added `Local\\ObylonCoreMutex`. | Implemented; session-switch test pending |
| Readiness | The Brain must acknowledge `brain_security_ready` over the PID-authorized pipe before Core reports `ready`; otherwise Core reports `security_pending`. | Implemented; endpoint test pending |
| Brain supervision | Core owns Brain creation and retains the process handle for supervision. Terminal security exits do not respawn; ordinary process faults retain bounded recovery. | Implemented; endpoint test pending |
| Brain logs | Changed redirection from truncating `CREATE_ALWAYS` to append-only `OPEN_ALWAYS`/`FILE_APPEND_DATA`. | Implemented |
| Scheduler source | CLI task definition uses a boot trigger, SYSTEM principal, no execution timeout, and restart-on-failure policy. Installer invokes `obylonc boot enable`. | Source reviewed; installed task not verified |

## Changes reviewed and rejected or revised

1. **Deferred clone validation that allowed ready state** was revised. It hid a
   transient helper failure but weakened the hardware-binding gate.
2. **Five-minute Core retry for a confirmed clone** was removed. It concealed
   the failure and kept retrying a terminal identity violation.
3. **Fail-open signature verification when PyNaCl was absent** was removed.
4. **Truncating `brain_stdout.log` on every Brain spawn** was replaced so a
   restart storm no longer destroys the evidence needed to diagnose it.

## Remaining work before this can be called fixed

### Vault/signature consistency

- Add deterministic tests for: valid sign/save/reload, one-field tamper,
  missing signature, interrupted temporary write, failed replacement, invalid
  response, and trusted online repair.
- `GRACE_DAYS` is not part of the existing six-field server signature. The
  client now caps it at 14 days so local tampering cannot extend offline use,
  but a future server-contract revision should sign an explicit grace value.
- Do not delete a bad signature or accept legacy unsigned/broken vault data as
  a repair mechanism.

### Fingerprint helper and readiness

- Exercise the bounded identity policy against WMI/CIM slow start to ensure
  normal endpoints do not reach the terminal `security-blocked` state.
- Surface Core's authenticated `security_pending`/`ready`/`security_blocked`
  state to Broker and `obylonc doctor`; the Broker still observes process
  liveness only and deliberately does not use readiness to spawn another Core.
- Exercise helper resolution from both a PyInstaller package and source tree,
  including WMI/CIM slow start, missing helper, cancellation, and child-process
  cleanup.

### Lifecycle ownership

- Establish and document a single lifecycle owner at each level:
  Task Scheduler owns Broker launch; Broker owns one Core per interactive
  session; Core owns one Brain; only Core decides normal Brain recovery.
- Test duplicate manual task invocation, boot task invocation, login/session
  change, logout, and Core crash recovery. Mutexes prevent duplicates only if
  the deployed binary contains these changes.

### Deployment and validation

- Build all artifacts and install them together; source edits alone do not
  affect the currently installed EDR.
- Verify the installed Task Scheduler XML and real trigger history.
- Perform reboot tests on a representative endpoint; manual scheduled-task
  runs are not evidence for real boot readiness.
- Add structured timestamps for Broker spawn, Core ready, Brain security-ready,
  and blocked states, then record boot percentiles.

## Validation performed so far

| Check | Result |
| --- | --- |
| Raw-log startup timeline | Completed; repeated Core PIDs and signature-failure storm confirmed |
| Rust type check for Broker and Core | Passed with pre-existing warnings |
| Rust release build | Passed; fresh `ObylonBroker.exe` and `ObylonCore.exe` are in `rust/target/release/` |
| Go package tests | Passed (`go test ./...`) using an isolated writable cache |
| Go release build | Passed; fresh `obylonc.exe` is in `obylonc/` |
| CLI smoke check | Passed: fresh `obylonc.exe version` reports `7.0.0-LTS` |
| Rust common tests | 9 passed, 1 failed: `freeze_reason_defaults_to_violation_when_omitted`; the new `brain_security_ready` protocol test passed. The remaining failure is an existing IPC-defaulting mismatch outside the boot changes |
| Rust formatting check | Not clean because of unrelated existing formatting differences in `rust/core/src/main.rs` |
| Python syntax/runtime check | Not run: `py -3` reports no registered Python installation and no Python executable was found; the existing `dist/` Brain is therefore stale |
| Packaged helper test | Not run |
| Vault signature round-trip/tamper/repair test | Not run |
| Real Task Scheduler boot test | Not run |
| Real reboot, login, and session-change test | Not run |

## Production assessment

**Do not ship this workspace as production-ready yet.** The evidence identifies
the false-clone and vault-signature causes, and the current changes implement
strict signature persistence/repair, duplicate protection, readiness gating,
evidence retention, and terminal handling for security exits. A real reboot
validation suite, Python runtime tests, packaged-helper tests, and vault fault
injection remain required before release.
