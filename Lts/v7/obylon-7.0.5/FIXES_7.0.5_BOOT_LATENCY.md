# 7.0.5 LTS Deep Boot/Latency Fix

## Root cause

The previous 7.0.5 repair pass correctly identified hardware-fingerprint startup races, but the implementation still serialized the Brain startup path behind several operations that can block or depend on Windows/network readiness:

1. The live hardware fingerprint was still consumed synchronously by the normal boot path, so the new "asynchronous" probe could still become a startup wait.
2. Supabase SessionManager initialization (`create_client` / `auth.set_session` / session readback) was synchronous before `main()` started the worker graph. A transient Windows socket error could therefore delay the entire agent's useful startup.
3. Boot-time license heartbeat was also synchronous before the worker graph.
4. Realtime C2 could not become active until all of that critical-path work had completed.
5. The registration/reconciliation work was moved off the critical path, but the startup contract is now explicitly based on durable local node identity and background reconciliation rather than waiting for backend identity repair.

The supplied field logs also show that Broker itself usually spawns Core almost immediately after the broker is ready, so a generic "3 second Broker poll" does not explain multi-minute Brain startup. In the attached logs, Brain has both healthy sub-100 ms start-to-security-ready cases and separate crash/restart sequences with exponential backoff. fileciteturn16file1L81-L89 fileciteturn16file0L11-L22

## Fix

### Identity

Normal boot no longer waits for the fingerprint helper. The verified hardware fingerprint now runs in one background verifier thread. Availability failures remain `UNKNOWN`/pending and are retried with bounded per-probe timeouts and backoff. A genuine activation/live fingerprint mismatch remains terminal and exits with code 78, which Core already treats as a non-restartable security decision.

No hostname change is used as an identity key, and the security-ready IPC gate remains closed until identity is actually verified.

### Supabase session

Session creation/restoration now starts in a background bootstrap loop. The existing vault access/refresh token is loaded immediately, so Realtime may proceed as soon as it has a usable token. Transient client/socket failures are retried without blocking Brain's local worker startup.

### Boot license check

The online license heartbeat is now best-effort background work after local protection is armed. Cached local license state remains available immediately. A confirmed remote revoked/suspended/expired response still signals the existing invalidation event.

### Control-plane startup

`CORE_READY` is now a local-worker gate that opens after Core is reachable and the local vault has initialized. It is deliberately separate from Core's `BRAIN_SECURITY_READY` gate. Core continues to reject protected IPC until the identity verifier proves the endpoint.

### No detection downgrade

`SCAN_INTERVAL = 1` remains unchanged. Detection cadence was not relaxed to solve control-plane latency. Remote configuration polling and telemetry behavior remain separate concerns.

## Validation executed

- Python compile/compileall: PASS
- Python tests: PASS (38)
- Go tests: PASS
- Static regression checks cover asynchronous identity/session/license startup ordering
- Rust runtime tests were not executable in this Linux container because Cargo is not installed
- Real Windows behavior must be re-tested on the target endpoint
