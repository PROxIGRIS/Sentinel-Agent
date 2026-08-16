# Prompt: Build a real CLI for the Obylon agent

Separate task from the licensing dashboard prompt — paste this into Claude Code on its own.

---

## Context

`sentinel_agent.py` already has `argparse` wired up (`if __name__ == "__main__":`, near the bottom of the file) with two subcommands: `activate <LICENSE_KEY>` and `status`. It technically works, but it's the bare minimum, not something you'd hand to school IT staff or use yourselves when a support ticket comes in. This task is entirely about the CLI/support surface — **do not touch `scan_loop`, the detection engine, `WARDEN`, the thread architecture in `main()`, or anything else that isn't argument parsing and command handling.**

## Hard constraint — don't break existing deployments

The no-argument invocation (`python sentinel_agent.py`, no subcommand) currently boots the full monitoring agent. That's how it's already being launched — scheduled tasks, services, whatever's wrapping it in the field. **That exact behavior has to keep working with zero arguments, unchanged.** Everything below adds to the CLI; nothing about it should require existing launch configs to change.

---

## What's actually wrong with it today

1. **`status` runs the full boot theater before printing anything.** `BuildInfo.print_banner()` and `harden_installation()` are called unconditionally, before the command is even dispatched — so asking for a quick status check triggers the giant ASCII banner and the self-protection/install-hardening routine. A read-only diagnostic command should never do that.
2. **`status` prints raw vault fields with no interpretation.** `License ID: {vault.get('LICENSE_ID')}`, etc. — if the vault is empty or this machine was never activated, that's a wall of `None`s instead of "this machine hasn't been activated yet." No indication of what the status actually *means* (days until expiry, grace period remaining, when the last successful heartbeat was in human terms).
3. **`activate` silently swallows every failure mode except two.** It explicitly handles `"SUCCESS"` and `"NETWORK_ERROR"` — anything else `provision_via_license` returns falls into a bare `else: sys.exit(1)` with no message printed at the CLI layer. Whatever internal logging happens inside `provision_via_license` might explain it, might not; the person running the command shouldn't have to guess.
4. **There's no way to test connectivity or diagnose an auth/signature problem without reading raw logs.** We just spent real time manually reverse-engineering a `/license_heartbeat` 401 vs. an `/activate` signature failure from log output. That entire process should be a single command.
5. **No `--version`, no clean deactivate/reset, no way to package diagnostics for a support ticket.** Right now getting build info means reading the banner off a full boot; wiping a bad local vault means finding the file by hand; sending us your logs means digging through wherever they're written.
6. **`--help` is structurally present (argparse gives you that for free) but says almost nothing.** One-line `help=` strings per subcommand, no top-level description of what running with no arguments does, no usage examples, no explanation of what `status`'s output fields mean.

---

## Build these commands

### `status` — fix in place, don't just add to it
- Remove `BuildInfo.print_banner()` and `harden_installation()` from this path entirely — read-only commands print nothing but their own output.
- If the vault is empty/unactivated, print exactly that ("This workstation has not been activated. Run: `sentinel_agent.py activate <LICENSE_KEY>`") and exit — not a page of `None`s.
- Otherwise, print interpreted, human-readable output: license status with plain meaning (`Active — expires in 340 days`, not just the raw enum), last successful heartbeat as a relative time (`2 minutes ago`), grace days remaining if currently offline, node/hardware identity, agent version.

### `diagnose` — new, this is the important one
Runs the same connectivity path the boot-time check uses (`/license_heartbeat`, using the existing vaulted `ACCESS_TOKEN`), but reports every stage separately instead of collapsing everything into one pass/fail:
1. DNS/reachability to the enrollment endpoint
2. TLS handshake
3. HTTP response received — print the actual status code
4. If 401/403: report this explicitly as **"Authentication failed — this does not necessarily mean the license was revoked, it means the request couldn't be verified. If this persists, contact Obylon support."** Do not use the word "revoked" here unless the response body actually says so — this is the exact confusion from the last incident and the whole reason this command exists.
5. If a 2xx response came back: run `verify_server_signature()` and report pass/fail explicitly. On failure: **"Signature verification failed — the server's response could not be cryptographically verified. This usually means a payload mismatch or key rotation issue, not a license problem. Contact Obylon support with this output."**
6. If everything above passes, print the actual parsed license status from the response.

No banner, no `harden_installation()` — same rule as `status`.

### `deactivate` — new
Cleanly wipes the local vault (clears `ACCESS_TOKEN`, license/session state) so the machine can be freshly re-activated or decommissioned. Destructive — require an explicit confirmation (`--yes`/`-y` flag to skip it for scripted use, otherwise prompt).

### `--version` / `version` — new
Prints build/version info only (whatever `BuildInfo` already tracks) — no banner, no boot sequence, no network call. This is the thing to ask someone for first on a support call.

### `support-bundle` — new
Writes a single timestamped file (e.g. `obylon-support-<timestamp>.txt` in the current directory) containing: vault status (same fields as `status`, still no secrets — never include `ACCESS_TOKEN`, `REFRESH_TOKEN`, or the raw license key), the last N lines of the agent's log file, hardware fingerprint, OS/build version, and the result of the same checks `diagnose` runs. This is the thing a school's IT person runs and emails you instead of a back-and-forth asking them to copy-paste terminal output.

### `activate` — keep the command, fix the failure handling
Every distinct status `provision_via_license` can return needs a distinct, clear message at the CLI layer — not a bare `else: sys.exit(1)`. Go through what `provision_via_license` actually returns and give each case its own line: invalid/unknown key, node limit reached, expired license, signature failure, whatever else exists. If a case doesn't have a specific string yet, at minimum print the raw status before exiting instead of nothing.

---

## Help text

- Give the top-level parser a real `description` and an `epilog` with 2–3 concrete usage examples (`sentinel_agent.py activate OBY-XXXX-XXXX`, `sentinel_agent.py diagnose`, `sentinel_agent.py support-bundle`).
- Give every subcommand a proper `help=` string that explains what it does, not just names it.
- Add a global `--verbose`/`--debug` flag that raises log verbosity for any command, so troubleshooting doesn't require editing source to see more output.

## What to leave alone

`scan_loop`, `WARDEN`, the detection/lexicon engine, `main()`'s thread setup and the Lazarus watchdog, `realtime_c2_listener`, the heartbeat loops themselves — none of that changes. This task is the argument parser, the command dispatch block at the bottom of the file, and the small set of new functions each command needs. If a fix requires touching detection logic to get a diagnostic command working, stop and flag it instead of proceeding.

## Definition of done

- `sentinel_agent.py --help` reads like documentation, not like argparse's default output.
- `sentinel_agent.py status` on a never-activated machine says so in one line, no banner, no hardening routine triggered.
- `sentinel_agent.py diagnose` run against a genuinely broken heartbeat endpoint clearly distinguishes an auth failure from a signature failure from an actual revoked license — three different messages, not one generic error.
- `sentinel_agent.py support-bundle` produces one file with no secrets in it that's actually useful for triaging a ticket without remoting into the machine.
- Running the agent with zero arguments still boots exactly as it does today.
