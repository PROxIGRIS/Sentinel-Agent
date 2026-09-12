# Obylon Sentinel v8 — Master Engineering Prompt

**Brand name is "Obylon Sentinel." Full stop.** A previous edit pass drifted to "Nexus
Sentinel" — every docstring, log message, CLI help string, error dialog, class/module
name, file name, and installer string must say Obylon. Grep for "nexus"/"Nexus"/"NEXUS"
across the entire codebase and installer before considering this done. This is not
cosmetic — mismatched branding between the running product and what IT was shown during
sales/deployment is the kind of thing that makes a district security review stall.

## Ground rules for whoever (human or agent) executes this

1. **Preserve working detection logic exactly.** The lexical engine, Angel Engine,
   FSM/threat-scoring arbitration, and OCR-consumption fix from the last release cycle
   are validated and working. Porting them (to Rust or anywhere else) means preserving
   exact semantics — thresholds, scoring formulas, category logic — not "improving" them
   as a side effect of moving files around. If something looks wrong while porting it,
   flag it separately; don't silently change it.
2. **Don't do this as one giant PR.** Land Part A (below) first — it's independently
   valuable, lower-risk, and fixes real bugs without touching the process architecture.
   Part B (the Rust split) is a multi-week rewrite; do it in the phased sequence at the
   end of this document, with the old Python capture path kept as a fallback until the
   new path is validated on real hardware across a reboot + multi-user session flip.
3. **Every claim in this document about *why* something is broken is based on reading
   the actual v7 source and the actual Inno installer script.** Where something below
   requires a server-side (Supabase Edge Function) change too, it's flagged explicitly —
   don't assume a client-only fix is sufficient.

---

## Part A — Fix now, independent of the Rust migration

### A1. Vault ownership and write durability

**Problem:** `ObylonVault` lives at `{commonappdata}\Obylon\obylon.enc`, DPAPI-encrypted
with `CRYPTPROTECT_LOCAL_MACHINE`. The installer grants SYSTEM/Administrators full
control there; standard users inherit whatever `C:\ProgramData` grants, typically
**Read & Execute only, not Modify**. The one-time install-time `activate` call runs as
the installing admin, so the initial write succeeds. But the actual agent — running as
the logged-in student via the session broker — calls `vault._save()` on every heartbeat,
every token rotation, every status change, with no permission-error handling. Those
writes almost certainly fail silently. In-memory state is correct for that process's
life, but nothing persists. Combined with the session broker killing and respawning the
whole process on every session flip (constant on a shared lab PC), every fresh spawn
reloads the **stale, install-time vault** — a server-side revocation may never actually
take effect on a machine that's had a session flip since it was issued.

**Fix (superseded by, but should hold even before, Part B):**
- Short-term patch to the current Python code: wrap `_save()` in a try/except that
  detects `PermissionError` and falls back to a location the current process *can*
  write — but log this loudly, since a silently-degraded fallback location is exactly
  how this kind of bug goes unnoticed for months. Better: have `harden_installation()`
  (or the installer) explicitly grant the specific machine's "Users" or "Authenticated
  Users" group **Modify** (not just Read) on that folder as an interim fix, understanding
  this is a stopgap.
- Real fix, delivered by Part B: the vault becomes exclusively owned by the SYSTEM-tier
  Rust service (`obylon_service`). Python and the session worker never touch the DPAPI
  file directly — they query/mutate license state only through the IPC contract in B4.
  At that point the folder ACL can be tightened to **SYSTEM-only, no Administrators
  either** if the installer's activation flow is also moved to talk to the running
  service instead of writing the file directly.

### A2. License status isn't cryptographically covered

