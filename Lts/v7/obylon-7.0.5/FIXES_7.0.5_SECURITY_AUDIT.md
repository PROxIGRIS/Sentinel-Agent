# Obylon 7.0.5 LTS — Security Audit Fixes

This revision keeps the release version at **7.0.5-LTS**. It fixes five
issues found in a second-pass review that specifically looked at things
the prior fix passes (node reconciliation, command dispatch, boot
latency, tester regressions) didn't touch: the Supabase schema, and
cross-file/cross-language interactions between the installer, the Rust
broker/core binaries, the Python Brain, and the Go CLI.

## 1. Database: `anon` role had write access to evidence/command tables

### Observed
Nothing observed in the field — found by reading
`database-map/obylon_master_template.sql` directly. `admin_actions`,
`evidence_logs`, `workstations`, and `system_settings` all had RLS
policies granting the public Supabase `anon` role (the non-secret key
embedded in `obylonc.exe`/`Obylon.py`) `USING (true)` / `WITH CHECK
(true)` read/write, and `unauthorized_events` had an anon-and-authenticated
`DELETE` policy.

### Root cause
Leftover policies from before `SessionManager` (`Obylon.py`) existed.
The real agent has authenticated via `client.auth.set_session(access_token,
refresh_token)` before touching any of these tables for a while now, so
these anon policies had no legitimate purpose left — anyone with the
(non-secret) anon key and network access to the project could read every
workstation's command queue and flip a pending command's status,
fabricate or alter disciplinary evidence, or delete violation history
outright, with no activation, no Windows session, and no role.

### Fix
- `database-map/obylon_master_template.sql` — the anon policies are
  removed/tightened to `authenticated` in place, so new school projects
  provisioned from this template no longer get them.
- `database-map/db_rls_fixes.sql` — a standalone migration for
  **already-provisioned** school projects (editing the template doesn't
  retroactively fix projects that already exist). Phase 1 is safe to run
  immediately; Phase 2 (per-workstation row scoping) is intentionally
  guarded behind a `RAISE EXCEPTION` until `workstations.owner_id`'s
  population source is confirmed against the `/activate` edge function,
  which isn't in this source bundle.
- `device_tokens`, `agent_configs`, `allowed_apps`, `alerts`,
  `agent_health`, `activity_logs` were **not** touched — they weren't
  part of this review and shouldn't be assumed fixed.

## 2. `obylonc`: local privileged-action gate could be pointed at a fake server

### Observed
Nothing observed in the field — found by tracing `authServer()` in
`obylonc/cmd/auth.go`.

### Root cause
`requireCLIActionAuthorization()` (gates `deactivate`, `reset-identity`,
`boot enable/disable`, `evidence read`) and `runAuthAuthorize()` both
resolved the Umbraxis authorization endpoint through `authServer()`,
which — since both call sites passed an empty `--server` flag value —
fell through to the `UMBRAxis_AUTHZ_URL` environment variable, then the
vault's `AUTHZ_BASE_URL` field. The env var can be set with a plain
`setx` (no admin rights needed); the vault field lives in `obylon.enc`,
one of the files the non-admin session user has Modify rights on by
design. Either one let a local user redirect every "ask Umbraxis first"
check to a server they control that just always answers `ALLOW` —
including for `obylon.boot.disable`, which removes the scheduled task
that starts Broker/Core/Brain.

### Fix
`authServer()` now unconditionally returns a hardcoded
`productionAuthzURL` constant. The flag/env-var/vault override surface
is removed entirely rather than allowlisted — there was no legitimate
use of it found in this codebase. If a non-production endpoint is ever
genuinely needed, it should be a separate compile-time constant in a
non-release build, not a runtime value any local user can set.

## 3. Core could panic on first launch; several Brain state files couldn't persist

### Observed
Not reproduced on real hardware in this pass (no Windows box available
in this container) — found by tracing the installer's ACL grants against
what the interactive-user Core/Brain processes actually write. Flagged
as a real risk given `BUILD_STATUS.md`/prior fix docs already note that
real non-admin Windows session behavior has never been validated.

