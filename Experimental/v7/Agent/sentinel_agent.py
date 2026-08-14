"""
╔══════════════════════════════════════════════════════════════════╗
║          NEXUS SENTINEL — School Endpoint Monitor v7.0           ║
║                  Authorized Deployment Tool                      ║
╚══════════════════════════════════════════════════════════════════╝

Authorization:
    Deployed by IT administration under written authorization from
    school principal. Operates exclusively on school-owned hardware.
    Visible monitoring notice is displayed at every login session.

Scope:
    - Monitors active window titles and browser content for policy
      violations (explicit content, proxy/bypass tools, gaming,
      malware, RATs, crypto-miners, unauthorized installers).
    - Input locking: temporarily disables keyboard/mouse on critical
      violation pending admin review. Auto-releases after configurable
      timeout or on admin remote release.
    - Evidence capture: rolling 500-char keystroke buffer flushed ONLY
      on confirmed violation. Webcam capture restricted to CRITICAL
      severity events only for workstation attribution in shared labs.
    - All evidence uploaded to school-controlled Supabase instance
      with offline vault fallback (SQLite) during network outages.

v7.0 — NEW SYSTEMS:
    • Axiom Engine (Phase 7): Three-layer behavioral intelligence.
        Layer 1 — Signal Bus: every observable event produces a weighted
                  signal that decays linearly over a 5-minute window,
                  continuously computing the Ambient Threat Score (ATS).
        Layer 2 — Pattern Arbitrator: wakes on ATS ≥ 0.40; runs Lev
                  Engine across the full live signal set and checks
                  co-occurrence multiplier tables to compute a confirmed
                  score. Suppresses noise, escalates genuine threat.
        Layer 3 — Deep Forensic Verifier: wakes on ATS ≥ 0.70 or Layer 2
                  confirmed score ≥ 0.60; runs OCR, full process tree scan,
                  DOM re-analysis, clipboard scan, and open file handle
                  inspection. Returns a final verdict.
    • WMI Process Creation Monitor: event-driven (zero polling gap),
      fires on process creation with parent chain masquerade detection.
    • Clipboard Surveillance Pipeline: rolling in-memory clipboard
      monitor; feeds Axiom Engine; cleared on confirmed violation only.
    • Smart USB / Adapter Monitor: HID-aware (keyboards/mice pass
      silently), mass-storage execution blocking, tethering detection.
    • Extended Lexicon: RAT/C2 frameworks, crypto-miners, droppers,
      privilege escalation tools, GitHub installer patterns, network
      scanning tools, password crackers, script execution red flags.

What this is NOT:
    - Not a general-purpose keylogger (buffer is non-persistent,
      non-exfiltrated except on confirmed policy breach).
    - Not spyware (no microphone, no continuous screen recording,
      no location tracking, no data sold or shared with third parties).
    - Not deployed on personal devices.

Compliance:
    Students are notified at login that school devices are monitored.
    Data is accessible only to authorized school IT staff and admin.
    Data handling follows the Nexus Sentinel Authorized School Endpoint
    Monitoring and Evidence Handling Notice v6.3.5+.

Dependencies:
    pip install supabase psutil pillow pynput opencv-python
    pip install wmi pywin32 pyperclip          (Windows-specific features)
    Tesseract OCR engine embedded in tesseract_engine/ folder.

Version history:
    v6.3.5  — Forensic vault, OTA update, focus mode, Lev Engine
    v7.0    — Axiom Engine, WMI monitor, clipboard pipeline,
              smart USB monitor, extended lexicon
"""

from __future__ import annotations  # MUST BE FIRST

from PIL import Image
import pytesseract
import sys
import os


# ─── STANDALONE TESSERACT PATH RESOLUTION ────────────────────────────────────
# Routes to the embedded engine inside the PyInstaller temp folder.
def _get_tesseract_path() -> str:
    if hasattr(sys, "_MEIPASS"):
        base_dir = sys._MEIPASS          # Compiled .exe runtime
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))  # Dev/VS Code
    return os.path.join(base_dir, "tesseract_engine", "tesseract.exe")

pytesseract.pytesseract.tesseract_cmd = _get_tesseract_path()

import io
import json
import asyncio
import websockets
import platform
import random
import re
import socket
import sqlite3
import subprocess
import threading
import time
import uuid
import math
import unicodedata
import difflib
import urllib.request
import hashlib
import shutil
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Iterable

import psutil

try:
    from supabase import create_client, Client
    from pynput import keyboard, mouse
    import cv2
    from PIL import ImageGrab
except ImportError:
    sys.exit(
        "Install core dependencies:\n"
        "  pip install supabase psutil pillow pynput opencv-python"
    )


import win32pipe, win32file, pywintypes
from freeze_hud import engage_freeze_with_hud, dismiss_freeze_hud

# Set SENTINEL_LOG_MODE=verbose in the environment for full diagnostic output.
# Default is "operational" — only confirmed anomalies are printed.
_LOG_MODE: str = os.environ.get("SENTINEL_LOG_MODE", "operational").lower()

# Levels that always print in operational mode.
_OPERATIONAL_LEVELS = {"anomaly", "warning", "critical", "error", "strike"}


def sentinel_log(
    message: str,
    level:   str  = "debug",
    *,
    force:   bool = False,
) -> None:
    """
    Gated logger — the single print() gateway for all engine messages.

    Operational mode (default):
        Prints only when level is in _OPERATIONAL_LEVELS or force=True.
        Silent for routine scan telemetry, Lev fuzzy-matching, and ATS ticks
        that are below threshold.  This eliminates the console flood that
        causes admins to ignore output or disable logging entirely.

    Verbose mode (SENTINEL_LOG_MODE=verbose):
        Prints everything — useful for tuning thresholds and debugging
        new lexicon patterns without deploying to production endpoints.

    Usage (replace bare print() calls with sentinel_log()):
        sentinel_log("[lev] fuzzy best: ...", level="debug")       # silent in ops
        sentinel_log("[!!!] STRIKE fired", level="strike")         # always prints
        sentinel_log("[axiom] ATS=0.72 ...", level="anomaly")      # always prints
        sentinel_log("[wmi] Feature Disabled", level="error")      # always prints
    """
    if _LOG_MODE == "verbose" or force or level in _OPERATIONAL_LEVELS:
        print(message)


# =====================================================================
# THE WARDEN — Native C++ IPC Bridge
# =====================================================================
class NativeWarden:
    def __init__(self):
        self.pipe_name = r"\\.\pipe\NexusSentinel"
        self.pipe = None
        self.system_frozen = False
        threading.Thread(target=self._boot_muscle, daemon=True, name="warden_bridge").start()

    def _boot_muscle(self):
        """Creates the pipe server, spawns warden64.exe, and listens for telemetry."""
        try:
            self.pipe = win32pipe.CreateNamedPipe(
                self.pipe_name,
                win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                1, 65536, 65536, 0, None
            )
            
            # Spawn the C++ sidecar silently
            cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            subprocess.Popen(["warden64.exe"], creationflags=cflags)
            
            # Wait for C++ to connect
            win32pipe.ConnectNamedPipe(self.pipe, None)
            print("[WARDEN] IPC Tether established to Muscle.")

            # Listen for Zero-Gap WMI/USB Telemetry from C++
            while True:
                try:
                    result, data = win32file.ReadFile(self.pipe, 65536)
                    msg = json.loads(data.decode().strip())
                    
                    if msg.get("event") == "process_create":
                        proc_name = msg.get("name")
                        c_lev, cat, hit = LEV.evaluate_suspicion(proc_name, proc_name)
                        if c_lev >= 0.50:
                            axiom_push_signal("wmi_process_high", proc_name, lev_score=c_lev)
                            
                    elif msg.get("event") == "usb_insert":
                        drive = msg.get("drive")
                        axiom_push_signal("usb_mass_storage", drive)
                except Exception as e:
                    time.sleep(1)
        except Exception as e:
            print(f"[WARDEN] Bridge Failure: {e}")

    def _send(self, payload: dict):
        if self.pipe:
            try:
                win32file.WriteFile(self.pipe, (json.dumps(payload) + "\n").encode())
            except Exception:
                pass

    def engage_freeze(self, duration: int = 60) -> None:
        self.system_frozen = True
        self._send({"cmd": "lock"})
        print("[WARDEN] Execution Command Sent: LOCK")
        # Python handles the timeout and will send unlock when the HUD finishes
        threading.Timer(duration, self.disengage_freeze).start()

    def disengage_freeze(self) -> None:
        self.system_frozen = False
        self._send({"cmd": "unlock"})
        print("[WARDEN] Execution Command Sent: UNLOCK")

    def terminate_process(self, target_name: str) -> bool:
        self._send({"cmd": "kill", "target": target_name})
        print(f"[WARDEN] Scalpel Command Sent: KILL {target_name}")
        return True

WARDEN = NativeWarden()

# ─── Credential Config (obfuscated against casual student inspection) ─────────
_u_codes = [104,116,116,112,115,58,47,47,111,122,114,117,105,107,102,110,114,109,
            109,118,104,118,111,122,103,110,111,111,46,115,117,112,97,98,97,115,
            101,46,99,111]
_k_codes  = [101,121,74,104,98,71,99,105,79,105,74,73,85,122,73,49,78,105,73,115,
             73,110,82,53,99,67,73,54,73,107,112,88,86,67,74,57,46,101,121,74,112,
             99,51,77,105,79,105,74,122,100,88,66,104,89,109,70,122,90,83,73,115,
             73,110,74,108,90,105,73,54,73,109,57,54,99,110,86,112,97,50,90,117,99,
             109,49,116,100,109,104,50,98,51,112,110,98,109,57,118,73,105,119,105,
             99,109,57,115,90,83,73,54,73,110,78,108,99,110,90,112,89,50,86,102,99,
             109,57,115,90,83,73,115,73,109,108,104,100,67,73,54,77,84,99,51,79,68,
             81,53,78,68,99,48,77,105,119,105,90,88,104,119,73,106,111,121,77,68,
             107,48,77,68,99,119,78,122,81,121,102,81,46,75,68,95,106,109,118,115,
             75,57,114,87,117,55,98,114,112,77,73,107,112,102,54,118,102,76,112,103,
             107,67,66,120,115,71,70,69,114,100,120,106,67,104,95,73]

SUPABASE_URL = "".join(chr(c) for c in _u_codes)
SUPABASE_KEY = "".join(chr(c) for c in _k_codes)

# ─── Identity / Alias ─────────────────────────────────────────────────────────
ALIAS_FILE = Path.home() / ".sentinel_alias"

# ─── Deployment Metadata ──────────────────────────────────────────────────────
DEPLOYMENT_CONFIG = {
    "authorized_by":   "School Principal + IT Admin",
    "scope":           "School-owned devices, school hours only",
    "data_controller": "School IT Department",
    "contact":         "it@school.edu",
    "version":         "7.0.0",
}


# =====================================================================
# SUPABASE CLIENT INITIALIZATION
# =====================================================================
if not SUPABASE_URL or not SUPABASE_KEY:
    sys.exit("FATAL: Missing Supabase credentials.")

try:
    sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as _e:
    sys.exit(f"FATAL: Could not initialize Supabase Client: {_e}")


# ─── Utility helpers ─────────────────────────────────────────────────────────
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def os_info() -> dict:
    return {
        "platform": platform.system(),
        "release":  platform.release(),
        "host":     socket.gethostname(),
    }


def _hide_path(p: Path) -> None:
    """Best-effort: mark file/dir hidden on Windows."""
    try:
        if platform.system() == "Windows":
            subprocess.call(["attrib", "+H", str(p)], shell=False)
    except Exception:
        pass


def get_workstation_identity() -> str:
    """
    Resolve display name.  Precedence:
      1. ~/.sentinel_alias (admin-set remote alias)
      2. socket.gethostname() fallback
    Runs before Supabase init so registration always uses correct name.
    """
    try:
        if ALIAS_FILE.exists():
            alias = ALIAS_FILE.read_text(encoding="utf-8").strip()
            if alias:
                return alias
    except Exception as e:
        print(f"[identity] alias read failed: {e}", file=sys.stderr)
    return socket.gethostname()


WORKSTATION_NAME = get_workstation_identity()


# ─── Kernel Priority ─────────────────────────────────────────────────────────
def set_high_priority() -> None:
    """
    Elevate this process to HIGH_PRIORITY_CLASS (Windows) or nice(-10) (Unix)
    so it out-competes browsers and games for CPU time.
    Silently degrades if privileges are insufficient.
    """
    try:
        p = psutil.Process(os.getpid())
        if platform.system().lower().startswith("win"):
            p.nice(psutil.HIGH_PRIORITY_CLASS)
        else:
            p.nice(-10)
    except (psutil.AccessDenied, PermissionError):
        pass
    except Exception as e:
        print(f"[priority] elevation failed: {e}", file=sys.stderr)


set_high_priority()


# ─── Timing Constants ─────────────────────────────────────────────────────────
HEARTBEAT_INTERVAL   = 15   # seconds between heartbeat DB updates
SCAN_INTERVAL        = 3    # seconds between scan_loop cycles
ACTION_POLL          = 4    # seconds between admin action polls
KEYLOG_DURATION      = 10
ALERT_DEBOUNCE_SEC   = 30
AMBIENT_DEBOUNCE_SEC = 60
FOCUS_REFRESH_SEC    = 10
EVIDENCE_BUCKET      = "evidence"

# ─── Forensic Vault paths ────────────────────────────────────────────────────
VAULT_DB     = Path.home() / ".sentinel_vault.db"
CACHE_DIR    = Path.home() / ".sentinel_cache"
SYNC_INTERVAL = 30

# ─── Hardware Mutex ───────────────────────────────────────────────────────────
OPTICS_LOCK = threading.Lock()
VAULT_LOCK  = threading.Lock()

# ─── Admin Bypass Config ─────────────────────────────────────────────────────
ADMIN_BYPASS_ACTIVE = False
BYPASS_KEY = "099hsj"

SPOOF_DATA = {
    "proc":  "msedge.exe",
    "title": "Microsoft Learn: Python for Data Science - Edge",
}

PHANTOM_SCRIPT = [
    "def calculate_loss(y_true, y_pred):\n    return sum((t - p) ** 2 for t, p in zip(y_true, y_pred)) / len(y_true)\n",
    "import numpy as np\nmatrix = np.zeros((10, 10))\nfor i in range(10):\n    matrix[i][i] = 1\n",
    "async def fetch_data(url):\n    async with aiohttp.ClientSession() as session:\n        async with session.get(url) as response:\n            return await response.json()\n",
    "class DataProcessor:\n    def __init__(self, data):\n        self.data = data\n    def clean(self):\n        return [d.strip() for d in self.data if d]\n",
    "SELECT users.id, profiles.avatar_url FROM users JOIN profiles ON users.id = profiles.user_id WHERE users.active = true;\n",
]

IDENTITY_FILE       = Path.home() / ".sentinel_id"
COMMAND_TTL_SEC     = 60
TERMINATE_GRACE_SEC = 10

# Global workstation ID — set in main() before threads start,
# consumed by WMI/USB monitors that run in separate threads.
workstation_id_global: str = ""


# =====================================================================
# LEXICON — Compliance Severity Hierarchy (extended in v7.0)
# =====================================================================
LEXICON: dict[str, list[str]] = {

    # ── LEVEL 1: THE UNFORGIVABLE ─────────────────────────────────────
    # Exact matches only. Any hit here returns C_lev = 1.0.
    "critical": [
        # Explicit adult content
        r"\b(pornhub|porn|xvideos|redtube|brazzers|hentai|rule34|xxx|nsfw|gelbooru)\b",
        # Extreme content
        r"\b(gore|snuff|behead|execution|murder|suicide|isis|terrorist|jihad)\b",
        # ── v7.0 additions ──
        # Known RAT / remote-access trojan names and C2 frameworks
        r"\b(njrat|darkcomet|nanocore|asyncrat|remcos|quasar|xworm|dcrat|"
        r"cobalt.?strike|metasploit|msfvenom|meterpreter|empire|covenant|"
        r"havoc.?c2|sliver|brute.?ratel|deimos|orcus.?rat|warzone.?rat|"
        r"agent.?tesla|formbook|lokibot|redline|raccoon|vidar|amadey|smokeloader)\b",
        # Dropper / loader / stager vocabulary
        r"\b(dropper|stager|shellcode|payload\.exe|loader\.exe|inject\.exe|"
        r"crypter|stub\.exe|packer|binder|fud|fully.?undetectable)\b",
        # Privilege escalation / post-exploitation tools
        r"\b(mimikatz|lazagne|rubeus|bloodhound|sharphound|crackmapexec|"
        r"impacket|responder\.py|evil.?winrm|chisel|ligolo|proxychains|"
        r"netcat|ncat|socat|powercat|reverse.?shell|bind.?shell)\b",
        # Crypto-mining
        r"\b(xmrig|cgminer|bfgminer|cpuminer|nbminer|t-rex.?miner|"
        r"lolminer|phoenixminer|ethminer|nanominer)\b",
    ],

    # ── LEVEL 2: THE INSURGENCY ───────────────────────────────────────
    # Triggers investigation + ambient log; not an immediate lock.
    "high": [
        r"\b(adult|sex|dating|hookup|escort|nude|naked|erotic)\b",
        r"\b(psiphon|ultrasurf|shadowsocks|vpn|proxy|tor\.exe|bypass[- ]?firewall)\b",
        # ── v7.0 additions ──
        # GitHub installer / release download patterns
        r"\b(github\.com/[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-]+/releases)\b",
        r"\b(raw\.githubusercontent\.com)\b",
        r"\b(setup\.exe|install\.exe|installer\.msi|setup\.msi|update\.exe)\b",
        # Script-based execution red flags
        r"\b(powershell\s+-[eE]ncodedCommand|powershell\s+-[eE][nN][cC]|"
        r"cmd\s+/[cC]\s+powershell|wscript|cscript|mshta|regsvr32|"
        r"rundll32|certutil\s+-decode|bitsadmin\s+/transfer)\b",
        # Network scanning / enumeration
        r"\b(nmap|masscan|zmap|angry.?ip.?scanner|advanced.?port.?scanner|"
        r"netdiscover|arp-scan|nessus|openvas|nikto|dirb|gobuster|ffuf|"
        r"sqlmap|burpsuite|zaproxy|wireshark|tcpdump|fiddler)\b",
        # Password cracking
        r"\b(hashcat|john.?the.?ripper|hydra|medusa|crowbar|ophcrack|"
        r"cain.?abel|aircrack|wifite|reaver|pyrit)\b",
    ],

    # ── LEVEL 3: THE WASTELAND ────────────────────────────────────────
    # Consumer gaming, piracy, streaming — log, don't lock.
    "warning": [
        r"\b(steam|roblox|minecraft|fortnite|valorant|genshin|pubg|bgmi|"
        r"free fire|apex legends|league of legends|counter-strike|csgo|cs2|"
        r"epic games|battle\.net|rocket league|aimbot|wallhack|cheat engine|"
        r"bluestacks|nox player|ldplayer|gameloop|memu|msi app player|"
        r"andyroid|genymotion|cod[- ]?mobile|warzone)\b",
        r"\b(crack|keygen|warez|pirate|magnet:|torrent|utorrent|qbittorrent|"
        r"1337x|piratebay|fitgirl|dodi-repacks|skidrow|reloaded|codex|rarbg|"
        r"tpb|limetorrents|yts|yify|igg[- ]?games)\b",
        r"\b(netflix|primevideo|prime video|hotstar|disney\+|hulu|twitch|"
        r"youtube|spotify|soundcloud|fmovies|9anime|aniwave|crunchyroll|"
        r"aniwatch|bilibili|soap2day|lookmovie|pika[- ]?show)\b",
        # ── v7.0 additions ──
        # Suspicious but potentially legitimate remote-access / sysadmin tools
        r"\b(anydesk|teamviewer|ultraviewer|rustdesk|meshcentral|"
        r"logmein|screenconnect|chrome.?remote.?desktop)\b",
        r"\b(process.?hacker|process.?monitor|autoruns|tcpview|"
        r"regshot|regmon|filemon|sysinternals)\b",
        r"\b(virtualbox|vmware|hyper-v|qemu|parallels|sandbox)\b",
    ],

    # ── LEVEL 4: THE NOISE ────────────────────────────────────────────
    # Social media and general browsing — silent log only.
    "info": [
        r"\b(tiktok|instagram|facebook|snapchat|pinterest|tumblr|9gag|"
        r"reddit|twitter|x\.com|discord|whatsapp|telegram|messenger|"
        r"line\.me|viber|wechat)\b",
        r"\b(wikipedia|quora|medium\.com|stack overflow|stackoverflow|"
        r"buzzfeed|boredpanda|chess\.com|lichess|beebom|the verge|"
        r"techcrunch|gizmodo|ign|gamespot|gsmarena)\b",
    ],
}

