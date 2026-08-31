# Obylon Sentinel — Multi-Language Architecture & OTA Reliability Plan

Status: draft for review
Scope: Rust Core / Python Brain / Go CLI split, plus the OTA update system that has to keep all three in sync without ever bricking a machine.

---

## 1. Why OTA is the hard part now

Today's OTA (`phoenix.bat`: kill → move → relaunch) works because there's one exe. The moment this split ships, three independently-versioned binaries exist, one of them (Core) runs as a Windows Service whose binary file is **locked while running** — you cannot overwrite it in place, full stop. This document treats OTA as a first-class subsystem, not a script bolted on at the end, because a bad update to a fleet of classroom machines with no local IT on-site is the single worst failure mode this product can have.

Everything in Section 6 exists to satisfy one requirement: **a failed or bad update degrades to "still running the last known-good version," never to "broken machine, no agent, no way to fix it remotely."**

---

## 2. Process architecture

```
┌─────────────────────────────────────────────────────────────┐
│  WATCHDOG  (Rust, stable — this binary is effectively never  │
│  replaced; it is the SCM-registered Windows Service)         │
│                                                                │
│  Job: read `current` version pointer → spawn CORE as a child │
│  → health-check it → restart on crash → own the OTA swap     │
│  → hold the rollback/canary counters                          │
└───────────────────────────┬───────────────────────────────────┘
                             │ spawns + supervises
┌────────────────────────────▼──────────────────────────────────┐
│  CORE  (Rust, versioned/swappable child process)               │
│  ├── Enforcement        (input hooks, freeze — GIL-immune)     │
│  ├── Device identity     (hardware UUID, workstation identity) │
│  ├── License authority   (Ed25519 verify, token/session state) │
│  ├── Secure local state   (vault, DPAPI, encrypted config)     │
│  ├── OTA execution        (download/verify/stage — Watchdog    │
│  │                          performs the actual swap)          │
│  ├── Native capture        (screenshot/webcam → JPEG encode)   │
│  ├── Windows integration  (session broker, WMI, USB/net mon)   │
│  └── IPC authorization     (pipe ACL, session auth, protocol   │
│                              version handshake)                │
└───────────────────────────┬──────────────────────────────────────┘
                             │ named pipe IPC (control + data plane)
┌────────────────────────────▼──────────────────────────────────┐
│  BRAIN  (Python, summoned into user session by Core)           │
│  ├── Lexical / Context     (explosive lexicon, LEV, NLP)       │
│  ├── OCR                    (reads capture files Core wrote)   │
│  ├── Browser analysis                                          │
│  ├── FSM / Arbitration      (decides *when*, sends commands)   │
│  ├── Statistical models                                        │
│  └── Policy intelligence     (threat_score, mode logic)        │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  CLI (Go, obylonc.exe) — pure IPC client, zero independent    │
│  trust logic. status / diagnostics / auth / policy admin /    │
│  updates / logs / operator commands, all via the same pipe.   │
└──────────────────────────────────────────────────────────────┘
```

**Why Watchdog is its own layer, not folded into Core:** this is the piece that actually solves the "can't overwrite a running service binary" problem. Watchdog's own exe almost never changes — it has no business logic, just spawn/monitor/swap. Core is free to update as often as needed because it's a child process Watchdog is allowed to stop, replace on disk, and respawn. Without this split, every Core update needs a full `sc stop` / `sc start` cycle with the SCM, which is slower, more failure-prone, and means the machine has *zero* enforcement running for the duration of the swap.

---

## 3. IPC design (summary — full schema is a separate doc)

- **Transport:** named pipe (`\\.\pipe\ObylonCore`), ACL restricted to SYSTEM + the active session's user SID.
- **Control plane:** small JSON/msgpack messages (`freeze`, `unfreeze`, `show_overlay`, `hide_overlay`, `spawn_session`, config push). Low latency, no large payloads ever go here.
- **Data plane:** Core writes capture frames (screenshots, webcam) as JPEG to a `ProgramData` temp path and passes Brain a file path + metadata over the control pipe — never pushes raw image bytes through the same channel as freeze commands.
- **Version handshake:** first message on every connect is `{protocol_version, component_version}` both directions. Core supports its current protocol version **and the previous one**, so a Core update that ships slightly ahead of Brain doesn't immediately break the fleet — see Section 6.3.
- **Freeze is Core-authoritative:** Brain sends "freeze for 300s," Core owns the countdown and auto-expiry independently. If Brain crashes or the pipe dies mid-freeze, Core still unfreezes on schedule. Brain is never the single point of failure for un-freezing a student's machine.

---

## 4. Repository layout (sketch)

