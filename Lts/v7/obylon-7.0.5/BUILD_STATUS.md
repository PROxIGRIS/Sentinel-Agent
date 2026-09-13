# Obylon Repair Pass — Final Build Status

Build: `7.0.5-202609061200`
Status: release candidate after deep boot-latency refactor; real Windows endpoint revalidation is required before ship certification  
Date: `2026-09-06`

## Implemented

- SessionManager remains the single authenticated Supabase client/session owner. Missing-client recovery reconstructs the client from the persisted vault session instead of returning permanently false.
- Realtime authentication reads a fresh token from SessionManager before every connect/authentication cycle and no active `set_auth(ACCESS_TOKEN)` path remains.
- Python vault writes are atomic on both the primary and per-user fallback paths (`mkstemp` + flush + fsync + `os.replace`).
- Vault loading has exactly one `load()` implementation, uses one canonical signature payload including `hardware_uuid`, and quarantines corrupt/tampered vaults instead of deleting them.
- Identity state distinguishes `LEGACY_UNVERIFIED`, verified `READY`, unavailable/unknown, corruption, and mismatch. Only verified identity can cross the Core security-ready gate.
- Boot-time license heartbeat refuses to construct `Authorization: Bearer None`. License heartbeat continues to obtain tokens only from SessionManager.
- Sync daemon can recover a cold authenticated client independently of queue depth and now sleeps on idle/blocked paths instead of hot-spinning.
- Removed all active module-global Supabase-client (`sb`) usage.
- Windows Go fingerprint helper timeout is 12 seconds; non-Windows builds now expose the same status-returning API with an explicit unreliable result.
- Go grace-day validation now clamps negative values to zero.
- Release metadata and CLI version output carry build `7.0.5-202609061200`.

## Validation actually executed

- `python -m py_compile Obylon.py`: PASS
- `python -m pytest -q recovery_engine_test.py repair_pass_validation_test.py`: PASS (8 tests)
- Vault source contract: exactly 1 `load`, exactly 1 `_save`: PASS
- Realtime stale-token search: `set_auth(ACCESS_TOKEN)` has 0 matches: PASS
- Active `sb` usage search: 0 matches: PASS
- Python atomic-vault write simulation: PASS
- Python corrupt-vault quarantine simulation: PASS
- `gofmt -l .`: PASS (clean after formatting)
- `go test ./...`: PASS
- `GOOS=windows GOARCH=amd64 go build ./...`: PASS
- `GOOS=windows GOARCH=amd64 go test -c ./cmd`: PASS (cross-compiled test binary)
- `GOOS=windows GOARCH=amd64 go test -c ./internal/vault`: PASS (cross-compiled test binary)

## Not executed in this Linux container

- `GOOS=windows GOARCH=amd64 go test ./...`: compile completed, but the test binary cannot execute on Linux (`exec format error`).
- `cargo check --workspace`: NOT RUN because `cargo` is not installed in this environment.
- `cargo test --workspace`: NOT RUN because `cargo` is not installed in this environment.
- Real Windows DPAPI/WMI/CIM timing, reboot, Task Scheduler, Broker/Core/Brain session-switch behavior, and live Supabase auth/license/realtime fault injection: NOT RUN.

No test above is marked PASS unless it was actually executed or explicitly compiled as described. A real Windows endpoint remains required for final deployment validation.


## Ad-network reputation integration (7.0.1)
- Bundled `assets/data/obylon_ad_networks.json` from the supplied reputation database.
- Added `ad_network_reputation.py` with schema validation, IDNA/hostname normalization, label-boundary matching, finite-score sanitization, in-memory lookups, and no network I/O.
- Browser monetization telemetry is combined conservatively with the local reputation score; existing extension evidence remains authoritative when stronger.
- Mixed-use networks receive an additional damping factor to reduce false positives.
- Reputation is contextual only and cannot directly trigger an automatic block.
- Added 5 focused reputation tests; all pass.


## 7.0.5 Increment
- Added bounded adaptive scan pressure (NORMAL/ELEVATED/AGGRESSIVE) with hysteresis, telemetry freshness gating, OCR/evidence budgets, and dynamic scan cadence.
- Ad-network reputation remains contextual and never directly enforces.
- Refreshed Inno Setup script with relative build paths, corrected warmup timing, resizable wizard, proportional stage rail, and aligned custom-page layout.


## 7.0.5 Release Hardening

The final source review fixed several release-quality defects: stale 7.0.1 version/user-agent metadata across the README and Go CLI, an invalid Python syntax error in a debug patch helper, OTA acceptance of non-HTTPS download URLs, a bare exception that could hide OTA rollback failure, and an adaptive-scan regression test whose name overstated what it exercised. Documentation was also corrected to remove an unsupported sub-millisecond claim and to state the external Tesseract runtime requirement explicitly.

Validation after the pass: Python bytecode compilation passes for the complete source tree; Python functional tests pass 20/20 when intentionally excluded helper scripts requiring unavailable Windows-only dependencies; Go tests pass across all packages; Windows-targeted Go test compilation succeeds. Rust/C++/Inno Setup execution and a real Windows reboot/session/installer test were not available in this environment, so those remain release-gate checks rather than being falsely marked passed.


## 7.0.5 CLI/Auth Hardening

- Added a single command registry with explicit permission scope + server action metadata.
- Added `obylonc admin <command>` as the explicit privileged namespace while preserving top-level compatibility.
- Added `obylonc auth` admin shortcuts including `auth deactivate`, `auth reset-identity`, and boot controls.
- `doctor --fix` now requires the dedicated `obylon.agent.update` update authorization.
- License activation is integrated into the installer: setup collects the key and invokes the same signed CLI provisioning path before completion.
- Activation now sends `node_name`, `device_name`, and `hostname` consistently and stores/prints the resulting node name.
- Installer configures the SYSTEM boot task directly because it runs elevated before an Umbraxis technician credential exists.
- CLI help now exposes permission scopes, exact usage, admin paths, and operator guidance.


## 7.0.5 LTS Stabilization

This hotfix release fixes three field-facing reliability problems: duplicate workstation registration, non-persistent dashboard renames, and remote admin commands that could be claimed without execution. Registration now converges on persisted node identity/hardware identity, command consumers use an in-process action lease, and successful actions are acknowledged after dispatch.

The source package is validated on Linux for Python compilation/tests and Go tests/builds. Live Windows endpoint, Rust runtime, Supabase production behavior, and Inno Setup compilation remain external gates.


## 7.0.5 Deep Boot/Latency Fix

The normal boot path no longer blocks on live hardware-fingerprint collection, Supabase session restoration, or the online boot-time license heartbeat. Identity verification, session bootstrap, and the online license check are asynchronous; Core's protected IPC gate remains closed until identity is actually verified. The persisted NODE_ID/offline identity path is used immediately while backend reconciliation happens in the background.

This change is specifically intended to restore the fast post-login control-plane startup observed in earlier builds without reducing the 1-second security detection cadence. See `FIXES_7.0.5_BOOT_LATENCY.md`.

## Masterclass follow-up build

Build code: `OBY-MC-NR-20260913-1200-01`
Build date: `2026-09-13`
Version intentionally unchanged.

Implemented:
- multi-signal offline-first network recovery
- immediate session reconstruction on network restoration
- CLI-only Broker/Core/Brain log story translation
- human timestamps for raw epoch / Brain timestamps
- stable `OBY-*` diagnostic codes and Windows exit-code decoding
- regression tests for log translation and exit-code decoding
