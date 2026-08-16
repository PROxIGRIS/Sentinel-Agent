# Fix prompt: license/installer review findings

**How to use this:** paste this whole document as your first message to a
fresh AI coding session, together with the current `sentinel_agent.py` and
`Product.wxs`. Self-contained — no other context needed. Fix in the order
listed; items 1–3 are install-breaking or defeat license enforcement
entirely, items 4–7 are real but contained, items 8–9 are confirmations,
not code changes.

---

### 1. [CRITICAL] Deferred custom actions can't see `[LICENSEKEY]`

**Where:** `Product.wxs`, `Single_Activation` and `Fleet_Seed_Drop` custom
actions.

**Root cause:** Windows Installer does not expose the property table to
`Execute="deferred"` custom actions — this is an intentional security
boundary (deferred CAs may run under SYSTEM after the UI sequence has
already finished), not a WiX quirk. Referencing `[LICENSEKEY]` directly
inside a deferred CA's `ExeCommand` will resolve to an empty string at
execution time. `sentinel.exe activate` then receives no value for its
required positional `LICENSE_KEY` argument, argparse exits nonzero, and
because `Single_Activation` has `Return="check"`, that failure **aborts
and rolls back the entire MSI installation**. `Fleet_Seed_Drop` has the
identical defect — it will write an empty `license_seed.txt`, which the
agent's zero-touch fleet-ignition path will then feed into
`provision_via_license("", ...)`, get a hard invalid-key error, and
`sys.exit(1)` — and since nothing deletes the seed file on failure, it
retries the same empty key forever on every restart.

**Fix:** the standard CustomActionData pattern — capture the property via
a preceding *immediate* CA, then have the deferred CA read
`[CustomActionData]` instead of the raw property:

```xml
<CustomAction Id="Set_Single_Activation" Property="Single_Activation" Value="[LICENSEKEY]" />
<CustomAction Id="Single_Activation"
              Directory="INSTALLFOLDER"
              ExeCommand="&quot;[INSTALLFOLDER]obylon.exe&quot; activate [CustomActionData]"
              Execute="deferred" Impersonate="no" Return="check" />

<CustomAction Id="Set_Fleet_Seed_Drop" Property="Fleet_Seed_Drop" Value="[LICENSEKEY]" />
<CustomAction Id="Fleet_Seed_Drop"
              Directory="INSTALLFOLDER"
              ExeCommand="cmd.exe /c &quot;echo [CustomActionData] &gt; C:\ProgramData\Obylon\license_seed.txt&quot;"
              Execute="deferred" Impersonate="no" Return="check" />
```

And sequence the `Set_*` immediate CA directly before its deferred
counterpart, both carrying the same condition:

```xml
<InstallExecuteSequence>
  <Custom Action="Set_Single_Activation" After="InstallFiles">
    <![CDATA[DEPLOY_MODE="SINGLE" AND NOT Installed]]>
  </Custom>
  <Custom Action="Single_Activation" After="Set_Single_Activation">
    <![CDATA[DEPLOY_MODE="SINGLE" AND NOT Installed]]>
  </Custom>
  <Custom Action="Set_Fleet_Seed_Drop" After="InstallFiles">
    <![CDATA[DEPLOY_MODE="FLEET" AND NOT Installed]]>
  </Custom>
  <Custom Action="Fleet_Seed_Drop" After="Set_Fleet_Seed_Drop">
    <![CDATA[DEPLOY_MODE="FLEET" AND NOT Installed]]>
  </Custom>
</InstallExecuteSequence>
```

Also reconsider `Return="check"` on `Single_Activation` specifically: once
(1) is fixed, a genuinely wrong/expired/at-limit key will correctly cause
`obylon activate` to exit nonzero — and `Return="check"` will then roll
back the *entire file installation* over a licensing problem, forcing a
full MSI re-run to fix what should be a one-line CLI retry. Recommend
`Return="ignore"` instead, with the activation outcome written to a log
IT can check, so a bad key at install time doesn't nuke the install —
`obylon activate <correct-key>` afterward should be enough to recover.

---

### 2. [CRITICAL] `ServiceInstall`/`ServiceControl` register a service the code doesn't implement

