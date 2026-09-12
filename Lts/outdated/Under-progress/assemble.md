# Task: assemble, verify, and compile the full Obylon system

## What this is

A three-language system for Obylon Sentinel, a Windows endpoint agent for
school-managed lab computers under institutional authorization:

- **Rust** (`rust/`) — `ObylonBroker.exe` (Session 0 supervisor) and
  `ObylonCore.exe` (enforcement + a "fast lane" that arms minimum
  protection in ~100ms, before Python is even running)
- **Python** (`Obylon.py`) — the "brain": threat scoring, Supabase sync,
  OCR, FSM/arbitration. An IPC client to Core, not a standalone process
  with its own hooks/capture/CLI anymore.
- **Go** (`obylonc/`) — the CLI: activate, status, diagnose, deactivate,
  support-bundle, boot, reset-identity, ai, logs, version.

**Nothing in `rust/broker` or `rust/core` has been compiled on a real
Windows target yet.** The environment this was built in has no Windows
toolchain at all — the `windows` crate's Win32 module doesn't exist on a
non-Windows host, confirmed directly (`cargo check` fails immediately at
every version tried). Your job is to make it build, fixing real compiler
errors as you find them — not to redesign the architecture, not to
"improve" things that aren't broken, and not to reach for the hard
out-of-scope list at the bottom of this document.

`rust/common` and `obylonc` (Go) **have** been compiled and verified for
real — details below on exactly what that means and what it doesn't.

---

## What you're given

```
Obylon.py                        Python brain. IPC client to ObylonCore.exe
                                   over \\.\pipe\ObylonCore. No CLI, no
                                   hooks, no capture code of its own anymore.

rust/
├── Cargo.toml                    workspace root
├── common/     obylon-common     IPC schema (serde) + file logger.
│                                  COMPILED + UNIT-TESTED (5/5 passing,
│                                  on Linux — zero Windows deps).
├── broker/     ObylonBroker.exe  Session 0, SYSTEM: WTS summon ->
│                                  CreateProcessAsUser -> spawns
│                                  ObylonCore.exe into the interactive
│                                  session. Registered as the boot-time
│                                  scheduled task via `obylonc boot enable`.
└── core/       ObylonCore.exe    Runs IN the interactive session:
                                   - hooks (freeze/unfreeze, fail-safe
                                     auto-expiry timer independent of IPC)
                                   - native overlay window
                                   - keylog ring buffer (fed by the hook)
                                   - screenshot (GDI BitBlt)
                                   - webcam (Media Foundation)
                                   - FAST LANE: foreground-window +
                                     process + network-adapter monitoring,
                                     armed before Brain is even spawned;
                                     on a match, freezes/overlays/screenshots
                                     and reports the violation on its own
                                   - named-pipe IPC server (PID-authenticated
                                     — see Security section below)
                                   - spawns Obylon.py as its own child

obylonc/                          Go CLI. Pure IPC-free — reads/writes
                                   the same on-disk vault, log files, and
                                   fastlane_rules.json/identity_beacon.json
                                   Obylon.py and ObylonCore.exe use. No
                                   network calls to Core; no shared process.

docs/
└── obylon-architecture-and-ota-plan.md   Full architecture + OTA design
                                            (OTA is NOT implemented — see
                                            Out of Scope below).
```

---

## Environment you need

- **A real Windows machine**, or a properly configured cross-compile
  target (`x86_64-pc-windows-msvc` via `cargo-xwin`, or
  `x86_64-pc-windows-gnu` via `mingw-w64`). A native Windows box is much
  less friction given how COM/Win32-heavy this is (Media Foundation
  especially).
- **rustc 1.82 or newer**, via `rustup` — not a distro package manager.
  `windows-core` (a transitive dependency of the pinned `windows` crate
  version) requires it; this is exactly what stalled verification in the
  environment this was built in (that environment's `apt`-installed rustc
  was 1.75).
- **Go 1.21+** for the CLI — pure stdlib, no `proxy.golang.org` dependency,
  cross-compiles cleanly with `GOOS=windows GOARCH=amd64 go build`.
- **Python 3.11+** with `pip install supabase psutil pillow pywin32
  structlog httpx certifi`. Note `opencv-python`, `pynput`, and `wmi` are
  **not** required for the process-monitor or network-adapter-monitor
  paths anymore (moved to Rust) — if you see either reintroduced as a
  dependency for those specific paths, that's a regression, not a missing
  package to install. `wmi` is still legitimately used elsewhere (USB
  insertion monitoring, hardware fingerprinting, one other pre-existing
  scan-loop usage) — see Out of Scope for why those weren't touched.

