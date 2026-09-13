# obylonc

Standalone management CLI for the Obylon Sentinel endpoint agent, replacing
the `argparse`-based CLI that used to live inside `Obylon.py`. Written in
pure Go standard library — no third-party dependencies — so it builds to a
single static binary with `go build`.

## What moved, and what didn't

**Moved here:** `activate`, `status`, `diagnose`, `doctor`, `deactivate`,
`support-bundle`, `boot`, `reset-identity`, `ai`. Every one of these reads
or writes the *same* on-disk files the Python agent uses (the DPAPI-encrypted
vault at `%PROGRAMDATA%\Obylon\obylon.enc`, the machine identity file, the
log file) — there's no IPC between `obylonc` and the agent, they just agree
on a shared file format.

**Stayed in the agent:** `host` (the Session-0 broker that spawns the agent
into the active console session) and the bare, no-argument agent boot
sequence. Both are the agent's own entry points, not admin CLI commands, so
splitting them out didn't make sense.

**New:** `obylonc logs` — tails or follows (`-f`) the agent's live log file,
with `--level`, `--grep`, and `--no-color` filters.

## Building

```
go build -o obylonc.exe .
```

Cross-compile from macOS/Linux:

```
GOOS=windows GOARCH=amd64 go build -o obylonc.exe .
```

To bake in real version metadata at build time:

```
go build -ldflags "-X obylonc/cmd.Version=7.1.0 -X obylonc/cmd.Commit=$(git rev-parse --short HEAD)" -o obylonc.exe .
```

**A note on this build**: this project was written and reviewed in a
sandboxed environment with no Go toolchain and no network access, so it has
**not** been compiled or run. I checked it as thoroughly as I could without
a compiler — brace/import balance, every cross-package call site matched
against what's actually exported, no duplicate identifiers — but please run
`go build ./...` and `go vet ./...` yourself before relying on it, and
smoke-test `activate`/`status`/`diagnose` against a real vault before wider
rollout. The vault/DPAPI interop (see below) is the part most worth
verifying first, since a mistake there is the one that could affect a
production vault.

## Commands

| Command | What it does |
|---|---|
| `activate <KEY>` / `--key-file <path>` | Activate this workstation |
| `status` | Human-readable license status |
| `diagnose [--dev]` | Network + auth + signature checks |
| `doctor [--deep|--deepfix|--fix|--profile]` | Unified health, evidence, profiling, repair, and post-fix verification |
| `logs [-f] [-n N] [--level L] [--grep S]` | Tail/follow the live log |
| `ai ["prompt"] [-i]` | Streaming AI support assistant |
| `boot {status,enable,disable}` | Manage the boot-time scheduled task (Admin) |
| `support-bundle` | Write a troubleshooting bundle to the CWD |
| `reset-identity --confirm` | Wipe machine identity (Admin, imaging) |
| `deactivate [-y]` | Wipe the local vault |
| `version` / `-v` | Print version info |

Global output controls are consistent across the CLI: `--json`, `--quiet`, and `--no-color` where supported, plus `--verbose`/`--debug`. Doctor is the canonical diagnostic engine.

## Project layout

```
main.go                      entry point
cmd/
  root.go                    dispatch, help, shared flag parsing, `version`
  license.go                 activate, status, diagnose, deactivate, reset-identity
  ops.go                     logs, support-bundle, boot
  ai.go                      the AI support assistant (REPL + streaming chat)
internal/
  paths/                     every on-disk path shared with the agent
  vault/                     the DPAPI-encrypted config store
  identity/                  machine UUID + hardware fingerprint
  api/                       HTTP client for the license server + Ed25519 signature check
  ui/                        colors, icons, boxes, spinner — no external TUI lib
  platform/                  every Windows syscall/WMI shim, in exactly 2 files
                             (windows.go + other.go), used by everything above
```

`internal/platform` is deliberately the one place that knows it's running on
Windows. Every other package — `vault`, `identity`, `ui` — is plain portable
Go that calls into `platform.EncryptDPAPI`, `platform.HardwareFingerprint`,
`platform.EnableConsoleANSI`, etc. `logs`' file-tailing logic and the AI
chat session live directly inside `cmd/ops.go` and `cmd/ai.go` rather than
their own packages, since those commands were each package's only caller.

## Vault & signature compatibility (the parts that must match byte-for-byte)

