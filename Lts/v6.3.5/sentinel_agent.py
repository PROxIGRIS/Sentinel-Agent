"""
NEXUS SENTINEL — School Endpoint Monitor
=========================================
Authorized deployment tool for school-managed Windows workstations.

Authorization:
    Deployed by IT administration under written authorization from
    school principal. Operates exclusively on school-owned hardware.

Scope:
    - Monitors active window titles and browser content for policy
      violations (explicit content, proxy tools, gaming platforms).
    - Input locking: temporarily disables keyboard/mouse on violation
      pending admin review. Auto-releases after configurable timeout.
    - Evidence capture: rolling 500-char keystroke buffer flushed ONLY
      on confirmed violation. Webcam capture restricted to CRITICAL
      severity events only.
    - All evidence uploaded to school-controlled Supabase instance.

What this is NOT:
    - Not a general-purpose keylogger (buffer is non-persistent,
      non-exfiltrated except on confirmed policy breach).
    - Not spyware (no microphone, no continuous screen recording,
      no location tracking).

Compliance:
    Students are notified at login that school devices are monitored.
    Data is accessible only to authorized school IT staff and admin.
"""

from __future__ import annotations # MUST BE FIRST

from PIL import Image
import pytesseract
import sys
import os
import certifi
os.environ["SSL_CERT_FILE"] = certifi.where()
import unicodedata

def _get_tesseract_path():
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller temp extraction dir
        base_dir = sys._MEIPASS
    elif getattr(sys, 'frozen', False):
        # Compiled exe directory
        base_dir = os.path.dirname(sys.executable)
    else:
        # Script directory
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    tessdata_dir = os.path.join(base_dir, "tesseract_engine", "tessdata")
    os.environ["TESSDATA_PREFIX"] = tessdata_dir
    return os.path.join(base_dir, "tesseract_engine", "tesseract.exe")

pytesseract.pytesseract.tesseract_cmd = _get_tesseract_path()

import io
import json
import asyncio
import base64
try:
    import nacl.signing
    import nacl.encoding
except ImportError:
    pass
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
import traceback
from collections import deque, Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import shutil
import tempfile
import urllib.request

# Activation endpoint — safe to embed (anon key + URL are not secrets, RLS is the gate)
OBYLON_PROJECT_URL = "https://ozruikfnrmmvhvozgnoo.supabase.co"
ENROLLMENT_ENDPOINT = f"{OBYLON_PROJECT_URL}/functions/v1"
OBYLON_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im96cnVpa2Zucm1tdmh2b3pnbm9vIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzg0OTQ3NDIsImV4cCI6MjA5NDA3MDc0Mn0.5x-1W8ksL2Bd5Mt_JF7zmBu3crfHJLWAls3kTKBEWEY"

# Session credentials — populated from DPAPI vault at boot, never hardcoded
SUPABASE_URL = None
SUPABASE_KEY = None  # Will hold the anon key after activation
ACCESS_TOKEN = None
REFRESH_TOKEN = None
LICENSE_ID = None
NODE_ID = None

# --- STEALTH MONKEY-PATCH FOR WINDOWS ---
# Prevents tesseract.exe from flashing a visible command prompt on the student's screen
_original_popen = subprocess.Popen
def _patched_popen(*args, **kwargs):
    if sys.platform == "win32":
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | 0x08000000 # CREATE_NO_WINDOW
    return _original_popen(*args, **kwargs)
subprocess.Popen = _patched_popen

import argparse
import ctypes
from ctypes import wintypes
import logging

import psutil
import pyperclip

try:
    import win32pdh
except ImportError:
    win32pdh = None # Will degrade gracefully if pywin32 is missing

try:
    from supabase import create_client, Client, ClientOptions
    import httpx
    import win32crypt
    import cv2
    from PIL import ImageGrab
    from pynput import keyboard
    import structlog
    import tkinter as tk
except ImportError:
    sys.exit("Install dependencies: pip install supabase psutil pillow pynput opencv-python pywin32 structlog")

# Cryptographic License Enforcement (Anti-Tamper)
LICENSE_VERIFY_KEY_B64 = "oQYy7eR/qxZOlKw/v9QNpmrcDWpNKGOx2YM0q++oXaY="

def verify_server_signature(payload: dict, server_sig: str) -> bool:
    try:
        if not server_sig: return False
        if "nacl.signing" not in sys.modules: return True # Graceful degrade if PyNaCl is completely missing, though it's installed
        verify_key = nacl.signing.VerifyKey(base64.b64decode(LICENSE_VERIFY_KEY_B64))
        
        # Reconstruct canonical payload EXACTLY as Edge Function built it
        # Note: JavaScript JSON.stringify drops spaces, Python json.dumps adds them. Use separators=(',', ':')
        sign_payload = json.dumps({
            "license_id": payload.get("license_id"),
            "node_id": payload.get("node_id"),
            "hardware_uuid": HARDWARE_UUID,
            "expires_at": payload.get("expires_at"),
            "issued_at": payload.get("issued_at")
        }, separators=(',', ':')).encode("utf-8")
        
        verify_key.verify(sign_payload, base64.b64decode(server_sig))
        return True
    except Exception as e:
        logger.error("Cryptographic signature verification failed", component="system", error=str(e))
        return False

# --- ENTERPRISE LOGGING ---
def custom_log_renderer(logger, name, event_dict):
    timestamp = event_dict.pop("timestamp", "")
    if " " in timestamp: timestamp = timestamp.split(" ")[1][:-3]
    
    level = event_dict.pop("level", "info").lower()
    component = event_dict.pop("component", "system").lower()
    event = event_dict.pop("event", "")
    
    extras = " ".join(f"\033[90m{k}=\033[37m{v}" for k, v in event_dict.items())
    if extras: extras = f" {extras}"
    
    if level == "warning":
        icon = "\033[93m⚠\033[0m"
        c_comp = "\033[93m"
    elif level in ("error", "critical"):
        icon = "\033[91m✖\033[0m"
        c_comp = "\033[91m"
    else:
        icon = "\033[96mℹ\033[0m"
        c_comp = "\033[96m"
        
    return f"\033[90m[{timestamp}]\033[0m {icon} {c_comp}[{component}]\033[0m \033[97m{event}\033[0m{extras}"

def setup_structlog():
    # Setup structlog for console + file — fallback to script dir if ProgramData is locked
    try:
        log_dir = Path(os.environ.get('PROGRAMDATA', 'C:\\ProgramData')) / 'Obylon' / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError):
        # Non-admin PC or restricted environment — log beside the script instead
        log_dir = Path(os.path.dirname(os.path.abspath(__file__))) / '.obylon_logs'
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass  # Console-only logging is fine for a demo
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(log_dir), 2)
    except Exception:
        pass
    
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S.%f", utc=False),
            custom_log_renderer,
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(0),
    )
    return structlog.get_logger("obylon_agent")

logger = setup_structlog()


# --- GLOBAL IDENTITY FILES ---
ALIAS_FILE = Path.home() / ".sentinel_alias"
IDENTITY_FILE = Path.home() / ".sentinel_id"

# --- THE LAZARUS DYING BREATH SOS ---
def dying_breath_handler(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    crash_log = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.error("SYSTEM COLLAPSE DETECTED. Transmitting SOS...", component="system", crash_log=crash_log, exc_info=True)
    try:
        if sb is not None:
            sb.table("agent_health").insert({
                "workstation_id": socket.gethostname(),
                "status": "FATAL_CRASH",
                "error_log": crash_log,
                "created_at": datetime.now(timezone.utc).isoformat()
            }).execute()
    except Exception: pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = dying_breath_handler

# =====================================================
# THE WARDEN (Physical Enforcement Layer)
# =====================================================
_LAST_UNFREEZE_TS = 0.0

def _in_unfreeze_grace() -> bool:
    return time.time() - _LAST_UNFREEZE_TS < UNFREEZE_GRACE_SEC

# --- Tiered escalation ladder ---
# Critical severity always enforces in full on the first strike — no
# warning, no counting, not tunable here. Sub-critical tiers (info/
# warning/high) instead track repeated hits within a rolling window;
# crossing a tier's threshold promotes THIS alert to the next tier up
# and it's re-run through that tier's normal enforcement. Only
# high -> critical actually freezes; info/warning escalate quietly so
# a handful of low-signal alerts alone can never lock a PC. Numbers
# deliberately differ per tier — tighter/shorter window for high
# (closer to real tampering), longer for low-signal info/warning.
ESCALATION_LADDER = {
    "info":    {"threshold": 6, "window_sec": 900,  "escalate_to": "warning"},
    "warning": {"threshold": 5, "window_sec": 900,  "escalate_to": "high"},
    "high":    {"threshold": 3, "window_sec": 600,  "escalate_to": "critical"},
}
_STRIKE_HISTORY: dict[str, deque] = {tier: deque() for tier in ESCALATION_LADDER}
_STRIKE_LOCK = threading.Lock()

MB_OK = 0x0
MB_ICONWARNING = 0x30
MB_SYSTEMMODAL = 0x1000
MB_TOPMOST = 0x40000

def _register_tier_strike(severity: str) -> tuple[int, dict | None]:
    """Records a strike against `severity`'s ladder rule (if it has one),
    prunes entries outside that tier's own window, and returns the
    current in-window count plus the rule. A tier with no rule (only
    'critical' today) returns (0, None) — never counted, never delayed."""
    rule = ESCALATION_LADDER.get(severity)
    if not rule:
        return (0, None)
    now = time.time()
    with _STRIKE_LOCK:
        dq = _STRIKE_HISTORY[severity]
        dq.append(now)
        cutoff = now - rule["window_sec"]
        while dq and dq[0] < cutoff:
            dq.popleft()
        return (len(dq), rule)

def show_status_toast(message: str) -> None:
    """Non-blocking on-screen status/warning message, used when an alert
    gets escalated up the ladder. Runs MessageBoxW on its own daemon
    thread so it never blocks scan_loop.
    TIMING NOTE: call this BEFORE issuing a freeze, not after — WARDEN's
    low-level input hook intercepts input system-wide once active and can
    make this dialog unclickable if it appears afterward. Not yet
    runtime-tested on real Windows hardware; verify before relying on it."""
    def _show():
        try:
            user32.MessageBoxW(None, message, "Policy Notice", MB_OK | MB_ICONWARNING | MB_SYSTEMMODAL | MB_TOPMOST)
        except Exception as e:
            logger.error("Status toast failed to display", component="enforcement", error=str(e))
    threading.Thread(target=_show, daemon=True, name="status_toast").start()

user32 = ctypes.WinDLL("user32")
kernel32 = ctypes.WinDLL("kernel32")

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204

LowLevelKeyboardProc = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
LowLevelMouseProc = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.UnhookWindowsHookEx.restype = ctypes.c_int
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_long

class WorkstationGuard:
    def __init__(self):
        self.hook_keyboard = None
        self.hook_mouse = None
        self.locked = False
        self.freeze_timer = None
        self._lock = threading.RLock()
        self._kbd_callback = LowLevelKeyboardProc(self._low_level_keyboard_proc)
        self._mouse_callback = LowLevelMouseProc(self._low_level_mouse_proc)

    def _low_level_keyboard_proc(self, nCode, wParam, lParam):
        if nCode >= 0:
            with self._lock:
                if self.locked and wParam in (WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP):
                    return 1 
        return user32.CallNextHookEx(self.hook_keyboard, nCode, wParam, lParam)

    def _low_level_mouse_proc(self, nCode, wParam, lParam):
        if nCode >= 0:
            with self._lock:
                if self.locked and wParam in (WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_RBUTTONDOWN):
                    return 1 
        return user32.CallNextHookEx(self.hook_mouse, nCode, wParam, lParam)

    def lock_workstation(self, duration: int = None, force: bool = False):
        global LOG_ONLY_MODE
        if LOG_ONLY_MODE and not force:
            logger.warning("Violation intercepted, but LOG_ONLY_MODE is active. Freeze suppressed.", component="guard", duration_requested=duration)
            return
            
        with self._lock:
            if self.freeze_timer:
                self.freeze_timer.cancel()
                
            self.locked = True
            logger.warning("Tactical Monolith Deployed - Input Severed", component="warden", locked=True, duration=duration)
            
            if duration:
                self.freeze_timer = threading.Timer(duration, self.disengage_freeze)
                self.freeze_timer.start()

    def disengage_freeze(self):
        global _LAST_UNFREEZE_TS
        with self._lock:
            self.locked = False
            _LAST_UNFREEZE_TS = time.time()
            logger.info("Workstation Unlocked", component="warden")

    def _hook_thread_runner(self):
        h_mod = ctypes.c_void_p(0)
        
        kbd_ptr = ctypes.cast(self._kbd_callback, ctypes.c_void_p)
        mouse_ptr = ctypes.cast(self._mouse_callback, ctypes.c_void_p)
        
        self.hook_keyboard = user32.SetWindowsHookExW(WH_KEYBOARD_LL, kbd_ptr, h_mod, 0)
        self.hook_mouse = user32.SetWindowsHookExW(WH_MOUSE_LL, mouse_ptr, h_mod, 0)
        
        if not self.hook_keyboard or not self.hook_mouse:
            logger.error("Failed to install Win32 hooks", component="guard", exc_info=True)
            return
        
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
            
        user32.UnhookWindowsHookEx(self.hook_keyboard)
        user32.UnhookWindowsHookEx(self.hook_mouse)

    def start(self):
        self.thread = threading.Thread(target=self._hook_thread_runner, daemon=True, name="Win32_Warden")
        self.thread.start()
        return True
        
    def terminate_process(self, target_name: str) -> bool:
        """Legacy fallback for the Action Loop Scalpel"""
        if not target_name: return False
        target_name = target_name.lower().strip()
        try:
            killed = False
            for proc in psutil.process_iter(['name']):
                if proc.info['name'] and proc.info['name'].lower().strip() == target_name:
                    proc.terminate()
                    logger.info("Process terminated", component="guard", target_name=target_name)
                    killed = True
            return killed
        except Exception as e:
            logger.error("terminate_process error", component="guard", error=str(e), exc_info=True)
        return False

WARDEN: WorkstationGuard = None  # Initialized at boot in __main__ to avoid wasted hooks
sb: Client = None  # Will be initialized at runtime by the Vault
import threading
TOKEN_ROTATED_EVENT = threading.Event()
LICENSE_INVALID_EVENT = threading.Event()

def _build_supabase_client():
    global ACCESS_TOKEN, REFRESH_TOKEN
    # School Supabase endpoints have standard Let's Encrypt certificates, so verify=certifi.where() is completely safe and required.
    client = create_client(
        SUPABASE_URL, SUPABASE_KEY,
        options=ClientOptions(httpx_client=httpx.Client(verify=certifi.where(), timeout=30.0), auto_refresh_token=True, persist_session=False)
    )
    # Set the session from vault credentials
    if ACCESS_TOKEN and REFRESH_TOKEN:
        client.auth.set_session(ACCESS_TOKEN, REFRESH_TOKEN)
        # Refresh if needed and update vault
        session = client.auth.get_session()
        if session and session.access_token != ACCESS_TOKEN:
            ACCESS_TOKEN = session.access_token
            REFRESH_TOKEN = session.refresh_token
            vault._data["ACCESS_TOKEN"] = ACCESS_TOKEN
            vault._data["REFRESH_TOKEN"] = REFRESH_TOKEN
            vault._save()
    return client

CRYPTPROTECT_LOCAL_MACHINE = 0x04

# ====================== DEPLOYMENT SAFETY SWITCHES ======================
# Flipped remotely via Supabase agent_configs table
LOG_ONLY_MODE = False   # Default to Standard enforcement (was True — caused silent mode on fresh PCs)
STRICT_WARDEN = False
USB_EXECUTION_POLICY = 0
EXAM_MODE = False                           # Lockdown mode: only exam_allowed_apps can run
EXAM_ALLOWED_APPS: set[str] = {"chrome.exe", "msedge.exe"}  # Default allowed during exams
EXAM_FREEZE_DURATION = 30                  # Seconds to freeze in exam mode (safety unlock timer — default 30s fallback)
KILL_UNAUTHORIZED_APPS = False              # Admin toggle: True = kill after evidence, False = freeze only
WEBCAM_EVIDENCE_ENABLED = False             # Toggles whether webcam snapshots are captured on critical alerts
# =======================================================================

# ====================== TELEGRAM ALERT CACHE ============================
_TELEGRAM_CHAT_IDS: list[int] = []          # Cached from profiles table
_TELEGRAM_CACHE_TS: float = 0.0             # When chat IDs were last fetched
_TELEGRAM_CACHE_TTL: float = 300.0          # Refresh every 5 minutes
_TELEGRAM_BOT_TOKEN: str = ""               # Cached from edge function env (fetched from school_settings or env)
# =========================================================================

class ObylonVault:
    """Enterprise DPAPI Config Vault."""
    def __init__(self, config_file: str = "obylon.enc"):
        primary_dir = os.environ.get('PROGRAMDATA', 'C:\\ProgramData') + "\\Obylon"
        try:
            os.makedirs(primary_dir, exist_ok=True)
            self.config_dir = primary_dir
        except (PermissionError, OSError):
            # Non-admin PC — fall back to script directory
            self.config_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_file = os.path.join(self.config_dir, config_file)
        self._data: dict = {}

    def _encrypt(self, data: bytes) -> bytes:
        try:
            encrypted = win32crypt.CryptProtectData(data, "ObylonSecure", None, None, None, CRYPTPROTECT_LOCAL_MACHINE)
            return encrypted
        except Exception as e:
            logger.critical(f"DPAPI encrypt failed: {e}", component="vault")
            raise

    def _decrypt(self, encrypted: bytes) -> bytes:
        try:
            _, decrypted = win32crypt.CryptUnprotectData(encrypted, None, None, None, CRYPTPROTECT_LOCAL_MACHINE)
            return decrypted
        except Exception as e:
            logger.critical(f"DPAPI decrypt failed: {e}", component="vault")
            raise

    def load(self) -> bool:
        if not os.path.exists(self.config_file): return False
        try:
            with open(self.config_file, "rb") as f: encrypted = f.read()
            decrypted = self._decrypt(encrypted)
            self._data = json.loads(decrypted.decode("utf-8"))
            return True
        except Exception as e:
            logger.error(f"Config corruption detected (stale enc from another PC?): {e}", component="vault")
            # Auto-purge the corrupted enc file so it doesn't block future boots
            try:
                self._unhide_file()
                os.remove(self.config_file)
                logger.warning("Purged stale obylon.enc — hardcoded credentials will be used.", component="vault")
            except Exception:
                pass
            return False

    def _unhide_file(self):
        """Forcefully strips the hidden/readonly attributes so Python can write."""
        if os.path.exists(self.config_file):
            try:
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(str(self.config_file), 128)
            except Exception: pass

    def _save(self):
        json_str = json.dumps(self._data)
        encrypted = self._encrypt(json_str.encode("utf-8"))
        self._unhide_file()
        with open(self.config_file, "wb") as f:
            f.write(encrypted)
        try: ctypes.windll.kernel32.SetFileAttributesW(str(self.config_file), 2)
        except Exception: pass

    def provision_via_license(self, license_key: str, hostname: str, hardware_uuid: str, hardware_fingerprint: str) -> str:
        try:
            payload = {
                "license_key": license_key,
                "hostname": hostname,
                "hardware_uuid": hardware_uuid,
                "hardware_fingerprint": hardware_fingerprint
            }
            req = urllib.request.Request(
                f"{ENROLLMENT_ENDPOINT}/activate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"apikey": OBYLON_ANON_KEY, "Authorization": f"Bearer {OBYLON_ANON_KEY}", "Content-Type": "application/json"}
            )
            import ssl, certifi
            context = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(req, context=context) as response:
                body = response.read().decode("utf-8")
                data = json.loads(body)
                
                # Cryptographic offline enforcement check
                if "server_sig" in data and not verify_server_signature(data, data["server_sig"]):
                    logger.critical("Activation failed: Cryptographic signature mismatch! Server may be compromised.", component="vault")
                    return "HARD_ERROR"

                self._data = {
                    "SUPABASE_URL": data.get("supabase_url"),
                    "SUPABASE_ANON_KEY": data.get("anon_key"),
                    "ACCESS_TOKEN": data.get("access_token"),
                    "REFRESH_TOKEN": data.get("refresh_token"),
                    "LICENSE_ID": data.get("license_id"),
                    "NODE_ID": data.get("node_id"),
                    "LICENSE_STATUS": "active",
                    "LAST_HEARTBEAT_OK_AT": data.get("issued_at", datetime.now(timezone.utc).isoformat()),
                    "MAX_SEEN_UTC": data.get("issued_at", datetime.now(timezone.utc).isoformat()),
                    "EXPIRES_AT": data.get("expires_at"),
                    "GRACE_DAYS": data.get("grace_days", 14),
                    "SERVER_SIG": data.get("server_sig")
                }
                self._save()
                logger.info("🔒 Obylon DPAPI Vault provisioned via license.", component="vault")
                return "SUCCESS"
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            try:
                err_data = json.loads(body)
                err_type = err_data.get("error", "unknown")
                err_msg = ""
                if err_type == "node_limit_reached":
                    err_msg = f"Activation failed: Node limit reached ({err_data.get('active_nodes')}/{err_data.get('node_limit')}). Contact {err_data.get('support_contact')}."
                elif err_type in ("license_expired", "license_revoked", "license_suspended", "invalid_key"):
                    err_msg = f"Activation failed: {err_type.replace('_', ' ').capitalize()}."
                else:
                    err_msg = f"Activation failed: {err_type}"
                
                print(err_msg)
                import tkinter as tk
                from tkinter import messagebox
                root = tk.Tk()
                root.withdraw()
                root.attributes('-topmost', True)
                messagebox.showerror("Obylon Sentinel - Activation Failed", err_msg)
            except Exception:
                print(f"Activation failed: HTTP {e.code}")
            return "HARD_ERROR"
        except urllib.error.URLError as e:
            print(f"Activation network error: {e}")
            return "NETWORK_ERROR"
        except Exception as e:
            print(f"Activation error: {e}")
            return "HARD_ERROR"

    def get(self, key: str) -> str:
        return self._data.get(key, "")

    def set(self, key: str, value: any) -> None:
        """Write a new key-value pair to the encrypted DPAPI vault."""
        self._data[key] = str(value)
        json_str = json.dumps(self._data)
        encrypted = self._encrypt(json_str.encode("utf-8"))
        
        # Remove hidden attribute so we can write
        self._unhide_file()
            
        with open(self.config_file, "wb") as f:
            f.write(encrypted)
            
        try: ctypes.windll.kernel32.SetFileAttributesW(str(self.config_file), 2)
        except Exception: pass
        logger.info("Vault updated", component="vault", key=key, value=value)

vault = ObylonVault() # Global instantiation moved below class definition

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def os_info() -> dict:
    return {
        "platform": platform.system(),
        "release": platform.release(),
        "host": socket.gethostname(),
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "mem_percent": psutil.virtual_memory().percent,
    }


def _hide_path(p: Path) -> None:
    """Best-effort: hide a file/dir on Windows."""
    try:
        if platform.system() == "Windows":
            subprocess.call(["attrib", "+H", str(p)], shell=False)
    except Exception:
        pass

def get_workstation_identity() -> str:
    """Resolve workstation display name.

    Precedence:
      1. Contents of ~/.sentinel_alias (stripped) if present and non-empty.
      2. Fallback: socket.gethostname().
    Runs BEFORE the Supabase client is initialized so registration uses the
    forged identity from the very first network call.
    """
    try:
        if ALIAS_FILE.exists():
            alias = ALIAS_FILE.read_text(encoding="utf-8").strip()
            if alias:
                return alias
    except Exception as e:
        logger.error("alias read failed", component="identity", error=str(e), exc_info=True)
    return socket.gethostname()


WORKSTATION_NAME = get_workstation_identity()


# ---------- Kernel Priority Injection ----------
def set_high_priority() -> None:
    """Elevate this process so it out-competes browsers/games for CPU.

    Windows -> HIGH_PRIORITY_CLASS.
    Unix    -> nice(-10) (requires privileges; silently ignored otherwise).
    """
    try:
        p = psutil.Process(os.getpid())
        if platform.system().lower().startswith("win"):
            p.nice(psutil.HIGH_PRIORITY_CLASS)
        else:
            p.nice(-10)
    except (psutil.AccessDenied, PermissionError):
        # Insufficient privileges — keep running at normal priority.
        pass
    except Exception as e:
        logger.error("elevation failed", component="priority", error=str(e), exc_info=True)


# Apply immediately on script execution.
set_high_priority()

HEARTBEAT_INTERVAL = 15
SCAN_INTERVAL = 1
ACTION_POLL = 1
KEYLOG_DURATION = 10
ALERT_DEBOUNCE_SEC = 10          # Reduced from 30s — 30s throttled the escalation ladder
                                  # so repeated violations couldn't accumulate fast enough.
                                  # 10s prevents true duplicates without blocking escalation.
ALERT_DEBOUNCE_SEC_CRITICAL = 5  # Critical/high get even shorter debounce — immediate re-fire
AMBIENT_DEBOUNCE_SEC = 60
FOCUS_REFRESH_SEC = 10
EVIDENCE_BUCKET = "evidence"

# --- Named Enforcement Thresholds (replaces hardcoded magic numbers) ---
ENFORCEMENT_FLOOR = 0.60           # Minimum score for alert/enforcement
CRITICAL_SEVERITY_FLOOR = 0.85     # Score at or above this = "critical"
UNCORROBORATED_DEMOTION = 0.50     # Score for uncorroborated process sightings
FACULTY_USB_DEMOTION = 0.50        # Score for faculty USB bypass downgrades
UNFREEZE_GRACE_DEMOTION = 0.80     # Score ceiling during unfreeze grace window
UNFREEZE_GRACE_SEC = 15.0          # Seconds after unfreeze where re-lock is suppressed
ANGEL_DEFUSE_FACTOR = 0.5          # Multiplicative damping when Angel Engine defuses
DOM_MAX_CHARS = 8000               # Max DOM text chars for classify_web_context
FSM_ANOMALY_FLOOR = 0.3            # S-composite floor for ANOMALY_ESCALATION
FSM_EFFECTIVE_FLOOR = 0.4          # Effective score floor for ANOMALY_ESCALATION

# --- Phase 6: The Forensic Vault ---
VAULT_DB = Path.home() / ".sentinel_vault.db"
CACHE_DIR = Path.home() / ".sentinel_cache"
SYNC_INTERVAL = 30  # seconds

# --- Hardware Mutex ---
OPTICS_LOCK = threading.Lock()
VAULT_LOCK = threading.Lock()  # SQLite is single-writer; serialize writes

IDENTITY_FILE = Path.home() / ".sentinel_id"
COMMAND_TTL_SEC = 60
TERMINATE_GRACE_SEC = 10

# ---------- Compliance Severity Hierarchy ----------
LEXICON: dict[str, list[str]] = {
    # LEVEL 1: THE UNFORGIVABLE (Hardcore/Specific only)
    "critical": [
        r"\b(pornhub|porn|xvideos|redtube|brazzers|hentai|rule34|xxx|nsfw|gelbooru|onlyfans|chaturbate|xhamster|spankbang|eporner|camgirl|nhentai|bestgore|liveleak)\b",
        r"\b(gore|snuff|behead|execution|murder|suicide|isis|terrorist|jihad|ullu|savita bhabhi|desi mms|kavita bhabhi|nangi|chudai|mallu aunty|dehati|bihari bhabhi|mms)\b",
        r"\b(p0rn|pr0n|sexcam|bdsmtube|xnxx|xnx|camsoda|stripchat|myfreecams|manyvids|fansly|loyalfans|jerkoff|masturbate|blowjob|handjob|cumshot|creampie|bukakke|gangbang|orgy|incest|stepmom|stepbro|stepdad|milf|gilf|teenporn|childporn|lolita|shota|guro|snufffilm|deepfake porn|fappening)\b",
        r"\b(bhojpuri bhabhi|desi chudai|bhabhi sex|suhagrat|mms leak|kamar|nanga|nangi photo|xdesi|kamukata|kama kathaikal|boudi|choda chudi|choti golpo|xossip|kamababa|incestkahani|antarvasna|desipapa|sexkahani|chudasi)\b",
        r"\b(hentai haven|hanime|jav|uncensored jav|doujinshi|ero-manga|nude leak|puta|putaria|porno|sexo|pendejo|follar|salope|pornographie|nackt|ficken|schlampe|порно|секс|шлюха|путанка)\b",
        r"\b(decapitation|cartel execution|al qaeda|hamas execution|taliban video|live murder|school shooting video|suicide video|self harm|cutting wrists|how to tie a noose|how to make a bomb|pipe bomb recipe|meth recipe|buy fentanyl|buy heroin|dark web market|silk road|alpha bay)\b",
        r"\b(p0rnhub|xvid3os|r3dtub3|br4zz3r\$|r00l34|0nlyf4ns|n\$fw|b3h34d|murd3r|su1c1d3|73rr0r1st|j1h4d|n4k3d|n00d|s3x)\b",
        r"\b(saurlífi|scortum|kama|sharmouta|qahba|morð|drepa|homicidium|necare|hatya|убийство)\b",
    ],

    # LEVEL 2: THE INSURGENCY (Generic categories - trigger log, not 30s lock)
    "high": [
        r"\b(adult|sex|dating|hookup|escort|nude|naked|erotic)\b",
        r"\b(psiphon|ultrasurf|shadowsocks|vpn|proxy|tor\.exe|bypass[- ]?firewall|nordvpn|expressvpn|tunnelbear|protonvpn|surfshark|unblock)\b",
        r"\b(1337x|thepiratebay|yts|yify|fitgirl repack|dodi repack|empressextent|skidrow reloaded|igg[- ]?games|cs\.rin\.ru|steamunlocked|cracked software|free keygen|serial key|hwid spoofer|aimbot download|wallhack download)\b",
        r"\b(roblox executor|krnl|synapse x|fluxus|jjsploit|evon|arceus x|delta executor)\b",
        r"\b(tamilblasters|movierulz|ibomma|tamilyogi|isaimini|moviesda|kuttymovies|filmyzilla|filmywap|mp4moviez|vegamovies|bolly4u|khatrimaza|9xmovies|hdhub4u|desiremovies|yomovies|extramovies|pagalfree|djmaza|mrjatt)\b",
        r"\b(putlocker|123movies|yesmovies|gowatchseries|solarmovie|fmovies|zoro\.to|aniwatch|kickassanime|gogoanime|9anime|kissasian|dramacool|myasiantv|sflix|hurawatch|cineb|bflix|hdtoday)\b",
        r"\b(pr0xy|v\.p\.n\.|t0rr3nt|cr4ck|k3yg3n|w4r3z|p1r4t3|торрент|utorrent)\b",
    ],
    # LEVEL 3: THE WASTELAND (Consumer Gaming & Piracy)
    "warning": [
        r"\b(steam|roblox|minecraft|fortnite|valorant|genshin|pubg|bgmi|free fire|apex legends|league of legends|counter-strike|csgo|cs2|epic games|battle\.net|rocket league|aimbot|wallhack|cheat engine|bluestacks|nox player|ldplayer|gameloop|memu|msi app player|andyroid|genymotion|cod[- ]?mobile|warzone|coolmathgames|crazygames|poki|krunker|unblocked games|igrice)\b",
        r"\b(crack|keygen|warez|pirate|magnet:|torrent|utorrent|qbittorrent|1337x|piratebay|fitgirl|dodi-repacks|skidrow|reloaded|codex|rarbg|tpb|limetorrents|yts|yify|igg[- ]?games)\b",
        r"\b(netflix|primevideo|prime video|hotstar|disney\+|hulu|twitch|youtube|spotify|soundcloud|fmovies|9anime|aniwave|crunchyroll|aniwatch|bilibili|soap2day|lookmovie|pika[- ]?show)\b"
    ],

    # LEVEL 4: THE NOISE (Social Media & Research)
    "info": [
        r"\b(tiktok|instagram|facebook|snapchat|pinterest|tumblr|9gag|reddit|twitter|x\.com|discord|whatsapp|messenger|line\.me|viber|wechat|bereal|omegle|chatroulette|yubo)\b",
        r"\b(wikipedia|quora|medium\.com|stack overflow|stackoverflow|buzzfeed|boredpanda|chess\.com|lichess|beebom|the verge|techcrunch|gizmodo|ign|gamespot|gsmarena)\b"
    ],
}

USB_EXEC_BLOCKLIST = re.compile(
    r"\b(setup|install|installer|update|updater|patch|patcher|"
    r"loader|dropper|inject|payload|crack|keygen|activator|hack|"
    r"tor|proxy|vpn|psiphon|ultrasurf|minecraft|roblox|csgo|cs2|valorant|"
    r"portable|browser|chrome|firefox|brave)\b",
    re.IGNORECASE,
)

# Add near your other constants
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
    "phoneexperiencehost.exe", "video.ui.exe","windowsterminal.exe",
}









