---

## Deployment layout (where files actually go)

All four artifacts (`ObylonBroker.exe`, `ObylonCore.exe`, the PyInstaller-
built `obylon.exe`, `obylonc.exe`) install to the same folder, e.g.
`C:\Program Files\Obylon\`. Runtime data lives under
`C:\ProgramData\Obylon\`:

```
C:\ProgramData\Obylon\
├── obylon.enc                    encrypted vault (DPAPI)
├── logs\
│   ├── broker.log
│   └── core.log
├── capture\                      screenshot/webcam JPEGs — Core writes,
│                                  Python reads-then-deletes
├── events\
│   └── events.jsonl              Core -> Python event queue (new_process,
│                                  new_network_adapter, fast_lane_violation)
├── fastlane_rules.json           written by Python, read by Core every ~5s
└── identity_beacon.json          written by Python after Supabase handshake,
                                    read by Core for direct fast-lane reporting
```

---

## Build order

1. **`obylonc` (Go)** — `cd obylonc && GOOS=windows GOARCH=amd64 go build
   -o obylonc.exe .` This should just work; it already did in the
   environment this was built in (`go vet` and `gofmt` both clean).
2. **`rust/common`** — `cargo test -p obylon-common` from `rust/`. Should
   also just pass — this has zero Windows dependencies.
3. **`rust/broker`** — `cargo build -p obylon-broker --release`. Fix real
   compiler errors here before touching `core`; it's the smaller binary.
4. **`rust/core`** — `cargo build -p obylon-core --release`. Expect more
   errors here. If Media Foundation or WinHTTP errors are blocking
   everything else, temporarily stub their two IPC match arms (`CaptureWebcam`
   returning `IpcResponse::err("temporarily disabled")`, similarly for the
   direct-report call inside `trigger_fastlane_violation`) to get
   hooks/freeze/overlay/keylog/screenshot/fast-lane-detection compiling and
   testable as their own milestone, then come back for those two pieces
   separately.
5. **Full workspace** — `cargo build --release` at the `rust/` root once
   both binaries build individually.
6. **Python** — `python -m py_compile Obylon.py`, then build with
   PyInstaller as before (same command as always — nothing about the
   PyInstaller invocation itself changed this pass).

---

## Known risk areas — ranked by likelihood, check these first

1. **WinHTTP direct-report POST** (`winhttp_post_json` in `core/src/main.rs`)
   — the single least-familiar API surface in the file. If this fails,
   **that's fine and expected to investigate calmly, not urgently** — it's
   a latency optimization only. The durability guarantee is the events
   queue (`events.jsonl`), which Python drains into its own already-proven
   `vault_enqueue()` SQLite sync path regardless of whether this succeeds.
2. **Media Foundation webcam capture** (`capture_webcam_inner`,
   `sample_to_jpeg`) — COM lifetime, device enumeration, and format
   negotiation. `MF_SOURCE_READER_ENABLE_VIDEO_PROCESSING` is now enabled
   on the source reader specifically so cameras that natively output
   NV12/YUY2/MJPEG (most of them) auto-convert instead of failing
   `SetCurrentMediaType` outright — validate this fix on real hardware
   before trusting it; it was reasoned through carefully but never
   compiled.
3. **DPI awareness + virtual-screen geometry** (`virtual_screen_rect()`,
   `SetProcessDpiAwarenessContext` in `main()`) — new this pass, fixes a
   real bug (screenshots/overlay silently cropped on scaled displays and
   secondary monitors) but needs testing on an actual scaled display
   (125%/150%) and, if available, a dual-monitor rig with a monitor
   positioned left of or above the primary (negative virtual-screen
   origin is the trickiest case).
4. **Pipe PID-based access control** (`handle_connection`'s authorization
   check against `BRAIN_PID`) — new this pass, closes a real "any local
   script can send unfreeze" gap. Verify the legitimate Brain<->Core
   connection still works (i.e. this doesn't accidentally reject its own
   client) — and know the documented residual gap: PIDs are reused by the
   OS over time, and Core doesn't yet watch for Brain's process exit to
   clear `BRAIN_PID` immediately, so there's a narrow window where a
   crashed Brain's PID could theoretically be reassigned before Core
   notices. Not fixed in this pass — flagged in the code comment where it
   lives.
5. **`&mut T` vs `*mut T` on out-parameters, pervasive across the whole
   file.** windows-rs has changed this convention across versions. Every
   FFI call was written assuming the modern ergonomic `&mut T` style. If
   you see `expected *mut T, found &mut T`, that's this — a local
   `as *mut _`/`as *const _` cast, not a logic change.
6. **`bool` vs `windows::Win32::Foundation::BOOL` argument coercion** —
   same category, several call sites.
7. **GDI function return types** (`BitBlt`, `ReleaseDC`, `GetDIBits`,
   `SelectObject`) — some return `Result<()>` in current windows-rs,
   others return raw `i32`/`BOOL` because their semantics aren't cleanly
   boolean.
8. **Windows feature flags** — every feature in both `Cargo.toml` files was
   checked against the live crates.io index at write-time and should be
   correct; if the compiler can't find a type, windows-rs's error messages
   are unusually good about naming the exact feature to add.

None of the above should require touching control flow, the threading
model, or the IPC schema. If a fix seems to need any of those, stop and
flag it rather than improvising a redesign.

---

## Verify the Python side

```
python -m py_compile Obylon.py
```

Then confirm none of these appear anywhere in the file — all should be
fully absent except in comments explaining their removal:
`cv2`, `pynput`, `keyboard.Listener`, `ImageGrab`, `_background_keylogger`,
`start_wmi_process_monitor`, `start_network_adapter_monitor`,
`argparse`, `cmd_host`, `cmd_diagnose`, `cmd_boot`, `cmd_ai`,
`cmd_support_bundle`, `cmd_reset_identity`.

`import wmi` legitimately still appears in a few other places (USB
insertion monitoring, hardware fingerprinting, one pre-existing scan-loop
usage) — these are deliberately untouched, see Out of Scope.

---

## Verify the Go CLI

```
cd obylonc
GOOS=windows GOARCH=amd64 go build -o obylonc.exe .   # should produce a
                                                        # real PE32+ binary