```
obylon/
├── core/                      # Rust — Watchdog + Core, one workspace
│   ├── Cargo.toml
│   ├── watchdog/
│   │   └── src/main.rs        # SCM service entry, spawn/health/swap only
│   └── engine/                # the actual "Core" — spawned by watchdog
│       └── src/
│           ├── main.rs
│           ├── enforcement/   # hooks.rs, freeze.rs, overlay.rs
│           ├── identity/      # hardware_uuid.rs, workstation.rs
│           ├── license/       # verify.rs, token.rs, heartbeat.rs
│           ├── state/         # vault.rs, dpapi.rs
│           ├── ota/           # download.rs, verify.rs, stage.rs
│           ├── capture/       # screenshot.rs, webcam.rs, encode.rs
│           ├── winint/        # session_broker.rs, wmi.rs, usb_net.rs
│           └── ipc/           # server.rs, auth.rs, schema.rs
│
├── brain/                     # Python
│   ├── pyproject.toml
│   └── obylon_brain/
│       ├── lexical/
│       ├── context/
│       ├── ocr/
│       ├── browser/
│       ├── fsm/
│       ├── arbitration/
│       ├── statistical/
│       ├── policy/
│       └── ipc_client/        # generated from proto/, thin wrapper only
│
├── cli/                       # Go
│   ├── go.mod
│   ├── cmd/obylonc/main.go
│   └── internal/
│       ├── ipc/                # generated from proto/, thin wrapper only
│       ├── status/
│       ├── diagnostics/
│       ├── auth/
│       ├── policyadmin/
│       ├── update/
│       ├── logs/
│       └── operator/
│
├── proto/                     # SINGLE SOURCE OF TRUTH for the IPC schema
│   ├── ipc.proto               # or a JSON Schema if you'd rather skip codegen
│   └── CHANGELOG.md            # every schema change bumps protocol_version
│
└── manifest/                   # OTA build tooling — not shipped to devices
    ├── build_manifest.py       # SHA256 every artifact, sign with Ed25519
    └── sign_key/                # private key lives in CI secrets, not here
```

The `proto/` directory matters more than it looks — three languages independently hand-rolling the same message schema is exactly how you got the hardcoded service-role key and the WebSocket/HTTP double-dispatch race before. One schema, codegen or hand-synced with a checked test, no exceptions.

---

## 5. On-disk deployment layout (sketch)

This is the layout the OTA system in Section 6 is built around. Versioned, never-overwrite-in-place, atomic pointer swap.

```
C:\Program Files\Obylon\
├── watchdog\
│   └── ObylonWatchdog.exe      # SCM-registered path — this almost never changes
│
├── versions\
│   ├── 7.2.0\
│   │   ├── core\ObylonCore.exe
│   │   ├── brain\               # embedded Python or onefile bundle
│   │   └── manifest.json        # signed: version, file hashes, protocol_version
│   ├── 7.3.0\
│   │   └── ... (same shape)
│   └── current -> 7.3.0         # NTFS junction, repointed atomically on activation
│
├── staging\
│   └── 7.4.0\                   # downloading / verifying — NOT live yet
│
└── bin\
    └── obylonc.exe              # Go CLI, resolves `current` at launch same as Core

C:\ProgramData\Obylon\
├── state\
│   ├── update_state.json        # current, previous, canary counters, last swap ts
│   └── protocol_compat.json     # which protocol versions Core currently accepts
├── logs\
│   ├── watchdog.log
│   ├── core.log
│   ├── brain.log
│   └── update.log
├── capture\                     # transient JPEG frames for the data-plane handoff
└── obylon.enc                   # vault, unchanged from today
```