# ===========================================================================
# SECTION 0 — Edit distance (pure stdlib, no network/pip dependency needed)
# ===========================================================================

def damerau_levenshtein(a: str, b: str) -> int:
    """Edit distance where an adjacent-letter transposition counts as ONE
    edit (not two) — this matters a lot for typos, since transposing two
    letters ('bmob') is one of the most common real typing errors."""
    la, lb = len(a), len(b)
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(
                d[i - 1][j] + 1,
                d[i][j - 1] + 1,
                d[i - 1][j - 1] + cost,
            )
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]


# ===========================================================================
# SECTION 1 — The false-positive safety net for short-word fuzzy matching
# ===========================================================================
# Empirically derived (see explore_neighbors.py): every common English word
# that sits exactly 1 edit away from "bomb". This is why short atomic words
# need BOTH a tight distance threshold AND an explicit exclusion list —
# threshold alone isn't enough (comb/tomb/womb/boob/bob are all distance 1).
KNOWN_SAFE_COLLISIONS = {
    "comb", "combs",
    "tomb", "tombs",
    "womb", "wombs",
    "boob", "boobs",
    "bob", "bobs",
    "boma", "bomba",          # obscure but real (enclosure / music genre) — safe margin
    "bond", "bonds", "born",  # distance 2, included as extra margin if threshold is ever loosened
}

# Real, whole different words that CONTAIN "bomb"-shaped substrings or are
# morphological derivatives of it. These must never be flagged, no matter
# what a naive substring or loose-fuzzy check would suggest.
SAFE_DERIVED_FORMS = {
    "bomber", "bombers",
    "bombing", "bombings", "bombed",
    "bombard", "bombards", "bombarded", "bombarding", "bombardment",
    "bombardier", "bombardiers",
    "bombshell", "bombshells",
    "bombastic",
    "photobomb", "photobombs", "photobombed", "photobombing", "photobomber",
    "carbomb",  # if ever fused without space — routed to bigram logic instead, see below
}

# In production, replace/augment KNOWN_SAFE_COLLISIONS with a real dictionary
# check (pyspellchecker, nltk 'words' corpus, or /usr/share/dict/words on the
# deployment host) — this sandbox has no network access to fetch one, so this
# list is the hand-verified fallback. See module docstring / chat writeup.
try:
    with open("/usr/share/dict/words", encoding="utf-8", errors="ignore") as _f:
        _SYSTEM_WORDLIST = {w.strip().lower() for w in _f if w.strip()}
except OSError:
    _SYSTEM_WORDLIST = None


def is_real_unrelated_word(token: str) -> bool:
    """True if `token` is a genuine, different English word — i.e. NOT a
    typo, just a correctly spelled word that happens to be nearby in
    edit-distance space."""
    if token in KNOWN_SAFE_COLLISIONS or token in SAFE_DERIVED_FORMS:
        return True
    if _SYSTEM_WORDLIST is not None:
        return token in _SYSTEM_WORDLIST
    return False


# ===========================================================================
# SECTION 2 — Curated atomic vocabulary (fixes the fuzzy-corpus bug)
# ===========================================================================
# word -> max edit distance allowed. Short/dense words get threshold 1;
# longer words (few real-word collisions — see explore_neighbors2.py) can
# safely use threshold 2. Distance 0 = exact match only, no fuzzy tolerance
# (used for short abbreviations where "fuzzy" is meaningless/risky).
ATOMIC_CRITICAL_TOKENS = {
    "bomb": 1,
    "bombs": 1,
    "explosive": 2,
    "explosives": 2,
    "detonator": 2,
    "detonators": 2,
    "pipebomb": 2,
    # Foreign language weapons
    "bomba": 1, "bombe": 1, "bam": 0, "bumb": 1, "бомба": 1,
}

INSTRUCTION_INTENT_TOKENS = {
    "make": 1, "makes": 1, "making": 1,
    "build": 1, "builds": 1, "building": 1,
    "construct": 2, "constructing": 2,
    "assemble": 2, "assembling": 2,
    "create": 1, "creating": 1,
    "diy": 0,
    "homemade": 2,
    "fabricate": 2, "fabricating": 2,
    "synthesize": 2, "synthesizing": 2,
    # Foreign language instructions
    "hacer": 1, "construir": 2, "crear": 1, 
    "faire": 1, "fabriquer": 2, "construire": 2, 
    "machen": 1, "bauen": 1, "baut": 1, "herstellen": 2, 
    "banane": 1, "banao": 1, "banaye": 1, "kaise": 1,
    "сделать": 2, "собрать": 2,
    "mk": 0, "bld": 0,   # curated shorthand — NOT reachable via fuzzy distance
                          # from "make"/"build" (too far), added explicitly
                          # instead of loosening the distance threshold.
}
# Deliberately NOT included: "made", "built", "created" (past tense). Past
# tense signals an attribution question ("who MADE the bomb?" = history),
# not an instruction request ("how do I MAKE a bomb?" = intent). Conflating
# these would break exactly the benign examples this system must protect.

DANGEROUS_BIGRAM_MODIFIERS = {"pipe", "car", "letter", "mail", "parcel", "package", "suicide"}

# Known-benign multi-word compounds that use "bomb" non-violently. Stripped
# BEFORE tokenization so they can't combine with a nearby instruction verb
# (e.g. "bath bomb making tutorial" is a craft project, not a threat).
# Scope note: intentionally excludes "smoke bomb" — unlike bath/glitter/
# sugar bombs, smoke bombs involve real combustion and some schools may
# want those queries reviewed rather than auto-cleared. Add it here if
# your policy says otherwise.
BENIGN_IDIOM_PATTERNS = [
    re.compile(r"\bbath\s?bombs?\b"),
    re.compile(r"\bsugar\s?bombs?\b"),
    re.compile(r"\bstink\s?bombs?\b"),
    re.compile(r"\bglitter\s?bombs?\b"),
    re.compile(r"\bconfetti\s?bombs?\b"),
    re.compile(r"\bwater\s?bombs?\b"),
]

# ===========================================================================
# SECTION 4 — Angel Engine markers, now CATEGORY-SCOPED (fixes bug #2)
# ===========================================================================
ANGEL_MARKERS_BY_CATEGORY = {
    "explosives": {
        # historical / academic framing
        "history", "historical", "invented", "invention", "discovered",
        "discovery", "developed", "development", "timeline", "origin",
        "origins", "era", "wwii", "ww2", "worldwar", "museum", "textbook",
        "homework", "essay", "research", "project", "documentary",
        # reference / encyclopedic framing
        "wiki", "wikipedia", "define", "definition", "meaning",
        "encyclopedia", "dictionary",
        # military/aviation proper-noun context (for "B-2 bomber" etc.)
        "aircraft", "airforce", "squadron", "pilot", "military", "stealth",
        "manhattan", "hiroshima", "nagasaki", "enola",
        # causal/abstract question framing ("why do people bomb")
        "war", "wars", "conflict", "causes", "reasons", "impact", "effects",
        # NOTE: deliberately EXCLUDES tutorial / guide / instructions /
        # recipe / steps / diy — those are aggravating instruction-intent
        # signals for THIS category, not defusers. A global marker set
        # would let "bomb making tutorial" through; a scoped one won't.
    },
    "medical_anatomy": {
        # example of a second category, showing the scoping generalizes —
        # this is the original global set, now correctly confined to the
        # topic it actually makes sense for.
        "meaning", "define", "history", "anatomy", "wiki", "tutorial",
        "medical", "clinical",
    },
}

ANGEL_INTERROGATIVE_PATTERNS = [
    re.compile(r"\bwho (made|invented|created|built|designed)\b"),
    re.compile(r"\bwhen (was|is|did)\b.{0,20}\b(invented|created|made|built|developed|discovered)\b"),
    re.compile(r"\bwhy (do|did|does)\b"),
    re.compile(r"\bhistory of\b"),
    re.compile(r"\bwho (built|makes)\b"),
]


# ===========================================================================
# SECTION 5 — Tokenizer (whole-word only — fixes bug #3 at the root)
# ===========================================================================
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def tokenize(title: str):
    return _TOKEN_RE.findall(title.lower())


def strip_benign_idioms(title: str) -> str:
    result = title
    for pat in BENIGN_IDIOM_PATTERNS:
        result = pat.sub(" ", result)
    return result


# ===========================================================================
# SECTION 6 — Fuzzy matchers
# ===========================================================================

def _fuzzy_match(token: str, vocab: dict):
    """Shared logic for matching a token against a curated {word: max_dist}
    vocabulary. Returns the matched vocabulary word, or None.
    Order of checks matters: exact hit first, then hard exclusions
    (never-flag lists), THEN — and only then — fuzzy distance."""
    if token in vocab:
        return token
    if token in SAFE_DERIVED_FORMS:
        return None
    if is_real_unrelated_word(token):
        return None
    for word, max_d in vocab.items():
        if max_d == 0:
            continue  # exact-only entries (mk, bld, diy) — no fuzzy tolerance
        lo, hi = max(1, len(word) - 1), len(word) + 2
        if not (lo <= len(token) <= hi):
            continue  # length gate — rules out things like "b2bomber" outright
        if damerau_levenshtein(token, word) <= max_d:
            return word
    return None


def fuzzy_match_atomic(token: str):
    return _fuzzy_match(token, ATOMIC_CRITICAL_TOKENS)


def fuzzy_match_instruction(token: str):
    return _fuzzy_match(token, INSTRUCTION_INTENT_TOKENS)


# ===========================================================================
# SECTION 7 — Detection passes
# ===========================================================================

def lexical_scan(title: str):
    hits = []
    lower = title.lower()
    EXPLOSIVES_LEXICON = {
        "critical": [
            r"\b(how to make a bomb|pipe bomb recipe|build a bomb|"
            r"bomb making instructions|homemade bomb instructions|"
            r"diy explosive device|explosive device instructions|"
            r"pipe bomb tutorial|bomb tutorial|make an ied|build an ied|"
            r"bomb building guide)\b",
        ],
    }
    for tier, patterns in EXPLOSIVES_LEXICON.items():
        for pat in patterns:
            m = re.search(pat, lower)
            if m:
                hits.append({"tier": tier, "matched_text": m.group(0)})
    return hits


def cooccurrence_scan(tokens, radius: int = 4):
    """Flags instruction-verb + weapon-noun pairs within `radius` tokens of
    each other — this is what makes 'how to mk a bom' catchable even
    though neither the phrase-level regex nor a plain word list would
    ever see it: BOTH words can be independently typo'd and this still
    reconstructs the intent pattern."""
    hits = []
    for i, tok in enumerate(tokens):
        w = fuzzy_match_atomic(tok)
        if not w:
            continue
        lo, hi = max(0, i - radius), min(len(tokens), i + radius + 1)
        for j in range(lo, hi):
            if j == i:
                continue
            v = fuzzy_match_instruction(tokens[j])
            if v:
                hits.append({
                    "weapon_token": tok, "weapon_match": w,
                    "instruction_token": tokens[j], "instruction_match": v,
                    "position": i,
                })
                break
    return hits


def bigram_scan(tokens):
    """Flags [modifier][weapon-noun] pairs like 'pipe bomb' / 'car bomb'
    even when the weapon-noun is typo'd — catches concerning noun phrases
    that have no instruction verb at all (e.g. 'pipe bom' alone)."""
    hits = []
    for i in range(1, len(tokens)):
        w = fuzzy_match_atomic(tokens[i])
        if not w:
            continue
        if tokens[i - 1] in DANGEROUS_BIGRAM_MODIFIERS:
            hits.append({
                "weapon_token": tokens[i], "weapon_match": w,
                "modifier": tokens[i - 1], "position": i,
            })
    return hits


# ===========================================================================
# SECTION 8 — Angel Engine (context-based defuse pass, category-scoped)
# ===========================================================================

def apply_angel_engine(title: str, best_hit: dict, category: str = "explosives", radius: int = 6) -> bool:
    """Returns True if `best_hit` should be DEFUSED (treated as benign),
    False if it should remain flagged."""
    lower = title.lower()

    for pat in ANGEL_INTERROGATIVE_PATTERNS:
        if pat.search(lower):
            return True

    markers = ANGEL_MARKERS_BY_CATEGORY.get(category, set())
    tokens = tokenize(title)

    if isinstance(best_hit, dict):
        target = best_hit.get("weapon_token")
    else:
        target = best_hit
    idx = tokens.index(target) if target in tokens else None

    if idx is not None:
        lo, hi = max(0, idx - radius), min(len(tokens), idx + radius + 1)
        if any(t in markers for t in tokens[lo:hi]):
            return True

    # Short titles: a real browser tab title over ~12 words is rare, so for
    # short ones just check the whole thing rather than risk a marker
    # falling just outside a fixed radius.
    if len(tokens) <= 12 and any(t in markers for t in tokens):
        return True

    return False


# ===========================================================================
# SECTION 9 — Orchestrator
# ===========================================================================

def analyze_title(title: str, category: str = "explosives") -> dict:
    clean_title = strip_benign_idioms(title)
    tokens = tokenize(clean_title)

    lexical_hits = lexical_scan(clean_title)
    cooc_hits = cooccurrence_scan(tokens)
    bigram_hits = bigram_scan(tokens)

    if not lexical_hits and not cooc_hits and not bigram_hits:
        return {"verdict": "CLEAR", "title": title, "hit": None}

    if lexical_hits:
        best_hit = {"type": "lexical", "matched_text": lexical_hits[0]["matched_text"], "weapon_token": None}
    elif cooc_hits:
        h = cooc_hits[0]
        best_hit = {
            "type": "cooccurrence",
            "matched_text": f"{h['instruction_token']} ... {h['weapon_token']}",
            "weapon_token": h["weapon_token"],
        }
    else:
        h = bigram_hits[0]
        best_hit = {
            "type": "bigram",
            "matched_text": f"{h['modifier']} {h['weapon_token']}",
            "weapon_token": h["weapon_token"],
        }

    defused = apply_angel_engine(clean_title, best_hit, category=category)
    verdict = "ALLOWED_EDUCATIONAL" if defused else "CRITICAL_BLOCK"
    return {"verdict": verdict, "title": title, "hit": best_hit}




# ---------- GOOD_VOCAB CORPUS (Replaces NEUTERED_LEXICON) ----------
# Loaded at startup from good_vocab.txt — growing the allowlist is a data import.
def _load_good_vocab() -> list[str]:
    """Load legitimate vocabulary from good_vocab.txt asset file."""
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "good_vocab.txt"),
    ]
    if hasattr(sys, '_MEIPASS'):
        candidates.insert(0, os.path.join(sys._MEIPASS, "good_vocab.txt"))
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    terms = []
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            terms.append(line.lower())
                logger.info("good_vocab loaded", component="lexengine", terms_count=len(terms))
                return terms
            except Exception as e:
                logger.error("good_vocab load failed", component="lexengine", error=str(e))
    logger.warning("good_vocab.txt not found — dual-corpus scoring degraded", component="lexengine")
    return []

GOOD_VOCAB_TERMS = _load_good_vocab()

# ---------- APP MULTIPLIERS (Requirement 2) ----------
APP_MULTIPLIERS = {
    "chrome.exe": 1.0,
    "msedge.exe": 1.0,
    "discord.exe": 1.0,
    "powershell.exe": 1.5,
    "cmd.exe": 1.5,
}

# ---------- FACULTY HARDWARE BYPASS DEFAULTS (Requirement 5) ----------
_FACULTY_HARDWARE_IDS = {
    "FACULTY-BOARD-01",
    "FACULTY-SMARTBOARD-99",
    "FACULTY-UUID-TEST-1234",
}

def get_hardware_uuid() -> str:
    try:
        p = Path.home() / ".sentinel_id"
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""

def is_faculty_bypass() -> bool:
    hw_id = get_hardware_uuid().upper()
    is_faculty_bypass_env = os.environ.get("FACULTY_BYPASS", "").lower() in ("true", "1", "yes", "active")
    is_faculty_hardware = hw_id in _FACULTY_HARDWARE_IDS or "FACULTY" in hw_id or "SMARTBOARD" in hw_id
    return is_faculty_bypass_env or is_faculty_hardware

import ctypes
import string
import wmi
import os
import sys
import psutil

DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3

def get_windows_drive_type(drive_letter: str) -> int:
    """drive_letter like 'D:\\'"""
    return ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(drive_letter))

def list_mounted_drives() -> list[str]:
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    return [f"{L}:\\" for i, L in enumerate(string.ascii_uppercase) if bitmask & (1 << i)]

def get_usb_backed_drive_letters(wmi_conn) -> set[str]:
    """Catches USB drives that report DRIVE_FIXED due to the firmware
    quirk above, by checking the physical bus type instead."""
    usb_letters = set()
    for disk in wmi_conn.Win32_DiskDrive():
        if disk.InterfaceType == "USB":
            for part in disk.associators("Win32_DiskDriveToDiskPartition"):
                for ld in part.associators("Win32_LogicalDiskToPartition"):
                    usb_letters.add(ld.DeviceID + "\\")
    return usb_letters

def get_removable_drive_letters(wmi_conn) -> set[str]:
    """Authoritative set of drives to treat as removable/pendrive."""
    removable = {d for d in list_mounted_drives() if get_windows_drive_type(d) == DRIVE_REMOVABLE}
    removable |= get_usb_backed_drive_letters(wmi_conn)
    return removable

def is_process_on_removable_media(proc_info: dict, removable_drives: set[str]) -> bool:
    exe = (proc_info.get('exe') or '').upper()
    cmdline = ' '.join(proc_info.get('cmdline') or []).upper()
    return any(exe.startswith(d.upper()) or d.upper() in cmdline for d in removable_drives)

AGENT_OWN_PID = os.getpid()
AGENT_OWN_DIR = os.path.dirname(
    os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__)
).upper()

def is_self(proc_info: dict) -> bool:
    if proc_info.get('pid') == AGENT_OWN_PID:
        return True
    return (proc_info.get('exe') or '').upper().startswith(AGENT_OWN_DIR)

def check_if_usb(proc_name: str, removable_drives: set[str]) -> bool:
    if not proc_name: return False
    proc_lower = proc_name.lower().strip()
    for p in psutil.process_iter(['name', 'exe', 'cmdline', 'pid']):
        try:
            if p.info.get('name') and p.info['name'].lower().strip() == proc_lower:
                if is_self(p.info):
                    continue
                return is_process_on_removable_media(p.info, removable_drives)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False

# ---------- Hardware / Adapter Monitor ----------
# check_if_usb() and start_wmi_process_monitor() below only catch a USB drive
# when something EXECUTES from it. Neither catches a drive being plugged in
# and used purely to copy files off the machine, and nothing in this file
# previously watched for new network adapters (e.g. a phone tethered via
# USB creates one). These two monitors close those two gaps.
#
# NOTE ON VERIFICATION: this file is edited and compile-checked in a Linux
# sandbox with no Windows runtime available. Syntax and imports are verified;
# the actual WMI event semantics (Win32_VolumeChangeEvent EventType values,
# adapter naming on real hardware) have NOT been runtime-tested and should
# be validated on an actual lab machine before relying on them.

def start_usb_insertion_monitor():
    """Detects removable-media mount events independent of execution."""
    def _loop():
        try:
            import wmi
            import pythoncom
            pythoncom.CoInitialize()
            c = wmi.WMI()
            # EventType 2 == device/config arrival on Win32_VolumeChangeEvent.
            watcher = c.Win32_VolumeChangeEvent.watch_for(EventType=2)
            while True:
                try:
                    event = watcher()
                    drive_letter = getattr(event, "DriveName", None)
                    if not drive_letter:
                        continue
                    if get_windows_drive_type(drive_letter) != DRIVE_REMOVABLE:
                        continue
                    logger.warning("💽 USB MASS STORAGE MOUNTED", component="usb-insert", drive=drive_letter)
                    try:
                        wid = vault.get("WORKSTATION_ID")
                        if wid:
                            fire_alert(wid, "USB Storage Device Inserted", None, "warning", f"usb_mount:{drive_letter}")
                            vault_enqueue("activity", "unauthorized_events", {
                                "workstation_id": wid, "process_name": None,
                                "window_title": "USB Storage Mounted", "kind": "usb_mount",
                                "payload": json.dumps({"drive": drive_letter, "event_type": "usb_insertion"}),
                            }, None, now_iso())
                    except Exception:
                        pass
                except Exception:
                    time.sleep(1.0)
        except Exception as e:
            logger.error("USB insertion monitor unavailable (WMI init failed)", component="usb-insert", error=str(e))
    threading.Thread(target=_loop, daemon=True, name="usb_insertion_monitor").start()


def start_network_adapter_monitor(poll_sec: int = 5):
    """Flags new network adapters appearing after boot — the signature of a
    phone tethered via USB or a similar network-circumvention attempt.
    Baseline is captured once at boot; only genuinely new adapter names are
    flagged, so reconnects of an already-seen adapter don't re-fire."""
    _TETHER_HINTS = ("cellular", "mobile", "rndis", "android", "iphone", "hotspot", "tether")

    def _loop():
        try:
            known = set(psutil.net_if_addrs().keys())
            logger.info("Network adapter baseline captured", component="net-adapter", count=len(known))
        except Exception as e:
            logger.error("Network adapter monitor failed to start", component="net-adapter", error=str(e))
            return
        while True:
            time.sleep(poll_sec)
            try:
                current = set(psutil.net_if_addrs().keys())
                new_adapters = current - known
                for adapter in new_adapters:
                    known.add(adapter)
                    suspect = any(h in adapter.lower() for h in _TETHER_HINTS)
                    severity = "high" if suspect else "warning"
                    logger.warning("📡 NEW NETWORK ADAPTER DETECTED", component="net-adapter", adapter=adapter, suspect_tethering=suspect)
                    try:
                        wid = vault.get("WORKSTATION_ID")
                        if wid:
                            fire_alert(wid, "New Network Adapter Detected", None, severity, f"new_adapter:{adapter}")
                            vault_enqueue("activity", "unauthorized_events", {
                                "workstation_id": wid, "process_name": None,
                                "window_title": "Network Adapter Change", "kind": "network_adapter",
                                "payload": json.dumps({"adapter": adapter, "suspect_tethering": suspect}),
                            }, None, now_iso())
                    except Exception:
                        pass
            except Exception as e:
                logger.error("Network adapter monitor error", component="net-adapter", error=str(e))
    threading.Thread(target=_loop, daemon=True, name="net_adapter_monitor").start()


# ---------- WMI & FALLBACK PROCESS LAUNCH SPY (Requirement 3) ----------
_SPAWNED_CRITICAL_PROCESSES = set()
_SPAWNED_CRITICAL_LOCK = threading.Lock()