go vet ./...                                           # should be silent
gofmt -l .                                             # should print nothing
```

If you touch `internal/api/api.go`'s signature canonicalization
(`canonicalSignPayload`/`signFieldJSON`), re-run this exact check — it
guards against the specific bug that was found and fixed (every field's
original JSON type, string/number/bool, must be preserved when
re-serializing for the Ed25519 signature check, matching Python's
`json.dumps()` behavior exactly):

```go
// Should print identical output for both:
// {"expires_at":1798761600}       <- numeric field
// {"expires_at":"2027-01-01..."}  <- string field
```

---

## Integration smoke test (once everything builds)

Do this on an actual Windows test machine, not just a clean compile.

1. Install all four artifacts to the same folder. Run `obylonc boot
   enable` — confirm it registers against `ObylonBroker.exe` (not the old,
   now-nonexistent `obylon.exe host`).
2. Reboot, log in, tail `core.log` — confirm `"hooks installed"` and
   `"fast lane armed"` appear, in that order, within a second or two of
   login, well before Python's own boot banner would appear in the old
   timing.
3. Trigger each IPC command once from Python (or a small test script):
   `ping`, `freeze` (confirm keyboard/mouse actually lock, confirm
   auto-unfreeze fires on schedule even without sending `unfreeze`),
   `show_overlay`/`hide_overlay`, `get_keylog_snapshot` (type something
   first), `capture_screenshot`, `capture_webcam` (last — highest risk).
4. **Fast lane test:** add a distinctive fake entry to
   `fastlane_rules.json`'s `banned_process_names`, then launch a process
   with that exact name *before* Python has finished booting (or with
   Python's process killed entirely). Confirm: workstation freezes,
   overlay shows, a screenshot lands in `capture\`, and an entry appears in
   `events\events.jsonl` — all without Python running at all.
5. **DPI/multi-monitor test:** set display scaling to 150%, take a
   screenshot via `capture_screenshot`, confirm the resulting JPEG is the
   full real screen resolution, not a cropped corner. If a second monitor
   is available, confirm both the screenshot and the freeze overlay cover
   it too.
6. **Pipe security test:** from a separate, unrelated process (not the
   Brain process Core spawned), try connecting to `\\.\pipe\ObylonCore`
   and sending a command. Confirm it's rejected and logged as
   `"rejected pipe connection from unauthorized process"` — then confirm
   the *real* Brain process's own commands still work normally.
7. **Go CLI test:** `obylonc status`, `obylonc diagnose`, `obylonc
   activate <key>` against a real license, `obylonc boot status`.

---

## Definition of done

- [ ] `cargo test -p obylon-common` passes
- [ ] `cargo build -p obylon-broker --release` succeeds
- [ ] `cargo build -p obylon-core --release` succeeds (webcam/direct-report
      may ship temporarily stubbed if they need more than a build-fix pass
      — say so explicitly if that's the state you land in)
- [ ] `GOOS=windows GOARCH=amd64 go build` succeeds, `go vet`/`gofmt` clean
- [ ] `python -m py_compile Obylon.py` passes, orphan-reference sweep clean
- [ ] All 7 smoke-test steps above produce the expected result
- [ ] Report back: what you changed to get it compiling (so the risk
      list above can be corrected for next time), and the actual status of
      webcam capture and DPI/multi-monitor on real hardware

---

## HARD OUT OF SCOPE — do not do these

Reaching for any of these instead of a targeted build-fix is treating a
"make it compile" task as a redesign task. Don't.

- **Don't implement OTA.** It doesn't exist in either language yet — it's
  an explicitly later phase per the architecture doc. There is nothing to
  "finish" here; building it now is scope creep, not a fix.
- **Don't implement IPC protocol-version negotiation.** The architecture
  doc describes it as future work; the current schema doesn't have it.
  This is a known, accepted, documented gap — not a bug to close in a
  build-verification pass.
- **Don't add a full SDDL-based pipe ACL on top of the PID check.** The
  PID-based authorization in `handle_connection` already closes the actual
  threat (same-user process sending unauthorized commands) that an ACL
  can't distinguish anyway, since Core and Brain run as the same session
  user by design. Adding a second authorization layer now is unnecessary
  complexity for a threat model already covered.
- **Don't move USB-insertion detection to Rust.** Deliberately deferred —
  `RegisterDeviceNotification` + `WM_DEVICECHANGE` handling is meaningfully
  more novel Win32 surface for lower fast-lane payoff than what's already
  been moved (foreground window, process, network adapter). Leave
  `start_usb_insertion_monitor()` in Python exactly as it is.
- **Don't move `get_hardware_fingerprint()`'s algorithm to Rust.** Its
  *timing* was moved to a background thread; its *algorithm* was
  deliberately left untouched in Python, because migrating it risks a
  fingerprint mismatch against every already-activated machine's stored
  value — a far worse failure mode than a slightly slower boot. If you
  find yourself rewriting this in Rust, stop.
- **Don't split `core/src/main.rs` into multiple files/modules.** This is
  a deliberate, explicit choice (monolith preferred over module sprawl for
  this phase), not an oversight. Reorganizing into `hooks.rs`/`ipc.rs`/
  `capture.rs`/etc. is a valid future refactor but is not what this task
  is for.
- **Don't merge `broker` and `core` into one binary**, or otherwise change
  the two-binary Session-0/interactive-session split. This split exists
  specifically because a Windows Service's own binary can't be replaced
  while running, and because low-level input hooks can only run in the
  interactive session, not Session 0.
- **Don't add new dependencies** (`crossbeam`, `tokio`, a full HTTP+TLS
  crate, etc.) to work around a build error. The keylog mutex issue was
  fixed by shrinking the critical section, not by reaching for a lock-free
  crate; WinHTTP was chosen over a full HTTP client specifically to avoid a
  new dependency tree for one best-effort request. If a build error seems
  to need a new crate, that's a signal to reconsider the approach, not to
  add the dependency.
- **Don't swap Media Foundation for OpenCV/DirectShow** if RGB32
  negotiation gives you trouble beyond what `MF_SOURCE_READER_ENABLE_VIDEO_PROCESSING`
  already fixes. The entire point of this migration was getting off the
  Python/OpenCV dependency — reintroducing it in Rust defeats that.
- **Don't change the IPC message schema** (`common/src/lib.rs`'s
  `IpcRequest`/`IpcResponse`) unless a field is factually wrong. It's the
  single source of truth both languages depend on, and it already has a
  test guarding against schema drift.
- **Don't re-add `cv2`, `pynput`, or `wmi` to Python's process-monitor or
  network-adapter-monitor code paths.** Both were deliberately moved to
  Rust's `ToolHelp32`/`GetAdaptersAddresses` polling specifically to remove
  the GIL-blocking COM import cost from Python's boot window. If a build
  or runtime issue tempts you to restore the old Python-side watcher as a
  "quick fix," don't — fix the Rust side instead.
- **Don't touch the Go CLI's already-fixed signature verification or boot
  task target** without a concrete reason tied to a real test failure.
  Both were bugs found and fixed by cross-checking against the real Python
  source; reverting either would reintroduce a confirmed, previously-broken
  behavior.
