# Obylon Recovery Intelligence: Master Implementation Plan

## Objective

Turn Obylon's existing recovery behavior into a deterministic, bounded, evidence-driven Recovery Intelligence layer that can detect a known failure class, choose a pre-approved repair, execute it through typed callbacks, verify that the repair actually restored the dependency, and stop safely when the problem is security-terminal or outside the engine's authority.

The target is **95+/100 engineering quality after implementation + endpoint validation**, not merely a large feature count. A compile or a pretty log is not evidence of 95/100. The final score requires the failure-injection and Windows reboot tests in this document.

## What the current codebase already has

Obylon is split into Rust Broker, Rust Core, Python Brain, and Go CLI. Core owns Brain supervision and the security-ready boundary. The Brain already has explicit Network/Auth/Client/License/Sync/Security state enums and a `SystemStateTracker`; `SessionManager` is intended to be the single owner of authenticated Supabase state. The queue is durable SQLite, Realtime is a separate async listener, license heartbeat is a long-running loop, and the main thread currently contains a watchdog that resurrects dead Brain threads.

The current code also contains the exact lifecycle weaknesses that make a recovery orchestrator valuable:

- A missing Supabase client previously defeated `force_refresh()` because the method returned immediately when `_client` was `None`.
- Realtime had a stale global-token dependency even though `SessionManager` rotates credentials.
- Identity availability, identity corruption, and hardware mismatch were previously too easy to collapse into one boolean boot decision.
- Boot could signal Core security-ready without proving identity readiness.
- The Brain watchdog could recreate a failed thread without a bounded repair budget.
- Sync recovery could run before a usable client existed.
- The signature verifier previously had a fail-open dependency path when PyNaCl was unavailable.
- The existing repair notes explicitly prohibit infinite retries, blind client recreation, arbitrary sleeps, broad exception swallowing, deletion of invalid security state, or lowering security gates.

These are design inputs, not invitations to rewrite the product.

## Recovery philosophy

Recovery must be an **expert system**, not a free-form self-modifying AI.

The engine is allowed to reason over facts such as:

- network online/offline
- client present/absent
- authenticated/unauthenticated
- license valid/unavailable/terminal
- identity verified/unavailable/mismatched/corrupt
- vault intact/corrupt
- Realtime connected/disconnected
- queue blocked/degraded
- previous activation evidence
- same-machine evidence
- explicit recovery authorization

The engine is not allowed to:

- execute shell commands from telemetry
- import or execute arbitrary Python named by a failure message
- change enforcement policy
- fabricate a license
- convert hardware mismatch into "repairable"
- delete corrupt security evidence
- accept unsigned license/security state
- silently clear a terminal security state
- mutate arbitrary files

## Core state model

Keep the existing component states and add Recovery as a coordinating state, not as a replacement for them.

```text
Network
  OFFLINE / ONLINE

Auth
  UNINITIALIZED / REFRESHING / AUTHENTICATED / AUTH_REQUIRED /
  AUTH_FAILED / AUTH_TERMINAL

Client
  ABSENT / CREATING / READY / INVALID / FAILED

License
  UNKNOWN / VALID / CHECKING / TEMPORARILY_UNAVAILABLE /
  UNAUTHORIZED / REVOKED / SUSPENDED / EXPIRED

Identity/Security
  UNKNOWN / READY / BLOCKED / CORRUPT / IDENTITY_MISMATCH

Sync
  IDLE / BLOCKED_BY_NETWORK / BLOCKED_BY_AUTH /
  BLOCKED_BY_CLIENT / FLUSHING / DEGRADED

Recovery
  IDLE / PLANNING / ACTING / VERIFYING / COOLDOWN /
  BUDGET_EXHAUSTED / BLOCKED / RECOVERED
```

A successful action is never equal to a successful recovery. The post-condition validator must prove the dependency is healthy again.

## Recovery class policy

### Automatically recoverable

`RECOVERABLE_AUTH` -> refresh/rebuild session within a bounded window.

`RECOVERABLE_CLIENT` -> reconstruct the Supabase client from already-loaded configuration/session material.

`RECOVERABLE_LICENSE` -> perform one license heartbeat operation, but only through the central SessionManager and only if the license response is cryptographically valid.

`RECOVERABLE_IDENTITY` -> retry identity acquisition when the evidence is unavailable. Do not reinterpret a mismatch as an availability problem.

`RECOVERABLE_VAULT` -> re-read and validate the vault. Any repair that changes signed security material requires separate authorization and post-validation.

`RECOVERABLE_SYNC` -> recover auth/client dependencies, then resume the queue. Never make the queue responsible for credential lifecycle.