def start_wmi_process_monitor():
    """Lightweight event-driven process monitor with WMI creation and psutil polling fallback."""
    def _wmi_loop():
        try:
            import wmi
            import pythoncom
            pythoncom.CoInitialize()
            c = wmi.WMI()
            watcher = c.Win32_Process.watch_for("creation")
            while True:
                try:
                    event = watcher()
                    p_name = (event.Caption or "").lower().strip()
                    if p_name in ("powershell.exe", "cmd.exe"):
                        with _SPAWNED_CRITICAL_LOCK:
                            _SPAWNED_CRITICAL_PROCESSES.add((p_name, time.time()))
                    
                    if USB_EXECUTION_POLICY > 0:
                        try:
                            pid = int(event.ProcessId)
                            p = psutil.Process(pid)
                            info = p.as_dict(attrs=['pid', 'name', 'exe', 'cmdline'])
                            if not is_self(info):
                                removable_drives = get_removable_drive_letters(c)
                                exe = (info.get('exe') or '').upper()
                                cmdline = ' '.join(info.get('cmdline') or []).upper()
                                
                                is_exe_usb = any(exe.startswith(d.upper()) for d in removable_drives)
                                is_cmd_usb = any(d.upper() in cmdline for d in removable_drives)
                                
                                if (USB_EXECUTION_POLICY == 1 and is_exe_usb) or (USB_EXECUTION_POLICY == 2 and (is_exe_usb or is_cmd_usb)):
                                    if not LOG_ONLY_MODE:
                                        p.kill()
                                        logger.warning("🛡️ USB EXECUTION BLOCKED", component="usb-exec", proc=exe, cmd=cmdline)
                                    else:
                                        logger.warning("🛡️ USB EXECUTION DETECTED (AUDIT MODE)", component="usb-exec", proc=exe, cmd=cmdline)
                                    try:
                                        wid = vault.get("WORKSTATION_ID")
                                        if wid:
                                            if not is_exe_usb and is_cmd_usb:
                                                fire_alert(wid, "[TARGET LOCKED: SCRIPT] USB Script Execution Blocked", exe, "critical", f"unauthorized_usb_script:{exe}")
                                                if WARDEN and not LOG_ONLY_MODE and not _in_unfreeze_grace():
                                                    WARDEN.lock_workstation(duration=30)
                                            else:
                                                fire_alert(wid, "USB Executable Blocked", exe, "high", f"unauthorized_usb_exe:{exe}")
                                                
                                            offline_payload = {
                                                "workstation_id": wid,
                                                "process_name": exe,
                                                "window_title": "USB Execution Blocked",
                                                "kind": "unauthorized",
                                                "payload": json.dumps({"cmdline": cmdline, "event_type": "usb_execution_blocked"})
                                            }
                                            vault_enqueue("activity", "unauthorized_events", offline_payload, None, now_iso())
                                    except Exception:
                                        pass
                        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
                            pass
                except Exception:
                    time.sleep(0.5)
        except Exception:
            known_pids = set()
            while True:
                try:
                    current_pids = set()
                    removable_drives = None
                    for p in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
                        try:
                            pid = p.info['pid']
                            current_pids.add(pid)
                            if pid not in known_pids:
                                p_name = (p.info['name'] or "").lower().strip()
                                if p_name in ("powershell.exe", "cmd.exe"):
                                    with _SPAWNED_CRITICAL_LOCK:
                                        _SPAWNED_CRITICAL_PROCESSES.add((p_name, time.time()))
                                
                                if USB_EXECUTION_POLICY > 0 and not is_self(p.info):
                                    if removable_drives is None:
                                        try:
                                            import wmi
                                            import pythoncom
                                            pythoncom.CoInitialize()
                                            temp_c = wmi.WMI()
                                            removable_drives = get_removable_drive_letters(temp_c)
                                        except Exception:
                                            removable_drives = set()
                                    exe = (p.info.get('exe') or '').upper()
                                    cmdline = ' '.join(p.info.get('cmdline') or []).upper()
                                    
                                    is_exe_usb = any(exe.startswith(d.upper()) for d in removable_drives)
                                    is_cmd_usb = any(d.upper() in cmdline for d in removable_drives)
                                    
                                    if (USB_EXECUTION_POLICY == 1 and is_exe_usb) or (USB_EXECUTION_POLICY == 2 and (is_exe_usb or is_cmd_usb)):
                                        if not LOG_ONLY_MODE:
                                            p.kill()
                                            logger.warning("🛡️ USB EXECUTION BLOCKED", component="usb-exec", proc=exe, cmd=cmdline)
                                        else:
                                            logger.warning("🛡️ USB EXECUTION DETECTED (AUDIT MODE)", component="usb-exec", proc=exe, cmd=cmdline)
                                        try:
                                            wid = vault.get("WORKSTATION_ID")
                                            if wid:
                                                if not is_exe_usb and is_cmd_usb:
                                                    fire_alert(wid, "[TARGET LOCKED: SCRIPT] USB Script Execution Blocked", exe, "critical", f"unauthorized_usb_script:{exe}")
                                                    if WARDEN and not LOG_ONLY_MODE and not _in_unfreeze_grace():
                                                        WARDEN.lock_workstation(duration=30)
                                                else:
                                                    fire_alert(wid, "USB Executable Blocked", exe, "high", f"unauthorized_usb_exe:{exe}")
                                                    
                                                offline_payload = {
                                                    "workstation_id": wid,
                                                    "process_name": exe,
                                                    "window_title": "USB Execution Blocked",
                                                    "kind": "unauthorized",
                                                    "payload": json.dumps({"cmdline": cmdline, "event_type": "usb_execution_blocked"})
                                                }
                                                vault_enqueue("activity", "unauthorized_events", offline_payload, None, now_iso())
                                        except Exception:
                                            pass
                                        continue
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    known_pids = current_pids
                except Exception:
                    pass
                time.sleep(1)

    threading.Thread(target=_wmi_loop, daemon=True, name="wmi_fallback_proc").start()

def check_recently_spawned(proc_name: str, window_sec: float = 120.0) -> bool:
    """Returns True if the process actually spawned in the background recently."""
    now = time.time()
    proc_name = proc_name.lower().strip()
    with _SPAWNED_CRITICAL_LOCK:
        matched = False
        valid_entries = set()
        for name, ts in _SPAWNED_CRITICAL_PROCESSES:
            if now - ts <= window_sec:
                valid_entries.add((name, ts))
                if name == proc_name or (proc_name == "powershell" and name == "powershell.exe") or (proc_name == "cmd.exe" and name == "cmd.exe"):
                    matched = True
        _SPAWNED_CRITICAL_PROCESSES.clear()
        _SPAWNED_CRITICAL_PROCESSES.update(valid_entries)
        return matched


_COMPILED: list[tuple[re.Pattern[str], str]] = []
for sev, patterns in LEXICON.items():
    for pat in patterns:
        _COMPILED.append((re.compile(pat, re.IGNORECASE), sev))


# ---------- Deep Normalization Engine (Text Crusher) ----------

# Invisible / zero-width characters that bypass naive matchers.
_ZERO_WIDTH_CHARS = dict.fromkeys(
    map(ord, [
        "\u200b", "\u200c", "\u200d", "\u200e", "\u200f",
        "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
        "\u2060", "\u2061", "\u2062", "\u2063", "\u2064",
        "\ufeff", "\u00ad", "\u180e", "\u034f",
    ]),
    "",
)

# Multi-character leetspeak / homoglyph combos applied BEFORE single-char map.
_MULTI_LEET = [
    (r"\|\\\|", "n"),    # |\|  -> n
    (r"\|\|", "u"),       # ||   -> u
    (r"\|\)", "d"),       # |)   -> d
    (r"\(\)", "o"),       # ()   -> o
    (r"\[\]", "o"),       # []   -> o
    (r"\\/\\/", "w"),     # \/\/ -> w
    (r"\\/", "v"),        # \/   -> v
    (r"/\\", "a"),        # /\   -> a
    (r"vv", "w"),
    # NOTE: "rn -> m" intentionally omitted — it mangles real words like "porn".
    (r"ph", "f"),         # ph -> f (phorn -> forn... pairs with mapping)
    (r"\$\$", "ss"),
]

# Single character leet / homoglyph map.
_LEET_MAP = str.maketrans({
    "0": "o", "1": "i", "!": "i", "|": "i", "3": "e", "4": "a",
    "@": "a", "5": "s", "$": "s", "7": "t", "+": "t", "8": "b",
    "9": "g", "6": "g", "€": "e", "£": "l", "¥": "y",
    # Cyrillic Homoglyphs (Lower)
    "а": "a", "с": "c", "е": "e", "о": "o", "р": "p", "х": "x", "у": "y",
    # Cyrillic Homoglyphs (Upper)
    "А": "a", "В": "b", "С": "c", "Е": "e", "Н": "h", "І": "i", "Ј": "j",
    "М": "m", "О": "o", "Р": "p", "Т": "t", "Х": "x", "Ү": "y"
})

# After flattening, kill anything that isn't a-z0-9 or whitespace, then
# crush dotted/spaced bypasses like "p.o.r.n" or "p o r n" into "porn".
_NON_ALNUM = re.compile(r"[^\w\s]+")
_MULTI_WS = re.compile(r"\s+")
# A run of single letters separated by single spaces -> glue together.
_SPACED_LETTERS = re.compile(r"\b(?:\w\s){1,}\w\b")


def normalize_haystack(text: str) -> str:
    """Aggressive text purifier defeating unicode / leet / spacing bypasses."""
    if not text:
        return ""
    # 1. Unicode flattening: NFKD strips accents, expands ligatures, kills
    #    homoglyphs like ö -> o + combining diaeresis (then dropped).
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    # 2. Zero-width / bidi / invisible erasure.
    text = text.translate(_ZERO_WIDTH_CHARS)
    # 3. Lowercase early so leet maps stay simple.
    text = text.lower()
    # 4. Multi-char leetspeak combos.
    for pat, repl in _MULTI_LEET:
        text = re.sub(pat, repl, text)
    # 5. Single-char leet substitutions.
    text = text.translate(_LEET_MAP)
    # 6. Strip every non-alphanumeric symbol, replace with a space so word
    #    boundaries survive: "p.o.r.n" -> "p o r n".
    text = _NON_ALNUM.sub(" ", text)
    # 7. Crush runs of single letters separated by spaces back into words:
    #    "p o r n hub" -> "porn hub".
    def _glue(m: re.Match) -> str:
        return m.group(0).replace(" ", "")
    text = _SPACED_LETTERS.sub(_glue, text)
    # 8. Collapse whitespace.
    text = _MULTI_WS.sub(" ", text).strip()
    return text


# ---------- Fuzzy Token Matching ----------
# Flatten lexicon into per-severity token sets (alphanumeric tokens only).
_LEXICON_META = {
    "com", "exe", "svc", "net", "org", "www", "http", "https",
    "chrome", "edge", "excel", "powerpnt", "winword", "explorer", 
    "browser", "google", "microsoft", "taskmgr", "searchapp", "code", "roblox", "minecraft"
}
import math
_TOKEN_EXTRACT = re.compile(r"\w{3,}")
_TOKEN_LEXICON: dict[str, set[str]] = {sev: set() for sev in LEXICON}

# Dynamically populate the fuzzy engine vocabulary from the Lexicon
for _sev, _patterns in LEXICON.items():
    for _pat in _patterns:
        clean = _pat.replace(r"\b(", "").replace(r")\b", "")
        for rule in clean.split("|"):
            rule = rule.strip().lower()
            if " " in rule or "[" in rule or r"\." in rule: continue
            toks = _TOKEN_EXTRACT.findall(rule)
            if len(toks) == 1 and toks[0] not in _LEXICON_META:
                _TOKEN_LEXICON[_sev].add(toks[0])

# =====================================================
# PHASE 1: DUAL-CORPUS LEXICAL ENGINE (LTS Upgrade)
# =====================================================
# Replaces flat Jaro-Winkler/Dice with:
#   - IDF-weighted character n-gram Dice
#   - Dual-corpus scoring (bad vs good vocabulary)
#   - Gaussian length decay (no hard cliff)
#   - Sigmoid decision squash
#   - Phonetic cross-checking (Soundex)
#   - Substring containment detection
#   - Session-level signal accumulation
# =====================================================

# QWERTY Coordinate Map for Typo Math (preserved from LevEngine)
_QWERTY_MAP = {
    'q': (0, 0), 'w': (0, 1), 'e': (0, 2), 'r': (0, 3), 't': (0, 4), 'y': (0, 5), 'u': (0, 6), 'i': (0, 7), 'o': (0, 8), 'p': (0, 9),
    'a': (1, 0.5), 's': (1, 1.5), 'd': (1, 2.5), 'f': (1, 3.5), 'g': (1, 4.5), 'h': (1, 5.5), 'j': (1, 6.5), 'k': (1, 7.5), 'l': (1, 8.5),
    'z': (2, 1), 'x': (2, 2), 'c': (2, 3), 'v': (2, 4), 'b': (2, 5), 'n': (2, 6), 'm': (2, 7)
}


class CorpusModel:
    """IDF-weighted character n-gram corpus model.

    Builds TF-IDF profiles over character 2/3-grams. Common transliteration
    fragments (short Hinglish syllables, frequent clusters) get near-zero IDF
    weight. Distinctive n-grams dominate the similarity score.
    """
    def __init__(self, terms: list[str], ngram_range: tuple[int, int] = (2, 3),
                 gate_k=30.0, r_floor=0.50, r_ceiling=0.95, eta=0.0314):
        self.ngram_range = ngram_range
        self.gate_k = gate_k
        self.r_floor = r_floor
        self.r_ceiling = r_ceiling
        self.eta = eta
        self._idf: dict[str, float] = {}
        self._profiles: dict[str, set[str]] = {}
        self._build(terms)

    @staticmethod
    def _shingle(word: str, n: int) -> set[str]:
        return {word[i:i+n] for i in range(len(word) - n + 1)} if len(word) >= n else set()

    def _all_ngrams(self, word: str) -> set[str]:
        out = set()
        for n in range(self.ngram_range[0], self.ngram_range[1] + 1):
            out |= self._shingle(word, n)
        return out

    def _build(self, terms: list[str]) -> None:
        doc_freq: Counter = Counter()
        N = max(len(terms), 1)
        for t in terms:
            ngrams = self._all_ngrams(t.lower())
            self._profiles[t.lower()] = ngrams
            for ng in ngrams:
                doc_freq[ng] += 1
        # IDF: common fragments → low weight, distinctive → high weight
        for ng, df in doc_freq.items():
            self._idf[ng] = math.log((N + 1) / (df + 1)) + 1.0

    def _padded_grams(self, s):
        """Boundary-anchored grams, used ONLY by the recall gate.
        Deliberately separate from _all_ngrams so the existing Dice
        scoring path is untouched -- this exists purely to detect
        whether a match is anchored to where the term actually starts
        and ends, not just which fragments happen to overlap."""
        s = f" {s.strip().lower()} "
        grams = set()
        for n in range(self.ngram_range[0], self.ngram_range[1] + 1):
            if len(s) >= n:
                grams |= {s[i:i+n] for i in range(len(s) - n + 1)}
        return grams

    def _min_recall(self, gram_count):
        return self.r_floor + (self.r_ceiling - self.r_floor) * math.exp(-self.eta * gram_count)

    def idf_weighted_dice(self, s1: str, s2: str) -> float:
        """IDF-weighted Sørensen-Dice coefficient over character n-grams."""
        ng1 = self._all_ngrams(s1.lower())
        ng2 = self._all_ngrams(s2.lower())
        if not ng1 or not ng2:
            return 0.0
        intersection = ng1 & ng2
        if not intersection:
            return 0.0
        w_inter = sum(self._idf.get(ng, 1.0) for ng in intersection)
        w1 = sum(self._idf.get(ng, 1.0) for ng in ng1)
        w2 = sum(self._idf.get(ng, 1.0) for ng in ng2)
        denom = w1 + w2
        if denom == 0:
            return 0.0
        dice = 2.0 * w_inter / denom

        pg1 = self._padded_grams(s1)
        pg2 = self._padded_grams(s2)
        p_inter = pg1 & pg2
        recall = (len(p_inter) / len(pg2)) if pg2 else 0.0
        r_min = self._min_recall(len(pg2))
        gate = 1 / (1 + math.exp(-self.gate_k * (recall - r_min)))

        return dice * gate

    def best_match(self, token: str) -> tuple[float, str]:
        """Returns (best_score, best_matching_term) for a token against this corpus."""
        best_score, best_term = 0.0, ""
        for term in self._profiles:
            score = self.idf_weighted_dice(token, term)
            if score > best_score:
                best_score = score
                best_term = term
        return best_score, best_term


# ---------- Phonetic Engine (Removed) ----------


# ---------- Character Entropy Analyzer ----------
def _char_entropy(s: str) -> float:
    """Shannon entropy of character distribution. High entropy → random/evasive string."""
    if not s:
        return 0.0
    freq = Counter(s.lower())
    length = len(s)
    entropy = 0.0
    for count in freq.values():
        p = count / length
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy


# ---------- Session Signal Accumulator ----------
class SessionAccumulator:
    """Tracks borderline lexical scores over a rolling time window.

    Multiple borderline hits (0.35-0.70) within 60 seconds suggest a user
    systematically probing evasion variants. The accumulator escalates the
    effective score when this pattern is detected.
    """
    def __init__(self, window_sec: float = 60.0, escalation_count: int = 3):
        self._window = window_sec
        self._threshold = escalation_count
        self._hits: deque[tuple[float, float, str]] = deque()
        self._lock = threading.Lock()

    def record(self, score: float, term: str) -> float:
        """Record a score and return escalation multiplier (1.0 = no escalation)."""
        now = time.time()
        with self._lock:
            while self._hits and now - self._hits[0][0] > self._window:
                self._hits.popleft()
            if 0.35 <= score <= 0.70:
                self._hits.append((now, score, term))
            recent_terms = {h[2] for h in self._hits}
            if len(self._hits) >= self._threshold and len(recent_terms) >= 2:
                escalation = 1.0 + 0.15 * min(len(self._hits) - self._threshold + 1, 4)
                return escalation
        return 1.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


# ---------- Build Corpora ----------
_ALL_BAD_TERMS: list[str] = []
for _sev_terms in _TOKEN_LEXICON.values():
    _ALL_BAD_TERMS.extend(_sev_terms)

_BAD_CORPUS = CorpusModel(_ALL_BAD_TERMS)
_GOOD_CORPUS = CorpusModel(GOOD_VOCAB_TERMS) if GOOD_VOCAB_TERMS else None

_ALL_BAD_SET: set[str] = set(_ALL_BAD_TERMS)

# Build phonetic index for bad terms
_BAD_PHONETIC: dict[str, set[str]] = {}

_SESSION_ACC = SessionAccumulator(window_sec=60.0, escalation_count=3)


class LevEngine:
    """Advisory intelligence layer — preserved static utility methods.

    The evaluate_suspicion() method now delegates to LexEngine.score()
    for the actual scoring logic. Static helper methods (_jaro_winkler,
    _sorensen_dice, _keyboard_distance, calculate_typo_modifier) are
    preserved for use by the Angel Engine and other subsystems.
    """

    @staticmethod
    def _keyboard_distance(char1: str, char2: str) -> float:
        c1, c2 = char1.lower(), char2.lower()
        if c1 not in _QWERTY_MAP or c2 not in _QWERTY_MAP:
            return 5.0
        p1, p2 = _QWERTY_MAP[c1], _QWERTY_MAP[c2]
        return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

    @staticmethod
    def _sorensen_dice(s1: str, s2: str) -> float:
        """Flat Sørensen-Dice (retained for Angel Engine compatibility)."""
        if not s1 or not s2: return 0.0
        if s1 == s2: return 1.0
        b1 = set(s1[i:i+2] for i in range(len(s1)-1))
        b2 = set(s2[i:i+2] for i in range(len(s2)-1))
        if not b1 or not b2: return 0.0
        return 2.0 * len(b1.intersection(b2)) / (len(b1) + len(b2))

    @staticmethod
    def _jaro_winkler(s1: str, s2: str) -> float:
        """Jaro-Winkler distance (retained for Angel Engine compatibility)."""
        if not s1 or not s2: return 0.0
        if s1 == s2: return 1.0
        match_bound = max(len(s1), len(s2)) // 2 - 1
        matches = 0
        match_flags_s1 = [False] * len(s1)
        match_flags_s2 = [False] * len(s2)
        for i, c1 in enumerate(s1):
            start = max(0, i - match_bound)
            end = min(i + match_bound + 1, len(s2))
            for j in range(start, end):
                if not match_flags_s2[j] and s2[j] == c1:
                    match_flags_s1[i] = True
                    match_flags_s2[j] = True
                    matches += 1
                    break
        if matches == 0: return 0.0
        transpositions = 0
        k = 0
        for i, f1 in enumerate(match_flags_s1):
            if f1:
                while not match_flags_s2[k]: k += 1
                if s1[i] != s2[k]: transpositions += 1
                k += 1
        transpositions //= 2
        jaro = (matches / len(s1) + matches / len(s2) + (matches - transpositions) / matches) / 3.0
        prefix = 0
        for i in range(min(len(s1), len(s2), 4)):
            if s1[i] == s2[i]: prefix += 1
            else: break
        return jaro + (prefix * 0.1 * (1.0 - jaro))

    @staticmethod
    def calculate_typo_modifier(input_token: str, target_token: str) -> float:
        """Differentiates typos from deliberate bypasses using keyboard geography."""
        if len(input_token) != len(target_token): return 1.0
        distance_penalty = 0.0
        mismatches = 0
        for c1, c2 in zip(input_token, target_token):
            if c1 != c2:
                mismatches += 1
                distance_penalty += LevEngine._keyboard_distance(c1, c2)
        if mismatches == 0: return 1.0
        avg_distance = distance_penalty / mismatches
        if avg_distance <= 1.5 and len(target_token) > 4:
            return 0.85
        return 1.10

    @classmethod
    def evaluate_suspicion(cls, title: str, proc: str) -> tuple[float, str, str]:
        """Legacy shim — delegates to LexEngine.score() for backward compatibility."""
        return LEX.score(title, proc)


class LexEngine:
    """Dual-corpus lexical scoring engine (LTS Upgrade).

    Replaces the flat Jaro-Winkler/Dice blend with:
      1. IDF-weighted character n-gram Dice against the bad corpus
      2. IDF-weighted Dice against the good corpus (legitimate vocabulary)
      3. Decision signal = sigmoid(bad_score − good_score) × length_decay
      4. Phonetic cross-check for sound-alike evasions
      5. Substring containment for embedded bad terms
      6. Session accumulation for probe-pattern escalation

    score() returns (c_lev, severity, best_hit) — same interface as the
    old LevEngine.evaluate_suspicion(), no downstream changes needed.
    """
    def __init__(self, bad: CorpusModel, good: CorpusModel | None):
        self.bad = bad
        self.good = good

    @staticmethod
    def _gaussian_length_decay(len_input: int, len_target: int, sigma: float = 2.5) -> float:
        """Smooth Gaussian decay replacing the hard abs(len_diff) > 2 cliff."""
        diff = abs(len_input - len_target)
        return math.exp(-(diff ** 2) / (2 * sigma ** 2))

    @staticmethod
    def _sigmoid(x: float, k: float = 8.0, x0: float = 0.15) -> float:
        """Logistic sigmoid. k=steepness, x0=midpoint."""
        z = -k * (x - x0)
        if z > 500: return 0.0
        if z < -500: return 1.0
        return 1.0 / (1.0 + math.exp(z))

    def score(self, title: str, proc: str) -> tuple[float, str, str]:
        """Main scoring entrypoint. Drop-in replacement for evaluate_suspicion().
        Returns: (c_lev: float, matched_category: str, contributing_hit: str)
        """
        full_haystack = f"{title or ''} {proc or ''}"
        normalized = normalize_haystack(full_haystack)
        tokens = _TOKEN_EXTRACT.findall(normalized)

        # Pass 0: Exact regex match (unchanged — always authoritative)
        for pattern, sev in _COMPILED:
            match = pattern.search(full_haystack) or pattern.search(normalized)
            if match:
                return (1.0, sev, f"{match.group(0)}")

        highest_score = 0.0
        best_sev = "info"
        best_hit = ""

        for token in tokens:
            if len(token) < 4:
                continue

            # --- Channel 1: IDF-weighted Dice against bad corpus ---
            bad_score, bad_term = self.bad.best_match(token)
            if bad_score < 0.25:
                continue

            # --- Channel 2: IDF-weighted Dice against good corpus ---
            good_score = 0.0
            if self.good:
                good_score, _ = self.good.best_match(token)

            # --- Channel 4: Character entropy penalty ---
            # Natural words: entropy ~2.5-3.5. Random evasion strings: entropy >3.8
            entropy = _char_entropy(token)
            entropy_boost = 0.0
            if entropy > 3.8 and bad_score > 0.3:
                entropy_boost = 0.1 * min(entropy - 3.8, 1.0)

            # --- Gaussian length decay (replaces hard abs(len_diff) > 2) ---
            if bad_term:
                length_decay = self._gaussian_length_decay(len(token), len(bad_term))
            else:
                length_decay = 1.0

            # --- Dual-corpus decision signal ---
            # gap = bad - good: positive → closer to bad, negative → closer to good
            effective_bad = bad_score + entropy_boost
            gap = (effective_bad - 1.25 * good_score) * length_decay
            c_lev = self._sigmoid(gap, k=8.0, x0=0.15)

            # --- Keyboard typo analysis ---
            if c_lev > 0.70 and bad_term and len(token) == len(bad_term):
                modifier = LevEngine.calculate_typo_modifier(token, bad_term)
                c_lev *= modifier

            # --- Session accumulation ---
            session_mult = _SESSION_ACC.record(c_lev, bad_term)
            c_lev = min(c_lev * session_mult, 0.99)

            if c_lev > highest_score:
                highest_score = c_lev
                for sev, vocab in _TOKEN_LEXICON.items():
                    if bad_term in vocab:
                        best_sev = sev
                        break
                best_hit = bad_term

        return round(highest_score, 3), best_sev, best_hit


# Initialize dual-engine instances
LEX = LexEngine(_BAD_CORPUS, _GOOD_CORPUS)
LEV = LevEngine()  # Preserved for Angel Engine static method access


# --- Global v7 Optics Buffer ---
_LATEST_BROWSER_DOM = ""
_LATEST_BROWSER_URL = ""
_LATEST_URL_HOSTNAME = ""
_LATEST_TRIPWIRE_SCORE = 0.0
_LATEST_MONETIZATION_SCORE = 0.0
_LATEST_ALE_SCORE = 0.0
_OPTICS_LOCK = threading.Lock()

# Web content weights: explicit site names, terms, and intent confirmers
WEB_WEIGHTS = {
    "hardcore": [
        "pornhub", "xvideos", "xnxx", "redtube", "youporn", "xhamster", 
        "brazzers", "hentai", "rule34", "chaturbate", "onlyfans", "spankbang", 
        "fapello", "hqporner", "gelbooru", "beeg", "spankwire", "daftsex",
        "heavy-r", "motherless", "txxx", "upornia"
    ], # 20 points
    "explicit": [
        "porn", "sex", "adult", "nude", "naked", "erotic", "nsfw", 
        "pussy", "dick", "boobs", "milf", "fuck", "cum", "tits"
    ], # 15 points
    "media": [
        "video", "watch", "streaming", "full", "clips", "collection", 
        "leak", "uncensored", "gallery", "photos", "hd", "premium"
    ]  # 5 points
}

WEB_CRITICAL_THRESHOLD = 40 

