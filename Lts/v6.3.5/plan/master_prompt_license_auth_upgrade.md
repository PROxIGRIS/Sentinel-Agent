# Master build prompt: license-aware activation for Nexus Sentinel

**How to use this:** paste this whole document as your first message to a
fresh AI coding session (Claude Code or similar), together with the current
`sentinel_agent.py`. It is self-contained — no other context should be
needed. Do the agent-side and backend work in that order; treat the MSI
installer as a separate follow-up (noted at the end, out of scope here).

---

## 1. System context

Nexus Sentinel is the Python backend agent for Obylon, an enterprise
endpoint-monitoring/EDR product deployed on school-owned Windows
workstations. It runs as a compiled exe (PyInstaller), talks to a Supabase
project (Postgres + Auth + Realtime + Edge Functions), and is structured as
a set of self-healing background threads supervised by a watchdog. The file
is ~5,000 lines; almost none of it should change for this task — you are
touching only the credential/provisioning layer.

## 2. What's in the baseline today, and why it has to go

The file currently ships with a **hardcoded `service_role` Supabase key**
as a fallback (top of file, `SUPABASE_URL` / `SUPABASE_KEY` constants).
`service_role` bypasses Row Level Security entirely — anyone who runs
`strings` on the compiled exe gets full read/write on the whole project.
Provisioning is a raw `--provision URL KEY` CLI flag, which means school IT
would need to be handed the literal database URL and key by hand.

Both of these are being replaced with a **license-key activation model**:
school IT runs one command with an opaque license key, the key is checked
server-side against seat limits/expiry/revocation, and the agent receives
back short-lived, per-device, RLS-scoped credentials — never a shared
project key, never typed in by a human.

## 3. Target architecture

```
install agent → obylon activate <LICENSE_KEY>
                     │
                     ▼
        POST /functions/v1/activate
   {license_key, hostname, hardware_uuid, hardware_fingerprint}
                     │
      ┌──────────────┴───────────────┐
      │ server, in one locked txn:    │
      │  - resolve license by key hash│
      │  - check status/expiry        │
      │  - fingerprint-match against  │
      │    existing nodes on license  │
      │    (rebind, don't recount) OR │
      │    count active nodes < limit │
      │  - mint per-device Auth       │
      │    session, upsert node row   │
      └──────────────┬───────────────┘
                     ▼
   200: {supabase_url, anon_key, access_token,
         refresh_token, license_id, node_id, expires_at}
   4xx: {error: invalid_key | license_expired |
         license_revoked | license_suspended |
         node_limit_reached, active_nodes, node_limit}
                     │
                     ▼
        sealed into local DPAPI vault
                     │
                     ▼
   agent boots using the per-device session (RLS-scoped,
   same trust level as any other authenticated Supabase user)
                     │
                     ▼
   daily license_heartbeat thread (one more entry in the
   existing core_systems/Lazarus watchdog dict) re-checks
   status; offline tolerance up to N days on cached
   last-known-good; past that, or on revoked/expired with
   no grace left, agent fails closed and exits.
```

## 4. Data contracts

**`POST /functions/v1/activate`**
```json
// request
{ "license_key": "OBY-LINCOLN-7F2K9QX4H3M8RTNP",
  "hostname": "LIB-PC-14",
  "hardware_uuid": "generated identity-file uuid (see §6)",
  "hardware_fingerprint": "sha256 of motherboard+disk+MAC (see §6)" }

// 200 success
{ "supabase_url": "https://...supabase.co",
  "anon_key": "...",
  "access_token": "...",
  "refresh_token": "...",
  "license_id": "uuid",
  "node_id": "uuid",
  "expires_at": "2027-08-14T00:00:00Z",
  "grace_days": 14 }

// 401/403/409 error
{ "error": "node_limit_reached",
  "active_nodes": 20,
  "node_limit": 20,
  "support_contact": "support@obylon.io" }
```

**`POST /functions/v1/license_heartbeat`** (Bearer: the node's own
`access_token` — RLS naturally scopes this to the calling node's own row,
no extra lookup needed)
```json
// request
{ "hardware_uuid": "..." }

// response
{ "status": "active",           // active | grace | suspended | revoked
  "checked_at": "2026-08-14T12:00:00Z",
  "access_token": "... (rotated, optional)",
  "refresh_token": "... (rotated, optional)" }
```

