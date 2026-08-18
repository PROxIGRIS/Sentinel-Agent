# Fix: agent runs as SYSTEM in Session 0, can't see the interactive desktop

## Problem

`ObylonAgent` is currently registered as a scheduled task (`schtasks /Create /SC ONSTART`)
with no explicit `/RU`, which means it's created under the LocalSystem account context
of the installing MSI custom action. That means `obylon.exe` (no-args boot path) runs as
SYSTEM in Session 0.

On Windows Vista and later, Session 0 is isolated from the interactive user's desktop.
A process running there cannot:
- capture the logged-in user's screen (`PIL.ImageGrab.grab()` will return a blank/black or
  wrong-session image)
- receive global keyboard input via `pynput.keyboard.Listener` (low-level hooks are
  session-scoped)
- open a webcam preview or show a Tk window the user can actually see
  (the "hostile watermark" overlay in `main.py` around the `_hostile_watermark_thread`
  function assumes it's rendering into the user's visible desktop)

Net effect: as currently deployed, the agent most likely boots, runs, logs "started
successfully" — and silently monitors nothing, because it's watching an empty Session 0
desktop instead of the student's.

## Required fix

Split responsibilities into two roles inside the existing codebase, without changing the
behavior of the current no-args boot path (license/vault checks, `WorkstationGuard`,
keyboard listener, OCR pipeline, webcam evidence capture, hostile watermark — all of that
stays exactly as-is). We're only changing **who launches it and in which session**.

1. **New subcommand: `obylon.exe host`** (SYSTEM / Session 0 role)
   - Runs continuously as the thing the scheduled task actually invokes.
   - Calls `win32ts.WTSGetActiveConsoleSessionId()` to find the current console session.
   - When a valid session is found (and none is currently supervised), duplicates that
     session's user token and launches `obylon.exe` **with no arguments** (the existing
     full agent boot) inside that session as that session's user — this is the process
     that will actually do the monitoring.
   - Watches for session changes: user logon, logoff, lock/unlock (fast user switching
     matters here — school lab machines get used by many students per day). On logoff,
     terminate the launched child. On a new logon, launch a fresh child.
   - Restarts the child if it crashes (should not restart in a tight loop — back off).
   - This role needs no GUI, no OCR, no capture logic of its own — it's a thin
     supervisor/launcher.

2. **No change needed to the no-args boot path itself** — it already does the right thing,
   it's just been launched in the wrong session until now.

## Reference implementation for the launcher (needs hardening/testing, not a drop-in)

```python
# session_launcher.py — SYSTEM-side session-crossing launcher
import win32ts
import win32security
import win32process
import win32profile
import win32con
import win32api
import win32event
import pywintypes

SE_TCB_NAME = "SeTcbPrivilege"

def _enable_tcb_privilege():
    flags = win32security.TOKEN_ADJUST_PRIVILEGES | win32security.TOKEN_QUERY
    htoken = win32security.OpenProcessToken(win32api.GetCurrentProcess(), flags)
    priv_id = win32security.LookupPrivilegeValue(None, SE_TCB_NAME)
    win32security.AdjustTokenPrivileges(htoken, False, [(priv_id, win32security.SE_PRIVILEGE_ENABLED)])
    win32api.CloseHandle(htoken)

def launch_in_active_session(exe_path: str) -> "tuple | None":
    """Launch exe_path with no args inside the current console session as that
    session's user. Returns (hProcess, hThread, pid, tid) or None if no session
    is currently active (e.g. at the lock/login screen with fast user switching off,
    or nobody logged in yet)."""
    session_id = win32ts.WTSGetActiveConsoleSessionId()
    if session_id in (0xFFFFFFFF, None):
        return None

    _enable_tcb_privilege()

    user_token = win32ts.WTSQueryUserToken(session_id)
    try:
        primary_token = win32security.DuplicateTokenEx(
            user_token,
            win32security.SecurityIdentification,
            win32con.MAXIMUM_ALLOWED,
            win32security.TokenPrimary,
            win32security.SECURITY_ATTRIBUTES(),
        )
        env = win32profile.CreateEnvironmentBlock(user_token, False)

        startup = win32process.STARTUPINFO()
        startup.lpDesktop = "winsta0\\default"

        proc_info = win32process.CreateProcessAsUser(
            primary_token,
            exe_path,
            None,
            None,
            None,
            False,
            win32con.CREATE_UNICODE_ENVIRONMENT | win32process.CREATE_NEW_CONSOLE,
            env,
            None,
            startup,
        )
        return proc_info
    finally:
        win32api.CloseHandle(user_token)
```

Things the implementing agent must still handle (don't leave these out):
- Close all handles (`hProcess`, `hThread`, `primary_token`) once no longer needed —
  this runs indefinitely, handle leaks will accumulate.
- Register for session change notifications (`win32ts.WTSRegisterSessionNotification`
  against a hidden message-only window, or run this as a proper Windows service and
  handle `SERVICE_CONTROL_SESSIONCHANGE`) rather than polling
  `WTSGetActiveConsoleSessionId()` in a sleep loop — polling works but is sloppier and
  slower to react to fast user switching.
- Multiple concurrent sessions generally aren't a concern on a single school workstation,
  but handle the "no session yet" case (returns `None` above) by retrying rather than
  crashing the supervisor.
- Wrap the whole launcher in the same "IMMORTAL CATCH" pattern already used at the bottom
  of `main.py` — this process must never exit uncleanly, since it's the only thing
  standing between the machine and having no monitoring at all.

## Also update (once this lands)

The MSI's `RegisterStartupTask` custom action target needs to change from
`"[INSTALLFOLDER]obylon.exe"` to `"[INSTALLFOLDER]obylon.exe" host`, and should
explicitly pass `/RU "SYSTEM"` instead of relying on the implicit default:

```
schtasks /Create /TN "ObylonAgent" /TR "\"[INSTALLFOLDER]obylon.exe\" host" /SC ONSTART /RU "SYSTEM" /RL HIGHEST /F
```

(`ONSTART` is still correct for the *host* role — it should come up before any login so
it's ready the instant a student signs in. It's the no-args full-agent process that now
only ever runs inside a real user session.)

## Acceptance criteria — test on a real machine, not a dev session

1. Fresh install on a clean VM, reboot the machine (not just re-run the exe manually).
2. Log in as a normal (non-admin) user.
3. In Task Manager → Details tab, confirm there are now **two** obylon.exe processes:
   one under `SYSTEM` (the host), one under the logged-in username (the actual agent).
4. Confirm the OCR/keyboard/screen pipeline actually reacts to real activity on that
   session (trigger a test policy violation and confirm it's captured).
5. Log off and log a different user on — confirm the old child is gone and a new one
   spawns under the new username.
6. If the license is put into a revoked/expired state, confirm the hostile watermark
   overlay is now actually visible on the user's screen (this is the clearest visible
   proof the process is finally in the right session).