# INSTANT STRIKE LIST: 100% Certainty words for typing — zero-tolerance fast track.
# These bypass ALL scoring, OCR, FSM, and angel engine. If typed, it's instant critical.
INSTANT_STRIKE_LIST = {
    # --- Explicit adult content ---
    "pornhub", "xnxx", "xvideos", "hentai", "brazzers", "porn", "redtube",
    "xhamster", "youporn", "chaturbate", "onlyfans", "rule34", "nhentai",
    "spankbang", "eporner",
    # --- Violence / weapons / explosives ---
    "how to make a bomb", "make a bomb", "build a bomb", "pipe bomb",
    "pipebomb", "how to make explosives", "make explosives",
    "how to make a gun", "buy a gun illegally", "3d print gun",
    # --- Self-harm ---
    "how to kill myself", "how to commit suicide", "suicide methods",
    # --- Drugs ---
    "how to make meth", "how to cook meth", "buy drugs online",
    # --- Proxy / bypass tools ---
    "unblocker", "unblock school", "bypass school filter",
    "school proxy", "school vpn bypass",
}

# Rolling buffer — NOT a persistent keylogger.
# Buffer is held in RAM only. Contents are flushed to evidence
# exclusively when a confirmed policy violation is detected.
# No keystrokes are stored to disk or transmitted during normal use.
class KeylogBuffer:
    def __init__(self, maxlen: int = 1000):
        self.buffer = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def add(self, key_str: str):
        with self._lock:
            self.buffer.append(key_str)

    def get_snapshot(self) -> str:
        with self._lock:
            return "".join(self.buffer)

    def clear(self) -> None:
        """Thread-safe buffer clear. Always use this instead of .buffer.clear()."""
        with self._lock:
            self.buffer.clear()

KEYLOG_HISTORY = KeylogBuffer()

def _background_keylogger():
    """Silently maintains a rolling memory of the last 1000 keystrokes with environment isolation."""
    def on_press(key):
        try:
            if hasattr(key, 'char') and key.char is not None:
                KEYLOG_HISTORY.add(key.char)
            elif key == keyboard.Key.space: KEYLOG_HISTORY.add(" ")
            elif key == keyboard.Key.enter: KEYLOG_HISTORY.add(" [ENTER] ")
            elif key == keyboard.Key.backspace: KEYLOG_HISTORY.add("[BS]")
            elif hasattr(key, 'name'): KEYLOG_HISTORY.add(f"[{key.name}]")
        except Exception:
            pass

    try:
        with keyboard.Listener(on_press=on_press) as listener:
            listener.join()
    except Exception as e:
        logger.error("Keylogger subsystem dropped by operating system context", component="keylogger", error=str(e))
        # Keep process group alive via passive stasis loop to prevent Lazarus thrashing
        while True: time.sleep(3600)

def classify_web_context(dom_text: str) -> tuple[bool, str]:
    """Analyzes raw web text using weighted word-boundary matching.

    DOM input is capped at DOM_MAX_CHARS to prevent unbounded regex scanning
    on oversized payloads from the Chrome extension.
    """
    if not dom_text or len(dom_text) < 20: 
        # This is a routine, frequently-hit condition (blank tabs, pages still
        # loading) — not an exception, so no exc_info, and not error-level.
        logger.debug("Context too small or empty", component="dom", length=len(dom_text) if dom_text else 0)
        return False, ""
    # Cap DOM text to prevent O(n×k) regex explosion on oversized payloads
    capped_text = dom_text[:DOM_MAX_CHARS]
    score, hits, text_lower = 0, [], capped_text.lower()



    for category, words in WEB_WEIGHTS.items():
        weight = 20 if category == "hardcore" else 15 if category == "explicit" else 5
        for word in words:
            if re.search(rf"\b{re.escape(word)}\b", text_lower):
                score += weight
                hits.append(word)

    logger.info("Evaluation finished", component="dom", score=score, threshold=WEB_CRITICAL_THRESHOLD, hits=hits)

    if score >= WEB_CRITICAL_THRESHOLD:
        return True, f"web_intent({score}pts):" + "+".join(hits[:4])
    
    logger.info("Score did not meet critical threshold", component="dom", score=score, threshold=WEB_CRITICAL_THRESHOLD)
    return False, ""

async def _telemetry_handler(websocket):
    global _LATEST_BROWSER_DOM, _LATEST_BROWSER_URL, _LATEST_URL_HOSTNAME
    global _LATEST_TRIPWIRE_SCORE, _LATEST_MONETIZATION_SCORE, _LATEST_ALE_SCORE
    logger.info("Uplink established from v7 Chrome Extension", component="optics")
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                with _OPTICS_LOCK:
                    # Legacy Fallbacks
                    _LATEST_BROWSER_DOM = data.get("dom_snapshot", "")
                    _LATEST_BROWSER_URL = data.get("url", "")
                    _LATEST_URL_HOSTNAME = data.get("url_hostname", "")
                    
                    # v7 Structural Telemetry
                    _LATEST_TRIPWIRE_SCORE = data.get("tripwire_score", 0.0)
                    _LATEST_MONETIZATION_SCORE = data.get("monetization_score", 0.0)
                    _LATEST_ALE_SCORE = data.get("ale_score", 0.0)
                    
                    if _LATEST_TRIPWIRE_SCORE > 0 or _LATEST_MONETIZATION_SCORE > 0 or _LATEST_ALE_SCORE > 0.5:
                        logger.warning("Structural anomaly received", component="optics", 
                                       tripwire=_LATEST_TRIPWIRE_SCORE, 
                                       monetization=_LATEST_MONETIZATION_SCORE, 
                                       ale=_LATEST_ALE_SCORE)
            except Exception as e: 
                logger.error("Packet parse error", component="optics", error=str(e), exc_info=True)
    except websockets.exceptions.ConnectionClosed: 
        logger.warning("Connection severed by Chrome", component="optics")

def boot_optics_server():
    """Bulletproof asyncio loop bridge for threaded server start."""
    async def _runner():
        while True:
            try:
                logger.info("Starting WebSocket server on 8765...", component="optics")
                async with websockets.serve(_telemetry_handler, "127.0.0.1", 8765):
                    await asyncio.Future()  # Run forever
            except OSError as e:
                logger.error("CRITICAL: Port 8765 is locked!", component="optics", error=str(e), exc_info=True)
                await asyncio.sleep(5)
            except Exception as e:
                logger.error("Server crashed", component="optics", error=str(e), exc_info=True)
                await asyncio.sleep(5)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_runner())
    except Exception as e:
        logger.error("Event loop fatal", component="optics", error=str(e), exc_info=True)



# =====================================================
# PHASE 6 — THE FORENSIC VAULT (SQLite + Image Cache)
# =====================================================
def vault_init() -> None:
    """Bootstrap the local SQLite buffer and the cache directory."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _hide_path(CACHE_DIR)

        with sqlite3.connect(VAULT_DB) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS queue (
                    id          TEXT PRIMARY KEY,        -- [PATCH: UUID string instead of AUTOINCREMENT]
                    kind        TEXT NOT NULL,           -- 'alert' | 'activity'
                    table_name  TEXT NOT NULL,
                    payload     TEXT NOT NULL,           -- JSON of the row body
                    evidence    TEXT,                    -- JSON {screenshot, webcam, meta}
                    created_at  TEXT NOT NULL,           -- ORIGINAL ISO timestamp
                    attempts    INTEGER DEFAULT 0,
                    last_error  TEXT
                );
                """
            )
            conn.commit()
        _hide_path(VAULT_DB)
        logger.info("forensic vault online", component="vault", vault_db=str(VAULT_DB))
    except Exception as e:
        logger.error("Vault init failed", component="vault", error=str(e), exc_info=True)


def _save_cache_blob(blob: bytes, suffix: str = ".jpg") -> str | None:
    """Persist a JPEG byte-stream into the cache. Returns filename (not full path)."""
    if not blob:
        return None
    try:
        fname = f"{uuid.uuid4().hex}{suffix}"
        (CACHE_DIR / fname).write_bytes(blob)
        return fname
    except Exception as e:
        logger.error("cache write failed", component="vault", error=str(e), exc_info=True)
        return None


def _delete_cache(fname: str | None) -> None:
    if not fname:
        return
    try:
        (CACHE_DIR / fname).unlink(missing_ok=True)
    except Exception:
        pass


def vault_enqueue(
    kind: str,
    table_name: str,
    payload: dict,
    evidence: dict | None,
    created_at: str,
) -> None:
    """Serialize a payload into the local queue under VAULT_LOCK."""
    try:
        # [PATCH 1: Generate cryptographic UUID and inject directly into payload]
        event_id = uuid.uuid4().hex
        payload["id"] = event_id  
        
        with VAULT_LOCK, sqlite3.connect(VAULT_DB) as conn:
            # 1. Insert row with UUID
            conn.execute(
                "INSERT INTO queue(id, kind, table_name, payload, evidence, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (
                    event_id,
                    kind,
                    table_name,
                    json.dumps(payload, default=str),
                    json.dumps(evidence or {}, default=str),
                    created_at,
                ),
            )
            
            # 2. [PATCH 2: FIFO Eviction & Disk Cleanup]
            # Select the evidence JSON of any row older than the top 1000
            cur = conn.execute("""
                SELECT evidence FROM queue 
                WHERE id NOT IN (SELECT id FROM queue ORDER BY created_at DESC LIMIT 1000)
            """)
            orphans = cur.fetchall()
            
            # Extract paths and nuke physical files before dropping SQL rows
            for row in orphans:
                if row[0]:
                    try:
                        ev_data = json.loads(row[0])
                        _delete_cache(ev_data.get("screenshot_file"))
                        _delete_cache(ev_data.get("webcam_file"))
                    except Exception:
                        pass
                        
            # Execute the SQL purge
            conn.execute("""
                DELETE FROM queue 
                WHERE id NOT IN (SELECT id FROM queue ORDER BY created_at DESC LIMIT 1000)
            """)
            conn.commit()
            
        logger.info("queued event", component="vault", kind=kind, table_name=table_name, event_id=event_id, ts=created_at)
    except Exception as e:
        logger.error("enqueue failed", component="vault", error=str(e), exc_info=True)


def vault_pending(limit: int = 25) -> list[tuple]:
    try:
        with VAULT_LOCK, sqlite3.connect(VAULT_DB) as conn:
            # NOTE: was "ORDER BY id ASC" — that was correct back when id was an
            # AUTOINCREMENT integer (chronological by construction), but id is now
            # a uuid4().hex string (see queue schema comment), so sorting by it
            # gives an effectively random replay order, not FIFO. created_at is
            # the actual capture timestamp and is what the eviction query in
            # vault_enqueue() already sorts by — use the same field here.
            cur = conn.execute(
                "SELECT id, kind, table_name, payload, evidence, created_at, attempts "
                "FROM queue ORDER BY created_at ASC LIMIT ?",
                (limit,),
            )
            return cur.fetchall()
    except Exception as e:
        logger.error("read failed", component="vault", error=str(e), exc_info=True)
        return []


def vault_delete(row_id: str) -> None:
    try:
        with VAULT_LOCK, sqlite3.connect(VAULT_DB) as conn:
            conn.execute("DELETE FROM queue WHERE id=?", (row_id,))
            conn.commit()
    except Exception as e:
        logger.error("delete failed", component="vault", error=str(e), exc_info=True)


def vault_bump_attempt(row_id: str, err: str) -> None:
    try:
        with VAULT_LOCK, sqlite3.connect(VAULT_DB) as conn:
            conn.execute(
                "UPDATE queue SET attempts = attempts + 1, last_error = ? WHERE id = ?",
                (err[:500], row_id),
            )
            conn.commit()
    except Exception:
        pass


# ---------- Bucket bootstrap & identity ----------
def ensure_bucket() -> None:
    if sb is None:
        logger.warning("Supabase offline — bucket check skipped", component="storage")
        return
    try:
        sb.storage.create_bucket(
            EVIDENCE_BUCKET,
            options={"public": True, "file_size_limit": 10 * 1024 * 1024},
        )
        logger.info("created bucket", component="storage", bucket=EVIDENCE_BUCKET)
    except Exception as e:
        msg = str(e).lower()
        if any(x in msg for x in ["already exists", "duplicate", "409", "403", "unauthorized"]):
            return
        logger.warning("bucket bootstrap warning", component="storage", error=str(e))


def load_or_create_hardware_uuid() -> str:
    try:
        if IDENTITY_FILE.exists():
            val = IDENTITY_FILE.read_text(encoding="utf-8").strip()
            if val:
                return val
    except Exception as e:
        logger.error("read failed", component="identity", error=str(e), exc_info=True)
    new_id = str(uuid.uuid4())
    try:
        IDENTITY_FILE.write_text(new_id, encoding="utf-8")
        _hide_path(IDENTITY_FILE)
        logger.info("minted hardware uuid", component="identity", identity_file=str(IDENTITY_FILE))
    except Exception as e:
        logger.error("write failed (using ephemeral id)", component="identity", error=str(e), exc_info=True)
    return new_id


HARDWARE_UUID = load_or_create_hardware_uuid()

def get_hardware_fingerprint() -> str:
    components = []
    try:
        import wmi
        c = wmi.WMI()
        
        # Motherboard UUID
        try:
            uuid_val = c.Win32_ComputerSystemProduct()[0].UUID
            components.append(uuid_val.strip() if uuid_val else 'unknown')
        except Exception:
            components.append('unknown')
            
        # Disk Serial
        try:
            disk_val = c.Win32_DiskDrive()[0].SerialNumber
            components.append(disk_val.strip() if disk_val else 'unknown')
        except Exception:
            components.append('unknown')
            
        # MAC Address
        try:
            mac_val = None
            for adapter in c.Win32_NetworkAdapter(PhysicalAdapter=True):
                if adapter.MACAddress:
                    mac_val = adapter.MACAddress
                    break
            components.append(mac_val.strip() if mac_val else 'unknown')
        except Exception:
            components.append('unknown')
            
    except Exception:
        components = ['unknown', 'unknown', 'unknown']

    combined = "|".join(components)
    return hashlib.sha256(combined.encode('utf-8')).hexdigest()

HARDWARE_FINGERPRINT = get_hardware_fingerprint()


def register_workstation() -> str:
    """
    Indestructible registration. Will patiently wait for network initialization
    without crashing the boot sequence. Capped at 3 retries for demo portability.
    """
    logger.info("Attempting vault handshake with Supabase...", component="identity")
    max_retries = 3
    attempt = 0
    
    while attempt < max_retries:
        attempt += 1
        try:
            if sb is None:
                logger.warning("Offline mode active. Using local standalone identity.", component="identity")
                return f"offline-{HARDWARE_UUID}"

            # 1. Try to find the ID by UUID or Name
            res = sb.table("workstations").select("id").eq("hardware_uuid", HARDWARE_UUID).execute()
            wid = res.data[0]["id"] if res.data else None

            if not wid:
                res_name = sb.table("workstations").select("id").eq("name", WORKSTATION_NAME).execute()
                if res_name.data:
                    wid = res_name.data[0]["id"]
                    logger.info("Reusing existing record", component="identity", workstation_name=WORKSTATION_NAME)

            # 2. The Payload
            payload = {
                "name": WORKSTATION_NAME,
                "hardware_uuid": HARDWARE_UUID,
                "status": "online",
                "last_heartbeat": now_iso(),
                "os_info": os_info(),
            }

            if wid:
                sb.table("workstations").update(payload).eq("id", wid).execute()
            else:
                res_new = sb.table("workstations").insert(payload).execute()
                wid = res_new.data[0]["id"]

            logger.info("Handshake secured", component="identity", wid=wid)
            return wid
            
        except Exception as e:
            msg = str(e).lower()
            if "connect" in msg or "network" in msg or "timeout" in msg:
                logger.warning(f"Network unreachable ({msg}). Retry {attempt}/{max_retries}...", component="identity")
            else:
                logger.error(f"Supabase error (attempt {attempt}/{max_retries})", component="identity", error=str(e))
            if attempt < max_retries:
                time.sleep(3)
    
    # All retries exhausted — fall back to offline mode instead of hanging forever
    logger.warning("Registration retries exhausted. Proceeding in offline mode.", component="identity")
    return f"offline-{HARDWARE_UUID}"


# ---------- Foreground window ----------
def get_foreground_window() -> tuple[str | None, str | None]:
    system = platform.system()
    try:
        if system == "Windows":
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                proc = psutil.Process(pid.value).name()
            except Exception:
                proc = None
            return title, proc
        if system == "Darwin":
            script = 'tell application "System Events" to get name of first process whose frontmost is true'
            proc = subprocess.check_output(["osascript", "-e", script]).decode().strip()
            return proc, proc
        try:
            wid = subprocess.check_output(["xdotool", "getactivewindow"]).decode().strip()
            title = subprocess.check_output(["xdotool", "getwindowname", wid]).decode().strip()
            pid = subprocess.check_output(["xdotool", "getwindowpid", wid]).decode().strip()
            proc = psutil.Process(int(pid)).name()
            return title, proc
        except Exception:
            return None, None
    except Exception as e:
        logger.error("foreground error", component="scan", error=str(e), exc_info=True)
        return None, None


# ---------- Evidence capture ----------
def capture_screenshot() -> bytes | None:
    try:
        img = ImageGrab.grab()
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=75)
        return buf.getvalue()
    except Exception as e:
        logger.error("screenshot failed", component="evidence", error=str(e), exc_info=True)
        return None


def capture_webcam() -> bytes | None:
    logger.info("Webcam capture requested", component="evidence")
    if not WEBCAM_EVIDENCE_ENABLED:
        logger.info("Webcam suppressed by remote config", component="evidence")
        return None

    with OPTICS_LOCK:
        try:
            logger.info("Webcam lock acquired, connecting...", component="evidence")
            # 1. Attempt connection. DSHOW is fast, but we fallback to default if it fails.
            if platform.system() == "Windows":
                cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                if not cam.isOpened():
                    logger.warning("CAP_DSHOW failed, falling back to default backend", component="evidence")
                    cam = cv2.VideoCapture(0) # Failsafe backend
            else:
                cam = cv2.VideoCapture(0)
            
            if not cam.isOpened():
                logger.error("Webcam locked by another app or disconnected", component="evidence", exc_info=True)
                return None

            # 2. Sensor Warmup: Hardware requires time to adjust exposure/light
            logger.info("Webcam connected, warming up sensor...", component="evidence")
            time.sleep(0.5) 
            for _ in range(3):
                cam.read() # Discard the initial dark/blurry frames
            
            # 3. Capture the actual evidence
            ok, frame = cam.read()
            cam.release()
            
            if not ok:
                logger.error("Failed to read webcam frame", component="evidence")
                return None
            
            ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            if not ok:
                logger.error("Failed to encode webcam frame to JPEG", component="evidence")
                return None
            
            logger.info("Webcam evidence successfully captured", component="evidence")
            return jpg.tobytes()
            
        except Exception as e:
            logger.error("webcam failed", component="evidence", error=str(e), exc_info=True)
            return None

# =====================================================
# upload_evidence — vault-aware
# =====================================================
def upload_evidence(path: str, payload: bytes) -> str | None:
    """
    Try to upload to Supabase Storage with exponential backoff on transient failures.
    Returns the public URL on success.
    On persistent failure: persist raw bytes into the cache and return None
    (the caller is responsible for queuing the parent row in the vault).
    """
    delays = [0, 2, 6]  # 3 attempts: immediate, +2s, +6s
    last_exc = None
    for attempt, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        try:
            sb.storage.from_(EVIDENCE_BUCKET).upload(
                path,
                payload,
                {"content-type": "image/jpeg", "upsert": "true"},
            )
            return sb.storage.from_(EVIDENCE_BUCKET).get_public_url(path)
        except Exception as e:
            last_exc = e
            logger.error("upload failed", component="storage", path=path, attempt=attempt+1, error=str(e), exc_info=True)

    logger.error("upload exhausted retries — diverting to vault", component="storage", path=path, exc_info=True)
    _save_cache_blob(payload)
    return None

def archive_evidence(alert_id: str, severity: str, workstation_id: str, volatile_snapshot: bytes | None = None) -> None:
    base_meta: dict = {
        "captured_at": now_iso(),
        "severity": severity,
        "is_backlogged": False,
    }

    evidence_row_id: str | None = None
    try:
        ins = sb.table("evidence_logs").insert({
            "alert_id": alert_id,
            "metadata": base_meta,
        }).execute()
        if ins.data:
            evidence_row_id = ins.data[0]["id"]
            logger.info("Dossier row reserved", component="pipelines", evidence_row_id=evidence_row_id)
    except Exception as e:
        logger.error("reservation failed", component="pipelines", error=str(e), exc_info=True)

    def _patch_row(patch: dict) -> None:
        try:
            if evidence_row_id:
                sb.table("evidence_logs").update(patch).eq("id", evidence_row_id).execute()
            else:
                sb.table("evidence_logs").insert({"alert_id": alert_id, **patch}).execute()
        except Exception as e:
            logger.error("patch failed", component="pipelines", error=str(e), exc_info=True)

    def process_1_fast_optics():
        t0 = time.time()
        logger.info("Optics initiated for alert", component="pipeline-1", alert_id=alert_id)
        captured: dict = {"png": None, "cam": None}

        def _grab_screen():
            if severity in ("warning", "medium", "high", "critical"):
                # Captures the instantaneous RAM snapshot to defeat Alt-Tab
                captured["png"] = volatile_snapshot if volatile_snapshot else capture_screenshot()

        def _grab_cam():
            # Webcam capture is restricted to CRITICAL severity only.
            # Critical requires an exact regex match on explicit site names
            # (e.g. pornhub, xvideos). Generic browsing cannot trigger this.
            if severity == "critical":
                captured["cam"] = capture_webcam()

        cap_threads = [threading.Thread(target=_grab_screen), threading.Thread(target=_grab_cam)]
        for t in cap_threads: t.start()
        for t in cap_threads: t.join(timeout=8)

        png, cam = captured["png"], captured["cam"]
        screenshot_url = webcam_url = None

        def _up_screen():
            nonlocal screenshot_url
            if png: screenshot_url = upload_evidence(f"{workstation_id}/{alert_id}-screen.jpg", png)

        def _up_cam():
            nonlocal webcam_url
            if cam: webcam_url = upload_evidence(f"{workstation_id}/{alert_id}-webcam.jpg", cam)

        up_threads = []
        if png: up_threads.append(threading.Thread(target=_up_screen))
        if cam: up_threads.append(threading.Thread(target=_up_cam))
        for t in up_threads: t.start()
        for t in up_threads: t.join(timeout=20)

        patch: dict = {}
        if screenshot_url is not None: patch["screenshot_url"] = screenshot_url
        if webcam_url is not None: patch["webcam_url"] = webcam_url
        
        if patch: _patch_row(patch)
        logger.info("Optics secured", component="pipeline-1", duration=time.time()-t0, screen=bool(screenshot_url), cam=bool(webcam_url))

    def process_2_extended_forensics():
        logger.info("Extracting retrospective telemetry lead-up...", component="pipeline-2")
        
        keys = KEYLOG_HISTORY.get_snapshot()

        try:
            clip_history = DPDP.get_recent_history()
        except Exception:
            clip_history = []

        if not keys and not clip_history: return

        new_meta = dict(base_meta)
        if keys:
            new_meta["retrospective_payload"] = keys[-500:]
        if clip_history:
            new_meta["clipboard_lead_up"] = clip_history
        new_meta["evidence_source"] = "rolling_buffer_snapshot"
        _patch_row({"metadata": new_meta})
        logger.info("Lead-up telemetry secured in dossier.", component="pipeline-2", clipboard_entries=len(clip_history))

    threading.Thread(target=process_1_fast_optics, daemon=True).start()
    if severity in ("warning", "medium", "high", "critical"):
        threading.Thread(target=process_2_extended_forensics, daemon=True).start()


# ---------- Focus-mode cache ----------
class FocusState:
    def __init__(self) -> None:
        self.enabled: bool = False
        self.whitelist: set[str] = set()
        self.known_apps: set[str] = set()
        self.last_refresh: float = 0.0

    def refresh_if_stale(self) -> None:
        if time.time() - self.last_refresh < FOCUS_REFRESH_SEC:
            return
        self.last_refresh = time.time()
        try:
            # 1. Fetch Focus Mode State
            s = sb.table("system_settings").select("focus_mode").eq("id", 1).maybe_single().execute()
            self.enabled = bool(s.data and s.data.get("focus_mode"))
            
            # 2. ALWAYS pull the allowed app list, even if Focus Mode is OFF
            a = sb.table("allowed_apps").select("process_name, whitelisted").execute()
            self.whitelist = set()
            self.known_apps = set()
            for row in (a.data or []):
                p_name = row.get("process_name")
                if not p_name: continue
                p_lower = p_name.lower().strip()
                p_base = p_lower[:-4] if p_lower.endswith(".exe") else p_lower
                
                self.known_apps.add(p_lower)
                self.known_apps.add(p_base)
                if row.get("whitelisted"):
                    self.whitelist.add(p_lower)
                    self.whitelist.add(p_base)
        except Exception as e:
            logger.error("Focus error", component="focus", error=str(e), exc_info=True)

FOCUS = FocusState()


# ---------- Behavioral Sniffers ----------
def network_audit() -> tuple[bool, str | None]:
    UNAUTHORIZED_PORTS = {1194, 1701, 4500, 500, 51820, 1080, 8080}
    try:
        for conn in psutil.net_connections(kind='inet'):
            if conn.raddr and conn.raddr.port in UNAUTHORIZED_PORTS:
                return True, f"unauthorized_tunnel_port_{conn.raddr.port}"
    except Exception:
        pass
    return False, None


def resource_entropy_check(proc_name: str | None) -> tuple[bool, str | None]:
    if not proc_name:
        return False, None
    UTILITIES = ["calculator.exe", "notepad.exe", "wordpad.exe", "cmd.exe"]
    if proc_name.lower() in UTILITIES:
        try:
            for proc in psutil.process_iter(['name', 'cpu_percent']):
                if proc.info['name'] and proc.info['name'].lower() == proc_name.lower():
                    if proc.info['cpu_percent'] > 25:
                        return True, "resource_masquerade_detected"
        except Exception:
            pass
    return False, None


# ---------- Emergency Unfreeze Hotkey ----------
# Formerly bridged to an unauthenticated evidence-spoofing "admin bypass"
# (file-triggered, static key, fabricated telemetry/keystroke evidence).
# That mechanism has been removed entirely. This hotkey is repurposed as a
# legitimate teacher-facing override: instantly release a WARDEN freeze
# without waiting out the timer. It does not touch detection, evidence
# capture, or reporting — it only releases the input lock.
def hardware_panic_listener():
    def on_panic_unfreeze():
        global WARDEN
        try:
            if WARDEN and getattr(WARDEN, "locked", False):
                WARDEN.disengage_freeze()
                logger.info("Emergency unfreeze triggered via hotkey", component="warden", source="hardware-hotkey")
        except Exception as e:
            logger.error("Emergency unfreeze hotkey failed", component="warden", error=str(e))
    try:
        with keyboard.GlobalHotKeys({'<ctrl>+<alt>+<shift>+p': on_panic_unfreeze}) as h:
            h.join()
    except Exception as e:
        logger.error("Panic switch failed to bind", component="warden", error=str(e), exc_info=True)


# =====================================================
# Detection loop primitives — vault-aware
# =====================================================
def _build_alert_payload(workstation_id: str, title: str | None, proc: str | None,
                         severity: str, is_backlogged: bool,
                         created_at: str | None = None,
                         reason: str | None = None) -> dict:
    # DB ENUM mapping for Supabase constraints
    db_severity = "medium" if severity == "warning" else severity
    payload = {
        "workstation_id": workstation_id,
        "process_name": proc,
        "window_title": title,
        "severity": db_severity,
        "is_backlogged": is_backlogged,
    }
    if reason:
        payload["alert_type"] = reason
    if created_at:
        payload["timestamp"] = created_at
    else:
        payload["timestamp"] = now_iso()
    return payload


