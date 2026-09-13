# Obylon Masterclass Diagnostics

The diagnostic model is now a boot-chain forensic system rather than a process-presence guess.

## Commands

- `obylonc troubleshoot` performs a controlled dependency, Task Scheduler, native loader, boot-chain, Windows event, log, and heartbeat scan. It does not kill unrelated processes or claim telemetry that was not observed.
- `obylonc doctor --deepfix` runs the same evidence engine and applies only registered safe repairs. External dependencies such as the Microsoft Visual C++ Redistributable are reported explicitly when the doctor cannot safely install them itself.
- `obylonc doctor --fix` remains the bounded repair mode for the normal health check.

## What changed

1. The broker is treated as the first executable in the chain. A loader failure such as `0xC0000135 (STATUS_DLL_NOT_FOUND)` is surfaced before the Core/Brain stages are blamed.
2. Native runtime detection checks both the Visual C++ registry state and the actual loader DLLs.
3. Task Scheduler `Last Result` is decoded for known Windows process-loader failures.
4. Logs are only considered missing/healthy in the context of whether their producer is actually running.
5. Windows Application events are sampled when a native broker launch fails.
6. The installer performs a preflight confirmation for VC++ runtimes and stops before activation/boot-task registration if its installed payload is incomplete.
7. A fresh/reset Windows installation is now a first-class diagnostic target rather than an assumed development environment.

## Design rule

Every health statement should be backed by one of: an observed process, a verified file, a Windows API/command result, a timestamped log, or a decoded process exit code. Never print a success message merely because a code path executed.

## CLI Log Translation Layer

Raw logs remain authoritative and unchanged. The CLI adds a presentation-only forensic layer via `obylonc logs --deep`. The translator merges Broker, Core, and Brain streams by timestamp, renders local human-readable timestamps, explains common lifecycle events, and assigns stable `OBY-*` diagnostic codes. Windows/native exit codes such as `0xC0000135`, `0xC000007B`, and `0xC0000142` are decoded without altering the source logs.

## Network Recovery Model

The connectivity monitor distinguishes a usable local network path from control-plane availability. A recovered Wi-Fi adapter therefore moves the endpoint back to `ONLINE` even if Supabase/DNS/proxy is still recovering. A network-generation transition triggers authenticated-session reconstruction, and the durable queue re-evaluates its client before draining. This avoids the classic stale-client failure where Windows has recovered networking but the application remains logically offline.
