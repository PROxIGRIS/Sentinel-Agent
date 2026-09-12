# Obylon Sentinel 7.0.5-LTS

7.0.5 is the LTS stabilization release for the 7.0.x line while 7.1.x continues its larger production-evolution work.

## Fixed

- Duplicate workstation registration now converges on persisted node ID or hardware UUID instead of hostname, serializes local registration, and uses a deterministic ID for genuinely new rows.
- Existing node ID is sent during activation so an idempotent enrollment backend can reuse the existing record rather than creating another node.
- Node identity is now machine-bound: verified hardware fingerprint is persisted with the canonical node binding, fresh installs derive a deterministic hardware UUID from that fingerprint, and existing machine IDs are never rewritten.
- Node names are bounded/non-empty and dashboard rename persists to the machine-wide ProgramData node-name file, legacy alias file, live process state, and encrypted vault. Boot preserves the machine label instead of overwriting it with a stale per-user value.
- Realtime and HTTP polling now use a local action lease; commands are acknowledged only after dispatch and successful commands are temporarily de-duplicated.
- Lock/unlock/process commands now report their actual success rather than blindly acknowledging failed operations.

## Validation

Python/Go source tests and compilation are required for the release package. Real Windows endpoint behavior, live Supabase behavior, Rust runtime tests, and Inno Setup compilation remain external release-gate checks.


### LTS tester fixes
- Boot-time hardware identity verification now retries the verified WMI/CIM fingerprint helper in a bounded window. A transient Windows boot-time WMI startup race no longer makes the Brain exit before it can reach security-ready. A confirmed mismatch still fails closed.
- Remote `terminate`/shutdown no longer sleeps for the 10-second evidence grace period. Evidence capture remains best-effort in parallel while shutdown is dispatched through the authenticated Realtime -> Brain -> Core control path.
- Core IPC authorization uses the exact Brain PID instead of rebuilding a full process-tree snapshot for every command, reducing per-command latency and ToolHelp churn.
- Named-pipe busy retries use a 100 ms wait and a monotonic deadline.


### Deep boot-latency correction
- Normal boot no longer waits for hardware fingerprint verification, Supabase session restoration, or the online boot-time license heartbeat.
- Identity verification remains fail-closed: unavailable is pending/retry; a real mismatch remains terminal and prevents Core security-ready.
- Existing node IDs are used immediately for the control plane while server reconciliation runs in the background.
- Realtime C2 can begin as soon as a usable authenticated token is available instead of waiting for unrelated boot housekeeping.
- Security detection remains at a 1-second scan cadence.
