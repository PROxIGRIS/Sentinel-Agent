# Obylon Sentinel — verification + fix pass

## The one bug that explains "nothing works reliably"

`Obylon.py` called `_perf_section(...)`, `_name_current_thread(...)`, and
`_write_perf_snapshot_loop` at ~17 call sites throughout the file — but
none of the three were ever actually *defined* anywhere in it. `main()`'s
`core_systems` dict passes `_write_perf_snapshot_loop` as a bare dict
value, which Python must resolve immediately when building the dict —
so this raised `NameError` the instant `main()` ran, before a single
subsystem thread (heartbeat, scanner, actions, sync, c2 poller, realtime
C2 — all of it) ever started. `py_compile` can't catch this class of bug
(it's a runtime name lookup, not a syntax error), which is almost
certainly why it shipped. **Fixed**: the full infrastructure is restored,
matching the exact `_perf_section("scanner", "<name>")` call signature
already in use.

## Five previously-fixed issues that had regressed

This codebase branched from a snapshot that predated an earlier fix pass.
All five are restored:

1. **DPI awareness** (`SetProcessDpiAwarenessContext`) — was gone
   entirely. This + #2 together are what caused the reported cropped
   screenshots.
2. **Multi-monitor / virtual-screen capture** — both the overlay window
   and `capture_screenshot_to_file()` had reverted to `SM_CXSCREEN`/
   `SM_CYSCREEN` (primary monitor only, and scaled-down on any display
   above 100% DPI). Restored to `virtual_screen_rect()`.
3. **Webcam format negotiation** (`MF_SOURCE_READER_ENABLE_VIDEO_PROCESSING`)
   — gone; most cameras don't output RGB32 natively and would fail
   outright without it.
4. **Pipe PID-based access control** — gone entirely (pipe was back to
   the default DACL, meaning any local process could connect and send
   commands like `unfreeze`). Restored.
5. **Keylog mutex critical section** — had regressed to holding the lock
   through the (more expensive) string join, on the same mutex the
   keyboard hook thread touches on every keypress. Restored to
   clone-then-release.

## New bug found and fixed: broken perf-percentage math

`core_perf_snapshot.json`'s writer was resetting its accumulators to zero
every cycle and pre-computing a percentage assuming an exact 5-second
window (`hooks_s * 20.0`) — an assumption that breaks the moment any
cycle takes even slightly longer, and is incompatible with how `doctor
--profile` actually reads it (two cumulative samples, diffed over the
real observed elapsed time — how Task Manager does it too). There was
also a literal duplicate `"hooks"` JSON key with the AI's own unresolved
reasoning left in as comments. Rewritten to write plain, never-reset
cumulative CPU-seconds, matching Python's side exactly.

## Your explicit product decisions, implemented

- **Freeze no longer shows any overlay.** `do_freeze()`/
  `trigger_fastlane_violation()` now only sever input — no visual. The
  overlay is reserved exclusively for an explicit classroom-focus session
  (`ShowOverlay`/`HideOverlay`, sent by
  `show_classroom_focus_overlay()`/`hide_classroom_focus_overlay()`).
  The existing freeze-reason tracking (which stops a classroom-focus
  toggle from accidentally clearing an in-progress violation penalty)
  is untouched — that's still valuable independent of what's on screen.
- **Classroom overlay text is now genuinely large** — previously no font
  was ever created at all; `DrawTextW` just used whatever small default
  happened to be selected into the DC. Now sized at ~1/6 of screen
  height, so it scales proportionally across resolutions rather than
  looking tiny on a 4K display.

## Root cause of the slow/no DB connection on boot

Not a slowness problem — an ordering one. `ensure_bucket()` and
`register_workstation()` (already running concurrently with each other
from an earlier pass) didn't start until *after* a third, separate,
sequential network round-trip finished first: the boot-time license
heartbeat check, over its own raw `urllib` connection with its own 5-second
timeout. Nothing about that check depends on workstation registration
completing first. **Fixed**: both now start immediately once the Supabase
client is built, so they run concurrently with the license check instead
of stacking after it — the actual wall-clock win, not just running two
things in parallel with each other while a third thing blocks both.

(Corrected along the way: an initial read of this suggested `sb` was
built *after* `register_workstation()` needed it, which would have been
a much worse bug — always-offline, forever. That was wrong; `main()` is
only *called*, from `if __name__`, after the client is already built.
Caught before shipping it as a finding.)

## `doctor` — verified and completed

The Python/Rust instrumentation that *feeds* `obylonc doctor` existed;
the Go command that *reads* it didn't — `cmd/doctor.go` and
`cmd/doctor_profile.go` were entirely absent from this codebase. Both are
now built, wired into `root.go`, and verified for real: cross-compiles to
a genuine Windows PE32+ binary, `go vet`/`gofmt` clean on both platforms,
and both the health check and `--profile <duration>` modes were actually
run end-to-end (including timing the profile sleep to confirm it's a
real sleep, not a poll loop — `doctor --profile 2s` took measured 2.01s).
Paths point at the real, now-established `C:\ProgramData\Obylon\logs\`
location for both snapshot files, not an assumed one.

## Verified already correct — no changes needed

Checked against the actual verification report's remaining claims:
- `record_fastlane_alert()` — correctly writes to the `alerts` table
  without re-triggering enforcement Core already handled.
- `realtime_c2_listener`'s `sb is None` reconnect logic — correctly
  scoped, correctly rebuilds the global client.
- `overlay_watcher_loop` — a genuinely well-built debounced-poll fix for
  rapid show/hide spam; decouples caller flood rate from actual Win32
  message traffic.
- Go's signature-verification and boot-task-target fixes from an earlier
  pass — both still intact, untouched by this one.

## What to test first on real hardware

1. Boot the agent, confirm `obylon.log` shows the Supabase identity
   check completing without the multi-second stall.
2. Trigger a fast-lane violation — confirm freeze happens with **no**
   overlay.
3. Trigger classroom focus — confirm overlay appears, text is
   noticeably larger, freeze is in effect.
4. Take a screenshot on a scaled display (125%/150%) and, if available,
   a dual-monitor rig — confirm it's the full real resolution, not
   cropped.
5. `obylonc doctor` — confirm all three binaries show running, perf
   snapshots show as fresh.
6. `obylonc doctor --profile 60s` — confirm real, non-zero numbers for
   both Python Brain and Rust Core.
