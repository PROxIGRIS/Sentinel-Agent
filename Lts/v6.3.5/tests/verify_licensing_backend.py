#!/usr/bin/env python3
"""
verify_licensing_backend.py — exercises /activate and /license_heartbeat
directly over HTTP, completely independent of the Windows agent or MSI.

Run this FIRST, before touching obylon.exe or the installer at all. If
these checks don't pass, nothing downstream (CLI activation, the deferred
custom actions, the heartbeat loop) can work either — the backend has to
be right before there's any point testing the exe or the MSI around it.

Setup:
  1. In the Supabase SQL editor, mint one throwaway test license with a
     SMALL node_limit (2 is ideal — enough to prove rebinding works
     without needing a dozen fake activations to hit the ceiling):

       insert into licenses (token_hash, school_id, plan_tier, node_limit, expires_at, status)
       values (encode(digest('TEST-KEY-DELETE-ME', 'sha256'), 'hex'),
               '<a real school_id>', 'test', 2, now() + interval '7 days', 'active');

     (adjust column names/hash function to match your actual schema —
     the point is: a real row your /activate function will accept.)

  2. export OBYLON_SUPABASE_URL="https://xxxx.supabase.co"
     export OBYLON_ANON_KEY="..."
     export OBYLON_TEST_LICENSE_KEY="TEST-KEY-DELETE-ME"

  3. python3 verify_licensing_backend.py

  4. Afterwards, delete the test license and its consumed nodes from the
     DB — this script does not clean up after itself, on purpose, so a
     failed run leaves evidence to inspect rather than silently vanishing.

What this does NOT test: license revocation propagating to a *running*
agent (that needs the actual heartbeat thread on a live machine), and it
does not touch service_role or the DB directly — only the same two public
HTTP endpoints the compiled agent itself calls, with the same anon key.
"""
import os
import sys
import json
import uuid
import urllib.request
import urllib.error

SUPABASE_URL = os.environ.get("OBYLON_SUPABASE_URL")
ANON_KEY = os.environ.get("OBYLON_ANON_KEY")
LICENSE_KEY = os.environ.get("OBYLON_TEST_LICENSE_KEY")

if not all([SUPABASE_URL, ANON_KEY, LICENSE_KEY]):
    print("Set OBYLON_SUPABASE_URL, OBYLON_ANON_KEY, and OBYLON_TEST_LICENSE_KEY first — see the docstring.")
    sys.exit(1)

ACTIVATE_URL = f"{SUPABASE_URL}/functions/v1/activate"
HEARTBEAT_URL = f"{SUPABASE_URL}/functions/v1/license_heartbeat"

results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))


def _post(url, payload, headers):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"raw": body}
    except urllib.error.URLError as e:
        return 0, {"raw": f"connection failed: {e}"}


def activate(hardware_uuid, hardware_fingerprint, hostname="verify-script", key=None):
    payload = {
        "license_key": key or LICENSE_KEY,
        "hostname": hostname,
        "hardware_uuid": hardware_uuid,
        "hardware_fingerprint": hardware_fingerprint,
    }
    return _post(ACTIVATE_URL, payload, {"apikey": ANON_KEY, "Authorization": f"Bearer {ANON_KEY}", "Content-Type": "application/json"})


def heartbeat(access_token, hardware_uuid):
    return _post(
        HEARTBEAT_URL,
        {"hardware_uuid": hardware_uuid},
        {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
    )


print("=== Obylon licensing backend verification ===\n")

# 1. Basic activation
node1_uuid, node1_fp = f"verify-{uuid.uuid4()}", f"verify-fp-{uuid.uuid4()}"
status, body = activate(node1_uuid, node1_fp)
record(
    "Node 1 activates successfully",
    status == 200 and "access_token" in body,
    f"HTTP {status}: {body if status != 200 else 'ok'}",
)
node1_token = body.get("access_token") if status == 200 else None
node1_node_id = body.get("node_id") if status == 200 else None

# 2. Invalid key is rejected, with the right error shape
status, body = activate(str(uuid.uuid4()), str(uuid.uuid4()), key="not-a-real-key")
record(
    "Invalid key is rejected",
    status in (401, 403) and body.get("error") == "Invalid license key",
    f"HTTP {status}: {body}",
)

# 3. Simulated OS reinstall on the SAME physical machine — new identity
#    file (new hardware_uuid) but the same hardware_fingerprint — should
#    rebind to node 1's existing row, not consume a new seat.
reinstalled_uuid = f"verify-{uuid.uuid4()}"
status, body = activate(reinstalled_uuid, node1_fp)
reinstalled_access_token = body.get("access_token")
record(
    "Same-fingerprint reactivation rebinds (doesn't consume a new seat)",
    status == 200 and body.get("node_id") == node1_node_id,
    f"HTTP {status}, node_id={body.get('node_id')!r} (expected {node1_node_id!r})",
)

# 4. Node limit enforcement — keep activating genuinely distinct fake
#    machines until the server refuses. Point OBYLON_TEST_LICENSE_KEY at
#    a license with a small node_limit or this will just eat seats.
print(
    "\nProbing node limit (activates distinct fake nodes until rejected — "
    "use a test license with a small node_limit)..."
)
accepted = 1  # node 1 already counted; the rebind in #3 shouldn't have added one
last_status, last_body = None, None
for _ in range(2, 12):  # hard cap so a misconfigured license can't loop forever
    u, f = f"verify-{uuid.uuid4()}", f"verify-fp-{uuid.uuid4()}"
    last_status, last_body = activate(u, f)
    if last_status == 200:
        accepted += 1
    else:
        break
record(
    "Node limit is enforced",
    last_status in (401, 403, 409) and last_body.get("error") == "node_limit_reached",
    f"accepted {accepted} node(s) before rejection; last response HTTP {last_status}: {last_body}",
)

# 5. Heartbeat succeeds for an active node
#    Uses the rebound node's credentials to hit the heartbeat endpoint
if reinstalled_access_token:
    status, body = heartbeat(reinstalled_access_token, reinstalled_uuid)
    record(
        "Heartbeat succeeds for an active node",
        status == 200 and body.get("status") == "active",
        f"HTTP {status}: {body}",
    )
else:
    record("Heartbeat succeeds for an active node", False, "skipped — node 1 activation failed above")

print("\n=== Summary ===")
failed = [r for r in results if not r[1]]
print(f"{len(results) - len(failed)}/{len(results)} checks passed.")
if failed:
    print("\nFailed checks:")
    for name, _, detail in failed:
        print(f"  - {name}: {detail}")
    print(
        "\nDon't move on to testing obylon.exe or the MSI until these pass — "
        "a failure here will just resurface, harder to diagnose, once Windows "
        "and the installer are in the loop too."
    )
    sys.exit(1)

print(
    "\nBackend looks solid. Next: run the compiled obylon.exe's `activate` "
    "and `status` commands directly on a real Windows box — no MSI yet — "
    "before wrapping any of this in an installer."
)
print(
    "\nOne thing this script can't cover: actually revoking a license "
    "mid-session and confirming a *running* agent stops within one "
    "heartbeat cycle. Do that by hand — flip the test license's status to "
    "'revoked' in the SQL editor, then watch the live agent's log output."
)