- **Vault encryption**: Windows DPAPI, `CRYPTPROTECT_LOCAL_MACHINE`, no
  optional entropy — matches the agent's
  `win32crypt.CryptProtectData(data, "ObylonSecure", None, None, None, CRYPTPROTECT_LOCAL_MACHINE)`
  exactly. Either side can decrypt what the other wrote.
- **Signature verification**: Ed25519 over a canonical, compact
  (`separators=(',',':')`-equivalent) JSON object with keys in the exact
  order `license_id, node_id, hardware_uuid, expires_at, issued_at, status`
  — `hardware_uuid` always comes from the *local* machine, never from the
  server payload, matching `verify_server_signature()`.
- **Hardware fingerprint**: `sha256(motherboard UUID | disk serial | MAC)`,
  same WMI properties, same "unknown" fallback per component.

## Deliberate differences from the old Python CLI

- **Vault corruption**: the agent silently deletes and recreates a corrupt
  or foreign-machine vault. `obylonc` reports the error instead and leaves
  the file alone — an interactive admin tool shouldn't quietly destroy
  state. Use `reset-identity --confirm` or `deactivate` to clear it
  explicitly.
- **`obylonc ai "prompt"`** answers once and exits (scriptable), instead of
  always dropping into an interactive follow-up loop. Pass `-i`/
  `--interactive` to keep chatting afterward.
- **`obylonc ai`** streams responses token-by-token (Gemini's
  `streamGenerateContent` SSE endpoint) instead of waiting for the full
  reply.
- **`support-bundle`**'s log extract now actually finds the log file. The
  old CLI looked for `C:\ProgramData\Obylon\agent.log`, which never matched
  the agent's real log path (`...\Obylon\logs\obylon.log`) — every old
  bundle silently said "log file not found."
- **`OBYLON_AI_API_KEY`** env var overrides the embedded Gemini key, so it
  can be rotated without a rebuild.

## Integrating with the agent

Since the CLI code was removed from `Obylon.py` on your end, the two things
to wire up:

1. Keep the SYSTEM scheduled task pointed at `ObylonBroker.exe`. The installer
   creates this task directly, and `obylonc boot enable` can recreate the same
   broker task manually. Override the broker path with `--exe <path>` or
   `OBYLON_BROKER_PATH` if it is installed somewhere else.
2. Nothing else — no IPC, no shared state beyond the files already listed
   above.


## 7.0.5-LTS CLI/admin authorization hardening

The CLI command registry now assigns every operational command an explicit scope and action metadata. Use `obylonc admin <command>` for the explicit administrative namespace; `obylonc auth` additionally accepts safe admin shortcuts such as `deactivate`, `reset-identity`, `boot-enable`, and `support-bundle`. These paths do not bypass server authorization.

License activation is performed by the installer before setup completes. The installer stages the key in a temporary file and invokes `obylonc activate --key-file ... --node-name ...`; the same command remains available for re-provisioning and recovery.


## CLI masterclass workflow

The public troubleshooting surface is intentionally consolidated under `doctor`; there is no separate troubleshoot command.

```text
obylonc status                    # one-screen endpoint state
obylonc doctor                    # fast local health check
obylonc doctor --deep             # forensic dependency/boot/evidence scan
obylonc doctor --fix              # safe repairs from the fast scan
obylonc doctor --deepfix           # forensic scan + safe repair + verification
obylonc doctor --deep --json      # automation-friendly structured evidence
obylonc logs --file <path>        # inspect any component log through one log command
obylonc support-bundle             # sanitized support artifact with available evidence
```

Doctor reports stable finding IDs, severity, evidence, impact, and remediation. Native-loader failures are decoded from Windows exit status and correlated with Task Scheduler and Application event evidence so failures that occur before Obylon logging starts can still be diagnosed.

`--json` is intended for automation and integrations. Repair commands require `--yes` in quiet/JSON mode so they can never block waiting for a terminal confirmation.

## Log Story / Forensics

`obylonc logs --deep` is the human-readable interpretation layer for the raw Broker/Core/Brain logs. It merges the streams by timestamp, translates technical messages into plain-language events, and emits stable `OBY-*` diagnostic codes. Raw logs are never rewritten by this feature.

Example:

```text
obylonc logs --deep
```

The story can show: Broker started → Broker launched Core → Core started → Core reported Brain security-ready → Brain exited with code `0xC0000135` → `OBY-WIN-DLL-MISSING`.