**Where:** `Product.wxs`, `AgentExecutable` component.

**Root cause:** `ServiceInstall`/`ServiceControl` tell Windows this exe
*is* a Windows Service and to start it via the Service Control Manager.
SCM expects the process to call back through the Win32 Service Control
Handler API (`SetServiceStatus`, etc.) within ~30 seconds of launch.
`sentinel_agent.py` has no `win32serviceutil.ServiceFramework` subclass,
no `SvcDoRun`/`SvcStop`, no `servicemanager.StartServiceCtrlDispatcher()`
— it's a plain script-style process. SCM will time out waiting for the
handshake (Windows Error 1053), and `ServiceControl Start="install"
Wait="yes"` will hang or report failure during install.

**Fix — pick one:**
- **(a) Revert to Scheduled Task registration** (no agent code changes):
  remove `ServiceInstall`/`ServiceControl` from the wxs, and after the MSI
  completes, register a startup task:
  ```
  schtasks /Create /TN "ObylonAgent" /TR "\"C:\Program Files\Obylon\obylon.exe\"" /SC ONSTART /RL HIGHEST /F
  ```
  Task Scheduler doesn't require the SCM handshake — it just launches the
  process — and its own failure-restart settings give you most of the
  resilience a service would.
- **(b) Make it a real service**: wrap the agent's entry point in a
  `win32serviceutil.ServiceFramework` subclass with proper `SvcDoRun`
  (calling the existing `main()` on a thread) and `SvcStop` (signaling a
  clean shutdown). More correct for pre-logon start and SCM-managed
  restart policy, but a real code change, not just an installer change —
  only worth it if those specific benefits matter over (a)'s simplicity.

---

### 3. [CRITICAL] License revocation doesn't actually stop the agent

**Where:** `sentinel_agent.py`, `license_heartbeat_loop()`.

**Root cause:** this function runs as a background thread (registered in
`core_systems`). All three of its `sys.exit(1)` calls — on
revoked/suspended status, on 401/403, and on exceeding the 7-day offline
tolerance — only raise `SystemExit` **inside that thread**. That
terminates the heartbeat thread alone; the main thread, Warden
enforcement, evidence upload, and every other subsystem keep running
completely unaware the license was revoked. Worse, since this thread is
in `core_systems` under watchdog supervision, `resurrect()` may just
restart it, so it re-detects "revoked" every cycle forever without ever
affecting the running agent. As implemented, revocation is a no-op.

**Fix:** signal the main thread instead of exiting from the worker
thread — the codebase already has this exact idiom for
`TOKEN_ROTATED_EVENT`, reuse it:

```python
# near TOKEN_ROTATED_EVENT's definition
LICENSE_INVALID_EVENT = threading.Event()
```

Replace each `sys.exit(1)` in `license_heartbeat_loop` with setting a
reason and the event, e.g.:
```python
if status in ("revoked", "suspended"):
    logger.critical(f"License is {status}, shutting down.", component="license")
    LICENSE_INVALID_EVENT.set()
    return  # stop this thread's loop; don't exit the process from here
```
(same pattern for the 401/403 branch and the offline-tolerance branch).

Then in `main()`'s own loop (main thread), check
`LICENSE_INVALID_EVENT.is_set()` each cycle and perform an orderly
shutdown from there — unhook Warden cleanly, stop other threads, then
exit. That's the one place `sys.exit()` (or `os._exit()` if a harder stop
is wanted) actually terminates the whole process.

---

### 4. [HIGH] `obylon activate` always reports success

**Where:** `sentinel_agent.py`, `__main__`, the `activate` command branch.

```python
success = vault.provision_via_license(...)
if success:               # <- always truthy: provision_via_license returns
                           #    a string ("SUCCESS" | "HARD_ERROR" | "NETWORK_ERROR"),
                           #    never a bool, and never an empty string
```

**Fix:**
```python
status = vault.provision_via_license(args.LICENSE_KEY, hostname, HARDWARE_UUID, HARDWARE_FINGERPRINT)
if status == "SUCCESS":
    logger.info("Activation complete. Agent ready for background execution.", component="system")
    sys.exit(0)
elif status == "NETWORK_ERROR":
    logger.error("Activation failed: network unreachable. Check connectivity and retry.", component="system")
    sys.exit(1)
else:
    sys.exit(1)  # HARD_ERROR — provision_via_license already printed the specific reason
```