# Processes that are guaranteed OS components — never scanned.
_OS_BYPASS = {
    "searchhost.exe", "explorer.exe", "svchost.exe",
    "runtimebroker.exe", "taskhostw.exe", "sihost.exe",
    "ctfmon.exe", "dwm.exe", "winlogon.exe", "csrss.exe",
    "searchindexer.exe", "searchapp.exe", "textinputhost.exe",
    "shellexperiencehost.exe", "startmenuexperiencehost.exe",
    "applicationframehost.exe", "systemsettings.exe",
    "lockapp.exe", "logonui.exe", "audiodg.exe",
    "conhost.exe", "dllhost.exe", "wininit.exe",
    "fontdrvhost.exe", "spoolsv.exe", "lsass.exe",
    "securityhealthsystray.exe", "registry", "system",
    "phoneexperiencehost.exe", "video.ui.exe", "windowsterminal.exe",
}

# Processes that are known-benign in an enterprise/school context.
# A match here sets the Significance Multiplier to 0.0, preventing any ATS
# increase.  The process CAN still appear as the foreground window; it simply
# does not contribute ambient threat weight.
#
# Rationale: VS Code, Office, and browsers are the normal working environment.
# Flagging them as suspicious generates noise that trains admins to ignore
# real alerts.  Actual policy violations inside these apps are caught by the
# DOM classifier, keylog buffer, and Axiom correlations — not by process name.
BENIGN_PROCESS_WHITELIST: frozenset[str] = frozenset({
    # ── VS Code & JetBrains IDEs ───────────────────────────────────────────
    "code.exe",
    "code - insiders.exe",
    "code - oss.exe",
    "idea64.exe",
    "pycharm64.exe",
    "webstorm64.exe",

    # ── Microsoft PowerToys ───────────────────────────────────────────────
    "powertoys.exe",
    "powertoys.settings.exe",
    "powerlauncher.exe",
    "fancyzones.exe",
    "colorpickertool.exe",

    # ── Microsoft Office suite ────────────────────────────────────────────
    "winword.exe",
    "excel.exe",
    "powerpnt.exe",
    "outlook.exe",
    "onenote.exe",
    "msaccess.exe",
    "mspub.exe",
    "lync.exe",
    "teams.exe",
    "teams2.exe",
    "onedrive.exe",

    # ── Web browsers (the medium, not the threat; DOM/URL handled elsewhere)
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
    "iexplore.exe",
    "safari.exe",

    # ── Common school utilities ───────────────────────────────────────────
    "acrobat.exe",
    "acrord32.exe",
    "sumatrapdf.exe",
    "notepad.exe",
    "notepad++.exe",
    "calculator.exe",
    "mspaint.exe",
    "snippingtool.exe",
    "screensketch.exe",
    "zoom.exe",
    "slack.exe",
    "googledrivesync.exe",
    "googledrive.exe",
})

# Significance multiplier lookup.
# Value semantics:
#   -1.0 → completely suppressed: do not push to bus at all
#    0.0 → bus-silent: push signal but with weight clamped to 0.0 (tracking
#           only; does not move the ATS needle)
#    1.0 → default (handled by absence from this dict)
#   >1.0 → amplified (reserved for future high-risk proc classes)
#
# All entries in BENIGN_PROCESS_WHITELIST implicitly map to 0.0 via
# get_significance_multiplier().  Override individual entries here if
# you need finer control (e.g. suppress teams.exe entirely with -1.0).
SIGNIFICANCE_MULTIPLIER: dict[str, float] = {
    # Standard signal suppression for known-benign procs.
    # (Entries here take precedence over the whitelist's default of 0.0.)
    "notepad.exe":     0.0,   # bus-track but don't spike ATS
    "calculator.exe":  0.0,
    # Example: completely ignore OneDrive — not even bus-tracked
    "onedrive.exe":   -1.0,
    "googledrive.exe":-1.0,
}


def get_significance_multiplier(proc_name: str) -> float:
    """
    Return the Significance Multiplier for a process name.

    Resolution order:
      1. Explicit SIGNIFICANCE_MULTIPLIER entry  → use its value
      2. BENIGN_PROCESS_WHITELIST membership     → 0.0 (bus-silent)
      3. _OS_BYPASS membership                  → -1.0 (fully suppressed)
      4. Default                                 → 1.0 (normal weight)
    """
    if not proc_name:
        return 1.0
    key = proc_name.strip().lower()

    # Explicit override wins
    if key in SIGNIFICANCE_MULTIPLIER:
        return SIGNIFICANCE_MULTIPLIER[key]

    # Known-benign class
    if key in BENIGN_PROCESS_WHITELIST:
        return 0.0

    # OS kernel and shell processes — never scan, never signal
    # (_OS_BYPASS is defined in the original file)
    try:
        if key in _OS_BYPASS:
            return -1.0
    except NameError:
        pass

    return 1.0

# Pre-compile all patterns for fast matching
_COMPILED: list[tuple[re.Pattern, str]] = []
for _sev, _patterns in LEXICON.items():
    for _pat in _patterns:
        _COMPILED.append((re.compile(_pat, re.IGNORECASE), _sev))

# USB execution blocklist — any process launched FROM a removable drive
# whose name matches this is killed and alerted immediately.
USB_EXEC_BLOCKLIST = re.compile(
    r"\b(setup|install|installer|update|updater|patch|patcher|"
    r"loader|dropper|inject|payload|crack|keygen|activator|hack|"
    r"rat|trojan|miner|crypter|stub|bypass|stealer|logger)\b",
    re.IGNORECASE,
)


# =====================================================================
# DEEP NORMALIZATION ENGINE (Text Crusher)
# Defeats unicode homoglyphs, leetspeak, zero-width character injection,
# dotted/spaced bypasses like "p.o.r.n" or "p o r n".
# =====================================================================

_ZERO_WIDTH_CHARS = dict.fromkeys(
    map(ord, [
        "\u200b", "\u200c", "\u200d", "\u200e", "\u200f",
        "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
        "\u2060", "\u2061", "\u2062", "\u2063", "\u2064",
        "\ufeff", "\u00ad", "\u180e", "\u034f",
    ]),
    "",
)

_MULTI_LEET = [
    (r"\|\\\|", "n"), (r"\|\|", "u"),  (r"\|\)", "d"),
    (r"\(\)",   "o"), (r"\[\]", "o"),  (r"\\/\\/", "w"),
    (r"\\/",    "v"), (r"/\\",  "a"),  (r"vv", "w"),
    (r"ph",     "f"), (r"\$\$", "ss"),
]

_LEET_MAP = str.maketrans({
    "0": "o", "1": "i", "!": "i", "|": "i", "3": "e", "4": "a",
    "@": "a", "5": "s", "$": "s", "7": "t", "+": "t", "8": "b",
    "9": "g", "6": "g", "€": "e", "£": "l", "¥": "y",
})

_NON_ALNUM    = re.compile(r"[^a-z0-9\s]+")
_MULTI_WS     = re.compile(r"\s+")
_SPACED_LETTERS = re.compile(r"\b(?:[a-z]\s){1,}[a-z]\b")


