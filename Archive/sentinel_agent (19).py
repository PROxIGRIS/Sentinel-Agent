"""
Nexus Sentinel — Python monitoring sidecar
==========================================

Lightweight background service. Bundle to .exe with PyInstaller, then ship
inside the Electron wrapper as a sidecar process.

Build:
    pip install -r agent/requirements.txt
    pyinstaller --onefile --noconsole --name nexus_sentinel agent/sentinel_agent.py

Env (set by Electron wrapper before spawning):
    SUPABASE_URL                 — your Cloud project URL
    SUPABASE_PUBLISHABLE_KEY     — anon key
    SENTINEL_STATION             — workstation name (default: hostname)

Behaviour:
    * Registers / upserts the workstation row.
    * Emits heartbeat + uptime every 5 s.
    * Polls foreground window title; flags restricted keywords.
    * Captures a screenshot when severity == "high".
    * Polls admin_actions for remote lock / terminate.
"""
from __future__ import annotations
import os, sys, time, json, socket, platform, threading, base64, io, traceback

import psutil
import requests

try:
    import mss          # cross-platform screenshot
    from PIL import Image
except Exception:
    mss = None

# ---- foreground-window probing (Windows-first, graceful elsewhere) ----------
def get_foreground_window_title() -> str:
    if sys.platform.startswith("win"):
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value or ""
        except Exception:
            return ""
    if sys.platform == "darwin":
        try:
            from AppKit import NSWorkspace  # type: ignore
            return NSWorkspace.sharedWorkspace().frontmostApplication().localizedName() or ""
        except Exception:
            return ""
    # Linux: try wmctrl/xdotool if available
    try:
        import subprocess
        out = subprocess.check_output(["xdotool", "getactivewindow", "getwindowname"], timeout=1)
        return out.decode("utf-8", "ignore").strip()
    except Exception:
        return ""

def get_foreground_process_name() -> str:
    try:
        for p in psutil.process_iter(["name", "status"]):
            if p.info.get("status") == psutil.STATUS_RUNNING:
                return p.info["name"] or ""
    except Exception:
        pass
    return ""

# ---- restricted keywords ---------------------------------------------------
RESTRICTED = {
    "high":    ["unauthorized", "crack", "cheat", "keygen", "exploit"],
    "warning": ["game", "steam", "roblox", "minecraft", "proxy", "vpn",
                "tor", "youtube", "tiktok", "discord"],
}
def classify(title: str, proc: str) -> str | None:
    blob = f"{title} {proc}".lower()
    for kw in RESTRICTED["high"]:
        if kw in blob: return "high"
    for kw in RESTRICTED["warning"]:
        if kw in blob: return "warning"
    return None

# ---- supabase REST client (no SDK to keep the binary tiny) -----------------
class Cloud:
    def __init__(self, url: str, key: str):
        self.base = url.rstrip("/") + "/rest/v1"
        self.h = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
    def _req(self, method, path, **kw):
        return requests.request(method, self.base + path, headers=self.h, timeout=8, **kw)
    def upsert_workstation(self, name, os_info):
        r = self._req("GET", f"/workstations?name=eq.{name}&select=id")
        rows = r.json() if r.ok else []
        if rows:
            ws_id = rows[0]["id"]
            self._req("PATCH", f"/workstations?id=eq.{ws_id}", json={
                "status": "online",
                "last_heartbeat": _now(),
                "os_info": os_info,
            })
            return ws_id
        r = self._req("POST", "/workstations", json={
            "name": name, "status": "online", "last_heartbeat": _now(), "os_info": os_info,
        })
        return r.json()[0]["id"]
    def heartbeat(self, ws_id, uptime, cpu, mem):
        self._req("PATCH", f"/workstations?id=eq.{ws_id}",
                  json={"status": "online", "last_heartbeat": _now()})
        self._req("POST", "/heartbeat_logs", json={
            "workstation_id": ws_id, "uptime": uptime,
            "cpu_percent": cpu, "mem_percent": mem,
        })
    def alert(self, ws_id, proc, title, severity):
        r = self._req("POST", "/alerts", json={
            "workstation_id": ws_id, "process_name": proc,
            "window_title": title, "severity": severity,
        })
        try: return r.json()[0]["id"]
        except Exception: return None
    def evidence(self, alert_id, screenshot_b64, meta):
        self._req("POST", "/evidence_logs", json={
            "alert_id": alert_id,
            "screenshot_url": screenshot_b64,  # inline data: URL for Phase 1
            "metadata": meta,
        })
    def pending_actions(self, ws_id):
        r = self._req("GET",
            f"/admin_actions?target_id=eq.{ws_id}&status=eq.pending&select=id,command")
        return r.json() if r.ok else []
    def complete_action(self, action_id):
        self._req("PATCH", f"/admin_actions?id=eq.{action_id}", json={
            "status": "completed", "completed_at": _now(),
        })