**Vault contents** (same DPAPI-encrypted JSON blob pattern already in the
file — just more fields):
```json
{ "SUPABASE_URL": "...", "SUPABASE_ANON_KEY": "...",
  "ACCESS_TOKEN": "...", "REFRESH_TOKEN": "...",
  "LICENSE_ID": "...", "NODE_ID": "...",
  "LICENSE_STATUS": "active",
  "LAST_HEARTBEAT_OK_AT": "iso8601" }
```

## 5. Backend deliverables (Supabase)

**SQL** — three tables:
- `licenses(id, school_id, key_hash, plan_tier, node_limit, issued_at, expires_at, status, grace_days, created_by)` — `status` is `active|suspended|revoked`. Store only `sha256(license_key)`, never plaintext.
- `license_nodes(id, license_id, hardware_uuid, hardware_fingerprint, hostname, first_seen_at, last_seen_at, status, auth_user_id)` — `status` is `active|deactivated|reclaimed`.
- `license_events(id, license_id, node_id, event_type, created_at, detail)` — audit log: `activate`, `deny_limit`, `rebind`, `deactivate`, `reclaim`, `revoke`, `renew`.

RLS: `license_nodes` readable/updatable only where `auth.uid() = auth_user_id`. `licenses` and `license_events` are default-deny (only the edge functions, via `service_role`, touch them).

**Edge function `activate`**: validates the key hash, checks
status/expiry, then — inside one locked transaction (`select ... for
update` on the license row, so two simultaneous installs can't both slip
past the limit) — either matches `hardware_fingerprint` against an existing
node on 2-of-3 components (rebind, no seat consumed) or counts active nodes
against `node_limit` (reject if at limit, else insert). On success, create
or reuse a per-device Supabase Auth identity and sign in as it to mint the
returned session, exactly as the earlier enroll design did — this is that
same mechanism, just gated by license rules instead of a bare token.

**Edge function `license_heartbeat`**: reads the caller's own node via
`auth.uid()`, checks the parent license's current status/expiry, updates
`last_seen_at`, and returns the status. Optionally rotates the session.

**Scheduled job (dormancy reclaim)**: daily, mark `license_nodes` as
`reclaimed` where `last_seen_at < now() - interval '45 days'` and
`status = 'active'`, freeing the seat and logging a `reclaim` event.

## 6. Hardware fingerprinting — concrete implementation

Do **not** use `HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid` — it's
regenerated on OS reinstall, defeating the point. Use signals that live on
the physical hardware instead:
- Motherboard/BIOS UUID: `Win32_ComputerSystemProduct.UUID`
- Primary disk serial: `Win32_DiskDrive.SerialNumber` (first physical disk)
- Primary NIC MAC: `Win32_NetworkAdapter` filtered to physical adapters