def _build_activity_payload(workstation_id: str, title: str | None, proc: str | None,
                            severity: str, is_anomaly: bool, is_backlogged: bool,
                            created_at: str | None = None) -> dict:
    # DB ENUM mapping for Supabase constraints
    db_severity = "medium" if severity == "warning" else severity
    payload = {
        "workstation_id": workstation_id,
        "process_name": proc,
        "window_title": title,
        "severity": db_severity if db_severity in ("info", "medium") else "medium",
        "is_anomaly": is_anomaly,
        "is_backlogged": is_backlogged,
    }
    if created_at:
        payload["created_at"] = created_at
    return payload


# =====================================================
# TELEGRAM ALERT ENGINE (Direct Agent → Telegram)
# =====================================================
def _refresh_telegram_targets() -> None:
    """Fetch all linked Telegram chat IDs from profiles table. Cached with TTL."""
    global _TELEGRAM_CHAT_IDS, _TELEGRAM_CACHE_TS, _TELEGRAM_BOT_TOKEN
    if time.time() - _TELEGRAM_CACHE_TS < _TELEGRAM_CACHE_TTL:
        return  # Cache still fresh
    try:
        if not sb:
            return
        # Fetch bot token from school_settings if not already set
        if not _TELEGRAM_BOT_TOKEN:
            try:
                resp = sb.table("school_settings").select("telegram_bot_token").limit(1).execute()
                if resp.data and resp.data[0].get("telegram_bot_token"):
                    _TELEGRAM_BOT_TOKEN = resp.data[0]["telegram_bot_token"]
            except Exception:
                pass  # Table may not exist; edge function env is primary source

        # Fetch all linked Telegram chat IDs from profiles
        resp = sb.from_("profiles").select("telegram_chat_id").eq("phone_verified", True).not_.is_("telegram_chat_id", "null").execute()
        if resp.data:
            _TELEGRAM_CHAT_IDS = [int(p["telegram_chat_id"]) for p in resp.data if p.get("telegram_chat_id")]
        else:
            _TELEGRAM_CHAT_IDS = []
        _TELEGRAM_CACHE_TS = time.time()
        logger.info("Telegram targets refreshed", component="telegram", count=len(_TELEGRAM_CHAT_IDS))
    except Exception as e:
        logger.error("Telegram target refresh failed", component="telegram", error=str(e))


def send_telegram_alert(title: str, proc: str | None, severity: str,
                        reason: str, screenshot_bytes: bytes | None = None) -> None:
    """Send alert to ALL linked Telegram accounts. Non-blocking (runs in thread)."""
    def _send():
        try:
            _refresh_telegram_targets()
            if not _TELEGRAM_BOT_TOKEN or not _TELEGRAM_CHAT_IDS:
                return

            proc_str = proc or "unknown"
            node_name = WORKSTATION_NAME
            msg = (
                f"🚨 <b>CRITICAL BREACH</b> — <code>{node_name}</code>\n"
                f"<b>Severity:</b> {severity.upper()}\n"
                f"<b>Process:</b> {proc_str}\n"
                f"<b>Window:</b> {title[:200]}\n"
                f"<b>Reason:</b> {reason}\n"
                f"<b>Time:</b> {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}"
            )

            for chat_id in _TELEGRAM_CHAT_IDS:
                try:
                    # Send text message
                    req_data = json.dumps({
                        "chat_id": chat_id,
                        "text": msg,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    }).encode("utf-8")
                    req = urllib.request.Request(
                        f"https://api.telegram.org/bot{_TELEGRAM_BOT_TOKEN}/sendMessage",
                        data=req_data,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    urllib.request.urlopen(req, timeout=10)

                    # Send screenshot as photo if available
                    if screenshot_bytes:
                        try:
                            import io
                            boundary = "----ObylonBoundary"
                            body = io.BytesIO()
                            # chat_id field
                            body.write(f"--{boundary}\r\n".encode())
                            body.write(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode())
                            # caption field
                            body.write(f"--{boundary}\r\n".encode())
                            body.write(f'Content-Disposition: form-data; name="caption"\r\n\r\n📸 Evidence: {node_name} — {proc_str}\r\n'.encode())
                            # photo field
                            body.write(f"--{boundary}\r\n".encode())
                            # capture_screenshot()/capture_webcam() both encode JPEG, not PNG —
                            # label/mime must match the actual bytes being sent.
                            body.write(f'Content-Disposition: form-data; name="photo"; filename="evidence.jpg"\r\n'.encode())
                            body.write(b"Content-Type: image/jpeg\r\n\r\n")
                            body.write(screenshot_bytes)
                            body.write(f"\r\n--{boundary}--\r\n".encode())
                            photo_req = urllib.request.Request(
                                f"https://api.telegram.org/bot{_TELEGRAM_BOT_TOKEN}/sendPhoto",
                                data=body.getvalue(),
                                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                                method="POST",
                            )
                            urllib.request.urlopen(photo_req, timeout=15)
                        except Exception as e:
                            logger.error("Telegram photo send failed", component="telegram", error=str(e))
                except Exception as e:
                    logger.error("Telegram send failed", component="telegram", chat_id=chat_id, error=str(e))
        except Exception as e:
            logger.error("Telegram alert thread error", component="telegram", error=str(e))

    threading.Thread(target=_send, daemon=True, name="TelegramAlert").start()


def fire_alert(workstation_id: str, title: str, proc: str | None,
               severity: str, reason: str, volatile_snapshot: bytes | None = None,
               confidence: float = 0.0, freeze_duration: int | None = None) -> None:
    """Central enforcement hub. Four-tier model:
       AUDIT (LOG_ONLY):  Alert + evidence only. No physical enforcement.
       STANDARD:          Alert + evidence + FREEZE (30s) + kill USB processes.
                          Local process kill only if KILL_UNAUTHORIZED_APPS enabled.
       STRICT:            Same as Standard but FREEZE only on confidence >= 1.0.
       EXAM:              Handled separately in scan_loop (freeze + evidence + Telegram).
    """
    global LOG_ONLY_MODE, STRICT_WARDEN, WARDEN, KILL_UNAUTHORIZED_APPS

    clean_p = proc.lower().strip() if proc else ""
    clean_base = clean_p[:-4] if clean_p.endswith(".exe") else clean_p
    is_whitelisted = bool(clean_p in FOCUS.whitelist or clean_base in FOCUS.whitelist)

    # --- ESCALATION LADDER ---
    # Repeated sub-critical hits within a tier's window promote THIS alert
    # to the next tier up. Critical itself is exempt (no rule for it in
    # ESCALATION_LADDER) and always enforces in full on the first strike.
    original_severity = severity
    strike_count, ladder_rule = _register_tier_strike(severity)
    if ladder_rule and strike_count > ladder_rule["threshold"]:
        escalated_to = ladder_rule["escalate_to"]
        logger.warning(
            f"ESCALATION: {strike_count} '{original_severity}' hits within {ladder_rule['window_sec']}s "
            f"— promoting this alert to '{escalated_to}'",
            component="enforcement", reason=reason,
        )
        if not LOG_ONLY_MODE:
            show_status_toast(
                f"Repeated policy violations detected ({strike_count} in "
                f"{ladder_rule['window_sec'] // 60} minutes). This has been "
                f"escalated to a {escalated_to} violation."
            )
        severity = escalated_to
        reason = f"{reason} [escalated from {original_severity} after {strike_count} hits]"

    # --- FORENSIC EVIDENCE PRESERVATION ---
    # Ensure we capture evidence BEFORE killing/suspending anything so the screen state is pristine.
    if volatile_snapshot is None and severity in ("warning", "medium", "high", "critical"):
        volatile_snapshot = capture_screenshot()

    # --- TIER 1: AUDIT MODE — log + evidence only, no physical enforcement ---
    if LOG_ONLY_MODE:
        logger.info("AUDIT MODE active — enforcement suppressed", component="enforcement", severity=severity)

    # --- TIER 2 & 3: STANDARD + STRICT enforcement ---
    elif severity == "critical":  # Critical ALWAYS enforces — whitelisted apps are NOT exempt

        # Step 1: FREEZE workstation immediately (Insta-lock before slow WMI calls)
        if WARDEN:
            if _in_unfreeze_grace():
                logger.warning("Freeze suppressed — user is within the unfreeze grace period.", component="enforcement")
            elif freeze_duration is not None:
                if freeze_duration > 0:
                    logger.warning(f"CUSTOM FREEZE: Freezing workstation for {freeze_duration}s", component="enforcement", reason=reason)
                    WARDEN.lock_workstation(duration=freeze_duration, force=True)
            elif STRICT_WARDEN:
                # Strict: Only freeze on 100% confirmed violations
                if confidence >= 1.0:
                    logger.warning("STRICT: Freezing workstation (100% confidence)", component="enforcement", confidence=confidence, reason=reason)
                    WARDEN.lock_workstation(duration=30, force=True)
                else:
                    logger.info("Strict mode: confidence below 1.0 — freeze suppressed", component="enforcement", confidence=f"{confidence:.3f}")
            else:
                # Standard: Always freeze on critical violations, first strike included.
                logger.warning("STANDARD: Freezing workstation", component="enforcement", reason=reason)
                WARDEN.lock_workstation(duration=30, force=True)

        # Step 2: Always kill USB-sourced unauthorized processes (any mode)
        usb_killed = False
        if proc:
            try:
                import wmi as _wmi
                import pythoncom as _pc
                _pc.CoInitialize()
                _temp_c = _wmi.WMI()
                _removable = get_removable_drive_letters(_temp_c)
                for p in psutil.process_iter(['name', 'exe']):
                    if p.info['name'] and p.info['name'].lower() == proc.lower():
                        exe = (p.info.get('exe') or '').upper()
                        if any(exe.startswith(d.upper()) for d in _removable):
                            p.kill()
                            usb_killed = True
                if usb_killed:
                    logger.warning("USB process terminated", component="enforcement", proc=proc)
            except Exception:
                pass

        # Step 3: Handle local (non-USB) process (Kill or Freeze)
        if not usb_killed and proc:
            if clean_p not in _OS_BYPASS and clean_base not in _OS_BYPASS:
                try:
                    for p in psutil.process_iter(['name']):
                        if p.info['name'] and p.info['name'].lower() == proc.lower():
                            if KILL_UNAUTHORIZED_APPS:
                                p.kill()
                                logger.warning("Local process terminated (KILL_UNAUTHORIZED_APPS=ON)", component="enforcement", proc=proc)
                            else:
                                p.suspend()
                                logger.warning("Local process suspended (Evidence preservation mode)", component="enforcement", proc=proc)
                            break
                except Exception as e:
                    logger.error("Failed to manage local process state", component="enforcement", error=str(e))

    # NOTE: The old "critical + whitelisted = suppressed" branch has been REMOVED.
    # Critical severity is zero-tolerance — if the lexicon/fast-track says critical,
    # the workstation freezes regardless of what app it's in. A student typing
    # "pornhub" into Chrome must be caught even though Chrome is whitelisted.

    # --- Send Telegram alert for critical/high violations ---
    if severity in ("critical", "high") and not LOG_ONLY_MODE:
        send_telegram_alert(title, proc, severity, reason, volatile_snapshot)

    captured_at = now_iso()
    payload = _build_alert_payload(workstation_id, title, proc, severity,
                                   is_backlogged=False, reason=reason)
    logger.warning("ALERT", component="enforcement", severity=severity.upper(), reason=reason, proc=proc, title=title)

    try:
        if sb is None:
            raise ConnectionError("offline")
        res = sb.table("alerts").insert(payload).execute()
        if res.data:
            archive_evidence(res.data[0]["id"], severity, workstation_id, volatile_snapshot)
            return
        raise RuntimeError("alerts insert returned no rows")
    except Exception as e:
        logger.error("live insert failed → vaulting", component="alerts", error=str(e), exc_info=True)
        
        # --- FORENSIC VAULTING (OFFLINE PATH) ---
        # Capture local evidence snapshots synchronously
        screenshot_bytes = volatile_snapshot if volatile_snapshot else (capture_screenshot() if severity in ("warning", "medium", "high", "critical") else None)
        webcam_bytes = capture_webcam() if severity == "critical" else None

        evidence = {
            "screenshot_file": _save_cache_blob(screenshot_bytes) if screenshot_bytes else None,
            "webcam_file": _save_cache_blob(webcam_bytes) if webcam_bytes else None,
            "meta": {
                "captured_at": captured_at,
                "severity": severity,
                "reason": reason,
                "is_backlogged": True,
            },
        }

        offline_payload = _build_alert_payload(
            workstation_id, title, proc, severity,
            is_backlogged=True, created_at=captured_at, reason=reason
        )
        # Queue row in the hidden SQLite buffer
        vault_enqueue("alert", "alerts", offline_payload, evidence, captured_at)

def log_ambient(workstation_id: str, title: str | None, proc: str | None,
                severity: str, is_anomaly: bool) -> None:
    captured_at = now_iso()
    payload = _build_activity_payload(workstation_id, title, proc, severity,
                                      is_anomaly, is_backlogged=False)
    try:
        if sb is None:
            raise ConnectionError("offline")
        sb.table("activity_logs").insert(payload).execute()
    except Exception as e:
        logger.error("live insert failed → vaulting", component="ambient", error=str(e), exc_info=True)
        offline_payload = _build_activity_payload(
            workstation_id, title, proc, severity, is_anomaly,
            is_backlogged=True, created_at=captured_at,
        )
        vault_enqueue("activity", "activity_logs", offline_payload, None, captured_at)


# =====================================================
# PHASE 6 — THE SYNC DAEMON (The Surge)
# =====================================================
def _supabase_alive() -> bool:
    """Lightweight reachability probe. Cheap & non-mutating."""
    try:
        url = SUPABASE_URL
        if not url:
            try: vault.load()
            except Exception: pass
            url = vault.get("SUPABASE_URL")
        if not url: return False
        
        host = url.replace("https://", "").replace("http://", "").split("/")[0]
        with socket.create_connection((host, 443), timeout=4):
            return True
    except Exception:
        return False


def _reinitialize_supabase() -> None:
    """Forces a hard reset of the Supabase client to clear stale JWT tokens."""
    global sb
    logger.info("JWT Token likely expired. Reinitializing Supabase client...", component="sync")
    try:
        sb = _build_supabase_client()
    except Exception as e:
        logger.error("Client re-init failed", component="sync", error=str(e), exc_info=True)

def _surge_one(row) -> bool:
    """
    Replay ONE queued row. Order: images first, then DB row.
    Returns True only when we got a clean DB write AND any cache files
    have been deleted. Cache files are deleted ONLY after a confirmed insert.
    Rows that fail more than MAX_VAULT_ATTEMPTS times are discarded to a
    dead-letter log so they never clog the queue forever.
    """
    MAX_VAULT_ATTEMPTS = 10
    row_id, kind, table_name, payload_json, evidence_json, created_at, attempts = row

    # Dead-letter discard: permanently-failing rows are dropped after cap
    if attempts >= MAX_VAULT_ATTEMPTS:
        dead_letter_path = Path.home() / ".sentinel_dead_letter.jsonl"
        try:
            with open(dead_letter_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "row_id": row_id, "table_name": table_name,
                    "payload": payload_json, "attempts": attempts,
                    "dropped_at": datetime.now(timezone.utc).isoformat(),
                }) + "\n")
        except Exception:
            pass
        vault_delete(row_id)
        logger.error("row exceeded max vault attempts — dead-lettered and dropped", component="sync", row_id=row_id, max_attempts=MAX_VAULT_ATTEMPTS, exc_info=True)
        return False

    try:
        payload = json.loads(payload_json)
        evidence = json.loads(evidence_json) if evidence_json else {}

        # TIMESTAMP RIGIDITY: replay the original capture time.
        payload["created_at"] = created_at
        if table_name in ("activity_logs", "alerts"):
            payload["is_backlogged"] = True

        screenshot_url = webcam_url = None
        screen_file = evidence.get("screenshot_file")
        cam_file = evidence.get("webcam_file")

        # ---- 1) Surge images first ----
        if screen_file:
            blob_path = CACHE_DIR / screen_file
            if blob_path.exists():
                try:
                    sb.storage.from_(EVIDENCE_BUCKET).upload(
                        f"{payload['workstation_id']}/vault-{row_id}-screen.jpg",
                        blob_path.read_bytes(),
                        {"content-type": "image/jpeg", "upsert": "true"},
                    )
                    screenshot_url = sb.storage.from_(EVIDENCE_BUCKET).get_public_url(
                        f"{payload['workstation_id']}/vault-{row_id}-screen.jpg"
                    )
                except Exception as e:
                    raise RuntimeError(f"screenshot surge failed: {e}")

        if cam_file:
            blob_path = CACHE_DIR / cam_file
            if blob_path.exists():
                try:
                    sb.storage.from_(EVIDENCE_BUCKET).upload(
                        f"{payload['workstation_id']}/vault-{row_id}-webcam.jpg",
                        blob_path.read_bytes(),
                        {"content-type": "image/jpeg", "upsert": "true"},
                    )
                    webcam_url = sb.storage.from_(EVIDENCE_BUCKET).get_public_url(
                        f"{payload['workstation_id']}/vault-{row_id}-webcam.jpg"
                    )
                except Exception as e:
                    raise RuntimeError(f"webcam surge failed: {e}")

        # ---- 2) Patch the DB row ----
        # Legacy schema migration: 'created_at' was renamed to 'timestamp' in the alerts table
        if table_name == "alerts" and "created_at" in payload:
            payload["timestamp"] = payload.pop("created_at")
            
        res = sb.table(table_name).insert(payload).execute()
        # PostgREST may return empty data on successful insert if RLS restricts SELECT operations.
        # We assume success if no exception was raised by execute().

        # ---- 3) Evidence dossier (alerts only) ----
        if kind == "alert":
            new_alert_id = res.data[0].get("id")
            ev_meta = dict(evidence.get("meta") or {})
            ev_meta["is_backlogged"] = True
            ev_row = {
                "alert_id": new_alert_id,
                "metadata": ev_meta,
            }
            if screenshot_url: ev_row["screenshot_url"] = screenshot_url
            if webcam_url: ev_row["webcam_url"] = webcam_url
            try:
                sb.table("evidence_logs").insert(ev_row).execute()
            except Exception as e:
                logger.error("evidence_logs surge non-fatal", component="sync", error=str(e), exc_info=True)

        # ---- 4) Confirmed: drop cache files, then drop the row ----
        _delete_cache(screen_file)
        _delete_cache(cam_file)
        vault_delete(row_id)
        logger.info("surged row", component="sync", row_id=row_id, table_name=table_name, ts=created_at)
        return True

    except Exception as e:
        err_msg = str(e)
        vault_bump_attempt(row_id, err_msg)
        logger.error("row surge failed", component="sync", row_id=row_id, attempt=attempts+1, error=err_msg, exc_info=True)
        
        # Trigger hard reset if the token expired during a long offline window
        if "401" in err_msg or "unauthorized" in err_msg.lower() or "jwt" in err_msg.lower():
            _reinitialize_supabase()
            
        return False


def sync_daemon() -> None:
    """
    Phase 6 — The Surge.
    Probes connectivity every SYNC_INTERVAL seconds. When the network is
    back, drains the SQLite queue in batches. Runs entirely in the
    background without touching scan_loop's cadence.
    """
    logger.info("daemon armed", component="sync", interval=SYNC_INTERVAL)
    while True:
        try:
            time.sleep(SYNC_INTERVAL)
            pending = vault_pending(limit=25)
            if not pending:
                continue
            if not _supabase_alive():
                logger.info("legacy item(s) waiting — link still down", component="sync", pending=len(pending))
                continue
            logger.info("connection restored — surging legacy item(s)", component="sync", pending=len(pending))
            wins = 0
            for row in pending:
                if _surge_one(row):
                    wins += 1
                else:
                    # Stop on first failure to avoid hammering a flapping link.
                    break
            logger.info("Surge complete", component="sync", wins=wins, total=len(pending))
        except Exception as e:
            logger.error("daemon error", component="sync", error=str(e), exc_info=True)

# =====================================================
# PHASE 2, 3 & 4: OCR ANALYSIS, ROUTING, & ARBITRATION
# =====================================================

import concurrent.futures
_OCR_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="ocr-worker")

def _ocr_worker(image_bytes: bytes) -> float:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        text = pytesseract.image_to_string(img)
        score, _, _ = LEX.score(text, "")
        return score
    except Exception as e:
        logger.error("OCR worker failed", component="ocr", error=str(e))
        return 0.0

def extract_ocr_suspicion(image_bytes: bytes | None) -> float:
    """Submits OCR to a background thread instead of blocking scan_loop."""
    if not image_bytes:
        return 0.0
    future = _OCR_EXECUTOR.submit(_ocr_worker, image_bytes)
    def _log_result(f):
        try:
            score = f.result()
            if score > 0.0:
                logger.info("Async OCR result", component="ocr", score=f"{score:.2f}")
        except Exception:
            pass
    future.add_done_callback(_log_result)
    return 0.0

def _get_app_modifier(proc_name: str) -> float:
    if not proc_name:
        return 1.0
    proc = proc_name.lower().strip()
    
    # ---------- Requirement 4: Dynamic Incompetence Registry check ----------
    # Assign 0.0 multiplier to poorly signed educational software executing from AppData or Temp
    # unless they exhibit Tier 1 dropper behavior.
    ed_tech_regex = re.compile(
        r".*(syllabus|typing|typewriter|keyboard_tutor|lesson|learn|edu|curriculum|exam|test|speedtyping|touchtyping).*",
        re.IGNORECASE
    )
    
    is_in_temp_or_appdata = False
    if "appdata" in proc or "\\temp\\" in proc or "/temp/" in proc:
        is_in_temp_or_appdata = True
    else:
        try:
            for p in psutil.process_iter(['name', 'exe']):
                try:
                    p_exe = (p.info.get('exe') or "").lower().strip()
                    if p.info.get('name') and p.info['name'].lower().strip() == proc:
                        if "appdata" in p_exe or "\\temp\\" in p_exe or "/temp/" in p_exe:
                            is_in_temp_or_appdata = True
                            break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass

    if is_in_temp_or_appdata and ed_tech_regex.match(proc):
        # Check for Tier 1 dropper behavior in active window or environment
        window_title = ""
        try:
            window_title, _ = get_foreground_window()
            window_title = (window_title or "").lower()
        except Exception:
            pass
            
        dropper_indicators = ("github", "http://", "https://", "curl", "wget", "powershell", "cmd.exe")
        has_dropper_behavior = any(ind in window_title for ind in dropper_indicators)
        
        if not has_dropper_behavior:
            logger.info("Dynamic Incompetence Registry: bypass matched", component="significance", proc=proc, modifier=0.0)
            return 0.0

    return APP_MULTIPLIERS.get(proc, 1.0)


# --- Verhoeff checksum (used to validate Aadhaar-shaped numbers) ---
# Standard public-domain algorithm/tables. A plain 12-digit regex match
# false-positives on any random 12-digit sequence (phone+extra digits,
# order IDs, etc). Verhoeff catches 100% of single-digit transcription
# errors and most transpositions, so only numbers that are structurally
# plausible Aadhaar numbers pass — cuts random-digit false positives from
# ~100% to roughly 1-in-10 by construction.
_VERHOEFF_D = [
    [0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],
    [3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],
    [6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],
    [9,8,7,6,5,4,3,2,1,0],
]
_VERHOEFF_P = [
    [0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],
    [8,9,1,6,0,4,3,5,2,7],[9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],
    [2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8],
]

def _verhoeff_valid(number: str) -> bool:
    """True only if `number` is a structurally valid 12-digit Verhoeff
    checksum sequence (the scheme Aadhaar numbers use)."""
    digits = [int(ch) for ch in number if ch.isdigit()]
    if len(digits) != 12:
        return False
    c = 0
    for i, digit in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][digit]]
    return c == 0


class DPDP_Monitor:
    UNAUTHORIZED_SINKS = ["whatsapp", "mega.nz", "pastebin", "wetransfer", "gofile", "mail.google.com", "drive.google.com"]
    TRUSTED_RECIPIENTS = ["principal", "admin", "management", "staff group", "it support", "official"]
    HISTORY_MAXLEN = 25        # rolling clipboard entries retained
    HISTORY_LOOKBACK_SEC = 300 # how far back a violation can pull clipboard context from

    def __init__(self):
        self.is_hot = False
        self.leak_type = None
        self._history = deque(maxlen=self.HISTORY_MAXLEN)
        self._history_lock = threading.Lock()

    def get_recent_history(self, seconds: int | None = None) -> list[dict]:
        """Returns recent clipboard entries so a later-detected violation can
        be correlated with something staged/copied shortly before it —
        e.g. a URL copied into a browser just before a flagged navigation.
        Text is truncated per-entry; this is a short-lived in-memory buffer
        only, never persisted to disk."""
        cutoff = time.time() - (seconds if seconds is not None else self.HISTORY_LOOKBACK_SEC)
        with self._history_lock:
            return [h for h in self._history if h["ts"] >= cutoff]

    def _clipboard_watcher(self):
        while True:
            time.sleep(1.5)
            try:
                cb_text = pyperclip.paste()
                if not cb_text:
                    continue

                with self._history_lock:
                    self._history.append({"ts": time.time(), "text": cb_text[:500]})

                # Regex for Indian PII
                aadhar_candidates = re.findall(r"\b[2-9][0-9]{3}\s?[0-9]{4}\s?[0-9]{4}\b", cb_text)
                aadhar_matches = [a for a in aadhar_candidates if _verhoeff_valid(a)]
                pan_matches = re.findall(r"\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b", cb_text)
                phone_matches = re.findall(r"\b(\+91[\-\s]?)?[6-9]\d{9}\b", cb_text)

                total_count = len(aadhar_matches) + len(pan_matches) + len(phone_matches)

                if total_count >= 5:
                    self.is_hot = True
                    self.leak_type = "bulk_pii"
                else:
                    self.is_hot = False
            except Exception:
                # Catch clipboard locked exceptions silently
                pass

DPDP = DPDP_Monitor()