`versions\current` being a junction (not a copy) is what makes activation atomic — repointing a junction is a single filesystem operation, not a multi-gigabyte copy. Nothing reads from `staging\` until Watchdog decides to activate it, and nothing reads from an old version once `current` moves.

---

## 6. OTA update architecture

### 6.1 Design principles

1. Never touch a version that's currently running.
2. Never activate a version that hasn't been verified twice (once at staging, once immediately before activation — defends against disk corruption or tampering in the gap between the two).
3. Activation is one atomic operation, not a multi-file copy.
4. Every activation is provisionally on probation (canary window) until proven stable, with automatic rollback if it isn't.
5. A machine that can't reach the update server keeps running its current version indefinitely — the update check is never on the critical path for booting or enforcing.

### 6.2 Update flow

1. Watchdog (or Core, low-privilege check) polls the license/control-plane Supabase project for a new manifest — same infra you already use for licensing, no new service to stand up.
2. Manifest is Ed25519-signed (reuse the existing signing keys already used for admin command auth) and lists: version, protocol_version, per-file SHA256, minimum-compatible-previous-version.
3. Pre-flight: check free disk space for the full staged download before starting. Abort quietly and retry later if insufficient — do not partially download.
4. Download all files into `staging\<version>\`. This directory is invisible to everything else in the system until step 6.
5. Verify: manifest signature, then every file's SHA256 against the manifest. Any mismatch → delete staging dir, log, retry next cycle. `current` is untouched.
6. Smoke test: launch the staged Core binary with `--self-test` (spawns, initializes IPC server, exits clean) *without* it becoming the active version. Fail → same as step 5, abort and retry later.
7. Activation: Watchdog gracefully signals current Brain to shut down (bounded timeout, then force-kill), stops the current Core child, re-verifies staged files' hashes one more time, repoints the `current` junction, starts new Core, which spawns new Brain.
8. Canary window opens: Watchdog tracks crash/restart count for the new version over the next N minutes / K restart attempts, persisted in `update_state.json` so it survives a reboot mid-canary.
9. Canary passes → previous version marked eligible for garbage collection after a grace period (24–48h, keep it as an instant rollback target a little longer than strictly necessary). Canary fails → automatic rollback (6.4).

### 6.3 Version compatibility & update sequencing

- Core and Brain exchange `protocol_version` on every IPC connect. Core is built to accept its current protocol version **and the immediately preceding one**, so a fleet mid-rollout (some machines updated, some not) never has a Core talking to an incompatible Brain.
- Update order: **Core/Watchdog first, Brain second, CLI any time.** Core is the trust anchor and the one thing enforcement depends on; it should always be equal-or-ahead of Brain in protocol support, never behind.
- If Brain connects with a protocol_version Core genuinely can't support (skipped an update cycle entirely), Core refuses the connection, logs a clear "awaiting compatible Brain update" state visible via CLI diagnostics — it does **not** attempt to run in some undefined partially-compatible mode.
- CLI has no live dependency on Core's version beyond the IPC schema itself, so it can lag safely; it just needs to speak a protocol_version Core still accepts.

### 6.4 Rollback & canary health gate

- `update_state.json` tracks: `current_version`, `previous_version`, `activation_timestamp`, `restart_count_since_activation`, `canary_window_end`.
- If Core crashes or fails its own startup health check more than a small threshold (e.g. 3 times) within the canary window, Watchdog automatically repoints `current` back to `previous_version` and restarts — no human intervention, no waiting for IT to notice a classroom machine went dark.
- This state file must survive a reboot mid-canary (student shuts down the PC right after an update lands) — check it on every Watchdog startup, not just immediately post-swap.
- Keep the last **two** known-good versions on disk, not just one — protects against the edge case where the rollback target itself turns out to have a problem discovered later.

### 6.5 Integrity & signing chain

- Reuse the Ed25519 keypair already signing admin commands — one identity, one key-rotation story, not two.
- Manifest is signed; every artifact's hash is in the manifest; verify hash **and** re-verify immediately before activation (step 5 and the re-check in step 7) — closes the window where staging could be tampered with or corrupted between download and go-live.
- Core and Brain binaries should also carry Authenticode signatures for defense-in-depth against anything that bypasses the manifest check entirely (e.g. a compromised staging directory written by something other than the updater).

### 6.6 Staged rollout

- Roll out by percentage of fleet / by school, using the same per-school Supabase project structure you already have for the control-plane split — a bad build should be visible on a handful of machines via heartbeat/crash telemetry before it ever reaches the whole fleet, not discovered after every classroom in every school updates simultaneously.

### 6.7 Failure-mode table

| Failure scenario | Mitigation |
|---|---|
| Download interrupted or corrupted | Staged separately from `current`; SHA256-verified before activation is even considered |
| New Core crashes on startup | `--self-test` smoke test pre-activation; canary auto-rollback post-activation |
| Core and Brain protocol mismatch mid-rollout | Core accepts current + previous protocol version; explicit refusal state instead of silent partial operation |
| Bad build shipped to entire fleet at once | Staged rollout by school percentage via existing control plane |
| Manifest tampered / MITM | Ed25519-signed manifest + per-file SHA256, reusing existing signing identity |
| Machine offline during update window | Update check is non-blocking and retried with backoff; agent always runs on whatever `current` already points to |
| Windows Service binary locked while running | Watchdog (SCM-registered, stable) supervises a swappable Core child — never needs to replace its own running exe |
| Power loss / crash mid-swap | Activation is a single junction repoint, not a file copy; canary state file is checked on every Watchdog startup |
| Disk fills up during download | Pre-flight free-space check before download starts, abort cleanly if insufficient |
| Rollback target itself turns out bad | Keep last two known-good versions, not just one |

---

## 7. Phased implementation (OTA-specific milestones)

1. **Broker + enforcement + Watchdog** — ship with *no* OTA capability yet; manual redeploys only, same as today. Get the process split itself stable in production first.
2. **IPC authorization + version handshake** — build the protocol_version negotiation before anything depends on it.
3. **License authority + secure local state** — self-contained, no OTA dependency yet.
4. **OTA execution (this document, in full)** — versioned directories, staging, signing, canary/rollback. This is the milestone where updates go from "manual redeploy" to "safe to automate," so it should not ship until 1–3 have run stable in the field for a while.
5. **Native capture + data-plane channel.**
6. **Go CLI** — can build in parallel with 2 onward, since it only needs a working IPC server.

---

## 8. Open decisions before implementation starts

- Embedded Python interpreter vs. PyInstaller-bundled Brain — affects staging directory size and download bandwidth for schools on weaker connections.
- Canary window length and failure threshold — needs a number, not just "a few minutes."
- Garbage collection policy for old versions — fixed grace period vs. disk-space-pressure-triggered.
- Whether the update manifest check itself needs its own signed heartbeat separate from the license heartbeat, or can ride on the same channel.