Get these via PowerShell `Get-CimInstance`, shelled out through
`subprocess` — the file already monkey-patches `subprocess.Popen` with
`CREATE_NO_WINDOW` near the top (`_patched_popen`), so this reuses existing
infrastructure instead of adding a new `wmi` dependency. Concatenate the
three values, SHA-256 them, and that's `hardware_fingerprint`. Treat a
match on 2 of the 3 components as "same physical machine" server-side (a
new NIC or a swapped drive alone shouldn't force a re-registration; a
whole new PC won't match any).

The existing `load_or_create_hardware_uuid()` / `HARDWARE_UUID` (identity
file, wiped on reinstall) stays as-is — it's the primary node key.
`hardware_fingerprint` is the secondary signal that lets the server
recognize "this is probably the same box" even after that file is gone.

## 7. Agent-side task list

Work through these in order. Preserve existing style throughout — structlog
calls with `component=`, the emoji-flavored boot log lines, try/except
defensiveness, DPAPI via `win32crypt`. Don't touch anything outside this
list (detection engine, Warden, evidence capture, telemetry threads).

1. **Delete the hardcoded credential block.** Replace with an
   `ENROLLMENT_ENDPOINT` constant (`{OBYLON_PROJECT_URL}/functions/v1`) and
   an `OBYLON_ANON_KEY` constant — both safe to embed (see the earlier
   design note: anon key + endpoint URL are not secrets, RLS is the real
   gate). No fallback secret of any kind. `SUPABASE_KEY = None` until a
   session is loaded.

2. **Extend `ObylonVault`** (existing DPAPI encrypt/decrypt/load
   machinery stays untouched) with `provision_via_license(license_key,
   hostname, hardware_uuid, hardware_fingerprint) -> bool`: POSTs to
   `/activate`, and on success seals the full contract from §4 into the
   vault. On the specific error shapes from §4, surface a precise message
   (`node_limit_reached` → print the school's active/limit counts and the
   support contact; `license_expired`/`license_revoked` → say so plainly).
   Drop the old raw `provision(url, key)` method entirely — there's no
   legacy path to preserve on this baseline.

3. **Add the hardware fingerprint helper** next to
   `load_or_create_hardware_uuid()` — see §6.

4. **Rewrite `_build_supabase_client()`** to authenticate as the vault's
   stored session (`access_token`/`refresh_token`) rather than a single
   static key, same pattern as any per-user Supabase Auth client. If the
   stored session is expired, refresh it and write the rotated tokens back
   to the vault.

5. **Add a `license_heartbeat` thread as an entry in the existing
   `core_systems` dict**, not a separate ad hoc loop — that way the Lazarus
   watchdog already restarts it if it crashes, for free. Every ~24h: POST
   `/license_heartbeat`, update `LAST_HEARTBEAT_OK_AT`/`LICENSE_STATUS` in
   the vault on success. If the last successful heartbeat is older than a
   7-day offline-tolerance window, or the server explicitly returns
   `revoked`/`suspended` with no grace remaining, fail closed: log
   CRITICAL with the reason and exit — consistent with the boot-time
   fail-closed behavior in step 6, not a silent degrade. (Note this as an
   explicit decision, not an accident — a monitoring product that keeps
   running unlicensed indefinitely because of a network blip is the wrong
   default. If a "keep running in log-only mode instead of exiting" policy
   is preferred later, that's a one-line change to gate on the existing
   `LOG_ONLY_MODE` toggle rather than exiting.)

6. **Rewrite the `__main__` CLI block.** Replace `--provision URL KEY`
   with an `activate` subcommand: `obylon activate <LICENSE_KEY>` calls
   `vault.provision_via_license(...)` (hostname via `platform.node()`,
   `hardware_uuid` from `HARDWARE_UUID`, fingerprint from step 3), prints
   the outcome, exits 0/1 accordingly. Standard boot path: if
   `vault.load()` fails or lacks a complete session, log CRITICAL with
   `Run: obylon activate <LICENSE_KEY>` and exit — no fallback branch.
   Optionally add `obylon status` (prints license/node id and last
   successful heartbeat from the vault) — useful for IT support calls, not
   required. Do **not** add a local `obylon deactivate` — seat deactivation
   must only happen from the admin console (server-side), or a borrowed or
   compromised machine could self-deprovision to duck monitoring.

7. **Fix the Realtime client auth** in `_run_realtime()`: it currently
   passes the static project key as `token=`. Pass the vault's
   `access_token` instead, so the realtime channel is subject to the same
   RLS scoping as everything else — otherwise this one code path stays an
   unscoped hole even after everything above is done.

## 8. Guardrails

- Don't refactor, rename, or "clean up" anything outside the credential/
  provisioning surface. This is a large, working file — the diff should
  be reviewable as "the auth layer changed," not "the file was rewritten."
- Keep the DPAPI vault approach (`win32crypt`, machine-scoped) as-is; it's
  the right local-storage primitive already.
- Every new network call needs the same `verify=certifi.where()` pattern
  already used elsewhere in the file.
- No plaintext license key or session token in logs, ever.

## 9. Acceptance checklist

- [ ] No hardcoded secret of any kind exists anywhere in the file
- [ ] `obylon activate <KEY>` on a fresh machine succeeds and seals a
      session into the DPAPI vault
- [ ] Activating a 21st node against a 20-seat license is rejected, with
      the school's active/limit counts surfaced, and no seat is consumed
- [ ] Two simultaneous activations against the last open seat can't both
      succeed (verify the locking, not just the happy path)
- [ ] Reinstalling the OS on an already-activated machine re-binds via
      fingerprint match without consuming a new seat
- [ ] A genuinely new physical machine does consume a new seat
- [ ] An unprovisioned or vault-incomplete agent fails closed at boot with
      a clear, actionable message
- [ ] A revoked/expired license (past grace) causes the running agent to
      fail closed within one heartbeat cycle, tolerant of brief offline
      periods but not indefinitely
- [ ] The Realtime client authenticates with the node's own access token,
      not the anon key alone

## 10. Out of scope for this prompt

MSI installer packaging (WiX or similar) — a custom dialog for interactive
license-key entry, plus a silent `LICENSEKEY=` property for scripted
deployment via Intune/SCCM/GPO. Both should ultimately call the same
`activate` logic as the CLI. This is a different toolchain (WiX XML, not
Python) and deserves its own prompt once the activate contract above is
stable and tested end-to-end.