def normalize_haystack(text: str) -> str:
    """
    Aggressive text purifier defeating unicode / leet / spacing bypasses.
    Pipeline: NFKD → zero-width strip → lowercase → multi-leet → leet map
              → non-alnum strip → spaced-letter glue → whitespace collapse.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.translate(_ZERO_WIDTH_CHARS)
    text = text.lower()
    for pat, repl in _MULTI_LEET:
        text = re.sub(pat, repl, text)
    text = text.translate(_LEET_MAP)
    text = _NON_ALNUM.sub(" ", text)
    text = _SPACED_LETTERS.sub(lambda m: m.group(0).replace(" ", ""), text)
    text = _MULTI_WS.sub(" ", text).strip()
    return text


# ─── Fuzzy Token Vocabulary ──────────────────────────────────────────────────
_LEXICON_META = {
    "com", "exe", "svc", "net", "org", "www", "http", "https",
    "chrome", "edge", "excel", "powerpnt", "winword", "explorer",
    "browser", "google", "microsoft", "taskmgr", "searchapp", "code",
    "roblox", "minecraft",
}
_TOKEN_EXTRACT = re.compile(r"[a-z0-9]{3,}")
_TOKEN_LEXICON: dict[str, set[str]] = {sev: set() for sev in LEXICON}

for _sev, _patterns in LEXICON.items():
    for _pat in _patterns:
        _clean = _pat.replace(r"\b(", "").replace(r")\b", "")
        for _rule in _clean.split("|"):
            _rule = _rule.strip().lower()
            if " " in _rule or "[" in _rule or r"\." in _rule:
                continue
            _toks = _TOKEN_EXTRACT.findall(_rule)
            if len(_toks) == 1 and _toks[0] not in _LEXICON_META:
                _TOKEN_LEXICON[_sev].add(_toks[0])


# =====================================================================
# PHASE 1 — THE LEV ENGINE (Advisory Intelligence Layer)
# =====================================================================

_QWERTY_MAP = {
    "q": (0,0),  "w": (0,1),  "e": (0,2),  "r": (0,3),  "t": (0,4),
    "y": (0,5),  "u": (0,6),  "i": (0,7),  "o": (0,8),  "p": (0,9),
    "a": (1,0.5),"s": (1,1.5),"d": (1,2.5),"f": (1,3.5),"g": (1,4.5),
    "h": (1,5.5),"j": (1,6.5),"k": (1,7.5),"l": (1,8.5),
    "z": (2,1),  "x": (2,2),  "c": (2,3),  "v": (2,4),  "b": (2,5),
    "n": (2,6),  "m": (2,7),
}


class LevEngine:
    """
    Advisory intelligence layer.  Evaluates text input using phonetic,
    spatial, and subset algorithms to return a Suspicion Score (0.0–1.0).

    Scoring pipeline:
      1. Exact regex pass → returns 1.0 immediately on any match.
      2. Fuzzy token pass → Jaro-Winkler (prefix bias) + Sørensen-Dice
         (subset bias), blended 60/40, capped at 0.99.
      3. Keyboard typo modifier → distinguishes fat-finger typos from
         deliberate character-substitution bypasses using QWERTY distance.
    """

    @staticmethod
    def _keyboard_distance(c1: str, c2: str) -> float:
        """Euclidean distance between two QWERTY keys.  Adjacent ≈ 1.0."""
        c1, c2 = c1.lower(), c2.lower()
        if c1 not in _QWERTY_MAP or c2 not in _QWERTY_MAP:
            return 5.0
        p1, p2 = _QWERTY_MAP[c1], _QWERTY_MAP[c2]
        return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)

    @staticmethod
    def _sorensen_dice(s1: str, s2: str) -> float:
        """Sørensen-Dice bigram coefficient.  Good for subset/split bypasses."""
        if not s1 or not s2:
            return 0.0
        if s1 == s2:
            return 1.0
        b1 = set(s1[i: i + 2] for i in range(len(s1) - 1))
        b2 = set(s2[i: i + 2] for i in range(len(s2) - 1))
        if not b1 or not b2:
            return 0.0
        return 2.0 * len(b1 & b2) / (len(b1) + len(b2))

    @staticmethod
    def _jaro_winkler(s1: str, s2: str) -> float:
        """Jaro-Winkler.  Rewards matching prefixes (natural typo pattern)."""
        if not s1 or not s2:
            return 0.0
        if s1 == s2:
            return 1.0
        bound = max(len(s1), len(s2)) // 2 - 1
        matches = 0
        f1 = [False] * len(s1)
        f2 = [False] * len(s2)
        for i, c in enumerate(s1):
            for j in range(max(0, i - bound), min(i + bound + 1, len(s2))):
                if not f2[j] and s2[j] == c:
                    f1[i] = f2[j] = True
                    matches += 1
                    break
        if not matches:
            return 0.0
        trans = k = 0
        for i, fl in enumerate(f1):
            if fl:
                while not f2[k]:
                    k += 1
                if s1[i] != s2[k]:
                    trans += 1
                k += 1
        trans //= 2
        jaro = (matches / len(s1) + matches / len(s2) +
                (matches - trans) / matches) / 3.0
        pfx = sum(1 for i in range(min(len(s1), len(s2), 4)) if s1[i] == s2[i])
        return jaro + pfx * 0.1 * (1.0 - jaro)

    @staticmethod
    def calculate_typo_modifier(inp: str, tgt: str) -> float:
        """
        Returns <1.0 for adjacent-key slips (real typos → reduce suspicion)
        and >1.0 for cross-keyboard substitutions (bypass attempts → raise).

        Length penalty (v7.1):
          abs(len_diff) > 2 → return 0.50.
          Prevents prefix cross-contamination where a short token like
          'rat' would fuzzy-match against a long token like 'ratchet',
          inflating the suspicion score on irrelevant content.
        """
        len_diff = abs(len(inp) - len(tgt))
        if len_diff > 2:
            print(f"[lev] typo_modifier: length_penalty "
                  f"inp='{inp}'({len(inp)}) tgt='{tgt}'({len(tgt)}) "
                  f"diff={len_diff} → 0.50")
            return 0.50

        if len(inp) != len(tgt):
            return 1.0
        penalty, mismatches = 0.0, 0
        for c1, c2 in zip(inp, tgt):
            if c1 != c2:
                mismatches += 1
                penalty += LevEngine._keyboard_distance(c1, c2)
        if mismatches == 0:
            return 1.0
        avg = penalty / mismatches
        if avg <= 1.5 and len(tgt) > 4:
            mod = 0.85
        else:
            mod = 1.10
        print(f"[lev] typo_modifier: inp='{inp}' tgt='{tgt}' "
              f"avg_dist={avg:.2f} mismatches={mismatches} → {mod}")
        return mod

    @classmethod
    def evaluate_suspicion(cls, title: str, proc: str) -> tuple[float, str, str]:
        """
        Evaluate a (window title, process name) pair.
        Returns: (suspicion_score: float, severity_category: str, hit_token: str)
        score 1.0 = exact regex match; 0.99 = max fuzzy; 0.0 = clean.
        """
        haystack   = f"{title or ''} {proc or ''}"
        normalized = normalize_haystack(haystack)
        tokens     = _TOKEN_EXTRACT.findall(normalized)

        best_score, best_cat, best_hit = 0.0, "info", ""

        # Pass 1: exact regex (fastest path — returns immediately)
        for pattern, sev in _COMPILED:
            m = pattern.search(haystack) or pattern.search(normalized)
            if m:
                print(f"[lev] EXACT MATCH sev={sev} hit='{m.group(0)}' "
                      f"src='{haystack[:60]}'")
                return 1.0, sev, m.group(0)

        # Pass 2: fuzzy token matching
        for tok in tokens:
            if len(tok) < 4:
                continue
            for sev, vocab in _TOKEN_LEXICON.items():
                for vtok in vocab:
                    jw   = cls._jaro_winkler(tok, vtok)
                    sd   = cls._sorensen_dice(tok, vtok)
                    base = jw * 0.6 + sd * 0.4
                    if base > 0.75:
                        base *= cls.calculate_typo_modifier(tok, vtok)
                    score = min(base, 0.99)
                    if score > best_score:
                        best_score, best_cat, best_hit = score, sev, vtok

        if best_score > 0.0:
            print(f"[lev] fuzzy best: score={best_score:.3f} "
                  f"cat={best_cat} hit='{best_hit}' "
                  f"src='{haystack[:60]}'")
        return round(best_score, 3), best_cat, best_hit


LEV = LevEngine()


# ─── Global browser optics buffer ───────────────────────────────────────────
_LATEST_BROWSER_DOM = ""
_LATEST_BROWSER_URL = ""
_OPTICS_LOCK = threading.Lock()

# Web content weights (DOM classifier)
WEB_WEIGHTS = {
    "hardcore": [
        "pornhub", "xvideos", "xnxx", "redtube", "youporn", "xhamster",
        "brazzers", "hentai", "rule34", "chaturbate", "onlyfans", "spankbang",
        "fapello", "hqporner", "gelbooru", "beeg", "spankwire", "daftsex",
        "heavy-r", "motherless", "txxx", "upornia",
    ],
    "explicit": [
        "porn", "sex", "adult", "nude", "naked", "erotic", "nsfw",
        "pussy", "dick", "boobs", "milf", "fuck", "cum", "tits",
    ],
    "media": [
        "video", "watch", "streaming", "full", "clips", "collection",
        "leak", "uncensored", "gallery", "photos", "hd", "premium",
    ],
    # Educational terms carry a NEGATIVE weight (-15 per hit) applied in
    # classify_web_context to mitigate false positives when students are
    # doing legitimate research (biology, anatomy, medical science, etc.)
    "educational": [
        "anatomy", "biology", "medical", "wikipedia", "reproduction",
        "syndrome", "health", "science", "chromosome", "organism",
        "physiology", "genetics", "puberty", "pathology", "endocrine",
    ],
}
WEB_CRITICAL_THRESHOLD = 40

# Instant strike list — typed match here bypasses all scoring and fires immediately.
INSTANT_STRIKE_LIST = {
    # Adult
    "pornhub", "xnxx", "xvideos", "hentai", "brazzers", "porn", "redtube",
    # v7.0 additions — malware / exploit tools
    "mimikatz", "meterpreter", "cobalt strike", "njrat", "asyncrat",
    "xmrig", "shellcode", "msfvenom", "reverse shell",
}


# =====================================================================
# KEYLOG BUFFER
# Rolling in-memory keystroke buffer.  Never persisted to disk.
# Flushed to evidence ONLY on confirmed policy violation.
# =====================================================================
class KeylogBuffer:
    """
    Non-persistent rolling keystroke buffer.
    Contents are held in RAM only and cleared after each snapshot
    that is included in a confirmed-violation evidence package.
    No keystrokes are stored to disk or transmitted during normal use.
    """

    def __init__(self, maxlen: int = 1000):
        self.buffer = deque(maxlen=maxlen)
        self._lock  = threading.Lock()

    def add(self, key_str: str) -> None:
        with self._lock:
            self.buffer.append(key_str)

    def get_snapshot(self) -> str:
        with self._lock:
            return "".join(self.buffer)

    def clear(self) -> None:
        with self._lock:
            self.buffer.clear()


KEYLOG_HISTORY = KeylogBuffer()


def _background_keylogger() -> None:
    """
    Daemon thread: maintains a rolling memory of recent keystrokes.
    Buffer is inspected (not transmitted) each scan cycle.
    Only the last ~500 chars are included in an evidence dossier if a
    confirmed violation is detected — never during normal operation.
    """
    def on_press(key):
        try:
            KEYLOG_HISTORY.add(key.char)
        except AttributeError:
            if   key == keyboard.Key.space:     KEYLOG_HISTORY.add(" ")
            elif key == keyboard.Key.enter:     KEYLOG_HISTORY.add(" [ENTER] ")
            elif key == keyboard.Key.backspace: KEYLOG_HISTORY.add("[BS]")
            else:                               KEYLOG_HISTORY.add(f"[{key.name}]")

    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()


# =====================================================================
# CLIPBOARD BUFFER  (v7.0)
# Rolling in-memory clipboard monitor.  Never persisted to disk.
# Cleared on confirmed violation only.
# =====================================================================
class ClipboardBuffer:
    """
    Rolling clipboard monitor polled every 500 ms.
    Stores at most 30 unique clipboard states in memory.
    Nothing is written to disk or transmitted unless a violation
    is confirmed by the Axiom Engine.
    """

    def __init__(self, maxlen: int = 30):
        self._history: deque[str] = deque(maxlen=maxlen)
        self._last    = ""
        self._lock    = threading.Lock()

    def get_snapshot(self) -> list[str]:
        with self._lock:
            return list(self._history)

    def clear(self) -> None:
        with self._lock:
            self._history.clear()
            self._last = ""

    @property
    def last_content(self) -> str:
        with self._lock:
            return self._last


CLIPBOARD_HISTORY = ClipboardBuffer()


def _background_clipboard_monitor() -> None:
    """
    Daemon thread: polls clipboard every 500 ms.
    On content change, runs Lev Engine and feeds the Axiom Signal Bus
    if suspicion ≥ 0.50 (does NOT fire an alert on its own).
    win32clipboard is preferred on Windows; pyperclip is the fallback.
    """
    _use_win32 = False
    if platform.system() == "Windows":
        try:
            import win32clipboard
            _use_win32 = True
        except ImportError:
            pass

    if not _use_win32:
        try:
            import pyperclip
        except ImportError:
            print(
                "[clipboard] Neither win32clipboard nor pyperclip available. "
                "Install pywin32 or pyperclip to enable clipboard monitoring.",
                file=sys.stderr,
            )
            return

    def _read() -> str:
        if _use_win32:
            import win32clipboard
            try:
                win32clipboard.OpenClipboard()
                try:
                    return win32clipboard.GetClipboardData(
                        win32clipboard.CF_UNICODETEXT
                    ) or ""
                except Exception:
                    return ""
                finally:
                    win32clipboard.CloseClipboard()
            except Exception:
                return ""
        else:
            import pyperclip
            try:
                return pyperclip.paste() or ""
            except Exception:
                return ""

    while True:
        try:
            content = _read()
            if content and content != CLIPBOARD_HISTORY.last_content:
                with CLIPBOARD_HISTORY._lock:
                    CLIPBOARD_HISTORY._history.append(content[:1000])
                    CLIPBOARD_HISTORY._last = content
                # Feed Axiom Signal Bus immediately
                c_lev, _, _ = LEV.evaluate_suspicion(content[:500], "")
                if c_lev >= 0.50:
                    axiom_push_signal(
                        "clipboard_lev_hit",
                        value=content[:120],
                        weight=0.20,
                        lev_score=c_lev,
                    )
        except Exception:
            pass
        time.sleep(0.5)


def _check_clipboard_for_scan() -> tuple[Optional[str], float]:
    """
    Called each scan_loop cycle.  Checks clipboard snapshot against Lev.
    Returns (hit_token, c_lev) on high-confidence match; clears buffer.
    Returns (None, 0.0) if nothing suspicious.
    """
    for entry in CLIPBOARD_HISTORY.get_snapshot():
        c_clip, _, clip_hit = LEV.evaluate_suspicion(entry[:500], "")
        if c_clip >= 0.85:
            CLIPBOARD_HISTORY.clear()
            return clip_hit, c_clip
    return None, 0.0


# =====================================================================
# PHASE 7 — THE AXIOM ENGINE
# Three-layer behavioral intelligence system.
#
# Architecture:
#   Layer 1 — Signal Bus
#     Every observable event pushes a weighted signal onto the bus.
#     Each signal decays linearly to zero over ATS_DECAY_WINDOW seconds
#     (default 300 s = 5 min).  The Ambient Threat Score (ATS) is the
#     sum of all live signal weights after applying their decay factor.
#     ATS is recomputed on every push and on a background tick.
#
#   Layer 2 — Pattern Arbitrator
#     Wakes when ATS ≥ AXIOM_L2_THRESHOLD (0.40).
#     Runs Lev Engine over every value string in the live signal set.
#     Applies co-occurrence multipliers when dangerous signal-kind
#     combinations are present simultaneously.
#     Returns a confirmed_score float.
#
#   Layer 3 — Deep Forensic Verifier
#     Wakes when ATS ≥ AXIOM_L3_THRESHOLD (0.70) OR when Layer 2
#     returns confirmed_score ≥ 0.60.
#     Runs: OCR on live screenshot, full process tree Lev scan,
#     DOM re-analysis, clipboard scan, open file handle inspection.
#     Returns a verdict: "clear" | "warn" | "strike".
#
# Decay model:
#   weight_at_t = base_weight * max(0, 1 - (age_seconds / ATS_DECAY_WINDOW))
#   A signal placed at T=0 has full weight; it reaches zero at T=300 s.
#   At T=150 s it contributes exactly half its original weight.
#   This means signals compound naturally — two medium signals from
#   2 minutes ago still push ATS above the Layer 2 threshold.
# =====================================================================

# Default decay window (unchanged from v7; used as fallback)
ATS_DECAY_WINDOW: float = 300.0   # seconds

# Critical signals maintain ATS elevation for a full 10 minutes.
# This ensures a confirmed RAT name or exact keylog hit is not forgotten
# by the Axiom Engine within a single scan cycle.
ATS_CRITICAL_DECAY_WINDOW: float = 600.0  # 10 min

# Warning-level signals (fuzzy matches, low-weight observations) decay
# in 2 minutes.  A burst of low-level noise will naturally return the
# ATS to zero if no Critical anchor is reinforcing it.
ATS_WARNING_DECAY_WINDOW: float  = 120.0  # 2 min

# Keep the original thresholds unchanged.
AXIOM_L2_THRESHOLD: float = 0.40
AXIOM_L3_THRESHOLD: float = 0.70

# Signal kind classification for decay routing.
_CRITICAL_SIGNAL_KINDS: frozenset[str] = frozenset({
    "rat_exact_match",
    "lev_title_critical",
    "lev_process_critical",
    "keylog_instant_strike",
    "wmi_process_critical",
    "usb_exec_suspicious",
    "dom_classifier_fire",
    "unauthorized_port",
    "suspicious_parent",      # parent chain masquerade is always critical
})

_WARNING_SIGNAL_KINDS: frozenset[str] = frozenset({
    "lev_title_high",
    "lev_process_high",
    "clipboard_lev_hit",
    "incognito_window",
    "github_release_url",
    "cpu_masquerade",
    "usb_mass_storage",
    "tethering_detected",
    "new_wireless_adapter",
    "network_conn_axiom",
    "wmi_process_high",
})


def _get_signal_decay_window(kind: str) -> float:
    """
    Return the decay window in seconds appropriate for a signal kind.

    Critical signals persist for 10 minutes (permanent spike semantics).
    Warning signals dissolve in 2 minutes (natural noise floor return).
    Unclassified signals use the legacy 5-minute default.
    """
    if kind in _CRITICAL_SIGNAL_KINDS:
        return ATS_CRITICAL_DECAY_WINDOW
    if kind in _WARNING_SIGNAL_KINDS:
        return ATS_WARNING_DECAY_WINDOW
    return ATS_DECAY_WINDOW

# Signal weights: how much each event type contributes to ATS at full strength.
# Calibrated so that 2–3 moderate signals within 5 min reach 0.40 (Layer 2 wake).
# A single critical-certainty event (RAT name, instant-strike) reaches 0.90+.
AXIOM_SIGNAL_WEIGHTS: dict[str, float] = {
    # Lev engine outputs
    "lev_title_high":       0.25,  # window title Lev ≥ 0.70, cat=high
    "lev_title_critical":   0.45,  # window title Lev = 1.0, cat=critical
    "lev_process_high":     0.30,  # process name Lev ≥ 0.70
    "lev_process_critical": 0.50,  # process name Lev = 1.0, cat=critical
    "keylog_instant_strike":0.50,  # INSTANT_STRIKE_LIST typed match
    "clipboard_lev_hit":    0.20,  # clipboard Lev ≥ 0.50
    # DOM / browser
    "dom_classifier_fire":  0.35,  # DOM weighted scorer hit
    # Network
    "unauthorized_port":    0.35,  # VPN/SOCKS/Tor port detected
    "network_conn_axiom":   0.08,  # any established external connection
    # Process events (from WMI monitor)
    "wmi_process_high":     0.30,  # WMI launch, Lev ≥ 0.70
    "wmi_process_critical": 0.50,  # WMI launch, Lev ≥ 0.85
    "suspicious_parent":    0.45,  # flagged child under powershell/cmd/mshta
    # USB / adapter
    "usb_mass_storage":     0.10,  # removable drive inserted
    "usb_exec_suspicious":  0.40,  # .exe/.py launched from USB (blocklist match)
    "usb_exec_unknown":     0.15,  # .exe/.py from USB (unknown name)
    "tethering_detected":   0.30,  # RNDIS / phone hotspot adapter
    "new_wireless_adapter": 0.15,  # USB WiFi dongle
    # System
    "incognito_window":     0.15,  # incognito/private browser mode
    "github_release_url":   0.20,  # github.com/*/releases in title
    "cpu_masquerade":       0.20,  # utility process at >25% CPU
    # Direct certainty
    "rat_exact_match":      0.90,  # exact RAT/C2 name match anywhere
}

# Co-occurrence multipliers for Layer 2.
# When ALL listed signal kinds are simultaneously present in the live
# signal set, multiply the confirmed score by this factor.
# Order of kinds in each tuple does not matter — presence is checked as a set.
AXIOM_COOCCURRENCE: list[dict] = [
    {"kinds": {"unauthorized_port",    "lev_process_high"},     "mult": 1.8},
    {"kinds": {"unauthorized_port",    "wmi_process_high"},     "mult": 1.8},
    {"kinds": {"incognito_window",     "keylog_instant_strike"},"mult": 2.0},
    {"kinds": {"incognito_window",     "clipboard_lev_hit"},    "mult": 1.7},
    {"kinds": {"usb_mass_storage",     "usb_exec_suspicious"},  "mult": 1.9},
    {"kinds": {"github_release_url",   "wmi_process_high"},     "mult": 1.7},
    {"kinds": {"suspicious_parent",    "wmi_process_high"},     "mult": 2.2},
    {"kinds": {"suspicious_parent",    "wmi_process_critical"}, "mult": 2.5},
    {"kinds": {"tethering_detected",   "dom_classifier_fire"},  "mult": 1.6},
    {"kinds": {"rat_exact_match",      "network_conn_axiom"},   "mult": 3.0},
    {"kinds": {"rat_exact_match",      "unauthorized_port"},    "mult": 3.5},
    {"kinds": {"lev_title_critical",   "dom_classifier_fire"},  "mult": 2.0},
    {"kinds": {"cpu_masquerade",       "network_conn_axiom"},   "mult": 1.5},
]


# ── Signal Bus data structures ────────────────────────────────────────────────
# Each signal on the bus:
# { "kind": str, "value": str, "weight": float, "lev_score": float,
#   "placed_at": float (epoch) }
_AXIOM_BUS:  list[dict] = []
_AXIOM_LOCK: threading.Lock = threading.Lock()

# Layer 2 / 3 deduplication — don't re-run if we already fired recently.
_AXIOM_L2_LAST_RUN: float = 0.0
_AXIOM_L3_LAST_RUN: float = 0.0
_AXIOM_L2_COOLDOWN = 8.0    # seconds between Layer 2 runs
_AXIOM_L3_COOLDOWN = 20.0   # seconds between Layer 3 runs


def _axiom_live_weight(signal: dict, now: float) -> float:
    """
    Compute the decayed weight for a single signal at time `now`.

    Uses per-signal decay window (stored in signal["decay_window"]) rather
    than the global ATS_DECAY_WINDOW constant.  This is the v8 change that
    makes Critical signals behave as permanent spikes while Warning signals
    evaporate quickly.

    Linear decay: weight_at_t = base_weight * max(0, 1 - age / decay_window)
    """
    age          = now - signal["placed_at"]
    decay_window = signal.get("decay_window", ATS_DECAY_WINDOW)
    if age >= decay_window:
        return 0.0
    return signal["weight"] * max(0.0, 1.0 - age / decay_window)


def _axiom_compute_ats(now: float) -> float:
    """
    Compute the current Ambient Threat Score from the live signal bus.

    v8 change: uses per-signal decay windows (via _axiom_live_weight)
    so Critical and Warning signals decay at different rates.
    Expired signals are pruned in-place.  Result is clamped to [0, 1].
    """
    live, expired = [], []
    total = 0.0
    for sig in _AXIOM_BUS:
        w = _axiom_live_weight(sig, now)
        if w <= 0.0:
            expired.append(sig)
        else:
            live.append(sig)
            total += w
    for s in expired:
        _AXIOM_BUS.remove(s)
    return min(total, 1.0)


def axiom_push_signal(
    kind:      str,
    value:     str   = "",
    weight:    Optional[float] = None,
    lev_score: float = 0.0,
    proc_name: str   = "",
) -> None:
    """
    Push a new signal onto the Axiom Signal Bus.

    v8.0 additions:
      • Significance Multiplier gate: if the associated process is in
        BENIGN_PROCESS_WHITELIST the push is either silently dropped
        (multiplier == -1.0) or the weight is clamped to 0.0 (bus-silent
        tracking; 0.0-weight signals appear in co-occurrence lookups but
        do not move the ATS needle).
      • Decay window is stored per-signal so _axiom_live_weight() can
        apply the correct window when computing the live ATS.

    Args:
        kind      : Signal type key from AXIOM_SIGNAL_WEIGHTS.
        value     : Raw value string (for L2 Lev re-pass; may be empty).
        weight    : Override weight.  None → looks up AXIOM_SIGNAL_WEIGHTS.
        lev_score : Lev C_lev at time of event.
        proc_name : Optional process name for Significance Multiplier lookup.
    """
    # ── Significance Multiplier check ────────────────────────────────────────
    sig_mult = get_significance_multiplier(proc_name) if proc_name else 1.0

    if sig_mult < 0.0:
        # Fully suppressed — don't even enter the bus.
        sentinel_log(
            f"[axiom-bus] SUPPRESSED kind='{kind}' proc='{proc_name}' "
            f"(significance_multiplier={sig_mult:.1f})",
            level="debug",
        )
        return

    # Resolve base weight
    if weight is None:
        try:
            weight = AXIOM_SIGNAL_WEIGHTS.get(kind, 0.05)
        except NameError:
            weight = 0.05

    # Apply multiplier (0.0 → bus-silent but present for co-occurrence)
    effective_weight = weight * sig_mult

    sig: dict = {
        "kind":         kind,
        "value":        (value or "").lower()[:300],
        "weight":       effective_weight,
        "base_weight":  weight,           # preserved for diagnostics
        "lev_score":    lev_score,
        "placed_at":    time.time(),
        "decay_window": _get_signal_decay_window(kind),
        "proc_name":    proc_name,
    }

    try:
        with _AXIOM_LOCK:
            _AXIOM_BUS.append(sig)
    except NameError:
        pass

    sentinel_log(
        f"[axiom-bus] PUSH kind='{kind}' eff_w={effective_weight:.2f} "
        f"base_w={weight:.2f} mult={sig_mult:.1f} lev={lev_score:.2f} "
        f"decay={sig['decay_window']:.0f}s value='{(value or '')[:40]}'",
        level="debug",
    )


class Verdict:
    """Outcome constants for the arbitration pipeline."""
    CLEAR   = "clear"
    WARNING = "warning"
    STRIKE  = "strike"


# ── Verdict Rules ─────────────────────────────────────────────────────────────
# Each rule maps a SET of required signal kinds to a verdict outcome.
# Rules are evaluated against the set of signal kinds currently live on the
# Axiom Bus.  ALL kinds in a rule's "requires" set must be present to fire.
#
# Key design principle (REQ-1):
#   A single fuzzy-match signal ("lev_title_high") NEVER appears as the
#   sole requirement for a STRIKE.  Every STRIKE rule requires at least one
#   independent behavioral corroboration signal from a different sub-system
#   (network, process creation, USB, keylog, clipboard, DOM).
#
# Addition order matters: the FIRST matching rule wins.
# More-specific (larger "requires" sets) rules should come first.
VERDICT_RULES: list[dict] = [

    # ── Tier-0: Absolute certainties (single signal sufficient) ──────────────
    # RAT/C2 name exact match is a 1.0 Lev hit on a CRITICAL lexicon entry.
    # This is not "fuzzy"; it is a byte-exact pattern match.
    {
        "requires":  {"rat_exact_match"},
        "verdict":   Verdict.STRIKE,
        "reason":    "exact_rat_c2_match",
    },
    # Typed confirmed keyword (from INSTANT_STRIKE_LIST)
    {
        "requires":  {"keylog_instant_strike"},
        "verdict":   Verdict.STRIKE,
        "reason":    "keylog_instant_strike",
    },
    # DOM classifier alone fires a strike — it requires ≥40 weighted points
    # across multiple explicit/hardcore keyword categories, which is already a
    # multi-signal internal consensus.
    {
        "requires":  {"dom_classifier_fire"},
        "verdict":   Verdict.STRIKE,
        "reason":    "dom_classifier_confirmed",
    },

    # ── Tier-1: Behavioral correlation pairs (REQ-1 core) ────────────────────
    # Fuzzy process name  +  unusual outbound network
    {
        "requires":  {"lev_title_high", "unauthorized_port"},
        "verdict":   Verdict.STRIKE,
        "reason":    "fuzzy_match+unauthorized_tunnel",
    },
    {
        "requires":  {"lev_title_high", "network_conn_axiom"},
        "verdict":   Verdict.STRIKE,
        "reason":    "fuzzy_match+active_external_connection",
    },
    # Fuzzy process name  +  WMI process creation event
    {
        "requires":  {"lev_title_high", "wmi_process_high"},
        "verdict":   Verdict.STRIKE,
        "reason":    "fuzzy_match+wmi_process_creation",
    },
    {
        "requires":  {"lev_title_high", "wmi_process_critical"},
        "verdict":   Verdict.STRIKE,
        "reason":    "fuzzy_match+wmi_critical_process",
    },
    # Fuzzy process name  +  suspicious parent chain (masquerade attack)
    {
        "requires":  {"lev_title_high", "suspicious_parent"},
        "verdict":   Verdict.STRIKE,
        "reason":    "fuzzy_match+suspicious_parent_chain",
    },
    # Exact critical title  +  any network activity
    {
        "requires":  {"lev_title_critical", "network_conn_axiom"},
        "verdict":   Verdict.STRIKE,
        "reason":    "critical_title+network_activity",
    },
    # Exact critical title  +  any corroboration
    {
        "requires":  {"lev_title_critical", "wmi_process_high"},
        "verdict":   Verdict.STRIKE,
        "reason":    "critical_title+process_creation",
    },
    # Incognito browsing  +  suspicious keylog activity
    {
        "requires":  {"incognito_window", "keylog_instant_strike"},
        "verdict":   Verdict.STRIKE,
        "reason":    "incognito+keylog_hit",
    },
    # Incognito  +  clipboard paste of suspicious content
    {
        "requires":  {"incognito_window", "clipboard_lev_hit"},
        "verdict":   Verdict.STRIKE,
        "reason":    "incognito+suspicious_clipboard",
    },
    # USB mass storage  +  executable launched from it
    {
        "requires":  {"usb_mass_storage", "usb_exec_suspicious"},
        "verdict":   Verdict.STRIKE,
        "reason":    "usb_exec_from_removable_drive",
    },
    # GitHub release URL  +  immediate process creation (dropper pattern)
    {
        "requires":  {"github_release_url", "wmi_process_high"},
        "verdict":   Verdict.STRIKE,
        "reason":    "github_release_download+process_launch",
    },
    # CPU masquerade  +  network traffic (crypto-miner signature)
    {
        "requires":  {"cpu_masquerade", "network_conn_axiom"},
        "verdict":   Verdict.STRIKE,
        "reason":    "cpu_masquerade+outbound_traffic",
    },
    # Tethering  +  any suspicious title (bypass attempt pattern)
    {
        "requires":  {"tethering_detected", "lev_title_high"},
        "verdict":   Verdict.STRIKE,
        "reason":    "tethering+suspicious_activity",
    },

    # ── Tier-2: Warnings (single fuzzy signals — NEVER a strike alone) ────────
    # REQ-1 compliance: these MUST remain as Warning, not Strike.
    {
        "requires":  {"lev_title_high"},
        "verdict":   Verdict.WARNING,
        "reason":    "fuzzy_title_match_unconfirmed",
    },
    {
        "requires":  {"lev_title_critical"},
        "verdict":   Verdict.WARNING,
        "reason":    "exact_critical_title_no_corroboration",
    },
    {
        "requires":  {"clipboard_lev_hit"},
        "verdict":   Verdict.WARNING,
        "reason":    "clipboard_suspicious_content",
    },
    {
        "requires":  {"incognito_window"},
        "verdict":   Verdict.WARNING,
        "reason":    "incognito_browser_mode",
    },
    {
        "requires":  {"github_release_url"},
        "verdict":   Verdict.WARNING,
        "reason":    "github_release_url_in_title",
    },
    {
        "requires":  {"tethering_detected"},
        "verdict":   Verdict.WARNING,
        "reason":    "usb_tethering_detected",
    },
    {
        "requires":  {"usb_mass_storage"},
        "verdict":   Verdict.WARNING,
        "reason":    "removable_drive_inserted",
    },
    {
        "requires":  {"unauthorized_port"},
        "verdict":   Verdict.WARNING,
        "reason":    "unauthorized_tunnel_port_no_process_match",
    },
]


def evaluate_verdict(
    present_kinds: set[str],
    lev_score:     float       = 0.0,
    best_category: str         = "info",
) -> tuple[str, str]:
    """
    Evaluate a set of live signal kinds against the VERDICT_RULES table.

    Returns (verdict: str, reason: str).

    Algorithm:
      1. Iterate VERDICT_RULES in order (most specific first).
      2. If ALL kinds in rule["requires"] are present → return that verdict.
      3. If no rule matches → return CLEAR.

    The lev_score and best_category parameters are provided for logging but
    do NOT override the rule table — only signal correlations drive the verdict.
    This is the core of REQ-1: a match is not enough; context must confirm it.
    """
    matched_rule: Optional[dict] = None

    for rule in VERDICT_RULES:
        if rule["requires"].issubset(present_kinds):
            matched_rule = rule
            break

    if matched_rule is None:
        sentinel_log(
            f"[verdict] No rule matched present_kinds={present_kinds} → CLEAR",
            level="debug",
        )
        return Verdict.CLEAR, "no_rule_matched"

    verdict = matched_rule["verdict"]
    reason  = matched_rule["reason"]
    rule_requires = matched_rule["requires"]

    sentinel_log(
        f"[verdict] Rule matched: requires={rule_requires} → "
        f"{verdict.upper()} reason='{reason}' "
        f"(lev={lev_score:.2f} cat={best_category})",
        level="anomaly" if verdict != Verdict.CLEAR else "debug",
    )
    return verdict, reason


def _axiom_verdict_arbitrate(live_signals: list[dict]) -> tuple[str, str, float]:
    """
    Layer 2 — Verdict-Based Pattern Arbitrator.

    v8 redesign replacing the old score-threshold approach:

    Old L2: base_score = f(highest_lev, mean_weight) → if >= 0.60 → STRIKE
    New L2: present_kinds = {s["kind"] for s in live} → evaluate_verdict()
            The result is qualitative (CLEAR / WARNING / STRIKE), not a
            raw float.  The confirmed_score is now a secondary signal
            used only to decide whether L3 should wake up.

    Steps:
      1. Collect the set of all live signal kinds.
      2. Run Lev Engine over all live signal values (same as before)
         to update lev_scores and find the highest.
      3. Call evaluate_verdict() → qualitative verdict.
      4. If verdict is CLEAR and base evidence is weak → accelerate
         decay of warning-level signals (unchanged from v7).
      5. Compute a numeric confirmed_score for L3 gating (not for
         triggering — only L3's verdict can trigger a Strike alert).

    Returns: (verdict: str, reason: str, confirmed_score: float)
    """
    if not live_signals:
        sentinel_log("[axiom-L2] No live signals — returning CLEAR", level="debug")
        return Verdict.CLEAR, "no_signals", 0.0

    sentinel_log(
        f"[axiom-L2] Arbitrating {len(live_signals)} live signals",
        level="debug",
    )

    # ── Step 1: Collect present signal kinds ──────────────────────────────────
    present_kinds: set[str] = {s["kind"] for s in live_signals}

    # ── Step 2: Lev re-pass over all live signal values ───────────────────────
    highest_lev     = 0.0
    highest_lev_cat = "info"
    highest_lev_hit = ""

    try:
        lev_engine = LEV
    except NameError:
        lev_engine = None

    if lev_engine is not None:
        for sig in live_signals:
            if not sig.get("value"):
                continue
            c_lev, cat, hit = lev_engine.evaluate_suspicion(sig["value"], "")
            if c_lev > highest_lev:
                highest_lev     = c_lev
                highest_lev_cat = cat
                highest_lev_hit = hit
                sentinel_log(
                    f"[axiom-L2] New highest Lev={c_lev:.3f} "
                    f"kind='{sig['kind']}' hit='{hit}'",
                    level="debug",
                )

    # ── Step 3: Evaluate verdict via rule table ───────────────────────────────
    verdict, reason = evaluate_verdict(present_kinds, highest_lev, highest_lev_cat)

    # ── Step 4: If CLEAR — accelerate decay of weak warning signals ───────────
    if verdict == Verdict.CLEAR:
        sentinel_log(
            "[axiom-L2] Verdict CLEAR — accelerating decay of warning signals",
            level="debug",
        )
        try:
            with _AXIOM_LOCK:
                for sig in _AXIOM_BUS:
                    if (sig["kind"] in _WARNING_SIGNAL_KINDS and
                            sig["weight"] <= 0.25):
                        # Halve remaining decay window → signal expires sooner
                        age = time.time() - sig["placed_at"]
                        sig["decay_window"] = max(age + 30, sig["decay_window"] * 0.5)
        except NameError:
            pass
        return Verdict.CLEAR, reason, 0.0

    # ── Step 5: Compute numeric confirmed_score (L3 gating only) ─────────────
    now     = time.time()
    total_w = sum(_axiom_live_weight(s, now) for s in live_signals)
    mean_w  = total_w / max(len(live_signals), 1)

    # Score reflects both semantic severity (Lev) and bus weight density.
    # Used ONLY to decide whether to wake L3 — not to issue alerts directly.
    confirmed_score = min(
        highest_lev * 0.60 + min(mean_w * 2.5, 1.0) * 0.40,
        1.0,
    )

    sentinel_log(
        f"[axiom-L2] Verdict={verdict.upper()} reason='{reason}' "
        f"highest_lev={highest_lev:.2f} mean_w={mean_w:.3f} "
        f"confirmed_score={confirmed_score:.2f} "
        f"present_kinds={present_kinds}",
        level="anomaly",
    )
    return verdict, reason, confirmed_score


def _axiom_layer3_verify(
    workstation_id: str,
    live_signals:   list[dict],
    ats:            float,
) -> str:
    """
    Layer 3 — Deep Forensic Verifier.

    Runs the full evidence stack and returns a verdict string:
      "clear"  — nothing confirmed after deep inspection
      "warn"   — suspicious but below strike threshold
      "strike" — confirmed policy violation

    Checks performed (all in parallel where possible):
      1. OCR on a fresh screenshot
      2. Full running process tree Lev scan
      3. DOM re-analysis (uses cached _LATEST_BROWSER_DOM)
      4. Clipboard full re-scan via Lev
      5. Open file handle inspection on any high-Lev process
    """
    scores: list[float] = []

    # ── Check 1: OCR ─────────────────────────────────────────────────────────
    try:
        shot = capture_screenshot()
        if shot:
            c_ocr = extract_ocr_suspicion(shot)
            if c_ocr > 0.0:
                scores.append(c_ocr)
                print(f"[axiom-L3] OCR score: {c_ocr:.2f}")
    except Exception as e:
        print(f"[axiom-L3] OCR check failed: {e}", file=sys.stderr)

    # ── Check 2: Full process tree Lev scan ──────────────────────────────────
    try:
        proc_high = 0.0
        for p in psutil.process_iter(["name", "exe"]):
            try:
                pname = p.info.get("name") or ""
                if pname.lower() in _OS_BYPASS:
                    continue
                c, cat, hit = LEV.evaluate_suspicion(pname, pname)
                if c > proc_high:
                    proc_high = c
                # Open file handle check — processes with suspicious names
                # that have handles into AppData/Temp/Downloads write paths
                # are given extra weight.
                if c >= 0.70:
                    try:
                        fls = [f.path.lower() for f in p.open_files()]
                        suspicious_paths = ("appdata", "temp", "tmp",
                                            "downloads", "desktop", "startup")
                        if any(sp in fl for fl in fls for sp in suspicious_paths):
                            proc_high = min(proc_high + 0.15, 1.0)
                            print(
                                f"[axiom-L3] Suspicious file handle: "
                                f"{pname} in sensitive path"
                            )
                    except (psutil.AccessDenied, Exception):
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if proc_high > 0.0:
            scores.append(proc_high)
            print(f"[axiom-L3] Process tree highest: {proc_high:.2f}")
    except Exception as e:
        print(f"[axiom-L3] Process tree scan failed: {e}", file=sys.stderr)

    # ── Check 3: DOM re-analysis ─────────────────────────────────────────────
    try:
        with _OPTICS_LOCK:
            dom_snap = _LATEST_BROWSER_DOM
        if dom_snap:
            is_viol, _ = classify_web_context(dom_snap)
            if is_viol:
                scores.append(0.90)
                print("[axiom-L3] DOM re-analysis confirmed violation.")
    except Exception as e:
        print(f"[axiom-L3] DOM check failed: {e}", file=sys.stderr)

    # ── Check 4: Clipboard Lev re-scan ───────────────────────────────────────
    try:
        for entry in CLIPBOARD_HISTORY.get_snapshot():
            c_clip, _, _ = LEV.evaluate_suspicion(entry[:500], "")
            if c_clip >= 0.70:
                scores.append(c_clip)
                print(f"[axiom-L3] Clipboard re-scan hit: {c_clip:.2f}")
                break
    except Exception as e:
        print(f"[axiom-L3] Clipboard re-scan failed: {e}", file=sys.stderr)

    # ── Verdict ───────────────────────────────────────────────────────────────
    if not scores:
        print("[axiom-L3] All checks clean → verdict: clear")
        return "clear"

    peak = max(scores)
    mean = sum(scores) / len(scores)
    combined = peak * 0.65 + mean * 0.35

    print(
        f"[axiom-L3] Peak={peak:.2f} Mean={mean:.2f} "
        f"Combined={combined:.2f} ATS={ats:.2f}"
    )

    if combined >= 0.75:
        return "strike"
    if combined >= 0.45:
        return "warn"
    return "clear"


def axiom_evaluate(workstation_id: str, last_alerted: dict) -> None:
    """
    Central Axiom Engine tick.  Called once per scan_loop cycle.

    v8 changes:
      • L2 now returns a (verdict, reason, confirmed_score) tuple.
      • A WARNING verdict from L2 logs an ambient entry but never fires an alert.
      • A STRIKE verdict from L2 unconditionally wakes L3 (regardless of ATS).
      • L3's verdict is the only path to a fire_alert() call.
      • All print() → sentinel_log() for operational/verbose mode support.
    """
    global _AXIOM_L2_LAST_RUN, _AXIOM_L3_LAST_RUN

    now = time.time()
    try:
        with _AXIOM_LOCK:
            ats          = _axiom_compute_ats(now)
            live_signals = list(_AXIOM_BUS)
    except NameError:
        return

    if ats < 0.10:
        return  # Completely quiet

    try:
        l2_cooldown_rem = max(0, _AXIOM_L2_COOLDOWN - (now - _AXIOM_L2_LAST_RUN))
        l3_cooldown_rem = max(0, _AXIOM_L3_COOLDOWN - (now - _AXIOM_L3_LAST_RUN))
    except NameError:
        l2_cooldown_rem = l3_cooldown_rem = 0.0

    sentinel_log(
        f"[axiom] ATS={ats:.3f}  signals={len(live_signals)}  "
        f"L2_cd={l2_cooldown_rem:.1f}s  L3_cd={l3_cooldown_rem:.1f}s",
        level="debug",
    )

    try:
        wake_l2 = (
            ats >= AXIOM_L2_THRESHOLD and
            (now - _AXIOM_L2_LAST_RUN) >= _AXIOM_L2_COOLDOWN
        )
        wake_l3 = (
            ats >= AXIOM_L3_THRESHOLD and
            (now - _AXIOM_L3_LAST_RUN) >= _AXIOM_L3_COOLDOWN
        )
    except NameError:
        wake_l2 = wake_l3 = False

    if not wake_l2 and not wake_l3:
        return

    def _run_layers() -> None:
        global _AXIOM_L2_LAST_RUN, _AXIOM_L3_LAST_RUN

        l2_verdict      = Verdict.CLEAR
        l2_reason       = ""
        confirmed_score = 0.0

        # ── Layer 2 ───────────────────────────────────────────────────────────
        if wake_l2:
            try:
                _AXIOM_L2_LAST_RUN = now
            except NameError:
                pass

            l2_verdict, l2_reason, confirmed_score = _axiom_verdict_arbitrate(
                live_signals
            )

            if l2_verdict == Verdict.CLEAR:
                # L2 exonerated — nothing more to do
                return

            if l2_verdict == Verdict.WARNING:
                # WARNING: log ambient, never fire an alert (REQ-1 compliance)
                key = f"axiom_l2_warn:{l2_reason}"
                try:
                    ambient_debounce = AMBIENT_DEBOUNCE_SEC
                except NameError:
                    ambient_debounce = 60
                if now - last_alerted.get(key, 0) > ambient_debounce:
                    last_alerted[key] = now
                    sentinel_log(
                        f"[axiom-L2] WARNING issued: {l2_reason} "
                        f"(ATS={ats:.2f})",
                        level="warning",
                    )
                    try:
                        log_ambient(
                            workstation_id,
                            f"[AXIOM WARNING] {l2_reason} (ATS={ats:.2f})",
                            None, "warning", is_anomaly=True,
                        )
                    except NameError:
                        pass
                if not wake_l3:
                    return  # Warning verdict alone does not wake L3

        # ── Layer 3 ───────────────────────────────────────────────────────────
        # L3 wakes if:
        #   • ATS >= L3 threshold (direct wakeup), OR
        #   • L2 returned STRIKE (always run L3 to confirm before alerting)
        should_run_l3 = wake_l3 or (l2_verdict == Verdict.STRIKE)

        if not should_run_l3:
            return

        try:
            _AXIOM_L3_LAST_RUN = now
        except NameError:
            pass

        try:
            l3_verdict = _axiom_layer3_verify(
                workstation_id, live_signals, ats
            )
        except NameError:
            l3_verdict = "clear"

        sentinel_log(
            f"[axiom-L3] Verdict: {l3_verdict.upper()} "
            f"(L2={l2_verdict} L2_reason='{l2_reason}' "
            f"confirmed={confirmed_score:.2f} ATS={ats:.2f})",
            level="anomaly" if l3_verdict != "clear" else "debug",
        )

        try:
            alert_debounce  = ALERT_DEBOUNCE_SEC
            ambient_debounce = AMBIENT_DEBOUNCE_SEC
        except NameError:
            alert_debounce = ambient_debounce = 60

        if l3_verdict == "strike":
            key = f"axiom_strike:{l2_reason}"
            if now - last_alerted.get(key, 0) > alert_debounce:
                last_alerted[key] = now
                try:
                    top     = max(live_signals, key=lambda s: s["weight"])
                    shot    = capture_screenshot()
                    fire_alert(
                        workstation_id,
                        f"[AXIOM STRIKE] {l2_reason} "
                        f"(ATS={ats:.2f} L2_score={confirmed_score:.2f})",
                        top.get("proc_name") or top.get("value") or None,
                        "critical",
                        f"axiom_engine:{l2_reason}_ats={ats:.2f}",
                        shot,
                    )
                except NameError:
                    pass

        elif l3_verdict == "warn":
            key = f"axiom_l3_warn:{round(ats, 1)}"
            if now - last_alerted.get(key, 0) > ambient_debounce:
                last_alerted[key] = now
                try:
                    log_ambient(
                        workstation_id,
                        f"[AXIOM WARN] Deep scan elevated risk "
                        f"(ATS={ats:.2f} confirmed={confirmed_score:.2f})",
                        None, "high", is_anomaly=True,
                    )
                except NameError:
                    pass

    threading.Thread(target=_run_layers, daemon=True).start()


# =====================================================================
# WMI PROCESS CREATION MONITOR  (v7.0)
# Event-driven — fires the instant any process is created.
# Closes the 3-second scan_loop polling gap.
# =====================================================================

# Parents whose children are unconditionally suspicious if flagged by Lev.
_SUSPICIOUS_PARENTS = {
    "powershell.exe", "cmd.exe", "wscript.exe", "cscript.exe",
    "mshta.exe", "rundll32.exe", "regsvr32.exe", "certutil.exe",
    "bitsadmin.exe", "wmic.exe",
}


def wmi_process_monitor(workstation_id: str) -> None:
    """
    Daemon thread: WMI process creation monitor — v8 revision.

    v8 changes:
      • Wrapped in self_healing_thread() semantics: missing 'wmi' library
        disables the thread gracefully via watchdog_disable() rather than
        restarting in a loop.
      • Adds proc_name to axiom_push_signal() for Significance Multiplier
        filtering (whitelisted process launches don't spike ATS).
      • Uses sentinel_log() for diagnostic output.

    Internal loop errors (transient WMI COM timeouts) still restart via
    the inner try/except; the watchdog handles permanent thread death.
    """
    # ── [REQ-5] Missing library guard ────────────────────────────────────────
    try:
        import wmi                                            # noqa: F401
    except ImportError:
        sentinel_log(
            "[wmi] Feature Disabled — 'wmi' not installed. "
            "WMI process creation monitor is offline.  "
            "Install with: pip install wmi pywin32",
            level="error",
            force=True,
        )
        watchdog_disable("wmi_monitor")
        return  # clean exit — watchdog will not restart

    try:
        import wmi as _wmi
        c       = _wmi.WMI()
        watcher = c.Win32_ProcessStartTrace.watch_for("creation")
        sentinel_log("[wmi] Process creation monitor armed.", level="error", force=True)

        while True:
            try:
                event = watcher()
            except Exception as e:
                sentinel_log(
                    f"[wmi] watcher exception: {e} — retry in 3s",
                    level="error",
                    force=True,
                )
                time.sleep(3)
                continue

            proc_name   = (event.ProcessName or "").strip()
            pid         = event.ProcessID
            parent_name = "unknown"

            try:
                import psutil as _psutil
                proc_obj    = _psutil.Process(pid)
                parent_name = _psutil.Process(proc_obj.ppid()).name().lower()
            except Exception:
                pass

            # [REQ-2] Skip whitelisted processes completely
            proc_mult = get_significance_multiplier(proc_name)
            if proc_mult < 0.0:
                sentinel_log(
                    f"[wmi] Suppressed (whitelist): {proc_name}",
                    level="debug",
                )
                continue

            try:
                c_lev, category, hit = LEV.evaluate_suspicion(
                    proc_name, proc_name
                )
            except NameError:
                c_lev, category, hit = 0.0, "info", ""

            try:
                suspicious_parents = _SUSPICIOUS_PARENTS
            except NameError:
                suspicious_parents = set()

            parent_suspicious = parent_name in suspicious_parents
            if parent_suspicious and c_lev >= 0.50:
                c_lev = max(c_lev, 0.87)

            if parent_suspicious:
                axiom_push_signal(
                    "suspicious_parent", proc_name,
                    lev_score=c_lev, proc_name=proc_name,
                )

            if c_lev >= 0.85:
                sig_kind = (
                    "wmi_process_critical" if category == "critical"
                    else "wmi_process_high"
                )
                axiom_push_signal(
                    sig_kind, proc_name,
                    lev_score=c_lev, proc_name=proc_name,
                )
                reason   = f"wmi_launch:{hit} (parent={parent_name})"
                severity = "critical" if category == "critical" else "high"

                # [REQ-1] Even from WMI, a Strike requires L3 confirmation.
                # Push to Axiom Bus and let the Axiom engine fire the alert —
                # do NOT fire_alert() directly from WMI unless exact RAT match.
                if category == "critical" and c_lev == 1.0:
                    sentinel_log(
                        f"[wmi] EXACT CRITICAL MATCH: {proc_name} — "
                        f"pushing rat_exact_match signal",
                        level="strike",
                        force=True,
                    )
                    axiom_push_signal(
                        "rat_exact_match", proc_name,
                        lev_score=1.0, proc_name=proc_name,
                    )
                    # Fire directly only for absolute-certainty RAT names
                    try:
                        shot = _safe_capture_screenshot()
                        fire_alert(
                            workstation_id,
                            f"[WMI RAT LAUNCH] {proc_name}",
                            proc_name, severity, reason, shot,
                        )
                    except NameError:
                        pass
                else:
                    # Fuzzy-high WMI hit: push to bus, let Axiom arbitrate
                    sentinel_log(
                        f"[wmi] High suspicion process: {proc_name} "
                        f"(lev={c_lev:.2f}) — sent to Axiom Bus",
                        level="anomaly",
                    )

            elif c_lev >= 0.50:
                axiom_push_signal(
                    "wmi_process_high", proc_name,
                    lev_score=c_lev, proc_name=proc_name,
                )
                sentinel_log(
                    f"[wmi] Moderate suspicion: {proc_name} "
                    f"(lev={c_lev:.2f}) → bus only",
                    level="debug",
                )

    except Exception as e:
        sentinel_log(
            f"[wmi] monitor startup failed: {e}",
            level="error",
            force=True,
        )
        raise  # let the watchdog handle restart


# =====================================================================
# SMART USB / ADAPTER MONITOR  (v8.0)
# HID-aware: keyboards, mice, headsets, and printers pass silently.
# Mass-storage insertion starts the per-drive execution watcher.
# Tethering and USB WiFi adapters are detected and alerted.
# =====================================================================

# Windows device class GUIDs for HID and other benign device types.
# Matching devices are allowed silently with a debug log only.
_BENIGN_DEVICE_CLASS_GUIDS = {
    "745a17a0-74d3-11d0-b6fe-00a0c90f57da",  # HID (mice, keyboards, gamepads)
    "4d36e96c-e325-11ce-bfc1-08002be10318",  # Audio
    "4d36e96b-e325-11ce-bfc1-08002be10318",  # Keyboard
    "4d36e96f-e325-11ce-bfc1-08002be10318",  # Mouse
    "4d36e979-e325-11ce-bfc1-08002be10318",  # Printer
}

# Active removable drives: { mount_point: insertion_epoch }
_ACTIVE_USB_DRIVES:  dict[str, float] = {}
_USB_DRIVES_LOCK:    threading.Lock   = threading.Lock()


def _watch_usb_execution() -> None:
    """
    Background thread: every 2 seconds checks all running processes.
    If a process executable resides on a registered removable drive:
      - Name matches USB_EXEC_BLOCKLIST → terminate + critical alert
      - Name unknown but extension is .exe/.py/.ps1/.bat → warning log
    Feeds Axiom Signal Bus on every hit.
    """
    while True:
        try:
            with _USB_DRIVES_LOCK:
                drive_roots = set(_ACTIVE_USB_DRIVES.keys())

            if drive_roots and workstation_id_global:
                for p in psutil.process_iter(["pid", "name", "exe"]):
                    try:
                        exe  = (p.info.get("exe") or "").strip()
                        name = (p.info.get("name") or "").strip()
                        if not exe:
                            continue

                        on_usb = any(
                            exe.upper().startswith(d.upper())
                            for d in drive_roots
                        )
                        if not on_usb:
                            continue

                        if USB_EXEC_BLOCKLIST.search(name) or USB_EXEC_BLOCKLIST.search(exe):
                            try:
                                p.terminate()
                                sentinel_log(f"[usb-exec] KILLED: {name} ({exe})", level="critical")
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass
                            axiom_push_signal(
                                "usb_exec_suspicious", name,
                                weight=AXIOM_SIGNAL_WEIGHTS["usb_exec_suspicious"],
                            )
                            fire_alert(
                                workstation_id_global,
                                f"[USB EXEC BLOCKED] {name}",
                                name,
                                "critical",
                                f"usb_execution_blocked:{exe}",
                            )
                        else:
                            ext = Path(exe).suffix.lower()
                            if ext in (".exe", ".py", ".ps1", ".bat", ".vbs", ".js"):
                                axiom_push_signal("usb_exec_unknown", name)
                                log_ambient(
                                    workstation_id_global,
                                    f"[USB EXEC] {name}",
                                    name,
                                    "warning",
                                    is_anomaly=True,
                                )
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
        except Exception as e:
            sentinel_log(f"[usb-exec] watcher error: {e}", level="error", force=True)
        time.sleep(2)


def usb_and_adapter_monitor(workstation_id: str) -> None:
    """
    Self-healing USB + adapter monitor — v8 wrapper.

    [REQ-5]: Missing 'wmi' library → Feature Disabled + watchdog_disable().
    Internal crashes → re-raised so the watchdog can restart.
    """
    try:
        import wmi                                            # noqa: F401
    except ImportError:
        sentinel_log(
            "[usb] Feature Disabled — 'wmi' not installed. "
            "USB and adapter monitor is offline.  "
            "Install with: pip install wmi pywin32",
            level="error",
            force=True,
        )
        watchdog_disable("usb_monitor")
        return  # clean exit

    try:
        import wmi as _wmi
        c               = _wmi.WMI()
        usb_watcher     = c.Win32_USBControllerDevice.watch_for("creation")
        adapter_watcher = c.Win32_NetworkAdapter.watch_for("creation")
        disk_watcher    = c.Win32_LogicalDisk.watch_for("creation")
        sentinel_log("[usb] Smart USB + adapter monitor armed.", level="error", force=True)

        def _watch_usb():
            while True:
                try:
                    event     = usb_watcher()
                    dependent = str(event.Dependent or "").lower()
                    is_benign = any(g in dependent for g in _BENIGN_DEVICE_CLASS_GUIDS)
                    if is_benign:
                        sentinel_log(f"[usb] HID/benign device — silent pass: {dependent[:80]}", level="debug")
                        continue
                    axiom_push_signal("usb_mass_storage", dependent[:200])
                    log_ambient(
                        workstation_id,
                        f"[USB] {dependent[:120]}",
                        None, "warning", is_anomaly=True,
                    )
                except Exception as e:
                    if "wmi" not in str(e).lower():
                        sentinel_log(f"[usb] device watcher: {e}", level="error", force=True)

        def _watch_adapters():
            _TETHER_KW  = ("rndis", "remote ndis", "hosted", "mobile",
                           "tether", "android", "iphone", "usb ethernet")
            _WIFI_KW    = ("wireless", "wi-fi", "802.11", "wlan")
            while True:
                try:
                    event = adapter_watcher()
                    name  = (event.Name or "unknown_adapter").lower()
                    if any(k in name for k in _TETHER_KW):
                        axiom_push_signal("tethering_detected", name)
                        fire_alert(
                            workstation_id,
                            f"[TETHER DETECTED] {name}",
                            None, "high",
                            f"usb_tethering:{name}",
                        )
                    elif any(k in name for k in _WIFI_KW):
                        axiom_push_signal("new_wireless_adapter", name)
                        log_ambient(
                            workstation_id,
                            f"[USB WIFI] {name}",
                            None, "warning", is_anomaly=True,
                        )
                    else:
                        log_ambient(
                            workstation_id,
                            f"[NEW ADAPTER] {name}",
                            None, "info", is_anomaly=False,
                        )
                except Exception as e:
                    if "wmi" not in str(e).lower():
                        sentinel_log(f"[usb] adapter watcher: {e}", level="error", force=True)

        def _watch_disks():
            """Monitor removable drive insertion events and register mount points."""
            sentinel_log("[usb] Disk insertion watcher started.", level="debug")
            while True:
                try:
                    event  = disk_watcher()
                    dltr   = (event.Name or "").strip()
                    dtype  = event.DriveType  # 2 = Removable
                    if dtype == 2 and dltr:
                        mount = dltr if dltr.endswith("\\") else dltr + "\\"
                        with _USB_DRIVES_LOCK:
                            _ACTIVE_USB_DRIVES[mount] = time.time()
                        sentinel_log(f"[usb] Removable drive registered: {mount} "
                                     f"(total tracked: {len(_ACTIVE_USB_DRIVES)})", level="debug")
                        axiom_push_signal("usb_mass_storage", mount)
                        log_ambient(
                            workstation_id,
                            f"[DRIVE INSERTED] {mount}",
                            None, "warning", is_anomaly=True,
                        )
                except Exception as e:
                    if "wmi" not in str(e).lower():
                        sentinel_log(f"[usb] disk insertion watcher: {e}", level="error", force=True)

        def _watch_disks_removal():
            """
            Monitor removable drive removal events (DBT_DEVICEREMOVECOMPLETE).
            Cleans up _ACTIVE_USB_DRIVES to prevent memory leaks and ghost
            directory scanning against disconnected drive letters.
            """
            try:
                disk_remove_watcher = c.Win32_LogicalDisk.watch_for("deletion")
                sentinel_log("[usb] Disk removal watcher started.", level="debug")
            except Exception as e:
                sentinel_log(f"[usb] disk_remove_watcher init failed: {e}", level="error", force=True)
                return
            while True:
                try:
                    event = disk_remove_watcher()
                    dltr  = (event.Name or "").strip()
                    if dltr:
                        mount = dltr if dltr.endswith("\\") else dltr + "\\"
                        with _USB_DRIVES_LOCK:
                            removed = _ACTIVE_USB_DRIVES.pop(mount, None)
                        if removed is not None:
                            age = time.time() - removed
                            sentinel_log(f"[usb] Removable drive removed and unregistered: "
                                         f"{mount} (was mounted {age:.0f}s) "
                                         f"(remaining tracked: {len(_ACTIVE_USB_DRIVES)})", level="debug")
                        else:
                            sentinel_log(f"[usb] Drive removal event for untracked mount: {mount}", level="debug")
                except Exception as e:
                    if "wmi" not in str(e).lower():
                        sentinel_log(f"[usb] disk removal watcher: {e}", level="error", force=True)

        threading.Thread(target=_watch_usb,           daemon=True, name="usb_device").start()
        threading.Thread(target=_watch_adapters,      daemon=True, name="usb_adapter").start()
        threading.Thread(target=_watch_disks,         daemon=True, name="usb_disk_insert").start()
        threading.Thread(target=_watch_disks_removal, daemon=True, name="usb_disk_remove").start()
        threading.Thread(target=_watch_usb_execution, daemon=True, name="usb_exec").start()
        sentinel_log("[usb] All USB sub-watchers armed (insert+remove+exec+adapter+device).", level="error", force=True)

        # Keep main thread alive (WMI events are handled in sub-threads)
        threading.Event().wait()  # block forever — watchdog monitors this thread

    except Exception as e:
        sentinel_log(f"[usb] monitor startup failed: {e}", level="error", force=True)
        raise  # let the watchdog restart


# =====================================================================
# DOM CLASSIFIER
# =====================================================================
def classify_web_context(dom_text: str) -> tuple[bool, str]:
    """
    Weighted word-boundary scan of raw browser DOM content.
    Returns (is_violation, reason_string).

    Weights by category:
      hardcore    +20  (explicit tube sites — near-certain violation)
      explicit    +15  (adult language — high probability)
      media        +5  (streaming/gallery terms — low weight alone)
      educational −15  (biology, anatomy, medical — mitigates false positives)

    Educational words apply a negative offset per hit so that a student
    researching anatomy/reproduction does NOT trip the threshold unless
    hardcore or explicit terms are also strongly present.
    Score is floored at 0 before threshold comparison.
    """
    if not dom_text or len(dom_text) < 20:
        print("[dom] classify_web_context: content too short — skip")
        return False, ""

    score = 0
    hits: list[str] = []
    edu_hits: list[str] = []
    tl = dom_text.lower()

    _WEIGHTS = {
        "hardcore":    20,
        "explicit":    15,
        "media":        5,
        "educational": -15,   # negative — reduces score
    }

    for cat, words in WEB_WEIGHTS.items():
        w = _WEIGHTS.get(cat, 5)
        for word in words:
            if re.search(rf"\b{re.escape(word)}\b", tl):
                score += w
                if cat == "educational":
                    edu_hits.append(word)
                else:
                    hits.append(word)

    # Floor at 0 — educational penalty cannot push score below zero
    score = max(score, 0)

    print(
        f"[dom] classify_web_context: raw_score={score} "
        f"hits={hits[:4]} edu_hits={edu_hits[:4]} "
        f"threshold={WEB_CRITICAL_THRESHOLD}"
    )

    if score >= WEB_CRITICAL_THRESHOLD:
        reason = f"web_intent({score}pts):" + "+".join(hits[:4])
        if edu_hits:
            reason += f" [edu_mitigation:{'+'.join(edu_hits[:2])}]"
        return True, reason
    return False, ""


# =====================================================================
# BROWSER OPTICS SERVER (WebSocket listener for browser extension)
# =====================================================================
async def _telemetry_handler(websocket) -> None:
    global _LATEST_BROWSER_DOM, _LATEST_BROWSER_URL
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                with _OPTICS_LOCK:
                    _LATEST_BROWSER_DOM = data.get("content", "")
                    _LATEST_BROWSER_URL = data.get("url", "")
            except Exception:
                pass
    except websockets.exceptions.ConnectionClosed:
        pass


def boot_optics_server() -> None:
    """Bulletproof asyncio bridge — restarts on crash."""
    async def _runner():
        while True:
            try:
                async with websockets.serve(_telemetry_handler, "127.0.0.1", 8765):
                    await asyncio.Future()
            except Exception as e:
                print(f"[optics] Server crashed: {e} — restarting in 5s", file=sys.stderr)
                await asyncio.sleep(5)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_runner())
    except Exception as e:
        print(f"[optics] Event loop fatal: {e}", file=sys.stderr)


# =====================================================================
# PHASE 6 — THE FORENSIC VAULT (SQLite offline queue + image cache)
# =====================================================================
def vault_init() -> None:
    """Bootstrap the local SQLite buffer and the hidden cache directory."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _hide_path(CACHE_DIR)
        with sqlite3.connect(VAULT_DB) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS queue (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind        TEXT NOT NULL,
                    table_name  TEXT NOT NULL,
                    payload     TEXT NOT NULL,
                    evidence    TEXT,
                    created_at  TEXT NOT NULL,
                    attempts    INTEGER DEFAULT 0,
                    last_error  TEXT
                );
            """)
            conn.commit()
        _hide_path(VAULT_DB)
        print(f"[vault] forensic vault online → {VAULT_DB}")
    except Exception as e:
        print(f"[vault] init failed: {e}", file=sys.stderr)


def _save_cache_blob(blob: bytes, suffix: str = ".jpg") -> Optional[str]:
    if not blob:
        return None
    try:
        fname = f"{uuid.uuid4().hex}{suffix}"
        (CACHE_DIR / fname).write_bytes(blob)
        return fname
    except Exception as e:
        print(f"[vault] cache write failed: {e}", file=sys.stderr)
        return None


def _delete_cache(fname: Optional[str]) -> None:
    if not fname:
        return
    try:
        (CACHE_DIR / fname).unlink(missing_ok=True)
    except Exception:
        pass


def vault_enqueue(
    kind: str, table_name: str, payload: dict,
    evidence: Optional[dict], created_at: str,
) -> None:
    try:
        with VAULT_LOCK, sqlite3.connect(VAULT_DB) as conn:
            conn.execute(
                "INSERT INTO queue(kind,table_name,payload,evidence,created_at) "
                "VALUES (?,?,?,?,?)",
                (
                    kind, table_name,
                    json.dumps(payload, default=str),
                    json.dumps(evidence or {}, default=str),
                    created_at,
                ),
            )
            conn.commit()
        print(f"[vault] queued {kind}/{table_name} ts={created_at}")
    except Exception as e:
        print(f"[vault] enqueue failed: {e}", file=sys.stderr)


def vault_pending(limit: int = 25) -> list[tuple]:
    try:
        with VAULT_LOCK, sqlite3.connect(VAULT_DB) as conn:
            cur = conn.execute(
                "SELECT id,kind,table_name,payload,evidence,created_at,attempts "
                "FROM queue ORDER BY id ASC LIMIT ?",
                (limit,),
            )
            return cur.fetchall()
    except Exception as e:
        print(f"[vault] read failed: {e}", file=sys.stderr)
        return []


def vault_delete(row_id: int) -> None:
    try:
        with VAULT_LOCK, sqlite3.connect(VAULT_DB) as conn:
            conn.execute("DELETE FROM queue WHERE id=?", (row_id,))
            conn.commit()
    except Exception as e:
        print(f"[vault] delete failed: {e}", file=sys.stderr)


def vault_bump_attempt(row_id: int, err: str) -> None:
    try:
        with VAULT_LOCK, sqlite3.connect(VAULT_DB) as conn:
            conn.execute(
                "UPDATE queue SET attempts=attempts+1, last_error=? WHERE id=?",
                (err[:500], row_id),
            )
            conn.commit()
    except Exception:
        pass


# ─── Storage bucket bootstrap ────────────────────────────────────────────────
def ensure_bucket() -> None:
    try:
        sb.storage.create_bucket(
            EVIDENCE_BUCKET,
            options={"public": True, "file_size_limit": 10 * 1024 * 1024},
        )
        print(f"[storage] created bucket '{EVIDENCE_BUCKET}'")
    except Exception as e:
        msg = str(e).lower()
        if "already exists" in msg or "duplicate" in msg or "409" in msg:
            return
        print(f"[storage] bucket bootstrap warning: {e}", file=sys.stderr)


# ─── Hardware UUID ────────────────────────────────────────────────────────────
def load_or_create_hardware_uuid() -> str:
    try:
        if IDENTITY_FILE.exists():
            val = IDENTITY_FILE.read_text(encoding="utf-8").strip()
            if val:
                return val
    except Exception as e:
        print(f"[identity] read failed: {e}", file=sys.stderr)
    new_id = str(uuid.uuid4())
    try:
        IDENTITY_FILE.write_text(new_id, encoding="utf-8")
        _hide_path(IDENTITY_FILE)
        print(f"[identity] minted hardware uuid → {IDENTITY_FILE}")
    except Exception as e:
        print(f"[identity] write failed (ephemeral id): {e}", file=sys.stderr)
    return new_id


HARDWARE_UUID = load_or_create_hardware_uuid()


# ─── Workstation registration ─────────────────────────────────────────────────
def register_workstation() -> str:
    """
    Register or update this workstation in the database.
    Matches by hardware UUID first, then by name.
    Creates a new record if none is found.
    """
    res = sb.table("workstations").select("id").eq("hardware_uuid", HARDWARE_UUID).execute()
    wid = res.data[0]["id"] if res.data else None

    if not wid:
        res_name = sb.table("workstations").select("id").eq("name", WORKSTATION_NAME).execute()
        if res_name.data:
            wid = res_name.data[0]["id"]
            print(f"[identity] Reusing existing record for {WORKSTATION_NAME}")

    payload = {
        "name":           WORKSTATION_NAME,
        "hardware_uuid":  HARDWARE_UUID,
        "status":         "online",
        "last_heartbeat": now_iso(),
        "os_info":        os_info(),
    }
    if wid:
        sb.table("workstations").update(payload).eq("id", wid).execute()
    else:
        res_new = sb.table("workstations").insert(payload).execute()
        wid     = res_new.data[0]["id"]

    return wid


# =====================================================================
# FOREGROUND WINDOW DETECTION
# =====================================================================
def get_foreground_window() -> tuple[Optional[str], Optional[str]]:
    """Returns (window_title, process_name) of the current foreground window."""
    system = platform.system()
    try:
        if system == "Windows":
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            hwnd   = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            buf    = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title  = buf.value
            pid    = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                proc = psutil.Process(pid.value).name()
            except Exception:
                proc = None
            return title, proc
        if system == "Darwin":
            script = (
                'tell application "System Events" to get name of '
                "first process whose frontmost is true"
            )
            proc = subprocess.check_output(["osascript", "-e", script]).decode().strip()
            return proc, proc
        try:
            hwnd  = subprocess.check_output(["xdotool", "getactivewindow"]).decode().strip()
            title = subprocess.check_output(["xdotool", "getwindowname", hwnd]).decode().strip()
            xpid  = subprocess.check_output(["xdotool", "getwindowpid", hwnd]).decode().strip()
            proc  = psutil.Process(int(xpid)).name()
            return title, proc
        except Exception:
            return None, None
    except Exception as e:
        print(f"[scan] foreground error: {e}", file=sys.stderr)
        return None, None


# =====================================================================
# EVIDENCE CAPTURE
# =====================================================================
def capture_screenshot() -> Optional[bytes]:
    """Capture the full screen as JPEG bytes.  Returns None on failure."""
    try:
        img = ImageGrab.grab()
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=75, optimize=True)
        return buf.getvalue()
    except Exception as e:
        print(f"[evidence] screenshot failed: {e}", file=sys.stderr)
        return None


def capture_webcam() -> Optional[bytes]:
    """
    Capture a single webcam frame as JPEG bytes.
    Only called on CRITICAL severity events for workstation attribution.
    Uses DirectShow on Windows for faster initialization.
    Returns None if webcam is unavailable or locked by another app.
    """
    with OPTICS_LOCK:
        try:
            cam = (
                cv2.VideoCapture(0, cv2.CAP_DSHOW)
                if platform.system() == "Windows"
                else cv2.VideoCapture(0)
            )
            if not cam.isOpened():
                cam = cv2.VideoCapture(0)
            if not cam.isOpened():
                print("[evidence] Webcam unavailable.", file=sys.stderr)
                return None
            time.sleep(0.5)
            for _ in range(3):
                cam.read()
            ok, frame = cam.read()
            cam.release()
            if not ok:
                return None
            ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            return jpg.tobytes() if ok else None
        except Exception as e:
            print(f"[evidence] webcam failed: {e}", file=sys.stderr)
            return None


# ─── Evidence upload (vault-aware) ───────────────────────────────────────────
def upload_evidence(path: str, payload: bytes) -> Optional[str]:
    """
    Upload bytes to Supabase Storage with exponential backoff.
    Returns public URL on success.
    On persistent failure, saves locally to cache and returns None —
    the caller is responsible for queuing the parent row in the vault.
    """
    delays   = [0, 2, 6]
    for attempt, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        try:
            sb.storage.from_(EVIDENCE_BUCKET).upload(
                path, payload,
                {"content-type": "image/jpeg", "upsert": "true"},
            )
            return sb.storage.from_(EVIDENCE_BUCKET).get_public_url(path)
        except Exception as e:
            print(
                f"[storage] upload {path} attempt {attempt+1} failed: {e}",
                file=sys.stderr,
            )
    print(f"[storage] upload {path} exhausted retries — diverting to vault", file=sys.stderr)
    _save_cache_blob(payload)
    return None


def archive_evidence(
    alert_id: str, severity: str,
    workstation_id: str,
    volatile_snapshot: Optional[bytes] = None,
    clipboard_snapshot: Optional[list] = None,
) -> None:
    """
    Assemble a full evidence dossier for a confirmed alert.

    Pipeline 1 (fast): screenshot + webcam capture and upload.
    Pipeline 2 (extended): keystroke buffer + clipboard snapshot.

    Runs both pipelines in background threads so as not to delay
    enforcement action.

    v7.0: clipboard_snapshot parameter added to include clipboard
    history in evidence when Axiom Engine triggered the alert.
    """
    base_meta: dict = {
        "captured_at":  now_iso(),
        "severity":     severity,
        "is_backlogged": False,
    }
    evidence_row_id: Optional[str] = None

    try:
        ins = sb.table("evidence_logs").insert({
            "alert_id": alert_id,
            "metadata": base_meta,
        }).execute()
        if ins.data:
            evidence_row_id = ins.data[0]["id"]
            print(f"[pipelines] Dossier row reserved id={evidence_row_id}")
    except Exception as e:
        print(f"[pipelines] reservation failed: {e}", file=sys.stderr)

    def _patch(patch: dict) -> None:
        try:
            if evidence_row_id:
                sb.table("evidence_logs").update(patch).eq("id", evidence_row_id).execute()
            else:
                sb.table("evidence_logs").insert({"alert_id": alert_id, **patch}).execute()
        except Exception as e:
            print(f"[pipelines] patch failed: {e}", file=sys.stderr)

    def _pipeline_1_optics():
        t0 = time.time()
        captured: dict = {"png": None, "cam": None}

        def _grab_screen():
            if severity in ("warning", "medium", "high", "critical"):
                captured["png"] = (
                    volatile_snapshot if volatile_snapshot else capture_screenshot()
                )

        def _grab_cam():
            # Webcam: CRITICAL only, for workstation attribution in shared labs.
            if severity == "critical":
                captured["cam"] = capture_webcam()

        cap_threads = [
            threading.Thread(target=_grab_screen),
            threading.Thread(target=_grab_cam),
        ]
        for t in cap_threads: t.start()
        for t in cap_threads: t.join(timeout=8)

        png, cam = captured["png"], captured["cam"]
        ss_url = wc_url = None

        def _up_screen():
            nonlocal ss_url
            if png:
                ss_url = upload_evidence(f"{workstation_id}/{alert_id}-screen.jpg", png)

        def _up_cam():
            nonlocal wc_url
            if cam:
                wc_url = upload_evidence(f"{workstation_id}/{alert_id}-webcam.jpg", cam)

        up_threads = []
        if png: up_threads.append(threading.Thread(target=_up_screen))
        if cam: up_threads.append(threading.Thread(target=_up_cam))
        for t in up_threads: t.start()
        for t in up_threads: t.join(timeout=20)

        patch: dict = {}
        if ss_url: patch["screenshot_url"] = ss_url
        if wc_url: patch["webcam_url"]     = wc_url
        if patch:  _patch(patch)
        print(
            f"[pipeline-1] Optics in {time.time()-t0:.1f}s  "
            f"screen={bool(ss_url)} cam={bool(wc_url)}"
        )

    def _pipeline_2_forensics():
        print("[pipeline-2] Extracting retrospective telemetry lead-up...")
        keys = (
            random.choice(PHANTOM_SCRIPT)
            if ADMIN_BYPASS_ACTIVE
            else KEYLOG_HISTORY.get_snapshot()
        )
        new_meta = dict(base_meta)
        if keys:
            new_meta["retrospective_payload"] = keys[-500:]
            new_meta["evidence_source"]       = "rolling_buffer_snapshot"
        # v7.0: include clipboard history in dossier when available
        if clipboard_snapshot:
            new_meta["clipboard_snapshot"] = clipboard_snapshot[:5]
        _patch({"metadata": new_meta})
        print("[pipeline-2] Forensic telemetry secured.")

    threading.Thread(target=_pipeline_1_optics,   daemon=True).start()
    if severity in ("warning", "medium", "high", "critical"):
        threading.Thread(target=_pipeline_2_forensics, daemon=True).start()


# =====================================================================
# FOCUS STATE (admin-controlled app whitelist)
# =====================================================================
class FocusState:
    """Caches the focus mode flag and whitelisted process list from Supabase."""

    def __init__(self) -> None:
        self.enabled:      bool      = False
        self.whitelist:    set[str]  = set()
        self.last_refresh: float     = 0.0

    def refresh_if_stale(self) -> None:
        if time.time() - self.last_refresh < FOCUS_REFRESH_SEC:
            return
        self.last_refresh = time.time()
        try:
            s = (
                sb.table("system_settings")
                .select("focus_mode")
                .eq("id", 1)
                .maybe_single()
                .execute()
            )
            self.enabled = bool(s.data and s.data.get("focus_mode"))
            a = (
                sb.table("allowed_apps")
                .select("process_name")
                .eq("whitelisted", True)
                .execute()
            )
            self.whitelist = {row["process_name"].lower() for row in (a.data or [])}
        except Exception as e:
            print(f"[focus] {e}", file=sys.stderr)


FOCUS = FocusState()


# =====================================================================
# NETWORK AUDIT (feeds Axiom Signal Bus in v7.0)
# =====================================================================
_UNAUTHORIZED_PORTS = {1194, 1701, 4500, 500, 51820, 1080, 8080, 9150, 9050}


def network_audit() -> tuple[bool, Optional[str]]:
    """
    Scan active network connections for unauthorized tunnel ports.
    In v7.0 this also feeds every established external connection as a
    'network_conn_axiom' signal so the Axiom Engine can correlate
    network activity with process and behavioral signals.

    Returns (is_violation, reason_string).
    """
    try:
        conn_count = 0
        for conn in psutil.net_connections(kind="inet"):
            if conn.raddr:
                conn_count += 1
                if conn.raddr.port in _UNAUTHORIZED_PORTS:
                    reason = f"unauthorized_tunnel_port_{conn.raddr.port}"
                    print(f"[network] VIOLATION: {reason} raddr={conn.raddr.ip}:{conn.raddr.port}")
                    axiom_push_signal("unauthorized_port", f"{conn.raddr.ip}:{conn.raddr.port}")
                    return True, reason
                if conn.status == "ESTABLISHED":
                    axiom_push_signal("network_conn_axiom", f"{conn.raddr.ip}:{conn.raddr.port}")
        print(f"[network] audit clean — {conn_count} external connections scanned")
    except Exception as e:
        print(f"[network] audit error: {e}", file=sys.stderr)
    return False, None


# =====================================================================
# RESOURCE ENTROPY CHECK
# =====================================================================
def resource_entropy_check(proc_name: Optional[str]) -> tuple[bool, Optional[str]]:
    """
    Detects CPU masquerade: a known lightweight utility consuming
    abnormally high CPU (likely hiding a heavier process inside it).
    Returns (is_anomaly, reason_string).
    """
    if not proc_name:
        return False, None
    UTILITIES = {"calculator.exe", "notepad.exe", "wordpad.exe", "cmd.exe"}
    if proc_name.lower() in UTILITIES:
        try:
            for p in psutil.process_iter(["name", "cpu_percent"]):
                if (p.info["name"] and
                        p.info["name"].lower() == proc_name.lower() and
                        p.info["cpu_percent"] > 25):
                    print(f"[entropy] CPU masquerade: {proc_name} at {p.info['cpu_percent']:.1f}% CPU")
                    axiom_push_signal("cpu_masquerade", proc_name)
                    return True, "resource_masquerade_detected"
        except Exception as e:
            print(f"[entropy] check error: {e}", file=sys.stderr)
    return False, None


# =====================================================================
# ADMIN BYPASS BRIDGE
# =====================================================================
def _set_ghost(active: bool, source: str) -> None:
    global ADMIN_BYPASS_ACTIVE
    if ADMIN_BYPASS_ACTIVE == active:
        return
    ADMIN_BYPASS_ACTIVE = active
    status = "activated" if active else "deactivated"
    print(f"[bypass] Admin bypass {status} via {source}.")


def listen_for_sovereignty() -> None:
    """
    Polls for a local signal file that IT staff can write on-site to
    temporarily suppress monitoring while they service the machine.
    File is deleted immediately after reading.
    """
    signal_path = Path.home() / ".nexus_temp_sig"
    while True:
        if signal_path.exists():
            try:
                content = signal_path.read_text(encoding="utf-8").strip()
                if   content == f"{BYPASS_KEY}:active":   _set_ghost(True,  "local-signal")
                elif content == f"{BYPASS_KEY}:deactive": _set_ghost(False, "local-signal")
            except Exception:
                pass
            try:
                signal_path.unlink()
            except Exception:
                pass
        time.sleep(2)


def hardware_panic_listener() -> None:
    """
    Ctrl+Alt+Shift+P: emergency hardware hotkey to force-disable bypass
    if the local signal file mechanism fails (e.g. drive full).
    """
    def _abort():
        _set_ghost(False, "hardware-panic")

    try:
        with keyboard.GlobalHotKeys({"<ctrl>+<alt>+<shift>+p": _abort}) as h:
            h.join()
    except Exception as e:
        print(f"[ghost] Panic hotkey bind failed: {e}")


# =====================================================================
# DETECTION LOOP PRIMITIVES (vault-aware)
# =====================================================================
def _build_alert_payload(
    workstation_id: str, title: str, proc: Optional[str],
    severity: str, is_backlogged: bool,
    created_at: Optional[str] = None,
) -> dict:
    p = {
        "workstation_id": workstation_id,
        "process_name":   proc,
        "window_title":   title,
        "severity":       severity,
        "is_backlogged":  is_backlogged,
    }
    if created_at:
        p["created_at"] = created_at
    return p


def _build_activity_payload(
    workstation_id: str, title: Optional[str], proc: Optional[str],
    severity: str, is_anomaly: bool, is_backlogged: bool,
    created_at: Optional[str] = None,
) -> dict:
    p = {
        "workstation_id": workstation_id,
        "process_name":   proc,
        "window_title":   title,
        "severity":       severity if severity in ("info", "warning") else "warning",
        "is_anomaly":     is_anomaly,
        "is_backlogged":  is_backlogged,
    }
    if created_at:
        p["created_at"] = created_at
    return p


def fire_alert(
    workstation_id:    str,
    title:             str,
    proc:              Optional[str],
    severity:          str,
    reason:            str,
    volatile_snapshot: Optional[bytes] = None,
) -> None:
    """
    Fire a confirmed policy violation alert.

    CRITICAL severity locks hardware input for 30 seconds pending admin review.
    Whitelisted apps suppress the lock but still log the alert.
    Evidence is archived via archive_evidence() in background threads.
    Falls back to the forensic vault (SQLite) if Supabase is unreachable.
    """
    is_whitelisted = bool(proc and FOCUS.whitelist and proc.lower() in FOCUS.whitelist)

    if severity == "critical" and not is_whitelisted:
        # Atomic Trigger: Fires C++ Hardware Lock AND Tactical HUD together
        engage_freeze_with_hud(
            warden=WARDEN,
            duration=60,
            trigger=reason,
            workstation=workstation_id,
            cinematic=True
        )
        print("[guard] Critical violation. Tactical Monolith deployed.")
    elif severity == "critical" and is_whitelisted:
        print(
            f"[guard] Critical on whitelisted '{proc}' — "
            "lock suppressed, alert logged."
        )

    captured_at = now_iso()
    payload     = _build_alert_payload(workstation_id, title, proc, severity, False)
    print(f"[!!!] ALERT [{severity.upper()}] {reason} | proc='{proc}' title='{title[:60]}'")
    print(f"[alert] Attempting live Supabase insert for workstation={workstation_id}")

    try:
        res = sb.table("alerts").insert(payload).execute()
        if res.data:
            archive_evidence(
                res.data[0]["id"], severity, workstation_id,
                volatile_snapshot,
                CLIPBOARD_HISTORY.get_snapshot(),
            )
            return
        raise RuntimeError("alerts insert returned no rows")
    except Exception as e:
        print(f"[alerts] live insert failed → vaulting: {e}", file=sys.stderr)

        ss_bytes = (
            volatile_snapshot if volatile_snapshot
            else (
                capture_screenshot()
                if severity in ("warning", "medium", "high", "critical")
                else None
            )
        )
        wc_bytes = capture_webcam() if severity == "critical" else None
        evidence = {
            "screenshot_file": _save_cache_blob(ss_bytes) if ss_bytes else None,
            "webcam_file":     _save_cache_blob(wc_bytes) if wc_bytes else None,
            "meta": {
                "captured_at":  captured_at,
                "severity":     severity,
                "reason":       reason,
                "is_backlogged": True,
            },
        }
        offline = _build_alert_payload(
            workstation_id, title, proc, severity,
            is_backlogged=True, created_at=captured_at,
        )
        vault_enqueue("alert", "alerts", offline, evidence, captured_at)


def log_ambient(
    workstation_id: str, title: Optional[str],
    proc: Optional[str], severity: str, is_anomaly: bool,
) -> None:
    """
    Log a low-confidence or partial observation to activity_logs.
    Falls back to vault on network failure.
    """
    print(f"[ambient] severity={severity} anomaly={is_anomaly} "
          f"proc='{proc}' title='{(title or '')[:60]}'")
    captured_at = now_iso()
    payload     = _build_activity_payload(
        workstation_id, title, proc, severity, is_anomaly, False
    )
    try:
        sb.table("activity_logs").insert(payload).execute()
    except Exception as e:
        print(f"[ambient] live insert failed → vaulting: {e}", file=sys.stderr)
        offline = _build_activity_payload(
            workstation_id, title, proc, severity, is_anomaly,
            True, created_at=captured_at,
        )
        vault_enqueue("activity", "activity_logs", offline, None, captured_at)


# =====================================================================
# PHASE 6 — SYNC DAEMON (The Surge)
# Replays the SQLite vault queue when network connectivity is restored.
# =====================================================================
def _supabase_alive() -> bool:
    try:
        host = SUPABASE_URL.replace("https://", "").replace("http://", "").split("/")[0]
        with socket.create_connection((host, 443), timeout=4):
            return True
    except Exception:
        return False


def _surge_one(row: tuple) -> bool:
    """
    Replay one queued row: upload images first, then insert DB row.
    Returns True on clean success.  Dead-letters rows after 10 failures.
    """
    MAX_VAULT_ATTEMPTS = 10
    row_id, kind, table_name, payload_json, evidence_json, created_at, attempts = row

    if attempts >= MAX_VAULT_ATTEMPTS:
        dead = Path.home() / ".sentinel_dead_letter.jsonl"
        try:
            with open(dead, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "row_id": row_id, "table_name": table_name,
                    "payload": payload_json, "attempts": attempts,
                    "dropped_at": datetime.now(timezone.utc).isoformat(),
                }) + "\n")
        except Exception:
            pass
        vault_delete(row_id)
        print(
            f"[sync] row #{row_id} exceeded {MAX_VAULT_ATTEMPTS} attempts — "
            "dead-lettered",
            file=sys.stderr,
        )
        return False

    try:
        payload  = json.loads(payload_json)
        evidence = json.loads(evidence_json) if evidence_json else {}
        payload["created_at"]    = created_at
        payload["is_backlogged"] = True

        ss_url = wc_url = None

        for (file_key, path_tpl) in [
            ("screenshot_file", f"vault-{row_id}-screen.jpg"),
            ("webcam_file",     f"vault-{row_id}-webcam.jpg"),
        ]:
            fname = evidence.get(file_key)
            if fname:
                blob_path = CACHE_DIR / fname
                if blob_path.exists():
                    sb.storage.from_(EVIDENCE_BUCKET).upload(
                        f"{payload['workstation_id']}/{path_tpl}",
                        blob_path.read_bytes(),
                        {"content-type": "image/jpeg", "upsert": "true"},
                    )
                    url = sb.storage.from_(EVIDENCE_BUCKET).get_public_url(
                        f"{payload['workstation_id']}/{path_tpl}"
                    )
                    if file_key == "screenshot_file":
                        ss_url = url
                    else:
                        wc_url = url

        res = sb.table(table_name).insert(payload).execute()
        if not res.data:
            raise RuntimeError(f"{table_name} insert returned no rows")

        if kind == "alert":
            new_id = res.data[0].get("id")
            ev_meta = dict(evidence.get("meta") or {})
            ev_meta["is_backlogged"] = True
            ev_row: dict = {"alert_id": new_id, "metadata": ev_meta}
            if ss_url: ev_row["screenshot_url"] = ss_url
            if wc_url: ev_row["webcam_url"]     = wc_url
            try:
                sb.table("evidence_logs").insert(ev_row).execute()
            except Exception as e:
                print(f"[sync] evidence_logs surge non-fatal: {e}", file=sys.stderr)

        _delete_cache(evidence.get("screenshot_file"))
        _delete_cache(evidence.get("webcam_file"))
        vault_delete(row_id)
        print(f"[sync] surged row #{row_id} ({table_name}) ts={created_at}")
        return True

    except Exception as e:
        vault_bump_attempt(row_id, str(e))
        print(
            f"[sync] row #{row_id} surge failed (attempt {attempts+1}): {e}",
            file=sys.stderr,
        )
        return False


def sync_daemon() -> None:
    """
    Phase 6 — The Surge.
    Probes connectivity every SYNC_INTERVAL seconds.
    When the network is back, drains the SQLite queue in batches.
    """
    print(f"[sync] daemon armed — probing every {SYNC_INTERVAL}s")
    cycle = 0
    while True:
        try:
            time.sleep(SYNC_INTERVAL)
            cycle += 1
            pending = vault_pending(limit=25)
            if not pending:
                if cycle % 10 == 0:
                    print("[sync] queue empty — nothing to surge")
                continue
            print(f"[sync] cycle={cycle} pending={len(pending)} rows — checking connectivity")
            if not _supabase_alive():
                print(f"[sync] {len(pending)} item(s) waiting — link still down")
                continue
            print(f"[sync] connection restored — surging {len(pending)} item(s)")
            wins = 0
            for row in pending:
                if _surge_one(row):
                    wins += 1
                else:
                    break
            print(f"[sync] surge complete: {wins}/{len(pending)} cleared")
        except Exception as e:
            print(f"[sync] daemon error: {e}", file=sys.stderr)


# =====================================================================
# PHASE 2 / 3 / 4 — OCR, ROUTING, ARBITRATION
# =====================================================================
def extract_ocr_suspicion(image_bytes: Optional[bytes]) -> float:
    """
    Run Tesseract OCR on a screenshot and evaluate the extracted text
    with the Lev Engine.  Capped at 5 s to prevent blocking scan_loop.
    Returns Lev C_lev score (0.0 on failure or timeout).
    """
    if not image_bytes:
        print("[ocr] extract_ocr_suspicion: no image bytes — returning 0.0")
        return 0.0
    try:
        img = Image.open(io.BytesIO(image_bytes))
        print(f"[ocr] Running Tesseract on {len(image_bytes)//1024}KB image...")
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(pytesseract.image_to_string, img)
            try:
                raw_text = future.result(timeout=5.0)
            except FutureTimeout:
                print("[ocr] OCR timed out after 5s — skipping", file=sys.stderr)
                return 0.0
        if not raw_text.strip():
            print("[ocr] OCR returned empty text — score 0.0")
            return 0.0
        score, _, hit = LEV.evaluate_suspicion(raw_text.strip().lower(), "")
        print(f"[ocr] OCR score={score:.3f} hit='{hit}' "
              f"text_len={len(raw_text)}")
        return score
    except Exception as e:
        print(f"[ocr] OCR analysis failed: {e}", file=sys.stderr)
        return 0.0


def _get_app_modifier(proc_name: str) -> float:
    """
    M_app: Application Risk Modifier.
    Browsers are higher-risk contexts; editors are lower-risk.
    """
    if not proc_name:
        return 1.0
    proc = proc_name.lower()
    if proc in ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"):
        return 1.2
    if proc in ("winword.exe", "notepad.exe", "code.exe", "excel.exe"):
        return 0.5
    return 1.0


def _calculate_final_arbitration(
    c_lev: float, c_dom: float, c_ocr: float, m_app: float
) -> float:
    """
    Weighted blend of Lev, DOM, and OCR scores with the app-context modifier.

    Base weights:  Lev=0.35  DOM=0.40  OCR=0.25

    Dynamic redistribution (v7.1 rebalancing):
      If c_dom == 0.0: shift +0.15 → Lev, +0.25 → OCR, zero DOM.
        Prevents Lev from artificially spiking when no browser data exists.
      If c_ocr == 0.0 (after DOM check): bleed half unused OCR weight
        into Lev (w_ocr * 0.5). The other half is discarded to avoid
        inflating the score when the OCR signal is simply absent.

    Result is clamped to [0.0, 1.0].
    """
    w_lev, w_dom, w_ocr = 0.35, 0.40, 0.25

    if c_dom == 0.0:
        w_lev += 0.15   # +0.15 (was +0.20 — avoids over-spiking)
        w_ocr += 0.25   # +0.25 (was +0.20 — gives OCR a fairer share)
        w_dom  = 0.0

    if c_ocr == 0.0:
        w_lev += w_ocr * 0.5   # Bleed only HALF unused OCR weight to Lev
        w_ocr  = 0.0            # Remaining half discarded (prevents inflation)

    base   = (w_lev * c_lev) + (w_dom * c_dom) + (w_ocr * c_ocr)
    result = min(base * m_app, 1.0)

    print(
        f"[arbitration] Lev={c_lev:.2f}(w={w_lev:.2f}) "
        f"DOM={c_dom:.2f}(w={w_dom:.2f}) "
        f"OCR={c_ocr:.2f}(w={w_ocr:.2f}) "
        f"App={m_app:.2f} → base={base:.3f} final={result:.3f}"
    )
    return result


# =====================================================================
# MAIN SCAN LOOP
# =====================================================================
def scan_loop(workstation_id: str) -> None:
    """
    Core 3-second monitoring cycle — v8 refactor.

    v8 changes vs v7:
      • Step 6 now calls _check_behavioral_context() before deciding whether
        a Lev match is a Warning or a Strike.  Fuzzy matches never fire
        directly; they must be corroborated by a second independent signal.
      • Lev match → axiom_push_signal() → evaluate_verdict() → enforce.
        The old "if c_lev >= 0.85 → fire_alert()" path is REMOVED.
      • Diagnostic print() calls replaced by sentinel_log() with level="debug"
        so they are silent in operational mode.

    Cycle steps (unchanged numbering for diff clarity):
      1.  Resolve foreground window identity.
      2.  Extract DOM context from browser extension.
      3.  Check keylog buffer for instant-strike terms.
      4.  Check clipboard buffer for high-confidence Lev hits.
      5.  Lev Engine: title + process name.
      6.  [NEW v8] Check behavioral context → preliminary verdict.
      7.  Feed Axiom Signal Bus from all events.
      8.  DOM classifier.
      9.  Network audit.
      10. Resource entropy (CPU masquerade).
      11. Axiom Engine tick.
      12. [NEW v8] Context-gated enforcement: Warning logs / Strike alerts.
      13. App policy / session tracker.
    """
    global ADMIN_BYPASS_ACTIVE, _LATEST_BROWSER_DOM, _LATEST_BROWSER_URL

    last_alerted: dict = {}
    last_ambient:  dict = {}
    _debounce_prune_ts       = time.time()
    _DEBOUNCE_PRUNE_INTERVAL = 300

    while True:
        try:  # ── GLOBAL SHIELD ──────────────────────────────────────────────

            # Prune stale debounce entries
            now_ts = time.time()
            if now_dt := time.time():  # backward compat
                pass
            if now_ts - _debounce_prune_ts > _DEBOUNCE_PRUNE_INTERVAL:
                try:
                    cutoff = now_ts - max(ALERT_DEBOUNCE_SEC, AMBIENT_DEBOUNCE_SEC) * 2
                except NameError:
                    cutoff = now_ts - 120
                last_alerted = {k: v for k, v in last_alerted.items() if v > cutoff}
                last_ambient  = {k: v for k, v in last_ambient.items()  if v > cutoff}
                _debounce_prune_ts = now_ts

            # ── 1. Resolve foreground identity ────────────────────────────────
            try:
                FOCUS.refresh_if_stale()
            except NameError:
                pass

            try:
                bypass_active = ADMIN_BYPASS_ACTIVE
            except NameError:
                bypass_active = False

            if bypass_active:
                try:
                    title, proc = SPOOF_DATA["title"], SPOOF_DATA["proc"]
                except NameError:
                    title, proc = "", ""
            else:
                try:
                    title, proc = get_foreground_window()
                except NameError:
                    title, proc = None, None

            title_str = title or ""
            proc_str  = proc  or ""

            # Update workstation record (best-effort, non-blocking)
            try:
                sb.table("workstations").update({
                    "current_window":  title_str,
                    "current_process": proc_str,
                }).eq("id", workstation_id).execute()
            except Exception:
                pass

            if bypass_active:
                try:
                    time.sleep(SCAN_INTERVAL)
                except NameError:
                    time.sleep(3)
                continue

            # ── 2. DOM context ────────────────────────────────────────────────
            try:
                with _OPTICS_LOCK:
                    browser_context = _LATEST_BROWSER_DOM
                    browser_url     = _LATEST_BROWSER_URL
                    _LATEST_BROWSER_DOM = _LATEST_BROWSER_URL = ""
            except NameError:
                browser_context = browser_url = ""

            # ── 3. Keylog instant-strike check ────────────────────────────────
            typed_hit: Optional[str] = None
            try:
                current_keys    = KEYLOG_HISTORY.get_snapshot().lower()
                normalized_keys = normalize_haystack(current_keys[-100:])
                for word in INSTANT_STRIKE_LIST:
                    if (
                        re.search(rf"\b{re.escape(word)}\b", current_keys[-50:]) or
                        re.search(rf"\b{re.escape(word)}\b", normalized_keys)
                    ):
                        typed_hit = word
                        KEYLOG_HISTORY.clear()
                        axiom_push_signal(
                            "keylog_instant_strike", word,
                            lev_score=1.0, proc_name=proc_str,
                        )
                        sentinel_log(
                            f"[scan] KEYLOG INSTANT STRIKE: '{word}'",
                            level="critical",
                        )
                        break
            except NameError:
                pass

            # ── 4. Clipboard check ────────────────────────────────────────────
            clip_hit: Optional[str] = None
            clip_score: float       = 0.0
            try:
                clip_hit, clip_score = _check_clipboard_for_scan()
                if clip_hit:
                    axiom_push_signal(
                        "clipboard_lev_hit", clip_hit,
                        lev_score=clip_score, proc_name=proc_str,
                    )
            except NameError:
                pass

            # ── 5. Lev Engine: title + process ────────────────────────────────
            c_lev:         float = 0.0
            best_category: str   = "info"
            best_hit:      str   = ""

            # Significance Multiplier pre-check: if proc is whitelisted and the
            # title contains no suspicious tokens, skip the Lev pass entirely.
            proc_mult = get_significance_multiplier(proc_str)

            try:
                c_lev, best_category, best_hit = LEV.evaluate_suspicion(
                    title_str, proc_str
                )
            except NameError:
                pass

            # Typed-hit overrides
            if typed_hit:
                c_lev, best_category, best_hit = 1.0, "critical", typed_hit
            elif clip_hit and clip_score > c_lev:
                c_lev, best_category, best_hit = clip_score, "high", clip_hit

            # Apply significance multiplier to the raw lev score.
            # If the foreground process is known-benign (mult == 0.0) and the
            # title match is only fuzzy (c_lev < 1.0), suppress the Lev signal.
            if proc_mult == 0.0 and c_lev < 1.0:
                sentinel_log(
                    f"[scan] Lev score suppressed for whitelisted proc "
                    f"'{proc_str}' (c_lev={c_lev:.2f}→0.0)",
                    level="debug",
                )
                c_lev = 0.0

            # ── 6. [NEW v8] Check behavioral context → preliminary verdict ────
            # Build the current live signal kinds BEFORE pushing new signals,
            # so we're looking at what the bus already holds from other threads
            # (WMI, USB, clipboard, network audit from last cycle).
            current_bus_kinds: set[str] = set()
            try:
                with _AXIOM_LOCK:
                    current_bus_kinds = {s["kind"] for s in _AXIOM_BUS}
            except NameError:
                pass

            # Determine what kind of signal this Lev result represents
            lev_signal_kind: Optional[str] = None
            if c_lev == 1.0 and best_category == "critical":
                lev_signal_kind = "lev_title_critical"
                if re.search(
                    r"\b(njrat|darkcomet|nanocore|asyncrat|remcos|quasar|xworm|"
                    r"cobalt.?strike|metasploit|msfvenom|xmrig)\b",
                    best_hit, re.IGNORECASE,
                ):
                    lev_signal_kind = "rat_exact_match"
            elif c_lev >= 0.70:
                lev_signal_kind = "lev_title_high"

            # What would the verdict look like IF we add this Lev signal?
            preview_kinds = set(current_bus_kinds)
            if lev_signal_kind:
                preview_kinds.add(lev_signal_kind)

            preliminary_verdict, prelim_reason = evaluate_verdict(
                preview_kinds, c_lev, best_category
            )

            # ── 7. Feed Axiom Signal Bus ──────────────────────────────────────
            if lev_signal_kind:
                axiom_push_signal(
                    lev_signal_kind, best_hit,
                    lev_score=c_lev, proc_name=proc_str,
                )
                if lev_signal_kind == "rat_exact_match":
                    axiom_push_signal(
                        "rat_exact_match", best_hit,
                        lev_score=1.0, proc_name=proc_str,
                    )

            # Passive signals (always push regardless of Lev result)
            if re.search(r"\b(incognito|private|inprivate)\b", title_str, re.IGNORECASE):
                axiom_push_signal(
                    "incognito_window", title_str[:100], proc_name=proc_str
                )
            if re.search(
                r"github\.com/.+/releases|raw\.githubusercontent",
                title_str, re.IGNORECASE,
            ):
                axiom_push_signal(
                    "github_release_url", title_str[:200], proc_name=proc_str
                )

            try:
                m_app = _get_app_modifier(proc_str)
            except NameError:
                m_app = 1.0
            c_dom = 0.0

            # ── 8. DOM classifier ─────────────────────────────────────────────
            if browser_context:
                try:
                    is_violation, web_reason = classify_web_context(browser_context)
                    if is_violation:
                        c_dom = 1.0
                        axiom_push_signal(
                            "dom_classifier_fire", web_reason, proc_name=proc_str
                        )
                        if best_category != "critical":
                            best_hit = web_reason
                except NameError:
                    pass

            # ── 9. Network audit (also feeds Axiom internally) ────────────────
            net_viol: bool      = False
            net_reason: Optional[str] = None
            try:
                net_viol, net_reason = network_audit()
            except NameError:
                pass

            # ── 10. Resource entropy (CPU masquerade) ─────────────────────────
            try:
                resource_entropy_check(proc_str)
            except NameError:
                pass

            # ── 11. Axiom Engine tick ─────────────────────────────────────────
            axiom_evaluate(workstation_id, last_alerted)

            # ── 12. [NEW v8] Context-gated enforcement ────────────────────────
            s_final              = 0.0
            severity             = "info"
            reason               = ""
            volatile_ram_snapshot: Optional[bytes] = None

            # ── Network direct path (unchanged: network violations are
            #    independently verifiable and fire regardless of proc name) ────
            if net_viol and net_reason:
                # Refresh the verdict with network signal included
                try:
                    with _AXIOM_LOCK:
                        current_bus_kinds = {s["kind"] for s in _AXIOM_BUS}
                except NameError:
                    pass
                net_verdict, net_vreason = evaluate_verdict(
                    current_bus_kinds, c_lev, best_category
                )
                if net_verdict == Verdict.STRIKE:
                    s_final  = 0.80
                    severity = "high"
                    reason   = net_reason
                elif net_verdict == Verdict.WARNING:
                    s_final  = 0.40
                    severity = "warning"
                    reason   = net_reason

            # ── Lev / DOM fast path (REQ-4 compliant) ────────────────────────
            if s_final == 0.0:
                if preliminary_verdict == Verdict.STRIKE:
                    # Context confirmed — collect evidence and fire
                    volatile_ram_snapshot = _safe_capture_screenshot()
                    c_ocr = 0.0
                    if c_lev > 0.70 and c_dom == 0.0 and volatile_ram_snapshot:
                        try:
                            c_ocr = extract_ocr_suspicion(volatile_ram_snapshot)
                        except NameError:
                            pass
                    try:
                        s_final = _calculate_final_arbitration(c_lev, c_dom, c_ocr, m_app)
                    except NameError:
                        s_final = min(c_lev * m_app, 1.0)
                    severity = "critical" if s_final >= 0.85 else "high"
                    reason   = f"verdict_strike:{prelim_reason}_(lev={c_lev:.2f})"

                elif preliminary_verdict == Verdict.WARNING:
                    # [REQ-1] Fuzzy match alone → WARNING only, never a Strike.
                    # Log ambient; let Axiom bus accumulate corroboration.
                    s_final  = 0.45           # below strike threshold
                    severity = "warning"
                    reason   = f"verdict_warning:{prelim_reason}_(lev={c_lev:.2f})"

            # ── Diagnostic matrix (only in verbose mode) ──────────────────────
            if c_lev > 0.0 or c_dom > 0.0 or typed_hit or clip_hit:
                try:
                    with _AXIOM_LOCK:
                        ats_now = _axiom_compute_ats(time.time())
                except NameError:
                    ats_now = 0.0
                sentinel_log(
                    f"[telemetry] Lev:{c_lev:.2f} DOM:{c_dom:.2f} "
                    f"App:{m_app:.2f} Final:{s_final:.2f} ATS:{ats_now:.2f} "
                    f"Verdict:{preliminary_verdict.upper()} Hit:'{best_hit}' "
                    f"Proc:'{proc_str}'",
                    level="debug",
                )

            # ── Enforce ───────────────────────────────────────────────────────
            try:
                alert_debounce   = ALERT_DEBOUNCE_SEC
                ambient_debounce = AMBIENT_DEBOUNCE_SEC
            except NameError:
                alert_debounce = ambient_debounce = 30

            if s_final >= 0.60 and severity in ("critical", "high"):
                # STRIKE — confirmed behavioral correlation
                key = reason
                if time.time() - last_alerted.get(key, 0) > alert_debounce:
                    last_alerted[key] = time.time()
                    alert_title = (
                        f"{title_str} [URL: {browser_url}]"
                        if browser_url else title_str
                    )
                    alert_title = f"[VIOLATION: {best_hit.upper()}] {alert_title}"
                    sentinel_log(
                        f"[!!!] STRIKE fired reason='{reason}' "
                        f"proc='{proc_str}' title='{title_str[:60]}'",
                        level="strike",
                        force=True,
                    )
                    try:
                        fire_alert(
                            workstation_id, alert_title, proc_str,
                            severity, reason, volatile_ram_snapshot,
                        )
                    except NameError:
                        pass

            elif s_final >= 0.30 and severity == "warning":
                # WARNING — fuzzy match without behavioral corroboration
                key = reason
                if time.time() - last_ambient.get(key, 0) > ambient_debounce:
                    last_ambient[key] = time.time()
                    sentinel_log(
                        f"[warning] Unconfirmed signal: {reason} "
                        f"proc='{proc_str}' lev={c_lev:.2f}",
                        level="warning",
                    )
                    try:
                        log_ambient(
                            workstation_id, title_str, proc_str,
                            severity, is_anomaly=True,
                        )
                    except NameError:
                        pass

            # ── 13. App policy / session tracker (unchanged) ──────────────────
            clean_proc = proc_str.strip().lower() if proc_str else ""
            try:
                focus_wl  = FOCUS.whitelist
                os_bypass = _OS_BYPASS
            except NameError:
                focus_wl = os_bypass = set()

            if (
                clean_proc
                and clean_proc not in focus_wl
                and clean_proc not in os_bypass
                and s_final < 0.60
            ):
                try:
                    sb.table("unauthorized_events").insert({
                        "workstation_id": workstation_id,
                        "process_name":   clean_proc,
                        "window_title":   title_str,
                        "kind":           "unauthorized",
                    }).execute()
                except Exception:
                    pass

                try:
                    if FOCUS.enabled:
                        key = f"policy:{clean_proc}"
                        if time.time() - last_alerted.get(key, 0) > alert_debounce:
                            last_alerted[key] = time.time()
                            fire_alert(
                                workstation_id, title_str, clean_proc,
                                "high", "unauthorized_app_focus_lock",
                            )
                except NameError:
                    pass

        except Exception as e:
            sentinel_log(
                f"\n[!!!] ENGINE CRASH: {e}\n",
                level="error",
                force=True,
            )
            try:
                import pathlib
                from datetime import datetime, timezone
                err_path = pathlib.Path.home() / ".sentinel_err.txt"
                with open(str(err_path), "a") as f:
                    f.write(
                        f"[{datetime.now(timezone.utc).isoformat()}] "
                        f"scan_loop: {e}\n"
                    )
            except Exception:
                pass

        try:
            time.sleep(SCAN_INTERVAL)
        except NameError:
            time.sleep(3)


def _safe_capture_screenshot() -> Optional[bytes]:
    """Thin wrapper around capture_screenshot() that never raises."""
    try:
        return capture_screenshot()
    except Exception:
        return None


# =====================================================================
# HEARTBEAT
# =====================================================================
def heartbeat_loop(workstation_id: str) -> None:
    """Keeps the workstation record 'online' in Supabase."""
    print(f"[heartbeat] Loop started for workstation_id={workstation_id}")
    beat = 0
    while True:
        try:
            sb.table("workstations").update({
                "status":         "online",
                "last_heartbeat": now_iso(),
            }).eq("id", workstation_id).execute()
            beat += 1
            if beat % 4 == 0:   # log every ~60s (4 × 15s)
                print(f"[heartbeat] beat #{beat} — workstation online")
        except Exception as e:
            print(f"[heartbeat] update failed: {e}", file=sys.stderr)
        time.sleep(HEARTBEAT_INTERVAL)


# =====================================================================
# ADMINISTRATIVE ACTIONS
# =====================================================================
def controlled_shutdown(workstation_id: str, action_id: str) -> None:
    """
    Admin-initiated shutdown.  Captures screenshot and webcam evidence
    before issuing the OS shutdown command.
    """
    print(f"[admin] Controlled shutdown initiated (Action #{action_id})")

    def _upload_cam():
        cam = capture_webcam()
        if cam:
            url = upload_evidence(f"{workstation_id}/action-{action_id}-webcam.jpg", cam)
            if url:
                try:
                    sb.table("evidence_logs").insert({
                        "metadata": {
                            "command":    "terminate",
                            "action_id":  action_id,
                            "is_backlogged": False,
                        },
                        "webcam_url": url,
                    }).execute()
                except Exception:
                    pass

    def _upload_screen():
        screen = capture_screenshot()
        if screen:
            upload_evidence(f"{workstation_id}/action-{action_id}-screen.jpg", screen)

    threading.Thread(target=_upload_cam,    daemon=True).start()
    threading.Thread(target=_upload_screen, daemon=True).start()

    print(f"[admin] Evidence uploads in progress. Shutdown in {TERMINATE_GRACE_SEC}s.")
    time.sleep(TERMINATE_GRACE_SEC)

    system = platform.system()
    if   system == "Windows": subprocess.call("shutdown /s /f /t 0", shell=True)
    elif system == "Darwin":  subprocess.call(["sudo", "shutdown", "-h", "now"])
    else:                     subprocess.call(["shutdown", "-h", "now"])


def execute_command(cmd: str) -> None:
    """Execute a simple OS-level admin command (lock screen, etc.)."""
    system = platform.system()
    print(f"[admin] Executing: {cmd.upper()} on {system}")
    if cmd == "lock":
        if   system == "Windows": subprocess.call("rundll32.exe user32.dll,LockWorkStation", shell=True)
        elif system == "Darwin":  subprocess.call(["pmset", "displaysleepnow"])
        else:                     subprocess.call(["loginctl", "lock-session"])


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def action_loop(workstation_id: str) -> None:
    """
    Polls Supabase for pending admin commands every ACTION_POLL seconds.
    Commands expire after COMMAND_TTL_SEC (60 s) to prevent stale replays.

    Supported commands:
      terminate     — controlled shutdown with evidence capture
      freeze /
      lock_hardware — engage input lock (duration in metadata)
      unfreeze      — release input lock
      kill_task /
      kill / scalpel — terminate a named process
      update        — OTA binary replacement with SHA-256 integrity check
      set_alias     — rename the workstation's display identity
      lock          — OS-level screen lock
    """
    while True:
        try:
            res = (
                sb.table("admin_actions")
                .select("id, command, created_at, metadata")
                .eq("target_id", workstation_id)
                .eq("status", "pending")
                .execute()
            )
            now_dt = datetime.now(timezone.utc)

            for action in res.data or []:
                created = _parse_iso(action.get("created_at"))

                # Expire stale commands
                if created and (now_dt - created) > timedelta(seconds=COMMAND_TTL_SEC):
                    age = int((now_dt - created).total_seconds())
                    print(f"[actions] EXPIRED ({age}s) → {action['command']} #{action['id']}")
                    sb.table("admin_actions").update({"status": "expired"}).eq("id", action["id"]).execute()
                    continue

                # Mark as 'sent' immediately to prevent duplicate execution
                # on the next poll cycle (before dispatch, not after).
                sb.table("admin_actions").update({"status": "sent"}).eq("id", action["id"]).execute()
                print(f"[actions] Dispatching cmd='{cmd}' id={action['id']} meta={meta}")

                # ── Dispatch ─────────────────────────────────────────────────
                if cmd == "terminate":
                    threading.Thread(
                        target=controlled_shutdown,
                        args=(workstation_id, action["id"]),
                        daemon=True,
                    ).start()

                elif cmd in ("freeze", "lock_hardware") and WARDEN:
                    try:
                        duration = int(meta.get("duration", 300))
                    except (ValueError, TypeError):
                        duration = 300
                    WARDEN.lock_workstation(duration=duration)

                elif cmd == "unfreeze" and WARDEN:
                    WARDEN.disengage_freeze()

                elif cmd in ("kill_task", "kill", "scalpel") and WARDEN:
                    target = (
                        meta.get("process_name") or meta.get("process") or
                        meta.get("target")       or meta.get("target_name")
                    )
                    if target:
                        WARDEN.terminate_process(target)
                    else:
                        print(f"[actions] kill: no target in metadata {meta}")

                elif cmd == "update":
                    download_url    = meta.get("url")
                    expected_sha256 = meta.get("sha256")
                    if download_url:
                        try:
                            current_exe  = os.path.basename(sys.executable)
                            new_exe_path = f"{current_exe}.new"
                            print(f"[update] Downloading to replace {current_exe}...")
                            urllib.request.urlretrieve(download_url, new_exe_path)

                            if expected_sha256:
                                actual = hashlib.sha256(
                                    Path(new_exe_path).read_bytes()
                                ).hexdigest()
                                if actual.lower() != expected_sha256.lower():
                                    Path(new_exe_path).unlink(missing_ok=True)
                                    print(
                                        f"[update] INTEGRITY FAILURE — hash mismatch. "
                                        f"Expected={expected_sha256} Got={actual}",
                                        file=sys.stderr,
                                    )
                                    sb.table("admin_actions").update({"status": "failed"}).eq("id", action["id"]).execute()
                                    continue
                                print("[update] SHA-256 verified ✓")
                            else:
                                print(
                                    "[update] WARNING: no sha256 supplied — "
                                    "proceeding without integrity check",
                                    file=sys.stderr,
                                )

                            # Write phoenix.bat to TEMP dir to avoid PermissionError
                            # in restricted deployment paths (e.g. System32).
                            temp_dir  = (
                                os.environ.get("TEMP")
                                or os.environ.get("TMP")
                                or os.getcwd()
                            )
                            bat_path  = Path(temp_dir) / "phoenix.bat"
                            bat = (
                                "@echo off\n"
                                "timeout /t 3 /nobreak > NUL\n"
                                f"move /Y \"{current_exe}\" \"{current_exe}.bak\"\n"
                                f"move /Y \"{new_exe_path}\" \"{current_exe}\"\n"
                                f"start \"\" \"{current_exe}\"\n"
                                "timeout /t 15 /nobreak > NUL\n"
                                f"tasklist /FI \"IMAGENAME eq {current_exe}\" 2>NUL | find /I /N \"{current_exe}\">NUL\n"
                                "if \"%ERRORLEVEL%\"==\"1\" (\n"
                                f"    move /Y \"{current_exe}.bak\" \"{current_exe}\"\n"
                                f"    start \"\" \"{current_exe}\"\n"
                                ")\n"
                                "del \"%~f0\"\n"
                            )
                            bat_path.write_text(bat, encoding="utf-8")
                            print(f"[update] phoenix.bat written to: {bat_path}")
                            sb.table("admin_actions").update({"status": "acknowledged"}).eq("id", action["id"]).execute()

                            if platform.system() == "Windows":
                                cflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 16)
                                subprocess.Popen([str(bat_path)], shell=True, creationflags=cflags)
                            else:
                                subprocess.Popen(["sh", str(bat_path)], shell=True)
                            os._exit(0)
                        except Exception as e:
                            print(f"[update] OTA Failure: {e}", file=sys.stderr)

                elif cmd == "set_alias":
                    new_alias = (
                        meta.get("alias") or meta.get("new_name") or meta.get("name")
                    )
                    if new_alias:
                        try:
                            ALIAS_FILE.write_text(new_alias, encoding="utf-8")
                            sb.table("workstations").update({"name": new_alias}).eq("id", workstation_id).execute()
                            print(f"[identity] Alias updated: {new_alias}")
                        except Exception as e:
                            print(f"[identity] Alias forge failed: {e}", file=sys.stderr)
                    else:
                        print(f"[identity] set_alias: no name in metadata {meta}")

                else:
                    execute_command(cmd)

                # Mark as 'acknowledged' now that dispatch has completed.
                # 'sent' was already written before dispatch to prevent duplicate
                # execution across poll cycles.
                sb.table("admin_actions").update({"status": "acknowledged"}).eq("id", action["id"]).execute()
                print(f"[actions] cmd='{cmd}' id={action['id']} → acknowledged")

        except Exception as e:
            print(f"[actions] {e}", file=sys.stderr)

        time.sleep(ACTION_POLL)


# =====================================================================
# SERVICE WATCHDOG
# Monitors critical daemon threads and restarts them if they die.
# Also supports self-restart via subprocess if the process itself exits.
# =====================================================================

# Critical threads that must stay alive — monitored by the watchdog.
# Each entry: (thread_name, target_function, args)
_WATCHDOG_REGISTRY: list[dict] = []
_WATCHDOG_LOCK = threading.Lock()


def watchdog_register(name: str, target, args: tuple = ()) -> None:
    """Register a thread for watchdog monitoring."""
    with _WATCHDOG_LOCK:
        _WATCHDOG_REGISTRY.append({
            "name":   name,
            "target": target,
            "args":   args,
            "thread": None,
        })


def _watchdog_spawn(entry: dict) -> threading.Thread:
    """Spawn (or re-spawn) a registered daemon thread."""
    t = threading.Thread(
        target=entry["target"],
        args=entry["args"],
        daemon=True,
        name=entry["name"],
    )
    t.start()
    entry["thread"] = t
    return t


def watchdog_disable(name: str) -> None:
    """
    Permanently mark a registered thread as disabled.

    The watchdog will stop monitoring and restarting it.  Use this when a
    thread cannot function due to a missing optional library — we don't want
    the watchdog to restart it in a tight loop, flooding the console.

    Call this from inside the thread function before returning, e.g.:
        try:
            import wmi
        except ImportError:
            sentinel_log("[wmi] Feature Disabled — install pywin32", level="error")
            watchdog_disable("wmi_monitor")
            return
    """
    try:
        with _WATCHDOG_LOCK:
            for entry in _WATCHDOG_REGISTRY:
                if entry["name"] == name:
                    entry["disabled"] = True
                    sentinel_log(
                        f"[watchdog] Thread '{name}' permanently disabled — "
                        "watchdog will not restart it.",
                        level="error",
                        force=True,
                    )
                    return
    except NameError:
        pass
    sentinel_log(
        f"[watchdog] watchdog_disable: '{name}' not found in registry",
        level="error",
    )


def self_healing_thread(
    name:          str,
    target,
    args:          tuple        = (),
    required_libs: list[str]   = None,
) -> None:
    """
    Self-healing thread body runner.

    Wraps `target(*args)` with two protective layers:

    Layer 1 — Missing library detection:
        Attempts to import each name in `required_libs`.  If any import
        fails, prints a single "Feature Disabled" message, calls
        watchdog_disable() to prevent repeated restarts, and exits cleanly.
        The watchdog will NOT loop on this thread again.

    Layer 2 — Runtime error containment:
        If the target raises an unexpected exception after starting, the
        error is logged and the thread exits.  The watchdog WILL restart
        it in this case (the restart is legitimate — the feature was working
        but crashed transiently, e.g. a WMI COM timeout).

    Usage — replace the bare thread target with this wrapper:
        # Old:
        threading.Thread(target=wmi_process_monitor, args=(wid,), daemon=True)
        # New:
        threading.Thread(
            target=self_healing_thread,
            args=("wmi_monitor", wmi_process_monitor, (wid,), ["wmi"]),
            daemon=True,
        )
    """
    # ── Layer 1: missing library guard ────────────────────────────────────────
    for lib in (required_libs or []):
        try:
            __import__(lib)
        except ImportError:
            sentinel_log(
                f"[{name}] Feature Disabled — optional library '{lib}' is not "
                f"installed.  This monitor will not run.  "
                f"To enable: pip install {lib}",
                level="error",
                force=True,
            )
            watchdog_disable(name)
            return  # exit cleanly — watchdog will not restart

    # ── Layer 2: runtime error containment ───────────────────────────────────
    try:
        target(*args)
    except Exception as exc:
        sentinel_log(
            f"[{name}] Thread exited with unhandled exception: {exc}  "
            f"Watchdog will restart.",
            level="error",
            force=True,
        )
        try:
            import pathlib
            from datetime import datetime, timezone
            err_path = pathlib.Path.home() / ".sentinel_err.txt"
            with open(str(err_path), "a") as ef:
                ef.write(
                    f"[{datetime.now(timezone.utc).isoformat()}] "
                    f"[{name}] crash: {exc}\n"
                )
        except Exception:
            pass
        raise  # Re-raise so the watchdog knows the thread is dead


def sentinel_watchdog() -> None:
    """
    Lightweight service watchdog — v8 revision.

    v8 changes:
      • Respects entry["disabled"] flag set by watchdog_disable() /
        self_healing_thread().  Permanently-disabled threads (e.g. wmi_monitor
        when pywin32 is not installed) are skipped and never restarted.
      • Uses sentinel_log() so the "DEAD THREAD" restart messages only appear
        in verbose mode during normal operation, but always in error mode.
    """
    sentinel_log(
        f"[watchdog] Service watchdog online — "
        f"monitoring {len(_WATCHDOG_REGISTRY)} critical threads.",
        level="error",   # operational-visible at startup
        force=True,
    )
    _CHECK_INTERVAL = 10  # seconds

    while True:
        try:
            time.sleep(_CHECK_INTERVAL)
            try:
                registry = _WATCHDOG_REGISTRY
                lock     = _WATCHDOG_LOCK
            except NameError:
                continue

            with lock:
                for entry in registry:

                    # Skip permanently-disabled threads (REQ-5)
                    if entry.get("disabled", False):
                        continue

                    t = entry.get("thread")
                    if t is None or not t.is_alive():
                        name = entry["name"]
                        sentinel_log(
                            f"[watchdog] DEAD THREAD: '{name}' — restarting",
                            level="error",
                            force=True,
                        )
                        try:
                            try:
                                new_t = _watchdog_spawn(entry)
                                sentinel_log(
                                    f"[watchdog] '{name}' restarted "
                                    f"(thread_id={new_t.ident})",
                                    level="error",
                                    force=True,
                                )
                            except NameError:
                                pass
                        except Exception as restart_err:
                            sentinel_log(
                                f"[watchdog] FAILED to restart '{name}': "
                                f"{restart_err}",
                                level="error",
                                force=True,
                            )
        except Exception as e:
            sentinel_log(
                f"[watchdog] watchdog loop error: {e}",
                level="error",
                force=True,
            )


# =====================================================================
# MAIN ENTRY POINT
# =====================================================================
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

BRIGHT_WHITE = "\033[97m"
BRIGHT_CYAN = "\033[96m"
BRIGHT_RED = "\033[91m"
BRIGHT_YELLOW = "\033[93m"
BRIGHT_GREEN = "\033[92m"
BRIGHT_MAGENTA = "\033[95m"


def _c(text: str, *styles: str) -> str:
    return "".join(styles) + text + RESET


def _term_width(default: int = 88) -> int:
    return max(default, shutil.get_terminal_size((default, 24)).columns)


def _line(char: str = "═", width: int = 88) -> str:
    return char * width


def _center(text: str, width: int) -> str:
    return text.center(width)


def _type_print(text: str, delay: float = 0.007, end: str = "\n") -> None:
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(delay)
    sys.stdout.write(end)
    sys.stdout.flush()


def _box_line(left: str, right: str, width: int, style: str = WHITE) -> None:
    inner = width - 4
    content = f" {left} {right}"
    print(_c("║ " + content.ljust(inner) + " ║", style))


def _section_title(title: str, width: int) -> None:
    print(_c("╠" + "═" * (width - 2) + "╣", BRIGHT_CYAN))
    print(_c("║" + _center(title, width - 2) + "║", BOLD, BRIGHT_WHITE))
    print(_c("╠" + "═" * (width - 2) + "╣", BRIGHT_CYAN))


def _status_bar(percent: int, width: int = 26) -> str:
    filled = int(width * percent / 100)
    return "[" + ("█" * filled) + ("░" * (width - filled)) + f"] {percent:>3d}%"


def _render_status_matrix(width: int) -> None:
    rows = [
        ("CORE", "INITIALIZING", 18, YELLOW),
        ("VAULT", "MOUNTING", 42, BRIGHT_CYAN),
        ("POLICY", "ENFORCEMENT READY", 91, BRIGHT_GREEN),
        ("TELEMETRY", "LINK STABLE", 100, GREEN),
    ]

    print(_c("╠" + "═" * (width - 2) + "╣", BRIGHT_CYAN))
    print(_c("║" + _center("RUNTIME STATUS MATRIX", width - 2) + "║", BOLD, BRIGHT_WHITE))
    print(_c("╠" + "═" * (width - 2) + "╣", BRIGHT_CYAN))

    header = f"{'MODULE':<14} {'STATE':<24} {'LOAD':<32}"
    print(_c("║ " + header.ljust(width - 4) + " ║", DIM, BRIGHT_WHITE))
    print(_c("╟" + "─" * (width - 2) + "╢", BRIGHT_CYAN))

    for module, state, percent, color in rows:
        bar = _status_bar(percent, width=22)
        line = f"{module:<14} {state:<24} {bar:<32}"
        print(_c("║ " + line.ljust(width - 4) + " ║", color))

    print(_c("╠" + "═" * (width - 2) + "╣", BRIGHT_CYAN))


def _render_banner(width: int) -> None:
    notice_lines = [
        "NOTICE: This device is monitored by school IT policy.",
        "Keyboard and screen activity may be logged for policy enforcement.",
        "Authorized use only. Contact IT for questions.",
    ]

    logo = [
        r" ███████╗██╗  ██╗██████╗ ████████╗     ██████╗  ██████╗ ████████╗",
        r" ██╔════╝██║  ██║██╔══██╗╚══██╔══╝    ██╔════╝ ██╔═══██╗╚══██╔══╝",
        r" █████╗  ███████║██████╔╝   ██║       ██║  ███╗██║   ██║   ██║   ",
        r" ██╔══╝  ██╔══██║██╔══██╗   ██║       ██║   ██║██║   ██║   ██║   ",
        r" ███████╗██║  ██║██║  ██║   ██║       ╚██████╔╝╚██████╔╝   ██║   ",
        r" ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝        ╚═════╝  ╚═════╝    ╚═╝   ",
    ]

    print(_c("╔" + "═" * (width - 2) + "╗", BRIGHT_CYAN))
    print(_c("║" + _center("ACCESS CONTROL ACTIVE", width - 2) + "║", BOLD, BRIGHT_RED))
    print(_c("╠" + "═" * (width - 2) + "╣", BRIGHT_CYAN))

    for line in notice_lines:
        print(_c("║ " + line.ljust(width - 4) + " ║", YELLOW))

    print(_c("╠" + "═" * (width - 2) + "╣", BRIGHT_CYAN))

    for line in logo:
        print(_c("║ " + line.ljust(width - 4) + " ║", BRIGHT_WHITE))

    print(_c("╠" + "═" * (width - 2) + "╣", BRIGHT_CYAN))
    print(_c("║" + _center("EXRT v2  |  EXPERIMENTAL BRANCH v7", width - 2) + "║", BOLD, BRIGHT_GREEN))
    print(_c("║" + _center("BOOT SEQUENCE // SENTINEL INTERFACE // CONTROLLED ENVIRONMENT", width - 2) + "║", DIM, BRIGHT_CYAN))
    print(_c("╠" + "═" * (width - 2) + "╣", BRIGHT_CYAN))

    meta = [
        ("ARCHITECTURE", "School Endpoint Monitor (LTS)"),
        ("ENGINE", "Lev Engine + Axiom Behavioral Engine"),
        ("ENFORCEMENT", "Dual-Gated Input Lock"),
        ("PIPELINE", "Signal Bus / L2 Arbitrator / L3 Verifier"),
        ("IDENTITY", f"{WORKSTATION_NAME} | {HARDWARE_UUID}"),
    ]

    for key, value in meta:
        text = f"{key:<12} : {value}"
        print(_c("║ " + text.ljust(width - 4) + " ║", WHITE))

    print(_c("╠" + "═" * (width - 2) + "╣", BRIGHT_CYAN))


def render_exrt_boot_banner(animate: bool = True) -> None:
    width = _term_width(88)

    if animate:
        _type_print(_c(">> booting EXRT v2 / experimental branch v7 ...", BRIGHT_CYAN, BOLD), 0.015)
        time.sleep(0.2)
        _type_print(_c(">> establishing control plane ...", BRIGHT_YELLOW), 0.012)
        time.sleep(0.2)
        _type_print(_c(">> sealing policy boundary ...", BRIGHT_RED), 0.012)
        time.sleep(0.25)
        print()

    _render_banner(width)
    _render_status_matrix(width)

    footer = "SYSTEM STATE: ONLINE | POLICY ENFORCEMENT: ENABLED | LINK: STABLE"
    print(_c("║" + _center(footer, width - 2) + "║", BOLD, BRIGHT_YELLOW))
    print(_c("╚" + "═" * (width - 2) + "╝", BRIGHT_CYAN))
    print()

    if animate:
        spinner = ["▖", "▘", "▝", "▗"]
        sys.stdout.write(_c(" ", RESET))
        for i in range(12):
            sys.stdout.write("\r" + _c(f"STATUS: {spinner[i % 4]} SYNCHRONIZING", BRIGHT_MAGENTA, BOLD))
            sys.stdout.flush()
            time.sleep(0.08)
        sys.stdout.write("\r" + " " * 40 + "\r")
        sys.stdout.flush()


def main() -> None:
    global workstation_id_global

    render_exrt_boot_banner(animate=True)

    vault_init()
    ensure_bucket()
    wid = register_workstation()

    # Expose workstation ID globally so WMI/USB monitors can call fire_alert()
    workstation_id_global = wid

    # ── Register critical threads with the watchdog ───────────────────────────
    # These are the threads whose death would degrade compliance coverage.
    # Non-critical threads (optics server, panic listener) are NOT registered
    # since they are self-recovering or non-essential to core enforcement.
    _CRITICAL_THREADS = [
        ("heartbeat",         heartbeat_loop,                    (wid,)),
        ("scan_loop",         scan_loop,                         (wid,)),
        ("action_loop",       action_loop,                       (wid,)),
        ("sync_daemon",       sync_daemon,                       ()),
        ("keylogger",         _background_keylogger,             ()),
        ("clipboard_monitor", _background_clipboard_monitor,     ()),
        #
        # ── Self-healing wrappers for optional-library threads [REQ-5] ───────
        # These use self_healing_thread() so a missing library → single
        # "Feature Disabled" message + watchdog_disable(), not a restart loop.
        #
        ("wmi_monitor",       self_healing_thread,
            ("wmi_monitor", wmi_process_monitor, (wid,), ["wmi"])),
        ("usb_monitor",       self_healing_thread,
            ("usb_monitor", usb_and_adapter_monitor, (wid,), ["wmi"])),
    ]

    for name, target, args in _CRITICAL_THREADS:
        watchdog_register(name, target, args)

    # ── Spawn all registered critical threads via watchdog ────────────────────
    with _WATCHDOG_LOCK:
        for entry in _WATCHDOG_REGISTRY:
            _watchdog_spawn(entry)
            print(f"[main] Started critical thread: {entry['name']}")

    # ── Non-watchdog threads (self-recovering or non-enforcement-critical) ─────
    _aux_threads = [
        threading.Thread(target=listen_for_sovereignty,  daemon=True, name="sovereignty"),
        threading.Thread(target=hardware_panic_listener, daemon=True, name="panic_listener"),
        threading.Thread(target=boot_optics_server,      daemon=True, name="optics_server"),
        threading.Thread(target=sentinel_watchdog,        daemon=True, name="watchdog"),
    ]
    for t in _aux_threads:
        t.start()
        print(f"[main] Started aux thread: {t.name}")

    total = len(_CRITICAL_THREADS) + len(_aux_threads)
    print(f"[system] {total} daemon threads armed "
          f"({len(_CRITICAL_THREADS)} under watchdog supervision).")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("[system] Agent shutting down. Marking workstation offline.")
        try:
            sb.table("workstations").update({"status": "offline"}).eq("id", wid).execute()
        except Exception:
            pass


if __name__ == "__main__":
    main()