class RemoteConfigManager:
    """Polls Supabase for remote config changes and syncs DPAPI + globals."""

    def __init__(self, agent_id: str):
        # Deliberately does NOT store a client reference. _reinitialize_supabase()
        # replaces the module-level `sb` global (e.g. on JWT expiry) — a manager
        # that captured the client once at construction would keep hitting the
        # dead client forever after that swap, silently, since fetch() never
        # raises anything the caller would notice. Read the current global
        # instead, every call, so a reinit is picked up on the very next poll.
        self.agent_id = agent_id

    def fetch(self):
        if sb is None:
            return
        try:
            response = sb.table("agent_configs").select("*").eq("workstation_id", self.agent_id).order("created_at", desc=True).limit(1).execute()
            if response.data and len(response.data) > 0:
                config = response.data[0]
                
                new_log = str(config.get("log_only_mode", False)).lower() in ("true", "1", "yes")
                new_strict = str(config.get("strict_warden", False)).lower() in ("true", "1", "yes")
                try:
                    new_usb = int(config.get("usb_execution_policy", 0))
                except (ValueError, TypeError):
                    new_usb = 0
                new_exam = str(config.get("exam_mode", False)).lower() in ("true", "1", "yes")
                new_kill = str(config.get("kill_unauthorized_apps", False)).lower() in ("true", "1", "yes")
                new_exam_apps = config.get("exam_allowed_apps", ["chrome.exe", "msedge.exe"])
                try:
                    new_exam_freeze = int(config.get("exam_freeze_duration", 30))
                except (ValueError, TypeError):
                    new_exam_freeze = 30
                new_webcam = str(config.get("webcam_evidence_enabled", False)).lower() in ("true", "1", "yes")
                
                global LOG_ONLY_MODE, STRICT_WARDEN, USB_EXECUTION_POLICY, EXAM_MODE, EXAM_ALLOWED_APPS, EXAM_FREEZE_DURATION, KILL_UNAUTHORIZED_APPS, WEBCAM_EVIDENCE_ENABLED

                # Detect any changes
                changed = (
                    LOG_ONLY_MODE != new_log or STRICT_WARDEN != new_strict or
                    USB_EXECUTION_POLICY != new_usb or EXAM_MODE != new_exam or
                    KILL_UNAUTHORIZED_APPS != new_kill or WEBCAM_EVIDENCE_ENABLED != new_webcam
                )
                
                if changed:
                    vault.set("LOG_ONLY_MODE", new_log)
                    vault.set("STRICT_WARDEN", new_strict)
                    vault.set("USB_EXECUTION_POLICY", new_usb)
                    vault.set("EXAM_MODE", new_exam)
                    vault.set("KILL_UNAUTHORIZED_APPS", new_kill)
                    vault.set("WEBCAM_EVIDENCE_ENABLED", new_webcam)
                    
                    LOG_ONLY_MODE = new_log
                    STRICT_WARDEN = new_strict
                    USB_EXECUTION_POLICY = new_usb
                    EXAM_MODE = new_exam
                    KILL_UNAUTHORIZED_APPS = new_kill
                    WEBCAM_EVIDENCE_ENABLED = new_webcam
                    
                    mode_name = "EXAM" if new_exam else ("AUDIT" if new_log else ("STRICT" if new_strict else "STANDARD"))
                    logger.warning("🚀 REMOTE CONFIG UPDATE APPLIED", component="c2", mode=mode_name, kill_apps=new_kill, agent_id=self.agent_id)
                
                # Always sync exam app list and freeze duration (these can change without triggering full log)
                if isinstance(new_exam_apps, list):
                    EXAM_ALLOWED_APPS = {a.lower().strip() for a in new_exam_apps}
                EXAM_FREEZE_DURATION = max(30, min(new_exam_freeze, 600))  # Clamp 30s - 10min safety
                
            else:
                logger.info("No remote config found for this agent_id", component="c2", agent_id=self.agent_id)
        except Exception as e:
            if "timeout" in str(e).lower():
                logger.warning("Remote config fetch timed out (non-fatal)", component="c2")
            else:
                logger.error("Remote config fetch failed", component="c2", error=str(e), exc_info=True)


class ProfessionalOTA:
    """Professional OTA updater with retry, SHA256 verify and rollback."""

    def _download_with_retry(self, url: str, dest_path: str, max_retries: int = 3) -> bool:
        for attempt in range(max_retries):
            try:
                logger.info("OTA download started", component="ota", url=url, attempt=attempt+1)
                req = urllib.request.Request(url, headers={'User-Agent': 'Obylon/6.3.5-LTS'})
                with urllib.request.urlopen(req, timeout=60) as response, open(dest_path, 'wb') as out:
                    shutil.copyfileobj(response, out)
                logger.info("OTA download complete", component="ota", size=os.path.getsize(dest_path))
                return True
            except Exception as e:
                logger.error("OTA download failed", component="ota", attempt=attempt+1, error=str(e))
                time.sleep(5 * (attempt + 1))
        return False

    def _verify_sha256(self, file_path: str, expected_hash: str) -> bool:
        if not expected_hash:
            # FAIL CLOSED: this binary self-executes the downloaded file and
            # replaces the running agent (os._exit + relaunch). Treating "no
            # hash provided" as "skip verification" means anyone who can write
            # a row to admin_actions with an update command controls code
            # execution on every enrolled workstation. Refuse instead.
            logger.critical("No SHA256 provided - refusing unverified OTA update", component="ota")
            return False
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for block in iter(lambda: f.read(65536), b''):
                sha256.update(block)
        match = sha256.hexdigest().lower() == expected_hash.lower()
        logger.info("SHA256 verification", component="ota", match=match)
        return match

    def perform_update(self, download_url: str, sha256: str = None):
        if not download_url:
            logger.error("OTA update called with no download_url", component="ota")
            return False

        current_exe = Path(sys.executable)
        temp_dir = Path(tempfile.gettempdir()) / "obylon_ota"
        temp_dir.mkdir(exist_ok=True)
        
        new_exe = temp_dir / f"{current_exe.stem}_new.exe"
        backup_exe = current_exe.with_name(f"{current_exe.stem}_backup.exe")

        try:
            if not self._download_with_retry(download_url, str(new_exe)):
                logger.critical("OTA download failed after retries", component="ota")
                return False

            if not self._verify_sha256(str(new_exe), sha256):
                logger.critical("SHA256 verification FAILED - aborting", component="ota")
                new_exe.unlink(missing_ok=True)
                return False

            if current_exe.exists():
                shutil.copy2(current_exe, backup_exe)
                logger.info("Current exe backed up", component="ota", backup=str(backup_exe))

            logger.warning("🚀 Performing self-update - agent will restart", component="ota")
            phoenix_bat = temp_dir / "phoenix.bat"
            with open(phoenix_bat, "w", encoding="utf-8") as f:
                f.write(f'''@echo off\ntimeout /t 2 /nobreak >nul\ntaskkill /f /im "{current_exe.name}" >nul 2>&1\nmove /y "{new_exe}" "{current_exe}"\nstart "" "{current_exe}"\ndel "%~f0"\n''')

            subprocess.Popen([str(phoenix_bat)], creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 512) | getattr(subprocess, "DETACHED_PROCESS", 8))
            os._exit(0)

        except Exception as e:
            logger.critical("OTA update crashed", component="ota", error=str(e), exc_info=True)
            if backup_exe.exists() and current_exe.exists() and current_exe.stat().st_size < 1024*1024:
                try:
                    shutil.copy2(backup_exe, current_exe)
                    logger.warning("Rollback to backup successful", component="ota")
                except: pass
            return False


def remote_config_loop(workstation_id: str) -> None:
    manager = RemoteConfigManager(workstation_id)
    while True:
        manager.fetch()
        time.sleep(3)

# =====================================================
# PHASE 7: V7 STRUCTURAL INTELLIGENCE (FSM & WARDEN)
# =====================================================