### Root cause
`installer/obylon-setup.iss` locks `{commonappdata}\Obylon` and
`{commonappdata}\Obylon\logs` to `system-full admins-full` — no grant for
standard users at all. Only three files
(`obylon.enc`/`identity_beacon.json`/`fastlane_rules.json`) ever had
their ACL individually widened for the interactive user, via
`ensure_acls()` in the broker. `ObylonCore.exe` — which runs as whichever
user is interactively logged in, i.e. a non-admin student on the target
deployment — opened its own log file as the very first thing in `main()`
with `FileLogger::open(&log_path()).expect(...)`, with no fallback.
Several Brain-side writes had the identical problem:
`node_identity.py`'s `save_binding()`/`save_machine_name()`
(`node_binding.json`/`node_name`), and `Obylon.py`'s
`IDENTITY_FILE.write_text(...)` (`.machine_id`) — the last one directly
contradicted `harden_installation()`'s own comment that `.machine_id`
"stays student-read-only."

### Fix
- `rust/common/src/lib.rs` — `FileLogger::open()` now falls back to a
  per-user `%LOCALAPPDATA%\Obylon\logs\<file>` location if the primary
  `ProgramData` path can't be opened, mirroring the fallback
  `Obylon.py`'s `setup_structlog()` already has for the same scenario.
- `rust/broker/src/main.rs` — `ensure_acls()` now also widens the
  `logs`/`capture`/`events` directories (with `(OI)(CI)` inheritance, so
  files created later inside them don't need to be individually
  enumerated) and adds `node_binding.json`, `node_name`, `.machine_id`,
  `recovery_journal.json` to the per-file grant list. `license_seed.txt`
  stays off the list on purpose — it's only ever read by the agent, never
  written.
- `src/brain/Obylon.py` — `harden_installation()`'s file list and stale
  comment updated to match.
- **Still needed:** real-device validation as a non-admin user. This fix
  is reasoned from the installer/ACL/code interaction, not confirmed
  against actual Windows ACL behavior.

## 4. `OBYLON_BRAIN_PATH` let the interactive user redirect what Core spawns as Brain

### Observed
Nothing observed in the field — found by tracing environment variable
flow from Broker's `CreateEnvironmentBlock(primary_token)` through to
Core's `CreateProcessW` call for Brain (`lpEnvironment: None`, i.e.
inherit Core's own environment).

### Root cause
`brain_exe_path()` in `rust/core/src/main.rs` honored `OBYLON_BRAIN_PATH`
unconditionally with no signature or path validation. Any local,
non-admin user could set it via `setx`, and it would flow straight
through to determine which executable Core spawns and trusts as "Brain"
— `is_authorized_brain_pid()` authorizes it automatically (Core spawned
it), so a two-line stub that just replies to the security-ready IPC
message could take the place of the real detection agent with zero
actual monitoring happening.

### Fix
The env var check is now gated behind `#[cfg(debug_assertions)]`, so
it's compiled out of release builds entirely and only exists in local
debug builds.

## 5. `fastlane_rules.json` had no floor — a cleared file meant a silent fast lane

### Observed
Nothing observed in the field — found by reading the loader in
`rust/core/src/main.rs` against the ACL grant on the same file (see #3).

### Root cause
`fastlane_rules.json` is one of the files granted broad write access so
the legitimate Python agent can persist policy into it. `load_fastlane_rules()`
only fell back to the compiled-in `default_fastlane_rules()` baseline for
a *missing or unparseable* file — a validly-parsed but emptied file
(`{"banned_process_names":[],...}` or just `{}`) produced a fully empty,
always-silent ruleset. There's no signing infrastructure to verify the
file's authenticity yet (`write_fastlane_rules()` in `Obylon.py` is
explicit the rules aren't server-signed today), so real cryptographic
verification isn't achievable purely client-side without server changes
outside this bundle.

### Fix
`load_fastlane_rules()` now merges whatever the file contains with the
compiled-in baseline instead of trusting the file outright — the file
can still add entries, it can no longer remove the ones Core ships with.
Covered by new unit tests (`fastlane_merge_*` in `core/src/main.rs`).

## Validation performed in source environment

- Python: `ast.parse()` full-file parse passes for `Obylon.py` and
  `node_identity.py`.
- Rust: hand-reviewed line by line; brace/paren balance checked
  mechanically; new logic (`merge_rule_list`, `fallback_log_path`) has
  unit tests. **Cargo is not installed in this container, so `cargo
  build`/`cargo test` were not actually run** — same limitation noted in
  the prior two fix docs. This must be compiled and the test suite run
  for real before shipping.
- Go: hand-reviewed; import usage double-checked so `authServer()`'s
  simplification doesn't leave `os`/`strings` unused. `go build`/`go
  vet` were not run — `go` is not installed in this container.
- SQL: policy list before/after diffed by hand against `pg_policies`
  semantics; not run against a live Supabase instance.

**Everything in this pass needs the same real-endpoint and real-build
validation the two fix docs above it already flagged as outstanding.**
