# Obylon EDR — Boot Reliability Issues

Status as of 2026-08-29: implementation is in progress; the changes below
still require compilation and a real reboot test on a Windows endpoint.

## Confirmed root causes

### 1. Clone detection treats a failed observation as a clone

The Python Brain previously accepted any output from `obylonc.exe
internal-fingerprint`, including the fallback value produced when WMI/CIM was
not ready during boot. It then compared that value with the activation-time
fingerprint and terminated the Brain on a mismatch. This is a false-positive
clone detection path, not proof that the workstation was cloned.

### 2. Packaged Brain searches for `obylonc.exe` in the wrong location

In a PyInstaller one-file build, `__file__` refers to the temporary extraction
directory. The helper CLI is installed alongside `obylon.exe`, not in that
temporary directory. Manual development launches can succeed while the
scheduled boot launch cannot find the helper, producing the false clone path
above.

### 3. Core launches the Brain only once

`ObylonCore.exe` spawned the Python Brain and immediately discarded its process
handle. An early Brain exit left Core alive but without telemetry, policy sync,
or a restart attempt. The broker sees that Core is still alive, so it cannot
recover this state either.

### 4. Startup task has no restart policy

`obylonc boot enable`, `obylonc doctor --fix`, and the installer created only
a basic `schtasks /sc onstart` task. If the broker itself exited, Task Scheduler
had no configured recovery behavior. The three task creation paths could also
drift apart over time.

### 5. Duplicate launches can install duplicate hooks

Neither Rust process had a named singleton mutex. A stale task, a manual task
run, or a second broker instance could therefore create duplicate brokers or
Core processes. Duplicate Cores mean duplicate hooks and competing Brain
supervisors.

## Fixes applied so far

| Area | Change |
| --- | --- |
| Fingerprint invocation | The Brain now resolves `obylonc.exe` beside `sys.executable` when packaged, validates an exact SHA-256 fingerprint, and applies a bounded timeout. |
| Clone verdict | An unavailable, malformed, or incomplete fingerprint now defers identity validation and records a warning; only two valid fingerprints that differ produce a clone verdict. |
| CLI fingerprint | The Go CLI now exposes a reliability status for the legacy-compatible fingerprint and refuses the internal fingerprint request when WMI data is incomplete. |
| Activation | CLI activation refuses to bind a license to an incomplete hardware identity. Fleet provisioning waits and retries until a stable identity is available. |
| Core launch | Core now resolves `obylon.exe` beside itself, writes Brain output using the active `PROGRAMDATA` path, and supervises the Brain with bounded exponential restart delays. |
| Confirmed clone handling | A confirmed mismatch uses a dedicated exit code, so Core backs off for remediation rather than hot-looping the Brain. |
| Duplicate protection | Named mutexes were added for the SYSTEM broker and the per-session Core. |
| Boot task | The CLI now builds a Task Scheduler XML definition with boot trigger, SYSTEM principal, no network gate, no execution limit, single-instance policy, and restart-on-failure recovery. `doctor --fix` uses the same path. |

## Still in progress

1. Update the installer to invoke the canonical `obylonc boot enable` task
   installer, rather than maintaining a separate raw `schtasks` definition.
2. Align version metadata across Python, CLI, and installer.
3. Format and compile Python, Go, and Rust; resolve any compiler findings.
4. Perform the required real reboot verification on a test endpoint. A manual
   task launch is not sufficient evidence for this bug class.

## Required endpoint verification

1. Build and install all four artifacts: `ObylonBroker.exe`,
   `ObylonCore.exe`, `obylon.exe`, and `obylonc.exe`.
2. Run `obylonc boot enable`, then `obylonc boot status` and `obylonc doctor`.
3. Reboot the endpoint, sign in, and confirm one Broker, one Core, and one
   Brain process are running.
4. Check `C:\ProgramData\Obylon\logs\broker.log`, `core.log`, and
   `brain_stdout.log` for a successful launch chain and `hardware identity
   verified`.
5. Repeat the reboot with normal boot contention; no `CLONE DETECTED` message
   should appear unless two complete, valid hardware fingerprints differ.