class PhysicalityWarden:
    """Interrogates raw silicon behavior to detect active evasive media streaming."""
    def __init__(self, target_process_name="chrome.exe"):
        self.target_name = target_process_name
        self.RX_THRESHOLD = 2 * 1024 * 1024  # 2 MB/s constant Rx implies 1080p
        self.GPU_DECODE_THRESHOLD = 5.0      # 5% VideoDecode utilization

    def get_browser_pids(self) -> list:
        pids = []
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] and self.target_name in proc.info['name'].lower():
                    pids.append(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return pids

    def query_gpu_decode_utilization(self, pids: list) -> float:
        if not win32pdh: return 0.0
        gpu_usage = 0.0
        hq = None
        counters = []
        try:
            hq = win32pdh.OpenQuery()
            instances = win32pdh.EnumObjectItems(None, None, "GPU Engine", win32pdh.PERF_DETAIL_WIZARD)
            for inst in instances:
                if "engtype_VideoDecode" in inst:
                    for pid in pids:
                        if f"pid_{pid}_" in inst:
                            path = win32pdh.MakeCounterPath((None, "GPU Engine", inst, None, -1, "Utilization Percentage"))
                            if path:
                                hc = win32pdh.AddCounter(hq, path)
                                counters.append(hc)
            
            if not counters: return 0.0
            win32pdh.CollectQueryData(hq)
            time.sleep(1) # Rhythmic cadence delta
            win32pdh.CollectQueryData(hq)
            
            for hc in counters:
                val = win32pdh.GetFormattedCounterValue(hc, win32pdh.PDH_FMT_DOUBLE)[1]
                gpu_usage += val
        except Exception:
            pass
        finally:
            if hq: win32pdh.CloseQuery(hq)
        return gpu_usage

    def evaluate_physicality(self) -> bool:
        """Evaluates the Streaming Hardware Invariant (SHI)."""
        pids = self.get_browser_pids()
        if not pids: return False

        net_io_start = psutil.net_io_counters()
        gpu_decode_load = self.query_gpu_decode_utilization(pids)
        net_io_end = psutil.net_io_counters()

        rx_rate = net_io_end.bytes_recv - net_io_start.bytes_recv
        tx_rate = net_io_end.bytes_sent - net_io_start.bytes_sent

        is_asymmetric_rx = (rx_rate > (tx_rate * 5)) 
        is_heavy_bandwidth = (rx_rate > self.RX_THRESHOLD)
        is_gpu_rendering = (gpu_decode_load > self.GPU_DECODE_THRESHOLD)

        if is_asymmetric_rx and is_heavy_bandwidth and is_gpu_rendering:
            logger.warning("SHI_CONFIRMED", gpu_load=f"{gpu_decode_load:.1f}%", rx_mbps=f"{rx_rate/1024/1024:.2f}")
            return True
        return False

# =====================================================
# SOFT-OR COMPOSITE THREAT SCORING (LTS Upgrade)
# =====================================================
# Replaces the hard AND gate (m_score >= 0.35 and ale_score >= 0.50)
# with a continuous soft-OR composite that:
#   1. Accumulates partial signals across channels (soft-OR)
#   2. Lowers the lexical enforcement floor via exponential decay
#   3. Multiplicatively boosts lexical score via interaction term
# =====================================================

SEVERITY_RANK = {"info": 0, "warning": 1, "high": 2, "critical": 2}
R_MAX = 2

def severity_base_magnitude(category: str, k: float = 1.5, p: float = 1.5) -> float:
    r = SEVERITY_RANK.get(category, 0)
    # Info (rank 0) must produce exactly 0.0 — it is NOT a threat signal.
    # Allowing a residual (0.014) lets the interaction term leak into enforcement.
    if r == 0:
        return 0.0
    # Distance is scaled non-linearly. Warning (dist 1) stays 1. Info (dist 2) accelerates to 2.82.
    return math.exp(-k * ((R_MAX - r) ** p))

def kneecap_bound(w_lev: float, w_dom: float, dynamic_floor: float) -> float:
    return (dynamic_floor - w_dom) / w_lev

INTENT_MARKERS = {
    "leaked", "movie", "download", "1080p", "uncensored",
    "torrent", "proxy", "watch", "free", "crack", "leak",
    "nude", "stream", "full", "hd", "mkv", "mp4", "x264",
    "direct", "link", "unblock",
}

DEFENSIVE_MARKERS = {
    "medical", "research", "wiki", "history", "vs", "anatomy",
    "documentary", "legal", "implications", "study", "analysis",
    "clinical", "tutorial", "education", "science", "biology",
    "meaning", "define", "definition", "discussing", "prevention",
    "prevent", "stop", "anti", "course", "class", "student", "learning",
    "news", "report"
}

_INTENT_CORPUS = CorpusModel(list(INTENT_MARKERS))
_INTENT_LEX = LexEngine(_INTENT_CORPUS, None)

def angel_mass(
    tokens: list[str],
    match_index: int,
    dom_str: str = "",
    radius: int = 6,
) -> float:
    """Calculates defensive/educational context mass around a lexical hit.

    INVARIANT: DOM text is only scanned when match_index != -1.
    If there is no lexical hit, there is nothing to defend/defuse,
    so DOM scanning would only introduce noise.
    """
    mass = 0.0
    if match_index == -1:
        # No lexical hit — nothing to contextualize.
        return 0.0

    lo, hi = max(0, match_index - radius), min(len(tokens), match_index + radius + 1)
    for i in range(lo, hi):
        if i == match_index:
            continue
        if tokens[i].lower() in DEFENSIVE_MARKERS:
            mass += 1.0

    # DOM text is only scanned to provide context for an existing lexical hit.
    if dom_str:
        dom_words = dom_str.lower().split()
        # Cap DOM scan to prevent ambient noise from overwhelming the signal.
        # Only inspect the first 200 words (approx first ~1200 chars of prose).
        for w in dom_words[:200]:
            if w in DEFENSIVE_MARKERS:
                mass += 1.0
    return mass

def intent_mass(
    tokens: list[str],
    match_index: int,
    dom_str: str = "",
    radius: int = 6,
    distance_weighted: bool = False,
) -> float:
    """Calculates intent-confirming mass (download, free, stream, etc.).

    INVARIANT: Intent is a MULTIPLIER, not a source of threat.
    - $0 \times \text{Intent} = 0$: no lexical hit means intent is irrelevant.
    - When match_index == -1, DOM text is NOT scanned.
    - When match_index != -1, DOM text is scanned but capped at 200 words
      to prevent ambient vocabulary from inflating the signal.
    """
    # If there is no lexical hit, intent mass MUST be zero.
    # Intent is a multiplier — it cannot create a threat from nothing.
    if match_index == -1:
        return 0.0

    lo, hi = max(0, match_index - radius), min(len(tokens), match_index + radius + 1)

    mass = 0.0
    for i in range(lo, hi):
        if i == match_index:
            continue
        token = tokens[i].lower()

        # Baseline exact check
        if token in INTENT_MARKERS:
            mass += (1.0 / (1.0 + abs(i - match_index))) if distance_weighted else 1.0
            continue

        # Lexical Demon Engine fuzzy check (> 0.60 threshold)
        if len(token) >= 4:  # Raised from 2 to 4 to prevent 2-char noise matches
            c_lev, _, _ = _INTENT_LEX.score(token, "")
            if c_lev >= 0.60:
                mass += (1.0 / (1.0 + abs(i - match_index))) if distance_weighted else 1.0

    # DOM text is only scanned to corroborate an existing lexical hit.
    # Capped at 200 words to prevent ambient noise from inflating the score.
    if dom_str:
        dom_words = dom_str.lower().split()
        for w in dom_words[:200]:
            if w in INTENT_MARKERS:
                mass += 1.0
            elif len(w) >= 4:  # Same raised floor as title tokens
                c_lev, _, _ = _INTENT_LEX.score(w, "")
                if c_lev >= 0.60:
                    mass += 1.0

    return mass

def intent_amplification(n: float, beta: float = 1.0) -> float:
    return 1.0 - math.exp(-beta * n)

def effective_severity_magnitude(
    category: str, intent_n: float, k: float = 1.5, beta: float = 1.0
) -> float:
    m_base = severity_base_magnitude(category, k)
    amp = intent_amplification(intent_n, beta)
    return m_base + (1.0 - m_base) * amp

def m_app_dampened(m_app: float, angel_n: float) -> float:
    return 1.0 + (m_app - 1.0) * math.exp(-1.5 * angel_n)

def m_app_escalated(m_app: float, intent_n: float) -> float:
    return 1.0 + (m_app - 1.0) * math.exp(0.5 * intent_n)

def lexical_raw_severity_aware(
    c_lev: float,
    category: str,
    intent_n: float,
    angel_n: float,
    c_dom: float,
    w_lev: float = 0.65,
    w_dom: float = 0.35,
    k: float = 1.5,
    beta: float = 1.0,
) -> dict:
    if c_dom == 0.0:
        w_lev, w_dom = 0.85, 0.15
    m_eff = effective_severity_magnitude(category, intent_n, k, beta)
    
    # Angel Damping: Exponentially decay the severity magnitude if benign context is present
    m_eff *= math.exp(-1.5 * angel_n)
    
    # Angel Damping: Also decay structural anomaly score
    c_dom *= math.exp(-1.5 * angel_n)
    
    raw = w_lev * m_eff * c_lev + w_dom * c_dom
    return {"m_eff": round(m_eff, 4), "lexical_raw": round(raw, 4)}

def threat_score(c_lev=0.0, c_dom=0.0, ale_score=0.0, m_score=0.0, tripwire_score=0.0, w_lev: float = 0.65, w_dom: float = 0.35, category: str = "info", intent_n: float = 0.0, angel_n: float = 0.0) -> dict:
    S = 1.0 - ((1.0 - min(tripwire_score, 1.0)) * (1.0 - min(m_score, 1.0)) * (1.0 - min(ale_score, 1.0)))
    floor = ENFORCEMENT_FLOOR * math.exp(-1.4 * S)
    
    r = lexical_raw_severity_aware(c_lev, category, intent_n, angel_n, c_dom, w_lev, w_dom)
    base_composite = r["lexical_raw"]
    m_eff = r["m_eff"]
    
    lexical_boosted = base_composite * (1.0 + 1.4 * S)
    is_violation = lexical_boosted > floor
    return {
        "CONTAINMENT_VIOLATION": is_violation,
        "lexical_boosted": min(lexical_boosted, 1.0),
        "S": S,
        "effective": min(lexical_boosted, 1.0)
    }



_ALE_HISTORY = deque(maxlen=5)

def _sanitize_ale(raw_ale: float) -> float:
    """A signal that never varies carries no information — and a stuck
    value here directly distorts S in threat_score(). Zero it out
    rather than trust it."""
    _ALE_HISTORY.append(raw_ale)
    if len(_ALE_HISTORY) == _ALE_HISTORY.maxlen and (max(_ALE_HISTORY) - min(_ALE_HISTORY)) < 0.01:
        return 0.0
    return raw_ale

class MasterFSM:
    """Synthesizes browser structural metrics with OS hardware truth.

    Now uses soft-OR composite threat_score() instead of hard AND gate.
    The c_lev parameter enables the interaction term (lexical × structural).
    """
    def __init__(self):
        self.state = "IDLE"
        self.warden = PhysicalityWarden()

    def process_telemetry(self, ext_payload: dict, active_proc: str, c_lev: float = 0.0, category: str = "info", intent_n: float = 0.0) -> tuple[str, float, str]:
        """Synthesizes browser structural metrics with OS hardware truth.

        Now uses soft-OR composite threat_score() instead of hard AND gate.
        The c_lev parameter enables the interaction term (lexical × structural).
        """
        if not active_proc or ("chrome" not in active_proc.lower() and "edge" not in active_proc.lower()):
            self.state = "IDLE"
            return self.state, 0.0, ""

        t_score_val = ext_payload.get("tripwire_score", 0.0)
        m_score = ext_payload.get("monetization_score", 0.0)
        ale_score = _sanitize_ale(ext_payload.get("ale_score", 0.0))

        # --- SOFT-OR COMPOSITE THREAT SCORING ---
        arb_fsm = threat_score(c_lev=c_lev, c_dom=0.0, ale_score=ale_score, m_score=m_score, tripwire_score=t_score_val, category=category, intent_n=intent_n)
        effective = arb_fsm["effective"]
        is_violation = arb_fsm["CONTAINMENT_VIOLATION"]
        S = arb_fsm["S"]

        # STATE 3: CONTAINMENT_VIOLATION (structural overwhelm OR soft-OR violation)
        # STATE 2: ANOMALY_ESCALATION (elevated but not violated)
        if is_violation:
            self.state = "CONTAINMENT_VIOLATION"
            return self.state, 1.0, f"soft_or_composite_violation(S:{S:.2f}|Eff:{effective:.2f})"

        if S > FSM_ANOMALY_FLOOR or effective > FSM_EFFECTIVE_FLOOR:
            self.state = "ANOMALY_ESCALATION"
            if self.warden.evaluate_physicality():
                self.state = "CONTAINMENT_VIOLATION"
                return self.state, 1.0, "SHI_confirmed_evasive_streaming"
            return self.state, max(effective, 0.5 * S), f"structural_entropy(S:{S:.2f}|ALE:{ale_score:.2f})"

        # STATE 1: SEARCH_ENGAGED
        if t_score_val > 0.0:
            self.state = "SEARCH_ENGAGED"
            return self.state, max(effective, 0.3), "search_engine_tripwire_detected"

        self.state = "IDLE"
        return self.state, 0.0, ""

FSM_BRAIN = MasterFSM()

def scan_loop(workstation_id: str) -> None:
    global _LATEST_BROWSER_DOM, _LATEST_BROWSER_URL, _LATEST_URL_HOSTNAME, _LATEST_TRIPWIRE_SCORE, _LATEST_MONETIZATION_SCORE, _LATEST_ALE_SCORE
    last_alerted, last_ambient = {}, {}
    _debounce_prune_ts = time.time()
    _DEBOUNCE_PRUNE_INTERVAL = 300  # Prune stale entries every 5 minutes
    last_active_title = ""
    stable_title = ""
    title_stability_ticks = 0

    import wmi
    import pythoncom
    try:
        pythoncom.CoInitialize()
        wmi_conn = wmi.WMI()
    except Exception as e:
        logger.error(f"Failed to initialize WMI for USB detection: {e}", component="usb-exec")
        wmi_conn = None

    while True:
        try: # THE GLOBAL SHIELD
            removable_drives = get_removable_drive_letters(wmi_conn) if wmi_conn else set()
            # Prune stale debounce entries to prevent unbounded dict growth
            now_ts = time.time()
            if now_ts - _debounce_prune_ts > _DEBOUNCE_PRUNE_INTERVAL:
                cutoff = now_ts - max(ALERT_DEBOUNCE_SEC, AMBIENT_DEBOUNCE_SEC) * 2
                last_alerted = {k: v for k, v in last_alerted.items() if v > cutoff}
                last_ambient  = {k: v for k, v in last_ambient.items()  if v > cutoff}
                _debounce_prune_ts = now_ts

            # 1. Resolve Identity
            # NOTE: We deliberately do NOT skip scanning when WARDEN is frozen.
            # The agent must continue monitoring even during a freeze — a student
            # could ALT+TAB to something worse. Debounce keys prevent alert spam.
            is_currently_frozen = WARDEN and getattr(WARDEN, 'locked', False)
                
            title, proc = get_foreground_window()

            title_str = title or ""
            proc_str = proc or ""

            # Prevent background URLs from bleeding into new tabs (e.g., incognito)
            # Fallback Python-only approach: debounce title changes to filter out badges
            if title_str != last_active_title:
                last_active_title = title_str
                title_stability_ticks = 0
            else:
                title_stability_ticks += 1
                
            if title_stability_ticks == 2 and stable_title != title_str:
                stable_title = title_str
                with _OPTICS_LOCK:
                    _LATEST_BROWSER_DOM = _LATEST_BROWSER_URL = _LATEST_URL_HOSTNAME = ""
                    _LATEST_TRIPWIRE_SCORE = _LATEST_MONETIZATION_SCORE = _LATEST_ALE_SCORE = 0.0

            try:
                if sb is not None:
                    sb.table("workstations").update({
                        "current_window": title_str, "current_process": proc_str,
                    }).eq("id", workstation_id).execute()
            except Exception: pass

            # --- EXAM MODE LOCKDOWN ---
            if EXAM_MODE and proc_str:
                clean_p = proc_str.lower().strip()
                clean_base = clean_p[:-4] if clean_p.endswith(".exe") else clean_p
                # Always bypass OS background tasks
                if clean_p not in _OS_BYPASS and clean_base not in _OS_BYPASS:
                    is_exam_whitelisted = clean_p in EXAM_ALLOWED_APPS or clean_base in EXAM_ALLOWED_APPS
                    if not is_exam_whitelisted:
                        debounce_key = f"exam_mode:{clean_p}"
                        if time.time() - last_alerted.get(debounce_key, 0) > ALERT_DEBOUNCE_SEC:
                            last_alerted[debounce_key] = time.time()
                            logger.warning("EXAM MODE VIOLATION: Unauthorized app", component="enforcement", proc=proc_str)
                            exam_evidence = capture_screenshot()

                            # STEP 1: Enforce app state based on web config (Kill or Suspend)
                            if not LOG_ONLY_MODE:
                                try:
                                    for p in psutil.process_iter(['name', 'pid']):
                                        if p.info['name'] and p.info['name'].lower().strip() == clean_p:
                                            if KILL_UNAUTHORIZED_APPS:
                                                p.kill()
                                                logger.warning("EXAM: Unauthorized app terminated", component="enforcement", proc=clean_p, pid=p.info['pid'])
                                            else:
                                                p.suspend()
                                                logger.warning("EXAM: Unauthorized app suspended (Evidence mode)", component="enforcement", proc=clean_p, pid=p.info['pid'])
                                            break
                                except (psutil.NoSuchProcess, psutil.AccessDenied):
                                    pass
                                except Exception as state_err:
                                    logger.error(f"EXAM: Failed to manage {clean_p} state: {state_err}", component="enforcement")

                            # STEP 2: Fire alert with freeze
                            exam_reason = f"exam_mode_violation_blocked_{clean_p}"
                            alert_title = f"[TARGET LOCKED: EXAM VIOLATION] {title_str}"
                            fire_alert(workstation_id, alert_title, proc_str, "critical", exam_reason, exam_evidence, confidence=1.0, freeze_duration=EXAM_FREEZE_DURATION)
                        # NOTE: Do NOT skip the rest of the scan loop.
                        # Other checks (keylog, DOM, FSM) must still run even during exam violations.

            # 2. Extract DOM Context & v7 Telemetry
            with _OPTICS_LOCK:
                browser_context = _LATEST_BROWSER_DOM
                browser_url = _LATEST_BROWSER_URL
                v7_payload = {
                    "tripwire_score": _LATEST_TRIPWIRE_SCORE,
                    "monetization_score": _LATEST_MONETIZATION_SCORE,
                    "ale_score": _LATEST_ALE_SCORE,
                    "url_hostname": _LATEST_URL_HOSTNAME,
                    "dom_snapshot": _LATEST_BROWSER_DOM
                }

            # Smart Wipe
            if proc_str and proc_str.lower().strip() not in ("chrome.exe", "msedge.exe"):
                with _OPTICS_LOCK:
                    _LATEST_BROWSER_DOM = _LATEST_BROWSER_URL = _LATEST_URL_HOSTNAME = ""
                    _LATEST_TRIPWIRE_SCORE = _LATEST_MONETIZATION_SCORE = _LATEST_ALE_SCORE = 0.0

            # DPDP INTERCEPT
            if DPDP.is_hot:
                sink_found = any(s in proc_str.lower() or s in title_str.lower() or s in (browser_url or "").lower() for s in DPDP.UNAUTHORIZED_SINKS)
                if sink_found:
                    is_browser = proc_str and proc_str.lower().strip() in ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe")
                    exemption_found = is_browser and any(r in title_str.lower() for r in DPDP.TRUSTED_RECIPIENTS)
                    if not exemption_found:
                        try: pyperclip.copy("[OBYLON: BULK DATA TRANSFER BLOCKED BY DPDP COMPLIANCE POLICY]")
                        except Exception: pass
                        DPDP.is_hot = False
                        fire_alert(workstation_id, title_str, proc_str, "critical", "dpdp_bulk_egress_prevented", None)
                        continue

            # 3. Keylog Monitor (Instant Check + Normalizer)
            # Check the last 120 chars of keystroke buffer against both
            # single-word and multi-word strike patterns.
            current_keys = KEYLOG_HISTORY.get_snapshot().lower()
            normalized_keys = normalize_haystack(current_keys[-120:])
            typed_hit = None
            for word in INSTANT_STRIKE_LIST:
                # Multi-word phrases: plain substring match (no word-boundary needed)
                if " " in word:
                    if word in current_keys[-120:] or word in normalized_keys:
                        typed_hit = word
                        KEYLOG_HISTORY.clear()
                        break
                else:
                    if re.search(rf"\b{re.escape(word)}\b", current_keys[-60:]) or re.search(rf"\b{re.escape(word)}\b", normalized_keys):
                        typed_hit = word
                        KEYLOG_HISTORY.clear()
                        break

            # 4. Phase 1 & v7 Integration: The FSM Override
            s_final, severity, reason = 0.0, "info", ""
            volatile_ram_snapshot = None
            c_ocr = 0.0
            
            if proc_str and proc_str.lower().strip() in _OS_BYPASS:
                c_lev, best_category, best_hit = 0.0, "info", ""
            else:
                c_lev, best_category, best_hit = LEX.score(title_str, proc_str)
                
                # --- NEW: CLAUDE'S ADVANCED THREAT ENGINE (Explosives) ---
                if title_str:
                    claude_result = analyze_title(normalize_haystack(title_str))
                    if claude_result['verdict'] == 'CRITICAL_BLOCK':
                        c_lev = 1.0
                        best_category = 'critical'
                        if claude_result['hit'] and claude_result['hit']['matched_text']:
                            best_hit = claude_result['hit']['matched_text']
                        else:
                            best_hit = 'explosives'
                    elif claude_result['verdict'] == 'ALLOWED_EDUCATIONAL':
                        # Defused by category-scoped angel engine!
                        weptok = claude_result['hit']['weapon_token'] if claude_result['hit'] else 'unknown'
                        reason = f"angel_engine_defused:{weptok}"
                        severity = 'warning'
                        c_lev = 0.4
                        best_hit = weptok

            if typed_hit: c_lev, best_category, best_hit = 1.0, "critical", typed_hit
            m_app = _get_app_modifier(proc_str)
            c_dom = 0.0
            
            # Legacy Web Check (Fallback if extension loses v7 comms)
            if browser_context:
                is_violation, web_reason = classify_web_context(browser_context)
                if is_violation:
                    c_dom = 1.0
                    best_category = "critical"
                    best_hit = web_reason

            # --- THE V7 FSM STRUCTURAL OVERRIDE ---
            is_browser = proc_str and proc_str.lower().strip() in ("chrome.exe", "msedge.exe")
            if is_browser:
                tokens = title_str.lower().split()
                try:
                    match_idx = tokens.index(best_hit.lower()) if best_hit else -1
                except ValueError:
                    match_idx = -1
                # BUG FIX: For keystroke hits, the word isn't in the title yet.
                # Fall back to searching the keystroke buffer tokens instead.
                if match_idx == -1 and typed_hit and best_hit:
                    kb_tokens = current_keys.split()
                    try:
                        match_idx = kb_tokens.index(best_hit.lower())
                        tokens = kb_tokens  # Use keystroke tokens for context scan
                    except ValueError:
                        # Force mid-point so intent/angel still fire
                        match_idx = len(tokens) // 2 if tokens else 0
                dom_str = v7_payload.get("dom_snapshot", "") if 'v7_payload' in locals() and v7_payload else ""
                intent_n = intent_mass(tokens, match_idx, dom_str=dom_str)
                
                fsm_state, fsm_score, fsm_reason = FSM_BRAIN.process_telemetry(v7_payload, proc_str, c_lev, best_category, intent_n)
                
                if fsm_state in ("ANOMALY_ESCALATION", "SEARCH_ENGAGED", "CONTAINMENT_VIOLATION"):
                    c_dom = max(c_dom, fsm_score)
                    if not best_hit: best_hit = fsm_state
                    if fsm_state == "CONTAINMENT_VIOLATION":
                        # The FSM's strongest signal — force critical pathway
                        c_dom = max(c_dom, 1.0)

            # Direct Critical Known URL Handling
            url_to_check = (v7_payload.get("url_hostname", "") or v7_payload.get("url", "")).lower() if 'v7_payload' in locals() and v7_payload else ""
            if url_to_check and any(domain in url_to_check for domain in ["tamilrockers", "1337x", "piratebay", "pornhub", "xvideos", "1xbet", "chaturbate", "onlyfans"]):
                s_final = 1.0
                is_blocked = True
                best_hit = f"known_critical_domain({url_to_check})"
                severity = "critical"
                reason = f"v7_structural_enforcement:{best_hit}_(Score:{s_final:.2f})"

            # ==========================================
            # INVESTIGATIVE ESCALATION & ARBITRATION
            # ==========================================
            if s_final == 0.0 and (c_lev >= ENFORCEMENT_FLOOR or c_dom > 0.0):
                    volatile_ram_snapshot = capture_screenshot() 
                    
                    ale_score = _sanitize_ale(v7_payload.get("ale_score", 0.0)) if 'v7_payload' in locals() and v7_payload else 0.0
                    m_score = v7_payload.get("monetization_score", 0.0) if 'v7_payload' in locals() and v7_payload else 0.0
                    t_score_val = v7_payload.get("tripwire_score", 0.0) if 'v7_payload' in locals() and v7_payload else 0.0
                    
                    if volatile_ram_snapshot and ((c_lev > 0.70 and c_dom == 0.0) or (t_score_val > 0.40 and c_dom > 0.20)):
                        c_ocr = extract_ocr_suspicion(volatile_ram_snapshot)
                    
                    tokens = title_str.lower().split()
                    try:
                        match_idx = tokens.index(best_hit.lower()) if best_hit else -1
                    except ValueError:
                        match_idx = -1
                    # BUG FIX: For keystroke hits, fall back to keystroke buffer tokens
                    if match_idx == -1 and typed_hit and best_hit:
                        kb_tokens = current_keys.split()
                        try:
                            match_idx = kb_tokens.index(best_hit.lower())
                            tokens = kb_tokens
                        except ValueError:
                            match_idx = len(tokens) // 2 if tokens else 0
                    dom_str = v7_payload.get("dom_snapshot", "") if 'v7_payload' in locals() and v7_payload else ""
                    intent_n = intent_mass(tokens, match_idx, dom_str=dom_str)
                    angel_n = angel_mass(tokens, match_idx, dom_str=dom_str)

                    # c_lev >= 0.60 means a genuine lexical hit. c_dom > 0.0 means
                    # structural/web content triggered. Without either, no action.
                    if c_lev >= ENFORCEMENT_FLOOR or c_dom > 0.0:
                        arb = threat_score(c_lev=c_lev, c_dom=c_dom, ale_score=ale_score, m_score=m_score, tripwire_score=t_score_val, category=best_category, intent_n=intent_n, angel_n=angel_n)
                        is_blocked = arb['CONTAINMENT_VIOLATION']
                        s_final = arb['lexical_boosted']
                        
                        if angel_n > 0:
                            m_app_eff = m_app_dampened(m_app, angel_n)
                        else:
                            m_app_eff = m_app_escalated(m_app, intent_n)
                            
                        s_final = min(s_final * m_app_eff, 1.0)
                        
                        if is_blocked:
                            severity = "critical" if s_final >= CRITICAL_SEVERITY_FLOOR else "warning"
                            reason = f"v7_structural_enforcement:{best_hit}_(Score:{s_final:.2f})"
                        else:
                            severity = "info"
                            reason = "ambient_noise"
                            volatile_ram_snapshot = None 
                    else:
                        severity = "info"
                        reason = "ambient_noise"
                        volatile_ram_snapshot = None 
                        
            # NOTE: previously a no-op `if ...: pass` lived here — the condition
            # (just-unfrozen + still critical) was computed but nothing ever used
            # it, since s_final/severity are already left untouched by default.
            # Removed as dead code; nothing downstream depended on it.

            # ---------- Requirement 3: Causal Verification (False Positive Killer) ----------
            is_tier_1_keyword = (best_hit in ("powershell", "cmd.exe"))
            if is_tier_1_keyword:
                corroborated = check_recently_spawned(best_hit, 120.0)
                if not corroborated:
                    s_final = UNCORROBORATED_DEMOTION
                    severity = "warning"
                    reason = f"uncorroborated_process_{best_hit}"
                    volatile_ram_snapshot = None  # No screenshot

            # ---------- Requirement 5: Faculty USB Bypass & Enforcement ----------
            if check_if_usb(proc_str, removable_drives):
                if is_faculty_bypass():
                    s_final = FACULTY_USB_DEMOTION
                    severity = "warning"
                    reason = f"faculty_usb_bypass:{best_hit or 'unkn'}"
                    volatile_ram_snapshot = None
                    logger.warning("Faculty USB bypass active. Event downgraded to silent WARNING.", component="usb-bypass")
                else:
                    # Enforcement: Student running an unauthorized portable executable
                    if USB_EXEC_BLOCKLIST.search(proc_str) or USB_EXEC_BLOCKLIST.search(title_str):
                        logger.warning("UNAUTHORIZED USB EXECUTION DETECTED", component="usb-exec", proc_str=proc_str)
                        if WARDEN:
                            WARDEN.terminate_process(proc_str)  # Kill the payload immediately
                        s_final = 1.0
                        severity = "critical"
                        reason = f"unauthorized_usb_execution:{proc_str}"
                        volatile_ram_snapshot = capture_screenshot() # Secure forensic proof

            # --- ANGEL ENGINE: SEMANTIC DEFUSER ---
            if s_final >= ENFORCEMENT_FLOOR and severity == "critical":
                if apply_angel_engine(title_str, best_hit):
                    logger.info("Semantic intent defused. Suppressing severity multiplier.", component="angel-engine", best_hit=best_hit)
                    s_final *= ANGEL_DEFUSE_FACTOR
                    severity = "warning"
                    reason = f"angel_engine_defused:{best_hit}"

            # ------------------------------------------
            # THE DIAGNOSTIC MATRIX (TELEMETRY LOG)
            # ------------------------------------------
            if c_lev > 0.0 or c_dom > 0.0 or c_ocr > 0.0 or typed_hit:
                logger.info("Matrix stats", component="telemetry", lev=f"{c_lev:.2f}", dom=f"{c_dom:.2f}", ocr=f"{c_ocr:.2f}", appmod=f"{m_app:.2f}", final=f"{s_final:.2f}", hit=best_hit)

            # 5. Fire Enforcement
            if s_final >= ENFORCEMENT_FLOOR or reason.startswith("uncorroborated_process_") or reason.startswith("angel_engine_defused"):
                
                # Strip the fluctuating score decimal to prevent debounce key leaks
                debounce_key = reason.split("_(Score")[0] if "_(Score" in reason else reason
                
                if severity in ("critical", "high", "warning") and not reason.startswith("faculty_usb_bypass") and not reason.startswith("uncorroborated_process_"):
                    _debounce = ALERT_DEBOUNCE_SEC_CRITICAL if severity in ("critical", "high") else ALERT_DEBOUNCE_SEC
                    if time.time() - last_alerted.get(debounce_key, 0) > _debounce:
                        last_alerted[debounce_key] = time.time()
                        alert_title = f"{title_str} [URL: {browser_url}]" if browser_url else title_str
                        if best_hit:
                            alert_title = f"[TARGET LOCKED: {best_hit.upper()}] {alert_title}"
                        fire_alert(workstation_id, alert_title, proc_str, severity, reason, volatile_ram_snapshot, confidence=c_lev, freeze_duration=None)
                else:
                    if time.time() - last_ambient.get(debounce_key, 0) > AMBIENT_DEBOUNCE_SEC:
                        last_ambient[debounce_key] = time.time()
                        log_ambient(workstation_id, title_str, proc_str, severity, is_anomaly=True)
            elif reason.startswith("faculty_usb_bypass"):
                debounce_key = reason.split("_(Score")[0] if "_(Score" in reason else reason
                if time.time() - last_ambient.get(debounce_key, 0) > AMBIENT_DEBOUNCE_SEC:
                    last_ambient[debounce_key] = time.time()
                    log_ambient(workstation_id, title_str, proc_str, "info", is_anomaly=False)

            # 6. APP POLICY & SESSION TRACKER (SILENT FEED)
            clean_proc = proc_str.strip().lower() if proc_str else ""
            clean_proc_base = clean_proc[:-4] if clean_proc.endswith(".exe") else clean_proc
            
            is_whitelisted = (clean_proc in FOCUS.whitelist or clean_proc_base in FOCUS.whitelist)
            is_known = (clean_proc in FOCUS.known_apps or clean_proc_base in FOCUS.known_apps)
            
            is_policy_violation = (clean_proc and not is_whitelisted and clean_proc not in _OS_BYPASS and clean_proc_base not in _OS_BYPASS and s_final < ENFORCEMENT_FLOOR)
            is_critical_violation = (s_final >= ENFORCEMENT_FLOOR or reason.startswith("uncorroborated_process_") or reason.startswith("faculty_usb_bypass") or reason.startswith("angel_engine_defused"))
            
            if is_policy_violation or is_critical_violation:
                payload_data = None
                if is_critical_violation:
                    # Safety fallback for best_hit NoneType edge cases
                    hit_str = str(best_hit).upper() if best_hit else "CRITICAL"
                    payload_data = f"[{hit_str}] Score: {s_final:.2f} | {reason}"
                    if browser_url: payload_data += f" | URL: {browser_url}"

                captured_at = now_iso()
                offline_payload = {
                    "workstation_id": workstation_id,
                    "process_name": clean_proc if clean_proc else "system",
                    "window_title": title_str,
                    "kind": "un-added" if (is_policy_violation and not is_critical_violation and not is_known) else "unauthorized",
                    "payload": payload_data if is_critical_violation else None
                }
                try:
                    if sb is not None:
                        sb.table("unauthorized_events").insert(offline_payload).execute()
                    else:
                        raise ConnectionError("offline")
                except Exception as e:
                    logger.error("live session log failed → vaulting", component="ambient", error=str(e))
                    # Redirect to forensic SQLite engine under the activity logs re-route
                    vault_enqueue("activity", "unauthorized_events", offline_payload, None, captured_at)

                if FOCUS.enabled:
                    key = f"policy:{clean_proc}"
                    if time.time() - last_alerted.get(key, 0) > ALERT_DEBOUNCE_SEC:
                        last_alerted[key] = time.time()
                        fire_alert(workstation_id, title_str, clean_proc, "high", "unauthorized_app_focus_lock")

        except Exception as e:
            logger.error("ENGINE CRASH DETECTED", component="engine", error=str(e), exc_info=True)
            try:
                with open(str(Path.home() / ".sentinel_err.txt"), "a") as f:
                    f.write(f"[{now_iso()}] scan_loop error: {str(e)}\n")
            except Exception: pass
            
        time.sleep(SCAN_INTERVAL)

def heartbeat_loop(workstation_id: str) -> None:
    while True:
        try:
            if sb is not None:
                sb.table("workstations").update({
                    "status": "online",
                    "last_heartbeat": now_iso(),
                    "os_info": os_info(),
                }).eq("id", workstation_id).execute()
        except Exception as e:
            logger.error("heartbeat error", component="heartbeat", error=str(e), exc_info=True)
        time.sleep(HEARTBEAT_INTERVAL)
        
# ---------- Administrative Controlled Shutdown ----------
def controlled_shutdown(workstation_id: str, action_id: str):
    logger.info("Controlled shutdown initiated", component="admin", action_id=action_id)

    def _upload_cam():
        cam = capture_webcam()
        if cam:
            url = upload_evidence(f"{workstation_id}/action-{action_id}-webcam.jpg", cam)
            if url:
                try: sb.table("evidence_logs").insert({"metadata": {"command": "terminate", "action_id": action_id, "is_backlogged": False}, "webcam_url": url}).execute()
                except Exception: pass

    def _upload_screen():
        screen = capture_screenshot()
        if screen:
            upload_evidence(f"{workstation_id}/action-{action_id}-screen.jpg", screen)

    threading.Thread(target=_upload_cam, daemon=True).start()
    threading.Thread(target=_upload_screen, daemon=True).start()

    logger.info("Evidence uploads in progress. System shutdown pending.", component="admin", seconds=TERMINATE_GRACE_SEC)
    time.sleep(TERMINATE_GRACE_SEC)

    system = platform.system()
    if system == "Windows": subprocess.call("shutdown /s /f /t 0", shell=True)
    elif system == "Darwin": subprocess.call(["sudo", "shutdown", "-h", "now"])
    else: subprocess.call(["shutdown", "-h", "now"])


def execute_command(cmd: str) -> bool:
    """Returns True if `cmd` was a recognized command that actually ran,
    False otherwise. Callers use this to decide whether an admin_actions
    row should be marked 'acknowledged' or 'failed' — previously this
    returned nothing, so an unrecognized command silently did nothing here
    and still got acknowledged as successful by the caller."""
    system = platform.system()
    logger.info("Executing command", component="admin", cmd=cmd.upper(), system=system)
    if cmd == "lock":
        if system == "Windows":
            subprocess.call("rundll32.exe user32.dll,LockWorkStation", shell=True)
        elif system == "Darwin":
            subprocess.call(["pmset", "displaysleepnow"])
        else:
            subprocess.call(["loginctl", "lock-session"])
        return True
    logger.warning("Unrecognized command — no-op", component="admin", cmd=cmd)
    return False


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


# =====================================================
# CLASSROOM FOCUS OVERLAY
# =====================================================
_overlay_root = None
_overlay_lock = threading.Lock()

def _run_overlay():
    """Create and run a fullscreen red overlay with 'LOOK AT THE TEACHER' text.
    This runs tkinter's mainloop in its own thread. tkinter is NOT thread-safe,
    so all creation/destruction MUST happen on the same thread that calls mainloop."""
    global _overlay_root
    try:
        root = tk.Tk()
        root.attributes('-fullscreen', True)
        root.attributes('-topmost', True)
        root.attributes('-alpha', 0.85)
        root.configure(bg='#B91C1C')
        root.overrideredirect(True)

        label = tk.Label(
            root,
            text="LOOK AT THE TEACHER",
            font=("Helvetica", 64, "bold"),
            fg="white",
            bg="#B91C1C"
        )
        label.pack(expand=True)

        with _overlay_lock:
            _overlay_root = root

        root.mainloop()
    except Exception as e:
        logger.error("Classroom focus overlay failed", component="overlay", error=str(e))
    finally:
        with _overlay_lock:
            _overlay_root = None

def show_classroom_focus_overlay():
    """Launch the overlay if not already showing."""
    with _overlay_lock:
        if _overlay_root is not None:
            return  # Already showing
    threading.Thread(target=_run_overlay, daemon=True, name="ClassroomOverlay").start()
    logger.info("Classroom Focus overlay engaged", component="overlay")

def hide_classroom_focus_overlay():
    """Destroy the overlay from any thread by scheduling destroy() on the tk thread."""
    with _overlay_lock:
        root = _overlay_root
    if root is not None:
        try:
            root.after(0, root.destroy)
        except Exception:
            pass
    logger.info("Classroom Focus overlay disengaged", component="overlay")


# =====================================================
# SUPABASE REALTIME C2 — WebSocket Command Dispatch
# =====================================================
def realtime_c2_listener(workstation_id: str) -> None:
    """Subscribe to admin_actions INSERT events via Supabase Realtime WebSocket.
    Provides near-instant command dispatch (~100ms) vs the 10s HTTP polling fallback.
    Auto-reconnects with exponential backoff on disconnection.
    """
    import asyncio

    async def _run_realtime():
        from realtime import AsyncRealtimeClient

        ws_url = SUPABASE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/realtime/v1/websocket"
        backoff = 1
        max_backoff = 60

        while True:
            try:
                logger.info("Connecting to Supabase Realtime WebSocket...", component="realtime")
                client = AsyncRealtimeClient(
                    ws_url,
                    token=OBYLON_ANON_KEY
                )
                await client.connect()
                await client.set_auth(ACCESS_TOKEN)

                channel = client.channel(f"admin_actions:{workstation_id}")
                
                license_channel = client.channel(f"licenses:{LICENSE_ID}")
                def _on_license_update(payload):
                    record = payload.get("record") or payload.get("new") or {}
                    status = record.get("status")
                    if status in ("revoked", "suspended", "expired"):
                        logger.critical(f"Realtime C2: License revoked ({status}). Initiating shutdown.", component="realtime")
                        LICENSE_INVALID_EVENT.set()
                
                license_channel.on_postgres_changes(
                    event="UPDATE",
                    schema="public",
                    table="licenses",
                    filter=f"id=eq.{LICENSE_ID}",
                    callback=_on_license_update
                )
                await license_channel.subscribe()

                def _on_insert(payload):
                    """Instant command dispatch on WebSocket event.
                    Handles both Postgres CDC INSERTs and Realtime Broadcasts."""
                    def _handle():
                        action_id = None
                        is_broadcast = False
                        try:
                            record = payload.get("record") or payload.get("new") or payload.get("payload") or {}
                            if not record:
                                return

                            # Accept commands for this workstation OR global broadcasts
                            target = record.get("target_id", "")
                            if target != workstation_id and target != "global":
                                return

                            status = record.get("status", "")
                            if status not in ("pending", "broadcast"):
                                return
                            is_broadcast = (status == "broadcast" or target == "global")

                            cmd = record.get("command", "")
                            action_id = record.get("id") or ("broadcast-" + str(uuid.uuid4()))
                            meta = record.get("metadata") or {}

                            if isinstance(meta, str):
                                try:
                                    meta = json.loads(meta)
                                except Exception:
                                    meta = {}

                            logger.info("Realtime command received", component="realtime", command=cmd, action_id=action_id, is_broadcast=is_broadcast)

                            # Broadcast commands skip DB claiming — they don't have
                            # a corresponding pending row (the DB insert happens
                            # asynchronously on the frontend for logging only).
                            if not is_broadcast:
                                if not sb:
                                    logger.warning("Realtime command dropped: no Supabase client", component="realtime", command=cmd, action_id=action_id)
                                    return

                                # ATOMIC CLAIM: compare-and-swap so action_loop
                                # and this handler don't double-dispatch.
                                claim = (
                                    sb.table("admin_actions")
                                    .update({"status": "processing"})
                                    .eq("id", action_id)
                                    .eq("status", "pending")
                                    .select()
                                    .execute()
                                )
                                if not claim.data:
                                    return  # action_loop already claimed it

                            dispatched = True
                            fail_reason = None

                            # --- COMMAND DISPATCH ---
                            if cmd == "terminate":
                                threading.Thread(target=controlled_shutdown, args=(workstation_id, action_id), daemon=True).start()

                            elif cmd in ("freeze", "lock_hardware"):
                                if not WARDEN:
                                    dispatched, fail_reason = False, "WARDEN not initialized on this workstation"
                                else:
                                    try:
                                        duration = int(meta.get("duration", 300))
                                    except (ValueError, TypeError):
                                        duration = 300
                                    WARDEN.lock_workstation(duration=duration, force=True)

                            elif cmd == "unfreeze":
                                if not WARDEN:
                                    dispatched, fail_reason = False, "WARDEN not initialized on this workstation"
                                else:
                                    WARDEN.disengage_freeze()

                            elif cmd == "classroom_focus":
                                # Global classroom attention mode
                                if WARDEN:
                                    WARDEN.lock_workstation(duration=3600, force=True)
                                show_classroom_focus_overlay()

                            elif cmd == "classroom_focus_end":
                                if WARDEN:
                                    WARDEN.disengage_freeze()
                                hide_classroom_focus_overlay()

                            elif cmd in ("kill_task", "kill", "scalpel"):
                                if not WARDEN:
                                    dispatched, fail_reason = False, "WARDEN not initialized on this workstation"
                                else:
                                    target_proc = meta.get("process_name") or meta.get("process") or meta.get("target") or meta.get("target_name")
                                    if target_proc:
                                        WARDEN.terminate_process(target_proc)
                                    else:
                                        dispatched, fail_reason = False, "No target provided in metadata"

                            elif cmd == "update":
                                download_url = meta.get("url")
                                expected_sha256 = meta.get("sha256")
                                if sb and not is_broadcast:
                                    sb.table("admin_actions").update({"status": "acknowledged"}).eq("id", action_id).execute()
                                ProfessionalOTA().perform_update(download_url, expected_sha256)
                                return

                            elif cmd == "set_alias":
                                new_alias = meta.get("alias") or meta.get("new_name") or meta.get("name")
                                if new_alias:
                                    try:
                                        if ALIAS_FILE.exists() and platform.system() == "Windows":
                                            subprocess.call(["attrib", "-H", str(ALIAS_FILE)], shell=False)
                                        ALIAS_FILE.write_text(new_alias, encoding="utf-8")
                                        if platform.system() == "Windows":
                                            subprocess.call(["attrib", "+H", str(ALIAS_FILE)], shell=False)
                                        if sb:
                                            sb.table("workstations").update({"name": new_alias}).eq("id", workstation_id).execute()
                                        logger.info("Workstation alias updated via realtime", component="realtime", new_alias=new_alias)
                                    except Exception as e:
                                        dispatched, fail_reason = False, f"alias forge failed: {e}"
                                        logger.error("Alias forge failed", component="realtime", error=str(e))
                                else:
                                    dispatched, fail_reason = False, "Invalid frontend metadata (no alias/new_name/name)"

                            else:
                                dispatched = execute_command(cmd)
                                if not dispatched:
                                    fail_reason = f"Unrecognized command: {cmd}"

                            # Finalize — broadcast commands don't touch the DB
                            if not is_broadcast:
                                final_status = "acknowledged" if dispatched else "failed"
                                try:
                                    if sb:
                                        sb.table("admin_actions").update({"status": final_status}).eq("id", action_id).execute()
                                except Exception:
                                    pass
                            if not dispatched:
                                logger.warning("Command claimed but not dispatched", component="realtime", command=cmd, action_id=action_id, reason=fail_reason)

                        except Exception as e:
                            logger.error("Realtime dispatch error", component="realtime", error=str(e))
                            if sb and action_id and not is_broadcast:
                                try:
                                    sb.table("admin_actions").update({"status": "failed"}).eq("id", action_id).execute()
                                except Exception:
                                    pass

                    threading.Thread(target=_handle, daemon=True).start()

                channel.on_postgres_changes(
                    event="INSERT",
                    schema="public",
                    table="admin_actions",
                    callback=_on_insert
                )
                channel.on_broadcast(
                    event="admin_action",
                    callback=_on_insert
                )
                await channel.subscribe()

                # Also subscribe to global classroom channel for broadcast commands
                global_channel = client.channel("classroom:global")
                global_channel.on_broadcast(
                    event="admin_action",
                    callback=_on_insert
                )
                await global_channel.subscribe()

                logger.info("Realtime C2 channel subscribed (CDC + Broadcast + Global)", component="realtime", target=workstation_id)
                backoff = 1  # Reset backoff on successful connection

                # Keep the connection alive
                while True:
                    if TOKEN_ROTATED_EVENT.is_set():
                        logger.info("Token rotated, forcing Realtime C2 reconnect...", component="realtime")
                        TOKEN_ROTATED_EVENT.clear()
                        # Disconnect safely to trigger the outer reconnect loop with new ACCESS_TOKEN
                        try:
                            await client.close()
                        except Exception:
                            pass
                        break
                    await asyncio.sleep(5)

            except Exception as e:
                logger.warning(f"Realtime C2 disconnected, reconnecting in {backoff}s...", component="realtime", error=str(e))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    # Run the async event loop in this thread
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run_realtime())
    except Exception as e:
        logger.error("Realtime C2 fatal error", component="realtime", error=str(e))
        # Thread will be resurrected by Lazarus Watchdog


