# Obylon 7.0.7 — Network Resilience

This revision hardens the endpoint against slow, missing, or recovering Wi-Fi and DNS.

## Runtime behavior
- Added a shared offline-first connectivity gate with background probing and adaptive backoff.
- Network state transitions are logged explicitly as `ONLINE` / `OFFLINE` instead of forcing workers to discover connectivity through long socket timeouts.
- Supabase session bootstrap waits on connectivity without blocking Brain startup.
- Remote configuration, license heartbeat, and recovery paths avoid repeated network attempts while offline.
- Connectivity probing is non-blocking to hot loops and does not perform a socket dial on every `network_reachable()` call.
- HTTP status errors are not misclassified as network outages.
- Network-dependent workers automatically resume when connectivity returns.
- HTTP client timeouts are bounded so a flaky adapter/proxy cannot hold a worker indefinitely.

## Native Core
- Fast-lane direct reporting is now asynchronous and single-flight. Enforcement no longer waits for a slow/offline network request.
- The durable local events queue remains authoritative when direct reporting cannot complete.

## Validation
- Python Brain source passes `py_compile`.
- Obylon CLI passes `go test ./...`.
- Windows-native Rust build was not available in this Linux build environment; Rust source was updated conservatively and should be compiled in the normal Windows release pipeline.


## Masterclass network + diagnostics hardening

- Connectivity is now multi-signal and treats local network availability separately from control-plane availability.
- Wi-Fi/driver recovery triggers immediate session reconstruction instead of trusting a potentially stale HTTP client.
- Queue surge retries are coordinated with network generation and session recovery.
- `obylonc logs --deep` reconstructs a timestamped Broker/Core/Brain story at the CLI layer without modifying raw logs.
- Stable CLI diagnostic codes (`OBY-*`) explain common Windows/native and boot-chain failures.
- Raw broker/core log files remain unchanged; interpretation exists only in the CLI.
- Build code: `OBY-MC-NR-20260913-1200-01`; version remains unchanged.