def _now():
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"

# ---- remote command execution ---------------------------------------------
def execute_command(cmd: str):
    if cmd == "lock":
        if sys.platform.startswith("win"):
            import ctypes; ctypes.windll.user32.LockWorkStation()
        elif sys.platform == "darwin":
            os.system("/System/Library/CoreServices/'Menu Extras'/User.menu/Contents/Resources/CGSession -suspend")
        else:
            os.system("loginctl lock-session")
    elif cmd == "terminate":
        # Terminate any process matching restricted keywords
        for p in psutil.process_iter(["name"]):
            n = (p.info.get("name") or "").lower()
            if any(k in n for k in RESTRICTED["high"] + RESTRICTED["warning"]):
                try: p.terminate()
                except Exception: pass
    elif cmd == "shutdown":
        if sys.platform.startswith("win"):
            os.system("shutdown /s /t 5")
        else:
            os.system("shutdown -h +1")
    elif cmd == "warn":
        # Lightweight no-op; UI handles the toast.
        pass

# ---- screenshot ------------------------------------------------------------
def capture_screenshot_data_url() -> str | None:
    if mss is None: return None
    try:
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            img = Image.frombytes("RGB", shot.size, shot.rgb)
            img.thumbnail((1280, 800))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=72, optimize=True)
            return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None

# ---- main loop -------------------------------------------------------------
def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY")
    if not url or not key:
        print("[sentinel] missing SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY", file=sys.stderr)
        sys.exit(2)

    name = os.environ.get("SENTINEL_STATION") or socket.gethostname()
    cloud = Cloud(url, key)

    os_info = {
        "platform": platform.system(),
        "release":  platform.release(),
        "version":  platform.version(),
        "machine":  platform.machine(),
        "cpu_count": psutil.cpu_count(),
        "ram_gb":   round(psutil.virtual_memory().total / (1024**3), 1),
    }
    ws_id = cloud.upsert_workstation(name, os_info)
    boot = time.time()
    print(f"[sentinel] online as {name} ({ws_id})")

    last_alert_signature = None  # debounce identical foreground hits

    def heartbeat_loop():
        while True:
            try:
                cloud.heartbeat(
                    ws_id,
                    int(time.time() - boot),
                    psutil.cpu_percent(interval=None),
                    psutil.virtual_memory().percent,
                )
            except Exception:
                traceback.print_exc()
            time.sleep(5)

    def watch_loop():
        nonlocal last_alert_signature
        while True:
            try:
                title = get_foreground_window_title()
                proc  = get_foreground_process_name()
                sev   = classify(title, proc)
                sig   = (title, proc, sev)
                if sev and sig != last_alert_signature:
                    last_alert_signature = sig
                    aid = cloud.alert(ws_id, proc, title, sev)
                    if sev == "high" and aid:
                        shot = capture_screenshot_data_url()
                        cloud.evidence(aid, shot, {
                            "captured_at": _now(),
                            "reason": "restricted-keyword match",
                        })
            except Exception:
                traceback.print_exc()
            time.sleep(2)

    def command_loop():
        while True:
            try:
                for a in cloud.pending_actions(ws_id):
                    execute_command(a["command"])
                    cloud.complete_action(a["id"])
            except Exception:
                traceback.print_exc()
            time.sleep(3)

    for fn in (heartbeat_loop, watch_loop, command_loop):
        threading.Thread(target=fn, daemon=True).start()

    while True: time.sleep(3600)

if __name__ == "__main__":
    main()