`RECOVERABLE_REALTIME` -> request a controlled reconnect using the newest SessionManager token and wait on a real connected event, not a sleep.

`RECOVERABLE_CONFIGURATION` -> reload through an existing typed configuration path only.

`THREAD_FAILURE` -> bounded restart through the existing local thread factory, not a new process supervisor.

### Never auto-repair

`HARDWARE_MISMATCH`

`LICENSE_REVOKED`

`VAULT_TAMPERED`

`SECURITY_TERMINAL`

These states must remain observable and terminal until an explicitly authorized administrative workflow changes the underlying security condition.

## Existing-activation identity recovery

This is the important "smart recovery" path requested for previously licensed machines.

The safe rule is:

```text
identity failure
   |
   +--> hardware mismatch -----------------> TERMINAL BLOCK
   |
   +--> vault tampered --------------------> TERMINAL BLOCK
   |
   +--> license revoked -------------------> TERMINAL BLOCK
   |
   +--> fingerprint unavailable -----------> BOUNDED RETRY
   |
   +--> identity record missing/corrupt
          |
          +--> same-machine evidence? ------ NO -> BLOCK / MANUAL REVIEW
          |
          +--> prior signed activation? ---- NO -> MANUAL ACTIVATION
          |
          +--> explicit reset/relink auth? - NO -> MANUAL REVIEW
          |
          +--> YES --------------------------> RELINK EXISTING ACTIVATION
                                                   |
                                                   +--> server accepts
                                                         |
                                                         +--> write identity
                                                         +--> verify identity
                                                         +--> verify license
                                                         +--> Core security-ready
```

The engine's `identity-reset-existing-license` plan therefore requires all of:

- `same_machine == true`
- `previously_licensed == true`
- `identity_reset_authorized == true`
- not `identity_mismatch`
- not `vault_tampered`
- not `license_revoked`

The action is **relink**, not license fabrication. It must call the existing workstation-registration/backend workflow and then revalidate the resulting workstation identity before readiness is restored.

## Engine architecture

```text
Telemetry / state change
          |
          v
  RecoveryObservation
          |
          v
  deterministic classifier
          |
          v
  candidate RecoveryPlans
          |
          +--> prerequisites / forbidden-fact gates
          |
          +--> sliding attempt budget
          |
          +--> cooldown
          |
          +--> deterministic score
          |
          v
  selected plan
          |
          v
  authorization callback
          |
          v
  typed action callback
          |
          v
  concrete post-condition validator
          |
          +------ failure ------> journal + bounded retry window
          |
          +------ success ------> journal + healthy state
          |
          +------ terminal -----> safe block
```

## Implemented in this pass

### 1. New module: `recovery_engine.py`

The new engine contains:

- explicit recovery classes and outcomes
- immutable observations and recovery plans
- atomic recovery journal persistence
- sliding-window attempt budgets
- cooldown enforcement
- prerequisite and forbidden-fact gates
- deterministic plan scoring
- typed action callbacks
- typed validators
- non-secret success history
- terminal/security classification
- no shell, no eval, no dynamic import, no arbitrary repair authority

### 2. Brain integration

The modified `Obylon.py` now:

- imports the engine
- creates one global Recovery Intelligence instance
- exposes a minimal state snapshot to it
- makes `SessionManager.force_refresh()` capable of rebuilding a missing Supabase client before refreshing
- refuses malformed refreshed JWTs
- obtains Realtime auth from SessionManager rather than the stale global access token
- adds `REALTIME_CONNECTED` as an actual readiness signal
- routes the missing-client sync recovery through the engine
- routes dead Brain-thread recovery through the engine instead of unconditional resurrection
- makes identity readiness explicit and withholds Core security-ready when identity is not ready
- makes missing PyNaCl verification fail closed
- leaves license/configuration recovery plans dormant until their one-shot operation is wired with a real post-condition validator

That last point is intentional. A recovery engine that lies about a license repair is worse than no engine. The remaining plan is therefore explicit rather than pretending an implementation exists.

## Phase 2: complete the one-shot license recovery path

Refactor the current long-running `license_heartbeat_loop()` into:

```python
def license_heartbeat_once(workstation_id: str) -> LicenseCheckResult:
    ...

def license_heartbeat_loop(workstation_id: str):
    while True:
        result = license_heartbeat_once(workstation_id)
        apply_offline_grace(result)
        wait_until_next_heartbeat()
```

The Recovery Engine should invoke only `license_heartbeat_once()`.

The result object must distinguish:

```text
VALID
TEMPORARILY_UNAVAILABLE
UNAUTHORIZED
REVOKED
SUSPENDED
EXPIRED
SIGNATURE_INVALID
MALFORMED_RESPONSE
```

Only `VALID` counts as recovered.