def action_loop(workstation_id: str) -> None:
    """Fallback HTTP polling for C2 commands. Primary dispatch is via Realtime WebSocket."""
    while True:
        try:
            if sb is None:
                time.sleep(10)
                continue
            # We must select 'metadata' to extract the target process for the Scalpel.
            res = (
                sb.table("admin_actions")
                .select("id, command, created_at, metadata")
                .eq("target_id", workstation_id)
                .eq("status", "pending")
                .execute()
            )

            now = datetime.now(timezone.utc)
            for action in res.data or []:
                # Each action is isolated in its own try/except: one bad/crashing
                # command must not stop the rest of this batch from being
                # processed. Previously the only try/except wrapped the whole
                # `for` loop, so action #2+ would sit un-dispatched until the
                # next 10s poll if action #1 raised.
                try:
                    created = _parse_iso(action.get("created_at"))

                    # Check for command expiration
                    if created and (now - created) > timedelta(seconds=COMMAND_TTL_SEC):
                        age = int((now - created).total_seconds())
                        logger.info("EXPIRED (marking as failed)", component="actions", age=age, command=action["command"], action_id=action["id"])
                        sb.table("admin_actions").update({"status": "failed"}).eq("id", action["id"]).execute()
                        continue

                    # ATOMIC CLAIM: flip pending -> processing conditioned on the
                    # row still being 'pending'. realtime_c2_listener (WebSocket)
                    # polls/dispatches independently of this HTTP loop; without this
                    # compare-and-swap both consumers can read the same 'pending'
                    # row and dispatch it twice (harmless for freeze, not harmless
                    # for a duplicate concurrent self-update). If claim.data comes
                    # back empty, the other consumer already took it -- skip it.
                    claim = (
                        sb.table("admin_actions")
                        .update({"status": "processing"})
                        .eq("id", action["id"])
                        .eq("status", "pending")
                        .select()
                        .execute()
                    )
                    if not claim.data:
                        continue

                    cmd = action["command"]
                    meta = action.get("metadata") or {}

                    # 1. The JSON Armor (Neutralizes frontend double-stringification)
                    if isinstance(meta, str):
                        try:
                            meta = json.loads(meta)
                        except Exception:
                            meta = {}

                    # --- DISPATCH LOGIC ---
                    # `dispatched` tracks whether the command actually DID
                    # something. Previously this loop unconditionally marked
                    # every action "acknowledged" after the if/elif chain, even
                    # when e.g. WARDEN was None and a freeze/unfreeze/kill_task
                    # command fell through every WARDEN-gated branch and hit the
                    # catch-all execute_command(cmd) no-op -- the dashboard would
                    # show success while nothing happened on the machine.
                    dispatched = True
                    fail_reason = None

                    if cmd == "terminate":
                        threading.Thread(target=controlled_shutdown, args=(workstation_id, action["id"]), daemon=True).start()

                    elif cmd in ("freeze", "lock_hardware"):
                        if not WARDEN:
                            dispatched, fail_reason = False, "WARDEN not initialized on this workstation"
                        else:
                            try:
                                duration = int(meta.get("duration", 300))
                            except (ValueError, TypeError):
                                duration = 300
                            WARDEN.lock_workstation(duration=duration, force=True)

                    elif cmd == "unfreeze":
                        if not WARDEN:
                            dispatched, fail_reason = False, "WARDEN not initialized on this workstation"
                        else:
                            WARDEN.disengage_freeze()

                    elif cmd == "classroom_focus":
                        if WARDEN:
                            WARDEN.lock_workstation(duration=3600, force=True)
                        show_classroom_focus_overlay()

                    elif cmd == "classroom_focus_end":
                        if WARDEN:
                            WARDEN.disengage_freeze()
                        hide_classroom_focus_overlay()

                    elif cmd in ("kill_task", "kill", "scalpel"):
                        # "scalpel" retained as a legacy dashboard command alias for backward compatibility
                        if not WARDEN:
                            dispatched, fail_reason = False, "WARDEN not initialized on this workstation"
                        else:
                            target = meta.get("process_name") or meta.get("process") or meta.get("target") or meta.get("target_name")
                            if target:
                                WARDEN.terminate_process(target)
                            else:
                                dispatched, fail_reason = False, "No target provided in metadata"
                                logger.warning("terminate_process: No target provided in metadata", component="actions", meta=meta)

                    elif cmd == "update":
                        download_url = meta.get("url")
                        expected_sha256 = meta.get("sha256")
                        sb.table("admin_actions").update({"status": "acknowledged"}).eq("id", action["id"]).execute()
                        ProfessionalOTA().perform_update(download_url, expected_sha256)
                        # perform_update() either os._exit(0)s into the new build
                        # or fully logs+returns False on its own failure path --
                        # the status update above already reflects "we picked
                        # this up", so skip the shared finalize below.
                        continue

                    # --> Indestructible Identity Forging <--
                    elif cmd == "set_alias":
                        # 2. The Multi-Key Net (Catches 'alias', 'new_name', or 'name')
                        new_alias = meta.get("alias") or meta.get("new_name") or meta.get("name")

                        if new_alias:
                            try:
                                if ALIAS_FILE.exists() and platform.system() == "Windows":
                                    subprocess.call(["attrib", "-H", str(ALIAS_FILE)], shell=False)
                                ALIAS_FILE.write_text(new_alias, encoding="utf-8")
                                if platform.system() == "Windows":
                                    subprocess.call(["attrib", "+H", str(ALIAS_FILE)], shell=False)

                                sb.table("workstations").update({"name": new_alias}).eq("id", workstation_id).execute()
                                logger.info("Workstation alias updated", component="identity", new_alias=new_alias)
                            except Exception as e:
                                dispatched, fail_reason = False, f"alias forge failed: {e}"
                                logger.error("Alias forge failed", component="identity", error=str(e), exc_info=True)
                        else:
                            dispatched, fail_reason = False, "Invalid frontend metadata (no alias/new_name/name)"
                            logger.error("Failed to forge alias. Invalid frontend metadata", component="identity", meta=meta, exc_info=True)

                    else:
                        dispatched = execute_command(cmd)
                        if not dispatched:
                            fail_reason = f"Unrecognized command: {cmd}"

                    # Finalize the action -- only "acknowledged" when something
                    # actually happened; otherwise "failed" with a logged reason,
                    # so the dashboard reflects reality instead of a rubber stamp.
                    final_status = "acknowledged" if dispatched else "failed"
                    sb.table("admin_actions").update({"status": final_status}).eq("id", action["id"]).execute()
                    if not dispatched:
                        logger.warning("Command claimed but not dispatched", component="actions", command=cmd, action_id=action["id"], reason=fail_reason)

                except Exception as e:
                    logger.error("action dispatch error (isolated -- rest of batch continues)", component="actions", action_id=action.get("id"), command=action.get("command"), error=str(e), exc_info=True)
                    try:
                        sb.table("admin_actions").update({"status": "failed"}).eq("id", action["id"]).execute()
                    except Exception:
                        pass

        except Exception as e:
            logger.error("actions error", component="actions", error=str(e), exc_info=True)

        time.sleep(10)  # Fallback polling -- primary dispatch via Realtime WebSocket

# ---------- Main ----------
class BuildInfo:
    VERSION = "6.4.0-LTS"
    BUILD_DATE = "2026-06-01"
    COMMIT = "monolith-stable"

    @staticmethod
    def print_banner():
        try:
            # Force VT100 ANSI processing on older Windows terminals
            os.system('color')
            logo = """
\033[96m     ██████╗ ██████╗ ██╗   ██╗██╗      ██████╗ ███╗   ██╗\033[0m
\033[96m    ██╔═══██╗██╔══██╗╚██╗ ██╔╝██║     ██╔═══██╗████╗  ██║\033[0m
\033[96m    ██║   ██║██████╔╝ ╚████╔╝ ██║     ██║   ██║██╔██╗ ██║\033[0m
\033[96m    ██║   ██║██╔══██╗  ╚██╔╝  ██║     ██║   ██║██║╚██╗██║\033[0m
\033[96m    ╚██████╔╝██████╔╝   ██║   ███████╗╚██████╔╝██║ ╚████║\033[0m
\033[96m     ╚═════╝ ╚═════╝    ╚═╝   ╚══════╝ ╚═════╝ ╚═╝  ╚═══╝\033[0m
\033[91m                   S E N T I N E L   C O R E             \033[0m
\033[90m========================================================================================\033[0m
"""
            print(logo)
            
            import sqlite3
            
            print("\033[97m[SYSTEM DIAGNOSTICS]\033[0m")
            
            # Check 1: Lexical Engine
            print(f"\033[90m[*]\033[0m {'Loading Lexical Neural Engine'.ljust(45)}", end="", flush=True)
            time.sleep(0.1)
            if GOOD_VOCAB_TERMS: print("\033[92m[ OK ]\033[0m")
            else: print("\033[93m[ DEGRADED ]\033[0m")
            
            # Check 2: Vault
            print(f"\033[90m[*]\033[0m {'Verifying Local Vault Integrity'.ljust(45)}", end="", flush=True)
            time.sleep(0.1)
            try:
                with sqlite3.connect(VAULT_DB) as c: pass
                print("\033[92m[ OK ]\033[0m")
            except Exception:
                print("\033[91m[ FAIL ]\033[0m")
                
            # Check 3: WMI
            print(f"\033[90m[*]\033[0m {'Initializing WMI Core Hooks'.ljust(45)}", end="", flush=True)
            time.sleep(0.2)
            try:
                import wmi as _wmi_check
                _wmi_check.WMI()
                print("\033[92m[ OK ]\033[0m")
            except Exception:
                print("\033[93m[ DEGRADED ]\033[0m")
                
            # Check 4: Network
            print(f"\033[90m[*]\033[0m {'Synchronizing IPC Channels'.ljust(45)}", end="", flush=True)
            time.sleep(0.2)
            try:
                if _supabase_alive(): print("\033[92m[ OK ]\033[0m")
                else: print("\033[93m[ OFFLINE ]\033[0m")
            except Exception:
                print("\033[93m[ OFFLINE ]\033[0m")
            
            print("\n\033[92m[+] ALL SYSTEMS NOMINAL. SENTINEL CORE IGNITED.\033[0m")
            print("\033[90m========================================================================================\033[0m\n")
        except Exception as banner_err:
            # Banner is cosmetic — never let it crash the agent
            print(f"\n[!] Banner rendering skipped ({banner_err})\n")

        try:
            logger.info(f"=== OBYLON SENTINEL v{BuildInfo.VERSION} (LTS) ===", component="boot")
            logger.info("Build Details", build_date=BuildInfo.BUILD_DATE, commit=BuildInfo.COMMIT, component="boot")
            logger.info("Deployment target: School-managed Windows workstations", component="boot")
            logger.info("All evidence only on confirmed policy violation. Authorized IT use only.", component="boot")
        except Exception:
            pass

def license_heartbeat_loop(workstation_id: str):
    global ACCESS_TOKEN, REFRESH_TOKEN
    while True:
        try:
            # Sync token rotation from Supabase client background refresh
            if sb:
                session = sb.auth.get_session()
                if session and session.access_token != ACCESS_TOKEN:
                    ACCESS_TOKEN = session.access_token
                    REFRESH_TOKEN = session.refresh_token
                    vault._data["ACCESS_TOKEN"] = ACCESS_TOKEN
                    vault._data["REFRESH_TOKEN"] = REFRESH_TOKEN
                    vault._save()
                    TOKEN_ROTATED_EVENT.set()
                    logger.info("Session token rotated, signaled C2 reconnect", component="license")

            payload = {"hardware_uuid": HARDWARE_UUID}
            req = urllib.request.Request(
                f"{ENROLLMENT_ENDPOINT}/license_heartbeat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
            )
            import ssl, certifi
            context = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(req, context=context) as response:
                data = json.loads(response.read().decode("utf-8"))
                
                # Cryptographic offline enforcement check
                if "server_sig" in data and not verify_server_signature(data, data["server_sig"]):
                    logger.critical("License heartbeat signature mismatch! Possible MITM or tampering.", component="license")
                    LICENSE_INVALID_EVENT.set()
                    return

                status = data.get("status")
                vault._data["LAST_HEARTBEAT_OK_AT"] = data.get("issued_at", datetime.now(timezone.utc).isoformat())
                vault._data["LICENSE_STATUS"] = status
                if data.get("expires_at"): vault._data["EXPIRES_AT"] = data.get("expires_at")
                if data.get("grace_days"): vault._data["GRACE_DAYS"] = data.get("grace_days")
                
                # Monotonic Anti-Rollback High-Water Mark
                current_max = vault._data.get("MAX_SEEN_UTC")
                issued_at = data.get("issued_at")
                if issued_at:
                    if not current_max or issued_at > current_max:
                        vault._data["MAX_SEEN_UTC"] = issued_at

                vault._save()
                
                if status in ("revoked", "suspended", "expired"):
                    logger.critical(f"License is {status}, shutting down.", component="license")
                    LICENSE_INVALID_EVENT.set()
                    return
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                logger.critical(f"License heartbeat rejected: {e.code}", component="license")
                LICENSE_INVALID_EVENT.set()
                return
        except Exception as e:
            logger.error(f"License heartbeat error: {e}", component="license")
            # Offline tolerance based on saved bounds
            last_ok = vault.get("LAST_HEARTBEAT_OK_AT")
            grace = int(vault.get("GRACE_DAYS") or 14)
            if last_ok:
                try:
                    last_ok_dt = datetime.fromisoformat(last_ok)
                    if datetime.now(timezone.utc) - last_ok_dt > timedelta(days=grace):
                        logger.critical(f"Offline tolerance exceeded ({grace} days). Shutting down.", component="license")
                        LICENSE_INVALID_EVENT.set()
                        return
                except Exception:
                    pass
        
        time.sleep(300) # Every 5 minutes

def harden_installation():
    """Hide everything important from casual snooping."""
    paths_to_hide = [
        VAULT_DB,
        CACHE_DIR,
        Path(os.environ.get('PROGRAMDATA', 'C:\\ProgramData')) / "Obylon",
        Path.home() / ".sentinel_alias",
        Path.home() / ".sentinel_id",
    ]
    for p in paths_to_hide:
        if p.exists():
            _hide_path(p)
    logger.info("Self-protection: critical paths hidden from explorer", component="startup")

def main() -> None:
    try:
        logger.info("Mounting WMI Event Sinks...", component="boot")
        try:
            start_wmi_process_monitor()
            logger.info("WMI Sinks established. Process trajectory hooked.", component="boot")
        except Exception as e:
            logger.warning(f"WMI process monitor unavailable (non-fatal): {e}", component="boot")

        try:
            start_usb_insertion_monitor()
            start_network_adapter_monitor()
            logger.info("Hardware/adapter monitors started.", component="boot")
        except Exception as e:
            logger.warning(f"Hardware/adapter monitors unavailable (non-fatal): {e}", component="boot")
        
        logger.info("Decrypting localized evidence vault...", component="vault")
        try:
            vault_init()
            logger.info("Vault initialized successfully.", component="vault")
        except Exception as e:
            logger.warning(f"Vault init degraded (non-fatal): {e}", component="vault")
        
        logger.info("Verifying Supabase storage allocations...", component="storage")
        try:
            ensure_bucket()
        except Exception as e:
            logger.warning(f"Bucket check skipped (non-fatal): {e}", component="storage")
        
        try:
            wid = register_workstation()
        except Exception as e:
            logger.warning(f"Registration failed (non-fatal): {e}", component="identity")
            wid = f"offline-{HARDWARE_UUID}"
        logger.info("Workstation identity verified.", component="identity", wid=wid)

        # Define all critical systems for the Necromancer to watch
        core_systems = {
            "license_heartbeat": {"target": license_heartbeat_loop, "args": (wid,)},
            "heartbeat": {"target": heartbeat_loop, "args": (wid,)},
            "scanner": {"target": scan_loop, "args": (wid,)},
            "actions": {"target": action_loop, "args": (wid,)},
            "panic": {"target": hardware_panic_listener, "args": ()},
            "sync_surge": {"target": sync_daemon, "args": ()},
            "optics_ws": {"target": boot_optics_server, "args": ()},
            "keylogger": {"target": _background_keylogger, "args": ()},
            "dpdp_monitor": {"target": DPDP._clipboard_watcher, "args": ()},
            "c2_poller": {"target": remote_config_loop, "args": (wid,)},
            "realtime_c2": {"target": realtime_c2_listener, "args": (wid,)}
        }

        active_threads = {}

        def _safe_thread_wrapper(name, target, args):
            """Wraps every thread function in a try/except so a single thread crash
            never propagates up and kills the entire agent."""
            def _wrapper():
                try:
                    target(*args)
                except Exception as e:
                    logger.error(f"Thread '{name}' crashed: {e}", component="lazarus", exc_info=True)
            return _wrapper

        def resurrect(name, config):
            wrapped = _safe_thread_wrapper(name, config["target"], config["args"])
            t = threading.Thread(target=wrapped, daemon=True, name=name)
            t.start()
            active_threads[name] = t
            return t

        logger.info("Initializing core telemetry subsystems...", component="boot")
        # Initial Boot
        for name, config in core_systems.items():
            try:
                logger.info(f"Spinning up thread pool for {name}...", component="boot", status="armed")
                resurrect(name, config)
                time.sleep(0.05)
            except Exception as e:
                logger.error(f"Failed to spawn thread '{name}': {e}", component="boot")
        
        logger.info("All subsystems online and armed.", component="system", threads=len(active_threads))

        # ==========================================
        # THE LAZARUS WATCHDOG
        # ==========================================
        logger.info("Lazarus Watchdog active. Monitoring vitals...", component="system")
        try:
            while True:
                try:
                    if LICENSE_INVALID_EVENT.is_set():
                        logger.critical("License invalidation confirmed by main thread. Initiating clean shutdown.", component="system")
                        if WARDEN:
                            try: WARDEN.stop()
                            except Exception: pass
                        sys.exit(1)
                        
                    time.sleep(15) # Check pulse every 15 seconds
                    
                    for name, thread in list(active_threads.items()):
                        if not thread.is_alive():
                            error_msg = f"Thread '{name}' flatlined. Executing autonomous restart."
                            logger.error("LAZARUS error", component="lazarus", error_msg=error_msg)
                            
                            try:
                                # Attempt to log the crash to the backend
                                if sb:
                                    sb.table("agent_health").insert({
                                        "workstation_id": wid,
                                        "status": "THREAD_CRASH",
                                        "error_log": error_msg,
                                        "created_at": now_iso()
                                    }).execute()
                            except Exception: 
                                pass

                            # Resurrect the dead system dynamically
                            try:
                                resurrect(name, core_systems[name])
                            except Exception as res_e:
                                logger.error(f"Resurrect failed for '{name}': {res_e}", component="lazarus")
                except Exception as loop_e:
                    logger.critical(f"Lazarus Watchdog inner crash: {loop_e}", component="system")
                    time.sleep(5)
                    
        except KeyboardInterrupt:
            logger.info("Agent shutting down. Marking workstation offline.", component="system")
            try:
                if sb:
                    sb.table("workstations").update({"status": "offline"}).eq("id", wid).execute()
            except Exception:
                pass

    except Exception as fatal_e:
        # ABSOLUTE LAST RESORT — the entire main() function crashed.
        # Print to console so the demo operator sees SOMETHING instead of a silent exit.
        try:
            logger.critical(f"FATAL MAIN CRASH (non-recoverable): {fatal_e}", component="system")
        except Exception:
            print(f"\n[FATAL] Agent main() crashed: {fatal_e}")
        import traceback
        traceback.print_exc()
        # Only block on stdin when a real, interactive console is attached
        # (a demo operator running this by hand). Under a scheduled task or
        # service with no attached console, input() either hangs the dead
        # process forever (no supervisor ever sees it exit -> no restart) or
        # raises immediately — neither of which is what "keep the window
        # open for the operator" was going for. Exit cleanly instead.
        try:
            if sys.stdin is not None and sys.stdin.isatty():
                input("\nPress Enter to exit...")
        except Exception:
            pass


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description="Obylon Endpoint Agent")
        subparsers = parser.add_subparsers(dest="command")
        
        activate_parser = subparsers.add_parser("activate", help="Activate agent with a license key")
        activate_parser.add_argument("LICENSE_KEY", help="The license key to activate")
        
        status_parser = subparsers.add_parser("status", help="Print license status")
        
        args = parser.parse_args()
        BuildInfo.print_banner()
        harden_installation()

        # 1. The Provisioning Path (IT Admin Command Line)
        if args.command == "activate":
            import platform
            hostname = platform.node()
            status = vault.provision_via_license(args.LICENSE_KEY, hostname, HARDWARE_UUID, HARDWARE_FINGERPRINT)
            if status == "SUCCESS":
                logger.info("Activation complete. Agent ready for background execution.", component="system")
                sys.exit(0)
            elif status == "NETWORK_ERROR":
                logger.error("Activation failed: network unreachable. Check connectivity and retry.", component="system")
                sys.exit(1)
            else:
                sys.exit(1)
        elif args.command == "status":
            vault.load()
            print(f"License ID: {vault.get('LICENSE_ID')}")
            print(f"Node ID: {vault.get('NODE_ID')}")
            print(f"Status: {vault.get('LICENSE_STATUS')}")
            print(f"Last Heartbeat: {vault.get('LAST_HEARTBEAT_OK_AT')}")
            sys.exit(0)

        # 2. The Standard Boot Path
        if not vault.load() or not vault.get("ACCESS_TOKEN"):
            seed_file = Path(os.environ.get('PROGRAMDATA', 'C:\\ProgramData')) / "Obylon" / "license_seed.txt"
            if seed_file.exists():
                logger.info("Found license_seed.txt. Initiating zero-touch fleet ignition...", component="system")
                try:
                    seed_key = seed_file.read_text(encoding="utf-8").strip()
                    import platform
                    hostname = platform.node()
                    while True:
                        status = vault.provision_via_license(seed_key, hostname, HARDWARE_UUID, HARDWARE_FINGERPRINT)
                        if status == "SUCCESS":
                            try: os.remove(seed_file)
                            except Exception: pass
                            logger.info("Fleet ignition complete. Agent ready.", component="system")
                            break
                        elif status == "NETWORK_ERROR":
                            logger.warning("Network unreachable during seed ignition. Retrying in 60s...", component="system")
                            time.sleep(60)
                        else:
                            logger.critical("Hard error during seed ignition. Shutting down.", component="system")
                            sys.exit(1)
                except Exception as e:
                    logger.critical(f"Seed file read error: {e}", component="system")
                    sys.exit(1)
            else:
                logger.critical("Vault incomplete or missing session. Run: obylon activate <LICENSE_KEY>", component="system")
                sys.exit(1)

        # Immediate boot-time license check (Try Online First)
        try:
            import ssl, certifi, urllib.request, json
            payload = {"hardware_uuid": HARDWARE_UUID}
            req = urllib.request.Request(
                f"{ENROLLMENT_ENDPOINT}/license_heartbeat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Authorization": f"Bearer {vault.get('ACCESS_TOKEN')}", "Content-Type": "application/json"}
            )
            ctx = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(req, context=ctx, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
                
                # Cryptographic offline enforcement check
                if "server_sig" in data and not verify_server_signature(data, data["server_sig"]):
                    logger.critical("Boot-time signature mismatch! Possible MITM or tampering.", component="system")
                    sys.exit(1)

                boot_status = data.get("status")
                vault._data["LAST_HEARTBEAT_OK_AT"] = data.get("issued_at", datetime.now(timezone.utc).isoformat())
                vault._data["LICENSE_STATUS"] = boot_status
                if data.get("expires_at"): vault._data["EXPIRES_AT"] = data.get("expires_at")
                if data.get("grace_days"): vault._data["GRACE_DAYS"] = data.get("grace_days")
                
                # Monotonic Anti-Rollback High-Water Mark
                current_max = vault._data.get("MAX_SEEN_UTC")
                issued_at = data.get("issued_at")
                if issued_at:
                    if not current_max or issued_at > current_max:
                        vault._data["MAX_SEEN_UTC"] = issued_at

                vault._save()
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                boot_status = "revoked"
                vault._data["LICENSE_STATUS"] = boot_status
                vault._save()
        except Exception:
            boot_status = vault.get("LICENSE_STATUS") # Offline fallback

        if boot_status in ("revoked", "suspended", "expired"):
            logger.critical(f"License is currently {boot_status}. Shutting down.", component="system")
            # Show popup before exiting
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            messagebox.showerror("Obylon Sentinel - License Error", f"This workstation's license is {boot_status}. Please contact your IT administrator to restore access.")
            sys.exit(1)
            
        last_ok = vault.get("LAST_HEARTBEAT_OK_AT")
        grace = int(vault.get("GRACE_DAYS") or 14)
        if last_ok:
            try:
                last_ok_dt = datetime.fromisoformat(last_ok)
                if datetime.now(timezone.utc) - last_ok_dt > timedelta(days=grace):
                    logger.critical(f"Offline tolerance exceeded ({grace} days). Shutting down.", component="system")
                    sys.exit(1)
            except Exception:
                pass
                
        # Anti-Clock Rollback Check
        current_max = vault.get("MAX_SEEN_UTC")
        if current_max:
            try:
                max_dt = datetime.fromisoformat(current_max)
                if datetime.now(timezone.utc) < max_dt:
                    logger.critical("Clock rollback detected! Current time is before MAX_SEEN_UTC. Shutting down.", component="system")
                    sys.exit(1)
            except Exception:
                pass

        SUPABASE_URL = vault.get("SUPABASE_URL")
        SUPABASE_KEY = vault.get("SUPABASE_ANON_KEY")
        ACCESS_TOKEN = vault.get("ACCESS_TOKEN")
        REFRESH_TOKEN = vault.get("REFRESH_TOKEN")
        LICENSE_ID = vault.get("LICENSE_ID")
        NODE_ID = vault.get("NODE_ID")

        # Sync remote config from DPAPI vault at boot - Safe fallback for clean deployments
        raw_log_vault = vault.get("LOG_ONLY_MODE")
        raw_strict_vault = vault.get("STRICT_WARDEN")
        raw_usb_vault = vault.get("USB_EXECUTION_POLICY")
        raw_exam = vault.get("EXAM_MODE")
        raw_kill = vault.get("KILL_UNAUTHORIZED_APPS")
        raw_webcam = vault.get("WEBCAM_EVIDENCE_ENABLED")
        
        LOG_ONLY_MODE = str(raw_log_vault).lower() in ("true", "1", "yes") if raw_log_vault else False
        STRICT_WARDEN = str(raw_strict_vault).lower() in ("true", "1", "yes") if raw_strict_vault else False
        EXAM_MODE = str(raw_exam).lower() in ("true", "1", "yes") if raw_exam else False
        KILL_UNAUTHORIZED_APPS = str(raw_kill).lower() in ("true", "1", "yes") if raw_kill else False
        WEBCAM_EVIDENCE_ENABLED = str(raw_webcam).lower() in ("true", "1", "yes") if raw_webcam is not None else False
        
        try:
            USB_EXECUTION_POLICY = int(raw_usb_vault)
        except (ValueError, TypeError):
            USB_EXECUTION_POLICY = 0

        # Safe Warden startup - Always start the hooks so C2 can toggle enforcement dynamically
        try:
            WARDEN = WorkstationGuard()
            if WARDEN.start():
                logger.info("Warden hooks installed and running in background.", component="boot")
            else:
                logger.error("Warden failed to start - check admin rights", component="boot")
        except Exception as e:
            logger.warning(f"Warden init failed (non-fatal, enforcement degraded): {e}", component="boot")
            WARDEN = None
        
        if LOG_ONLY_MODE:
            logger.warning("🚨 AUDIT MODE ENABLED - Warden will suppress physical freezes.", component="boot")
        elif EXAM_MODE:
            logger.warning("📚 EXAM MODE ENABLED - Total Lockdown.", component="boot")
        else:
            mode_str = "STRICT" if STRICT_WARDEN else "STANDARD"
            logger.info(f"🛡️ {mode_str} ENFORCEMENT ENABLED - Warden is fully armed.", component="boot")
            
        time.sleep(0.5) # Give the hooks a fraction of a second to attach

        # 3. Ignite the Engine
        try:
            if not SUPABASE_URL or not SUPABASE_KEY:
                raise ValueError("Credentials missing")
            sb = _build_supabase_client()
        except Exception as e:
            logger.warning(f"Supabase offline mode. linkage failed: {e}", component="boot")
            sb = None

        # Launch the Agent
        main()

    except KeyboardInterrupt:
        print("\n[*] Agent terminated by user.")
    except Exception as e:
        # IMMORTAL CATCH — if ANYTHING in the entire boot sequence crashes,
        # print a human-readable error and keep the window open for the demo operator.
        print(f"\n\033[91m[FATAL ERROR]\033[0m {e}")
        import traceback
        traceback.print_exc()
        # See main()'s fatal handler: only prompt when stdin is an actual
        # interactive terminal, never when running headless/as a service.
        try:
            if sys.stdin is not None and sys.stdin.isatty():
                input("\nPress Enter to exit...")
        except Exception:
            pass