---

### 5. [HIGH] `ProgramData\Obylon` is world-writable

**Where:** `Product.wxs`, `ProgramDataFolder` component.

```xml
<CreateFolder>
    <Permission User="Everyone" GenericAll="yes"/>
</CreateFolder>
```

This folder holds the DPAPI vault (`obylon.enc`) and, in FLEET mode, the
plaintext `license_seed.txt`. The vault uses `CRYPTPROTECT_LOCAL_MACHINE`
(machine-scoped, not user-scoped) DPAPI — meaning any local account on
that PC, including the students being monitored, can already decrypt it
given local code execution, and `Everyone: GenericAll` additionally lets
them delete it outright (denial of service against the monitoring
itself) or read the plaintext seed key. Restrict this:

```xml
<CreateFolder>
    <Permission User="SYSTEM" GenericAll="yes" />
    <Permission User="Administrators" GenericAll="yes" />
</CreateFolder>
```

---

### 6. [MEDIUM] No PATH registration

**Where:** `Product.wxs`, `AgentExecutable` component — missing entirely.

Add:
```xml
<Environment Id="AddInstallDirToPath" Name="PATH" Value="[INSTALLFOLDER]"
             Permanent="no" Part="last" Action="set" System="yes" />
```
Without this, `obylon activate <KEY>` only works from inside
`C:\Program Files\Obylon`, not from an arbitrary terminal.

---

### 7. [MEDIUM] Inconsistent binary name

**Where:** `Product.wxs` (`File Id="SentinelExe" Source="sentinel.exe"`,
`ServiceInstall Name="ObylonSentinel"`, CA `ExeCommand` references) vs.
the CLI UX goal of a bare `obylon activate <KEY>` command.

Rename the built exe and every reference to `obylon.exe` consistently
(`File Source`, CA `ExeCommand` strings, any `[INSTALLFOLDER]sentinel.exe`
paths), or explicitly decide to keep `sentinel.exe` and update all
IT-facing instructions/docs to say `sentinel activate <KEY>` instead —
just pick one and make every reference agree.

---

### 8. [CONFIRM] Golden-image identity reset for FLEET mode

Not a code bug, a process gap: if the master image used for cloning is
ever booted with the agent already run once (so `HARDWARE_UUID`'s
identity file already exists), every clone will inherit the *same*
hardware UUID, breaking per-node licensing. Confirm there's a
sysprep-equivalent step in the imaging pipeline that deletes the identity
file before the golden image is captured, so each clone regenerates a
fresh one on first boot.

---

### 9. [CONFIRM] WiX toolchain version

`Product.wxs` uses WiX v3 syntax (`<Product>` nested inside `<Wix
xmlns="http://schemas.microsoft.com/wix/2006/wi">`, `WixUI_InstallDir`
dialog model). That's fine and mature if building with WiX v3's
candle.exe/light.exe toolchain — it will not compile as-is with the
modern `wix.exe` v4/v5 CLI, which expects the v4 schema namespace and a
`<Package>`-based structure. Confirm which toolchain this is meant for
and keep everything (docs, build scripts) consistent with that choice.

---

## Acceptance checklist

- [ ] A deliberately wrong license key at install time does **not** roll
      back file installation, and the specific failure reason is visible
      to IT (log or console output)
- [ ] A deliberately wrong or empty `LICENSEKEY` in FLEET mode does not
      produce an infinite crash-restart loop on first boot
- [ ] The MSI actually starts the agent on a real Windows VM without
      Error 1053 or an install hang
- [ ] Revoking a test license server-side causes the running agent to
      stop enforcing/reporting within one heartbeat cycle — verified by
      actually revoking one and watching the process, not just reading
      the code
- [ ] `obylon activate <bad-key>` exits nonzero and says why
- [ ] A standard (non-admin) local user cannot delete or read
      `C:\ProgramData\Obylon\obylon.enc`
- [ ] `obylon activate <KEY>` works from a fresh terminal with no path
      prefix
- [ ] Every reference to the binary name agrees (File source, service/CA
      strings, docs)