## Phase 3: repair the vault persistence boundary

The existing repair notes require the Python vault to stop writing directly to `obylon.enc`.

Required implementation:

1. serialize the complete candidate state
2. encrypt it
3. create a temporary file beside the real vault
4. write bytes
5. flush
6. `fsync`
7. atomically replace the destination
8. keep the old file until replacement completes
9. quarantine unreadable/corrupt vaults instead of deleting them

This is especially important because the Recovery Engine itself persists a journal and because auth token rotation may race with other state updates.

## Phase 4: canonical vault signature handling

There must be one and only one `ObylonVault.load()` and one canonical signed payload. The payload must include the same fields on both signing and verification paths, including hardware identity where required by the actual signing contract.

Missing verifier dependencies are a hard failure.

## Phase 5: fingerprint and identity readiness

The current Go helper timeout must be aligned with the intended bounded contract. The repair notes specify 12 seconds for the Windows helper.

The non-Windows platform stub must export the same status-bearing API as Windows so cross-platform builds remain structurally complete.

Identity states must remain distinct:

```text
VERIFIED
LEGACY_UNVERIFIED
UNAVAILABLE
CORRUPT
MISMATCH
```

Only verified or explicitly supported legacy-unverified deployment states may be handled as compatible. Unavailable/corrupt/mismatch must not accidentally become clone matches or security-ready.

## Phase 6: Core readiness contract

The Brain must prove its security state before sending:

```python
_core_ipc_call({"cmd": "brain_security_ready"})
```

Core already distinguishes its own process liveness from Brain security readiness. Preserve that boundary.

Do not invent a new `brain_security_blocked` command unless Rust Core explicitly implements it first.

## Phase 7: Recovery triggers

Add calls only at evidence-producing points:

- SessionManager detects missing/failed auth session -> `RECOVERABLE_AUTH` / `RECOVERABLE_CLIENT`
- sync daemon sees network + missing client -> `RECOVERABLE_CLIENT`
- Realtime connection failure -> `RECOVERABLE_REALTIME` through an external trigger, not from inside the same blocked reconnect coroutine
- license one-shot returns a recoverable transient error -> `RECOVERABLE_LICENSE`
- fingerprint provider unavailable -> `RECOVERABLE_IDENTITY`
- identity record missing but prior activation and same-machine evidence are confirmed -> `RECOVERABLE_IDENTITY` + guarded relink plan
- queue degraded due dependency failure -> `RECOVERABLE_SYNC`
- thread flatline -> `THREAD_FAILURE`

Do not invoke recovery from code that already owns the resource being waited on if doing so can deadlock the owner.

## Phase 8: Recovery Journal

Persist only non-secret facts:

- plan id
- component
- signal
- reason summary
- attempts in the active window
- last outcome
- success count
- failure count
- timestamp
- sanitized high-level facts

Never persist access tokens, refresh tokens, license secrets, full JWTs, screenshots, or raw evidence blobs.

The journal is diagnostic history, not the source of truth for license or identity.

## Phase 9: Observability

Each recovery should emit structured telemetry:

```text
recovery_class
signal
component
plan
attempt
window
cooldown
facts summary
outcome
postcondition
next_action
session_generation
```

Recommended single-line event sequence:

```text
recovery_action_begin
recovery_action_failed / recovery_action_succeeded
recovery_verification_failed / recovery_verified
recovery_budget_exhausted
recovery_blocked_terminal
```

The key requirement is that an operator can reconstruct what happened without opening a debugger.

## Phase 10: Fault injection suite

Every repair class needs a test injection point. The test-only mechanism must be compiled/packaged out or cryptographically unreachable in release builds.

Required cases:

### Auth

- missing client
- malformed access token
- expired access token
- refresh success
- refresh failure
- refresh token revoked
- concurrent refresh attempts

### License

- 200 valid
- 401 then refresh success
- 401 then refresh failure
- 403
- 429
- 500
- timeout
- malformed JSON
- invalid signature
- revoked
- suspended
- expired
- offline grace

### Identity

- valid fingerprint
- unavailable fingerprint
- malformed fingerprint
- same-machine missing identity record
- hardware mismatch
- legacy no-fingerprint deployment
- relink accepted
- relink rejected

### Vault

- intact
- corrupted bytes
- signature mismatch
- missing signature
- interrupted write
- concurrent save
- quarantine path

### Realtime

- token rotation
- websocket drop
- stale token rejection
- reconnect success
- reconnect failure

### Queue/sync

- one event
- burst of events
- offline to online transition
- auth unavailable
- client missing
- reconnect during flush
- duplicate delivery
- poison row
- partial success
- process crash during flush

### Supervision