**Problem:** `verify_server_signature()`'s signed payload is `{license_id, node_id,
hardware_uuid, expires_at, issued_at}`. `status` (`active`/`revoked`/`suspended`/
`expired`) — the one field that actually decides whether the agent runs — is not part
of what's signed. Anything that can write to the vault (see A1 — and note the DPAPI
`LOCAL_MACHINE` scope means *any* local process, not just the agent, can decrypt/re-encrypt
that file once it can reach it) can set `LICENSE_STATUS` to whatever it wants without
tripping the "cryptographic tamper" check at all, because that check never looks at
status in the first place.

**Fix (client + server, coordinated — flag this to whoever owns the Edge Function):**
- Server: include `status` in the payload it signs for both `/activate` and
  `/license_heartbeat` responses.
- Client: add `status` to the `sign_payload` dict in `verify_server_signature()` and
  re-verify the signature **every time a cached status is loaded from the vault**, not
  only at the moment a live network response arrives. Right now a cached
  `LICENSE_STATUS` read from disk on the offline-fallback path is trusted with no
  re-verification against `SERVER_SIG` at all.
- Once Part B lands, this verification should live in Rust (`obylon_service`) exclusively
  — the one place with sole vault access is also the right place to hold the one
  function that can mark a license valid.

### A3. Hardware identity model

**Problem:** `HARDWARE_UUID` is a self-minted `uuid.uuid4()` cached in a flat file
(`IDENTITY_FILE`) — not derived from hardware despite the name. As of the v7 session
broker change, that file is anchored to the *logged-in user's* profile directory, not a
fixed machine location, meaning different student accounts on the same shared lab PC
each mint their own separate "hardware" identity and separately consume license seats.
Separately, if this file is present when a master image is captured for cloning
(the exact mistake your own deployment docs warn about), every cloned machine inherits
the identical UUID.

**Fix:**
- Machine identity is a machine-level concept — it belongs in the SYSTEM tier (Rust),
  minted and stored once, independent of which user is logged in.
- Add a real safety command instead of relying on documentation discipline:
  `obylon_service.exe reset-identity --confirm` — wipes the local identity + vault
  (not the server-side license entitlement) so it's safe to run deliberately before
  `sysprep`/image capture.
- Have the service compare the real WMI-derived `HARDWARE_FINGERPRINT` (motherboard
  UUID + disk serial + MAC — already computed, already sent to the backend, apparently
  never actually cross-checked) against what's on file for the current
  `HARDWARE_UUID` at boot. A fingerprint that doesn't match what the backend has on
  record for that node is a strong clone signal — refuse to boot as that identity and
  force re-provisioning instead of running silently as a duplicate.

### A4. License key exposure during install

**Problem:** `Exec('{app}\obylon.exe', 'activate ' + LicenseKey, ...)` puts the license
key on the process command line, which lands in plaintext in any EDR/SIEM that logs
process-creation events with full command lines — extremely common in exactly the school
environments this ships to.

**Fix:** pass the key via a short-lived temp file (written with a restrictive ACL,
deleted immediately after the child process reads it) or via an environment variable
scoped to that one child process, not argv.

### A5. Brand normalization

Covered at the top of this document — repeating here so it's tracked as a discrete,
checkable line item: grep and fix every "Nexus" reference, confirm installer strings
(`AppName`, dialog titles, `UninstallDisplayIcon` metadata, etc.) all say Obylon.

---

## Part B — Rust/Python architectural split

### B0. Why this is three tiers, not two

The original draft proposed the SYSTEM service itself doing "native hardware capture"
(screen via DXGI/GDI, webcam via MSMF) directly. **That reintroduces the exact bug the
session broker was built to fix.** DXGI Desktop Duplication and GDI `BitBlt` both
require running attached to the interactive user's desktop (`winsta0\default`) — a
SYSTEM service in Session 0 has no desktop to capture, full stop, the same way
`PIL.ImageGrab` couldn't see anything from Session 0 before. Moving this code to Rust
doesn't change that constraint; it's a Windows session-model fact, not a language
limitation.

The correct split is:

| Tier | Runs as | Session | Responsibilities |
|---|---|---|---|
| **`obylon_service`** | SYSTEM | 0 | Service lifecycle, session-change detection, spawns/supervises Tier 2, owns the DPAPI vault exclusively, owns machine identity, owns license activation/heartbeat/signature verification, USB + process-lineage sentry (no desktop needed for these), IPC server |
| **`obylon_session_worker`** | logged-in user | interactive (1+) | Screen capture (DXGI, GDI fallback), webcam capture (MSMF), global keyboard/mouse hooks, watermark/overlay rendering, IPC client to Tier 1, IPC server to Tier 3, spawns Tier 3 as its own child (inherits correct session/token/environment for free — no second `CreateProcessAsUser` needed) |
| **Python engine** | logged-in user | interactive (1+) | Master FSM, lexical/Angel Engine, Supabase telemetry sync (alerts/evidence/activity — *not* license/vault), offline SQLite evidence queue, extension WebSocket server. IPC client to both Tier 1 and Tier 2 |

### B1. Tier 1 — `obylon_service` (Rust, SYSTEM, Session 0)

- Registers as a genuine Windows Service (`SERVICE_AUTO_START`) via the `windows-service`
  crate — **not** a scheduled task. A real service gets SCM-managed crash recovery
  (Recovery tab / `sc failure`), proper start/stop semantics, and is a meaningfully
  better look to an EDR/security reviewer than a scheduled task silently launching a
  hidden process. Update the Inno script's `[Run]` step from `schtasks.exe /create` to
  service registration accordingly.
- Session broker: port the **existing, validated** Python broker logic exactly —
  `WTSGetActiveConsoleSessionId` polling or `WTSRegisterSessionNotification`,
  `WTSQueryUserToken` with fallback to borrowing a token from `explorer.exe`/`sihost.exe`
  when the primary path isn't ready yet, `DuplicateTokenEx` to a primary token with
  `TokenSessionId` explicitly pinned, `CreateEnvironmentBlock`, `CreateProcessAsUser`
  onto `winsta0\default`. Preserve the crash-rate-limited respawn and session-flip
  recycling behavior — don't reimplement just the happy path.
- Owns the DPAPI vault exclusively (A1). Consider dropping `CRYPTPROTECT_LOCAL_MACHINE`
  in favor of the default (caller/SYSTEM-scoped) flag now that no other principal needs
  direct decrypt access — this tightens the boundary from "any local process can decrypt"
  to "only SYSTEM can."
- Owns machine identity (A3) and the `reset-identity` safety command.
- Owns license activation, heartbeat polling, and `verify_server_signature` (extended
  per A2) — ports the existing Python logic, doesn't redesign the protocol.
- USB insertion/removal watcher (`RegisterDeviceNotification` — works fine from a
  service, doesn't need desktop access) and process-lineage/provenance tracking
  (`ParentProcessId` walk + `Zone.Identifier` ADS inspection) — port the **existing v7
  Python provenance logic** exactly; it was a genuine, validated fix last release, don't
  redesign it from scratch.
- IPC server for both pipes described in B4.

### B2. Tier 2 — `obylon_session_worker` (Rust, per-session)

- Spawned exclusively by Tier 1 via the session broker. One instance per active console
  session.
- Screen capture: DXGI Desktop Duplication API as primary (lower latency, correct
  multi-monitor/rotation handling), GDI `BitBlt` as fallback for older hardware/drivers
  that don't support duplication. Encode to JPEG in-memory.
- Webcam capture: Windows Media Foundation, encoded via `turbojpeg` (or `mozjpeg`/`image`
  crate) — no OpenCV dependency needed for a single-frame grab-and-encode.
- Global keyboard/mouse hooks (`SetWindowsHookEx`), rolling non-persistent 1000-char
  buffer, flushed only on confirmed violation — matches current policy exactly.
- Watermark/overlay rendering for license-invalid state — this is the first tier where
  it's actually possible for a user to see it, which the current architecture can't
  reliably guarantee.
- Spawns the Python engine (Tier 3) as its own child process — plain `CreateProcess`,
  no token games needed since it's already running with the correct session/token/
  environment context.

### B3. Tier 3 — Python engine (unchanged responsibilities, changed transport)

Strip out: direct Win32 hooking, OpenCV, PIL, direct DPAPI vault access, direct
license/heartbeat HTTP calls. Keep: Master Threat FSM, lexical/native-script engine,
Angel Engine, Supabase telemetry sync (alerts, evidence, activity — not license state),
offline SQLite evidence queue, extension WebSocket server. Replace every place that
currently calls into Win32 capture/hooks or the vault with a call over the IPC client
described below.

### B4. IPC contract — two pipes, not one, with an explicit security boundary

**`\\.\pipe\obylon_session`** (Tier 3 ↔ Tier 2, both running as the same user — lower
stakes, this is within a single trust boundary):
- `HEARTBEAT` — liveness, both directions.
- `TELEMETRY_EVENT` — Tier 2 → Tier 3: foreground window changes, USB/process events
  relayed up from Tier 1, input activity signals.
- `ENFORCEMENT_COMMAND` — Tier 3 → Tier 2: freeze/release input, terminate process,
  show/hide watermark, enter/exit exam-mode lockdown.
- `EVIDENCE_REQUEST` / a **separate binary framing**, not JSON: control messages
  (small, structured) go over NDJSON; evidence frames (screen/webcam JPEGs) should NOT
  be base64-wrapped into JSON — that's a ~33% size penalty and extra CPU for no benefit
  here. Use a 4-byte length-prefixed raw binary frame on this same pipe (announce
  `EVIDENCE_RESPONSE` with a byte count over NDJSON, then write the raw JPEG bytes
  immediately after), or a second dedicated pipe if that's simpler to implement cleanly.

**`\\.\pipe\obylon_control`** (Tier 3 ↔ Tier 1 — this one crosses a real privilege
boundary and needs to be treated that way):
- **This pipe must have an explicit security descriptor, not the default.** A named pipe
  with no DACL set is reachable by any local process — that would just reintroduce A1/A2
  as an IPC-shaped vulnerability instead of a file-shaped one. Restrict connections to
  processes running under the token of the currently-broker-launched session (or at
  minimum authenticated users, with the server independently re-validating the caller's
  session ID matches a session it actually spawned into).
- **The command surface is read-only for license state from Tier 3's side.** Expose
  narrow, specific operations — `LICENSE_STATUS_QUERY`, `REQUEST_HEARTBEAT_NOW`,
  `CONFIG_FLAG_GET` (for the remote toggles like `LOG_ONLY_MODE`, `STRICT_WARDEN`,
  `EXAM_MODE`, etc.) — never a generic `VAULT_SET key value` RPC. `LICENSE_STATUS` must
  only ever be set by Tier 1 itself, based on a signature it verified. If Tier 3 (or
  anything else that can connect to this pipe) can ask Tier 1 to set status directly,
  the whole point of moving vault ownership to Rust is defeated.

### B5. Migration plan

Don't cut over in one release:

1. Ship `obylon_service` (Tier 1) alongside the *existing* Python monolith, running in
   parallel/shadow mode — Tier 1 handles session brokering and vault/license ownership,
   but the current Python code keeps doing its own capture for now, just fetching
   license state over the new control pipe instead of reading the DPAPI file directly.
   This validates A1/A2/A3 in production without touching capture at all.
2. Ship `obylon_session_worker` (Tier 2) with capture/hooks, running side-by-side with
   the Python capture code disabled, on a small test fleet. Compare capture reliability
   and latency against the known-working Python baseline before removing the Python
   fallback.
3. Only once Tier 2 is validated across a real reboot + multi-user session-flip test on
   physical hardware (not just a dev VM you're sitting at) does Python capture code get
   deleted for good.

---

## Deliverables checklist

- [ ] `Cargo.toml` + workspace layout for `obylon_service` and `obylon_session_worker`
      as separate binaries sharing a common IPC/protocol crate.
- [ ] Tier 1: service lifecycle, session broker (ported from Python), vault module
      (DPAPI ownership, `reset-identity` command), license module (activation/heartbeat/
      signature verification, extended to cover `status`), USB + provenance sentry,
      `obylon_control` pipe server with ACL + verb-scoped command surface.
- [ ] Tier 2: DXGI/GDI screen capture, MSMF webcam capture, Win32 hooks, watermark
      overlay, `obylon_session` pipe server, Python child-process spawn.
- [ ] `ipc_client.py`: async/threaded client for both pipes, with the binary evidence
      framing handled separately from the NDJSON control channel.
- [ ] Refactored Python engine: `scan_loop`/`fire_alert` delegate to IPC instead of
      direct Win32/DPAPI calls; license/vault globals replaced with `LICENSE_STATUS_QUERY`
      calls.
- [ ] Updated Inno Setup script: service registration instead of `schtasks`, license key
      passed off-argv (A4), folder ACL tightened once Python no longer needs direct
      vault access (A1).
- [ ] Server-side note (separate ticket, not this codebase): extend the signed
      heartbeat/activation payload to include `status` (A2).

## Acceptance criteria

1. Fresh install → reboot → log in as a **standard, non-admin** user → confirm the
   agent is fully functional (not just running) end to end: capture actually captures,
   input hooks actually fire, watermark is actually visible when triggered.
2. Log off, log a different standard user on the same machine → confirm Tier 2 recycles
   correctly and the license/identity model does **not** fragment into a second seat.
3. Kill/crash Tier 2 deliberately → confirm Tier 1 respawns it with rate-limiting, not a
   tight crash loop.
4. From a standard user's own PowerShell session, attempt to open
   `C:\ProgramData\Obylon\obylon.enc` directly, and attempt to connect to
   `\\.\pipe\obylon_control` from a process not spawned by the broker → both must fail.
5. Simulate a server-issued revocation → confirm it actually takes effect after a
   session flip, not just within the currently-running process (this is the concrete
   regression test for A1/A2).
6. Capture a test master image with the identity present, without running
   `reset-identity` first → confirm the service detects this on first boot post-clone
   (fingerprint mismatch) rather than silently running as a duplicate.