- Brain crash
- Brain terminal security exit
- Core crash
- Broker restart
- duplicate launch
- session switch

## Phase 11: Windows validation

The engine is not considered production-ready until a real Windows endpoint demonstrates:

### Cold boot online

```text
Broker
  -> Core
    -> Brain
      -> identity verification
      -> auth
      -> client
      -> license
      -> security-ready
```

### Cold boot offline

```text
local security state
  -> bounded offline mode
  -> queue events
  -> no fake backend readiness
```

### Delayed network

```text
boot offline
  -> network appears
  -> Recovery Intelligence rebuilds auth/client
  -> license validated
  -> queue drains
  -> Realtime reconnects with fresh token
```

### Previously licensed identity loss

```text
identity state missing
  -> same-machine evidence verified
  -> prior activation evidence verified
  -> controlled relink
  -> server accepts
  -> identity verified
  -> license valid
  -> Core readiness restored
```

### Clone/tamper

```text
hardware mismatch / vault signature failure
  -> no recovery action
  -> no readiness
  -> terminal security path
```

## Phase 12: Code-quality gates

The 95+/100 gate should be scored as:

| Area | Weight | 95+ requirement |
|---|---:|---|
| Correctness | 25 | All recovery transitions have real validators; no false-positive success |
| Security | 25 | Terminal states are unreachable by automatic recovery; signature paths fail closed |
| Reliability | 20 | Bounded retries, sliding-window budgets, cooldowns, no restart storms |
| State fidelity | 10 | Internal state always matches concrete dependency health |
| Observability | 5 | Every decision is reconstructable from structured logs/journal |
| Test depth | 10 | Fault injection covers each recovery class and negative path |
| Maintainability | 5 | Typed APIs, isolated module, no dynamic code execution |

**Target:** >=95.

Any critical security defect is an automatic fail regardless of the numeric score.

## Non-negotiable invariants

1. Recovery can restore dependencies, but cannot manufacture security authority.
2. No automatic recovery may cross a confirmed hardware mismatch.
3. No automatic recovery may accept an invalid/unsigned security response.
4. No automatic recovery may delete forensic security state.
5. `SessionManager` remains the single owner of Supabase session credentials.
6. Realtime always consumes fresh credentials from `SessionManager`.
7. Core remains the enforcement and readiness boundary.
8. Broker/Core/Brain ownership remains unchanged.
9. Queue durability remains independent from authentication lifecycle.
10. Every successful recovery has a concrete post-condition.
11. Every recurring repair has a bounded attempt window.
12. Test-only fault injection is disabled by default and cannot be activated accidentally in production.

## Current pass validation

The following was run in this workspace:

```text
python -m py_compile Obylon.py recovery_engine.py   PASS
python -m pytest -q recovery_engine_test.py         PASS (5 tests)
```

Not yet run in this container:

```text
go test ./...
GOOS=windows GOARCH=amd64 go test ./...
GOOS=windows GOARCH=amd64 go build ./...
cargo check --workspace
cargo test --workspace
real Windows endpoint reboot / fault injection / Task Scheduler validation
```

Those omissions are deliberate evidence boundaries. They must not be relabeled as passes.

## Final acceptance definition

The Recovery Intelligence implementation is ready for production review only when:

- the Python engine tests pass
- the Go cross-platform stubs compile
- the Windows CLI build passes
- the Rust workspace checks pass
- the license one-shot operation has a real post-condition
- the Python vault writes are atomic
- corrupt vaults are quarantined
- the canonical signature verifier is single-path and fail-closed
- the identity state machine distinguishes unavailable/corrupt/mismatch
- the Core security-ready handshake is only reachable after readiness
- the previously-licensed same-machine relink path is tested
- the network/auth/client/license/sync/realtime recovery paths are all fault-injected
- a real reboot is tested online and offline
- delayed network recovery is tested
- token rotation followed by Realtime reconnect is tested
- three or more consecutive failures do not produce an endless restart storm
- no terminal security condition is auto-healed

## Deliverables in this pass

- `recovery_engine.py`: production-oriented deterministic Recovery Intelligence module.
- `recovery_engine_test.py`: focused engine unit tests.
- modified `Obylon.py`: safe integration points for auth/client, Realtime health, sync recovery, identity-readiness gating, signature fail-closed behavior, and bounded thread recovery.
- this document: implementation and validation plan.
- `RECOVERY_ENGINE_INTEGRATION.patch`: reviewable source diff.

## Design verdict

This approach is intentionally boring where security software should be boring: explicit state, typed actions, bounded budgets, real validators, durable diagnostics, and terminal states that do not get "helpfully" healed into nonsense. The intelligence is in classification and plan selection, not in giving an LLM a flamethrower and hoping it reads the documentation first.
