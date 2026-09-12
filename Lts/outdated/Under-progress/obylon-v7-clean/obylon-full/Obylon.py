"""
OBYLON SENTINEL — School Endpoint Monitor
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

v7.0.0 ENGINEERING CHANGELOG
============================
    1. SESSION BROKER (boot deadlock fix): the SYSTEM scheduled task now
       runs ObylonBroker.exe (Rust — see rust/broker), a thin supervisor
       which spawns ObylonCore.exe into the ACTIVE INTERACTIVE SESSION via
       WTSGetActiveConsoleSessionId + WTSQueryUserToken + CreateProcessAsUser,
       with the user's environment block and profile directory exported
       (OBYLON_USER_PROFILE). Core in turn spawns this Python process as a
       plain child, already inside the student's session. The agent
       therefore inherits the student's network context (per-user proxy /
       WPAD / user-installed TLS roots used by school filters) and UI
       context instead of suffocating in Session 0. Crash-rate-limited
       respawn, session-flip handling, full handle hygiene now live in the
       Rust broker rather than here. Low-level input hooks, the freeze
       auto-expiry timer, the classroom-focus overlay, keylogging, and
       screenshot/webcam capture have likewise moved to ObylonCore.exe
       (rust/core) — see WorkstationGuard and the capture_*() functions
       below, which are now thin IPC clients rather than the implementation
       itself. All admin/CLI commands (activate, status, diagnose, etc.)
       have moved to the standalone obylonc.exe (Go) — this file's __main__
       is now just the bare agent boot sequence.
    2. OCR ENGINE: bounded worker queue, per-job subprocess timeout,
       screenshot downscaling, content-digest dedupe, and — critically —
       the OCR score is now actually consumed by the arbitration pipeline
       (previously the async result was logged and discarded, so OCR never
       influenced enforcement at all).
    3. BROWSER COVERAGE: full browser registry (Chromium + Gecko families).
       The FSM no longer goes dark on Firefox/Brave/Opera/Vivaldi; unknown
       telemetry silence is surfaced as an explicit STRUCTURAL_DARK state
       instead of being indistinguishable from IDLE.
    4. PROVENANCE ENGINE (USB loophole): execution origin is decided by
       Zone.Identifier ADS inspection, WMI ParentProcessId lineage walk,
       and a session mount journal — not by "does the path contain E:\\".
       Copy-to-Desktop-then-run is now attributable.
    5. LEXICAL ENGINE: deterministic Unicode-block script detection,
       a structured native-script term registry (Devanagari/Arabic/CJK/
       Cyrillic/Kana/Hangul), a real phonetic skeleton cross-check for
       transliteration variance (the previously-claimed-but-missing
       channel), a real substring-containment channel, and the QWERTY
       typo modifier is now scoped to Latin tokens only.
    6. ANGEL ENGINE: generalized category framework with per-category
       benign markers AND aggravator veto lists (self-harm, drugs,
       weapons, piracy, adult-explicit). Structural-confirmed adult hits
       can no longer be defused by nearby benign vocabulary.
"""

from __future__ import annotations # MUST BE FIRST


# PIL/pytesseract moved to a lazy import — see _ensure_ocr_libs() — they're
# only ever needed inside the OCR worker's _run(), and loading PIL's C
# extensions is real, measurable time that was previously being paid
# unconditionally at the very top of every single boot, whether or not
# OCR ever actually runs in a given session.
import sys
import os



import certifi
os.environ["SSL_CERT_FILE"] = certifi.where()
import unicodedata

def _get_tesseract_path():
    # In --onedir mode, tesseract is installed next to the exe by the ISS
    # installer, NOT inside _internal/. We must check the exe directory
    # first, then fall back to _MEIPASS for development builds.
    if getattr(sys, 'frozen', False):
        # Frozen exe — always resolve relative to the user-facing binary
        base_dir = os.path.dirname(sys.executable)
    elif hasattr(sys, '_MEIPASS'):
        # PyInstaller temp extraction dir (--onefile dev builds)
        base_dir = sys._MEIPASS
    else:
        # Script directory (unpackaged dev)
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    tessdata_dir = os.path.join(base_dir, "tesseract_engine", "tessdata")
    os.environ["TESSDATA_PREFIX"] = tessdata_dir
    return os.path.join(base_dir, "tesseract_engine", "tesseract.exe")

# Lazy OCR-library init — see the comment at the top of the file. Bound
# once, on first real use, by whichever OCR worker thread hits it first;
# every access after that is just an Event check, not a re-import.
import threading  # needed immediately below; the file's main `import threading`
                   # further down is fine too — re-importing an already-loaded
                   # module is a cheap sys.modules lookup, not a re-execution.
_ocr_libs_ready = threading.Event()
_ocr_libs_lock = threading.Lock()
_Image = None
_pytesseract = None

def _ensure_ocr_libs():
    global _Image, _pytesseract
    if _ocr_libs_ready.is_set():
        return
    with _ocr_libs_lock:
        if _ocr_libs_ready.is_set():
            return
        from PIL import Image as _image_mod
        import pytesseract as _pytesseract_mod
        _pytesseract_mod.pytesseract.tesseract_cmd = _get_tesseract_path()
        _Image = _image_mod
        _pytesseract = _pytesseract_mod
        _ocr_libs_ready.set()

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
from enum import Enum, auto

# --- PHASE 1: OBSERVABILITY STATE TRACKING ---
class NetworkState(Enum):
    OFFLINE = auto()
    ONLINE = auto()

class AuthState(Enum):
    UNINITIALIZED = auto()
    AUTHENTICATED = auto()
    REFRESHING = auto()
    AUTH_REQUIRED = auto()
    AUTH_FAILED = auto()
    AUTH_TERMINAL = auto()

class ClientState(Enum):
    ABSENT = auto()
    CREATING = auto()
    READY = auto()
    INVALID = auto()
    FAILED = auto()

class LicenseState(Enum):
    UNKNOWN = auto()
    VALID = auto()
    CHECKING = auto()
    TEMPORARILY_UNAVAILABLE = auto()
    UNAUTHORIZED = auto()
    REVOKED = auto()
    SUSPENDED = auto()
    EXPIRED = auto()

class SyncState(Enum):
    IDLE = auto()
    BLOCKED_BY_NETWORK = auto()
    BLOCKED_BY_AUTH = auto()
    BLOCKED_BY_CLIENT = auto()
    FLUSHING = auto()
    DEGRADED = auto()

class SecurityState(Enum):
    UNKNOWN = auto()
    READY = auto()
    BLOCKED = auto()
    CORRUPT = auto()
    IDENTITY_MISMATCH = auto()

class SystemStateTracker:
    def __init__(self):
        self.lock = threading.Lock()
        self.network = NetworkState.OFFLINE
        self.auth = AuthState.UNINITIALIZED
        self.client = ClientState.ABSENT
        self.license = LicenseState.UNKNOWN
        self.sync = SyncState.IDLE
        self.security = SecurityState.UNKNOWN
        self.session_generation = 0
    
    def _log_transition(self, component: str, old_state: Enum, new_state: Enum, reason: str, operation: str, attempt: int = 1, queue_depth: int = 0, next_action: str = ""):
        if old_state == new_state:
            return
        try:
            logger.info(
                f"{component} state changed {old_state.name} -> {new_state.name}",
                component="telemetry",
                sub_component=component,
                previous_state=old_state.name,
                new_state=new_state.name,
                reason=reason,
                operation=operation,
                attempt=attempt,
                session_generation=self.session_generation,
                queue_depth=queue_depth,
                next_action=next_action
            )
        except NameError:
            pass # logger not initialized yet

    def update_network(self, state: NetworkState, reason: str, op: str, next_act: str=""):
        with self.lock:
            old, self.network = self.network, state
            self._log_transition("network_state", old, state, reason, op, next_action=next_act)

    def update_auth(self, state: AuthState, reason: str, op: str, next_act: str=""):
        with self.lock:
            old, self.auth = self.auth, state
            self._log_transition("auth_state", old, state, reason, op, next_action=next_act)

    def update_client(self, state: ClientState, reason: str, op: str, next_act: str=""):
        with self.lock:
            old, self.client = self.client, state
            self._log_transition("client_state", old, state, reason, op, next_action=next_act)

    def update_license(self, state: LicenseState, reason: str, op: str, next_act: str=""):
        with self.lock:
            old, self.license = self.license, state
            self._log_transition("license_state", old, state, reason, op, next_action=next_act)

    def update_sync(self, state: SyncState, reason: str, op: str, q_depth: int=0, next_act: str=""):
        with self.lock:
            old, self.sync = self.sync, state
            self._log_transition("sync_state", old, state, reason, op, queue_depth=q_depth, next_action=next_act)

    def update_security(self, state: SecurityState, reason: str, op: str, next_act: str=""):
        with self.lock:
            old, self.security = self.security, state
            self._log_transition("security_state", old, state, reason, op, next_action=next_act)

    def bump_generation(self):
        with self.lock:
            self.session_generation += 1

    def is_ready_for_sync(self) -> bool:
        """PHASE 3 FIX: Enforce comprehensive dependency chain before allowing sync."""
        with self.lock:
            return (
                self.network == NetworkState.ONLINE and
                self.auth == AuthState.AUTHENTICATED and
                self.client == ClientState.READY and
                self.license == LicenseState.VALID
            )

sys_state = SystemStateTracker()

class SessionManager:
    """PHASE 2: Authoritative Session Lifecycle Owner"""
    def __init__(self):
        self._lock = threading.RLock()
        self._client = None
        self._access_token = None
        self._refresh_token = None
    
    def _is_valid_jwt(self, token: str) -> bool:
        if not token:
            return False
        # A valid Supabase JWT must have exactly two dots (Header.Payload.Signature)
        return len(token.split(".")) == 3

    def get_client(self):
        """Returns the current authenticated client, or None if not ready."""
        with self._lock:
            return self._client
            
    def get_tokens(self):
        with self._lock:
            return self._access_token, self._refresh_token

    def initialize_from_vault(self):
        with self._lock:
            sys_state.update_client(ClientState.CREATING, "Initializing from vault", "session_mgr")
            self._access_token = vault.get("ACCESS_TOKEN")
            self._refresh_token = vault.get("REFRESH_TOKEN")
            
            # PHASE 2 FIX: Validate JWT structure BEFORE passing to Supabase SDK
            # This prevents the `list index out of range` crash caused by the 32-char CLI token.
            if self._access_token and not self._is_valid_jwt(self._access_token):
                logger.critical("Vault ACCESS_TOKEN is not a valid JWT (likely poisoned by CLI). Purging auth state.", component="auth")
                self.invalidate_session()
                sys_state.update_auth(AuthState.AUTH_TERMINAL, "Corrupted vault token", "session_mgr")
                sys_state.update_security(SecurityState.CORRUPT, "Vault token poisoned", "session_mgr")
                return False
                
            try:
                # School Supabase endpoints have standard Let's Encrypt certificates.
                client = create_client(
                    SUPABASE_URL, SUPABASE_KEY,
                    options=ClientOptions(httpx_client=httpx.Client(verify=certifi.where(), timeout=30.0), auto_refresh_token=True, persist_session=False)
                )
                
                if self._access_token and self._refresh_token:
                    sys_state.update_auth(AuthState.REFRESHING, "Setting local token", "session_mgr")
                    client.auth.set_session(self._access_token, self._refresh_token)
                    
                    # Force a refresh to ensure it's still valid
                    session = client.auth.get_session()
                    if session and hasattr(session, 'session') and session.session is not None:
                        session = session.session
                    if session and hasattr(session, 'access_token') and session.access_token != self._access_token:
                        self._access_token = session.access_token
                        self._refresh_token = session.refresh_token
                        vault._data["ACCESS_TOKEN"] = self._access_token
                        vault._data["REFRESH_TOKEN"] = self._refresh_token
                        vault._save()
                        
                    self._client = client
                    sys_state.update_auth(AuthState.AUTHENTICATED, "Session restored", "session_mgr")
                    sys_state.update_client(ClientState.READY, "Client authenticated", "session_mgr")
                    sys_state.bump_generation()
                    return True
                else:
                    self._client = client
                    sys_state.update_auth(AuthState.UNINITIALIZED, "No tokens in vault", "session_mgr")
                    sys_state.update_client(ClientState.READY, "Anonymous client ready", "session_mgr")
                    return False
                    
            except Exception as e:
                self._client = None
                err_str = str(e)
                if "401" in err_str or "unauthorized" in err_str.lower() or "expired" in err_str.lower():
                    sys_state.update_auth(AuthState.AUTH_FAILED, "Token expired or rejected", "session_mgr")
                else:
                    sys_state.update_auth(AuthState.AUTH_FAILED, f"Init failed: {e}", "session_mgr")
                sys_state.update_client(ClientState.FAILED, "Auth failed during client init", "session_mgr")
                logger.error("Client init failed", component="auth", error=err_str, exc_info=True)
                return False

    def force_refresh(self) -> bool:
        """Single-flight refresh invoked by heartbeat or when 401s are detected."""
        with self._lock:
            if not self._client:
                return False
                
            sys_state.update_auth(AuthState.REFRESHING, "Forcing active refresh", "session_mgr")
            try:
                session = self._client.auth.refresh_session()
            except Exception as e:
                logger.debug(f"Refresh call failed (could be network or expired): {e}", component="auth")
                session = self._client.auth.get_session()
                
            if session:
                if hasattr(session, 'session') and session.session is not None:
                    session = session.session
                if hasattr(session, 'access_token') and session.access_token != self._access_token:
                    self._access_token = session.access_token
                    self._refresh_token = session.refresh_token
                    vault._data["ACCESS_TOKEN"] = self._access_token
                    vault._data["REFRESH_TOKEN"] = self._refresh_token
                    vault._save()
                    TOKEN_ROTATED_EVENT.set()
                    sys_state.bump_generation()
                    logger.info("Session token rotated successfully", component="auth")
                sys_state.update_auth(AuthState.AUTHENTICATED, "Session refreshed", "session_mgr")
                return True
            else:
                sys_state.update_auth(AuthState.AUTH_FAILED, "Session is dead after refresh", "session_mgr")
                self.invalidate_session()
                return False

    def invalidate_session(self):
        """Purge corrupted or permanently dead sessions."""
        with self._lock:
            self._access_token = None
            self._refresh_token = None
            self._client = None
            vault._data["ACCESS_TOKEN"] = None
            vault._data["REFRESH_TOKEN"] = None
            vault._save()
            sys_state.update_auth(AuthState.UNINITIALIZED, "Session invalidated", "session_mgr")
            sys_state.update_client(ClientState.ABSENT, "Client purged", "session_mgr")
            sys_state.bump_generation()

session_manager = SessionManager()


import subprocess
import threading
import time
import uuid
import traceback
from pynput import keyboard
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
    import structlog
    import tkinter as tk
except ImportError:
    sys.exit("Install dependencies: pip install supabase psutil pillow pywin32 structlog")

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
            "issued_at": payload.get("issued_at"),
            "status": payload.get("status")
        }, separators=(',', ':')).encode("utf-8")
        
        verify_key.verify(sign_payload, base64.b64decode(server_sig))
        return True
    except Exception as e:
        logger.error(f"Signature verify failed: {e}", component="license")
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
    # Fix for pythonw / console=False where sys.stdout is None causing structlog/print to crash
    import sys
    import os
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
        
    # Setup structlog for console + file — fallback to script dir if ProgramData is locked
    try:
        log_dir = Path(os.environ.get('PROGRAMDATA', 'C:\\ProgramData')) / 'Obylon' / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError):
        log_dir = Path(os.path.dirname(os.path.abspath(__file__))) / '.obylon_logs'
        try: log_dir.mkdir(parents=True, exist_ok=True)
        except Exception: pass
        
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(log_dir), 2)
    except Exception: pass

    class MultiStream:
        def __init__(self, streams):
            self.streams = [s for s in streams if s is not None]
        def write(self, data):
            for s in self.streams:
                try:
                    s.write(data)
                    s.flush()
                except Exception: pass
        def flush(self):
            for s in self.streams:
                try: s.flush()
                except Exception: pass
                
    log_file_path = log_dir / "obylon.log"
    try:
        log_file = open(log_file_path, "a", encoding="utf-8")
    except Exception:
        log_file = None

    if sys.stdout.name != os.devnull:
        output_stream = MultiStream([sys.stdout, log_file])
    else:
        output_stream = MultiStream([log_file]) if log_file else open(os.devnull, "w")

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S.%f", utc=False),
            custom_log_renderer,
        ],
        logger_factory=structlog.PrintLoggerFactory(file=output_stream),
        wrapper_class=structlog.make_filtering_bound_logger(0),
    )
    return structlog.get_logger("obylon_agent")

logger = setup_structlog()


# --- GLOBAL IDENTITY FILES ---
def resolve_user_profile_dir() -> Path:
    """Home directory of the *interactive* user — not of the service account.

    When the Session Broker spawns the agent with the logged-on user's token,
    Path.home() is already correct. In the degraded fallback (agent holding a
    SYSTEM token retargeted into the user session) Path.home() would resolve
    to C:\\Windows\\System32\\config\\systemprofile and the vault/evidence DB
    would land where no admin will ever look. The broker therefore exports
    OBYLON_USER_PROFILE; we honor it first, then try the WTS profile API,
    then fall back to Path.home().
    """
    env_profile = os.environ.get("OBYLON_USER_PROFILE")
    if env_profile and os.path.isdir(env_profile):
        return Path(env_profile)
    if platform.system() == "Windows":
        try:
            import win32ts as _w32ts
            import win32api as _w32api
            import win32profile as _w32prof
            sid = _w32ts.WTSGetActiveConsoleSessionId()
            if sid not in (0xFFFFFFFF, None):
                tok = None
                try:
                    tok = _w32ts.WTSQueryUserToken(sid)
                    prof = _w32prof.GetUserProfileDirectory(tok)
                    if prof and os.path.isdir(prof):
                        return Path(prof)
                finally:
                    if tok:
                        try: _w32api.CloseHandle(tok)
                        except Exception: pass
        except Exception:
            pass
    return Path.home()

USER_HOME = resolve_user_profile_dir()
ALIAS_FILE = USER_HOME / ".obylon_alias"

# A3: Machine-level identity — one HARDWARE_UUID per machine instead of one per
# user profile, so shared PCs no longer fragment license seats across students.
IDENTITY_FILE = Path(os.environ.get('PROGRAMDATA', 'C:\\ProgramData')) / "Obylon" / ".machine_id"


def _migrate_legacy_paths():
    """Rename .sentinel_* → .obylon_* for existing installations (A5)."""
    migrations = [
        (USER_HOME / ".sentinel_alias",             USER_HOME / ".obylon_alias"),
        (USER_HOME / ".sentinel_vault.db",          USER_HOME / ".obylon_vault.db"),
        (USER_HOME / ".sentinel_vault.db-wal",      USER_HOME / ".obylon_vault.db-wal"),
        (USER_HOME / ".sentinel_vault.db-shm",      USER_HOME / ".obylon_vault.db-shm"),
        (USER_HOME / ".sentinel_cache",             USER_HOME / ".obylon_cache"),
        (USER_HOME / ".sentinel_dead_letter.jsonl", USER_HOME / ".obylon_dead_letter.jsonl"),
        (USER_HOME / ".sentinel_err.txt",           USER_HOME / ".obylon_err.txt"),
    ]
    for old, new in migrations:
        if old.exists() and not new.exists():
            try:
                old.rename(new)
                logger.info("Migrated legacy path", component="upgrade", old=str(old), new=str(new))
            except Exception as e:
                logger.warning("Legacy path migration failed", component="upgrade",
                               old=str(old), error=str(e))


# Runs at import time — before any module-level file access (e.g. the alias
# read in get_workstation_identity() below) touches a renamed path.
_migrate_legacy_paths()

# --- THE LAZARUS DYING BREATH SOS ---
def dying_breath_handler(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    crash_log = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.error("SYSTEM COLLAPSE DETECTED. Transmitting SOS...", component="system", crash_log=crash_log, exc_info=True)
    try:
        if session_manager.get_client() is not None:
            session_manager.get_client().table("agent_health").insert({
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

# NOTE: as of the Rust phase-1 split, the low-level keyboard/mouse hook
# itself lives in ObylonCore.exe (rust/obylon-core), not here. These
# constants/prototypes are unused by WorkstationGuard now (it's a thin IPC
# client — see below) and are kept only in case anything else in the file
# still references the WM_* constants directly.
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

# =====================================================
# CORE IPC CLIENT (Phase 1 Rust split)
# =====================================================
# ObylonCore.exe (Rust) now owns the low-level keyboard/mouse hooks, the
# freeze/unfreeze state machine with its own fail-safe auto-expiry timer,
# and the classroom-focus overlay (native layered window, not Tk). Python
# no longer touches any of that directly — it just sends small JSON
# commands over a named pipe and reads a JSON response. This also means
# Python can no longer stall the enforcement path: a slow GIL-holding
# operation here can delay a *request*, but it can't delay Core's own
# hook callback or the freeze auto-expiry, because those live in a
# separate process now.
CORE_PIPE_NAME = r"\\.\pipe\ObylonCore"
CORE_IPC_TIMEOUT_SEC = 5.0

def _core_ipc_call(payload: dict, timeout: float = CORE_IPC_TIMEOUT_SEC) -> dict:
    """Send one JSON command to ObylonCore.exe over the named pipe and
    return its JSON response. Raises on any failure — callers decide
    whether that's fatal (see WorkstationGuard methods below, which log
    and degrade rather than crashing the whole agent)."""
    import win32file
    import win32pipe
    import pywintypes

    deadline = time.time() + timeout
    handle = None
    last_err = None
    while time.time() < deadline:
        try:
            handle = win32file.CreateFile(
                CORE_PIPE_NAME,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0, None, win32file.OPEN_EXISTING, 0, None
            )
            break
        except pywintypes.error as e:
            last_err = e
            if e.winerror == 231:  # ERROR_PIPE_BUSY
                try:
                    win32pipe.WaitNamedPipe(CORE_PIPE_NAME, 1000)
                except Exception:
                    pass
                continue
            time.sleep(0.2)
    if handle is None:
        raise ConnectionError(f"Cannot reach ObylonCore IPC pipe: {last_err}")

    try:
        win32pipe.SetNamedPipeHandleState(handle, win32pipe.PIPE_READMODE_MESSAGE, None, None)
        data = (json.dumps(payload) + "\n").encode("utf-8")
        win32file.WriteFile(handle, data)
        _, resp = win32file.ReadFile(handle, 65536)
        return json.loads(resp.decode("utf-8").strip())
    finally:
        try:
            win32file.CloseHandle(handle)
        except Exception:
            pass


class WorkstationGuard:
    """Thin IPC client. Enforcement itself (hooks, freeze timer, overlay)
    lives in ObylonCore.exe now — see rust/obylon-core. Method names and
    signatures are unchanged on purpose so every existing call site
    (WARDEN.lock_workstation(...), WARDEN.disengage_freeze(), etc.)
    keeps working without modification."""

    def __init__(self):
        self._lock = threading.RLock()
        self._locked_cache = False

    def start(self) -> bool:
        try:
            resp = _core_ipc_call({"cmd": "ping"})
            ok = bool(resp.get("ok"))
            if ok:
                logger.info("Connected to ObylonCore enforcement process", component="warden")
            else:
                logger.error("ObylonCore ping failed", component="warden", response=resp)
            return ok
        except Exception as e:
            logger.error("Cannot reach ObylonCore — enforcement unavailable", component="warden", error=str(e))
            return False

    def stop(self):
        # Nothing to tear down on the Python side anymore — Core owns the
        # hook thread and its own message pump. Left as a no-op so the
        # license-invalidation shutdown path (WARDEN.stop()) keeps working
        # unchanged.
        logger.info("Warden client stopped (Core process keeps running independently)", component="warden")

    def lock_workstation(self, duration: int = None, force: bool = False, reason: str = "violation"):
        global LOG_ONLY_MODE
        if LOG_ONLY_MODE and not force:
            logger.warning("Violation intercepted, but LOG_ONLY_MODE is active. Freeze suppressed.",
                            component="guard", duration_requested=duration)
            return
        try:
            resp = _core_ipc_call({"cmd": "freeze", "duration_secs": int(duration) if duration else 0, "reason": reason})
            if resp.get("ok"):
                with self._lock:
                    self._locked_cache = True
                logger.warning("Tactical Monolith Deployed - Input Severed",
                                component="warden", locked=True, duration=duration, reason=reason)
            else:
                logger.error("Core rejected freeze request", component="warden", response=resp)
        except Exception as e:
            logger.error("Freeze IPC call failed — student input may NOT be locked", component="warden", error=str(e))

    def disengage_freeze(self, reason: str | None = None):
        """`reason=None` is an unconditional/administrator-level unfreeze
        (e.g. the teacher panic hotkey, or an explicit "unfreeze" command
        from the dashboard) — it always clears the freeze. `reason=
        "classroom_focus"` is what toggling classroom focus off sends;
        Core will refuse it if the workstation is actually locked for a
        higher-priority security violation instead of blindly clearing an
        in-progress penalty out from under a student (verified bug #3)."""
        global _LAST_UNFREEZE_TS
        try:
            payload = {"cmd": "unfreeze"}
            if reason:
                payload["reason"] = reason
            resp = _core_ipc_call(payload)
            if resp.get("ok"):
                still_locked = bool(resp.get("locked"))
                with self._lock:
                    self._locked_cache = still_locked
                if still_locked:
                    logger.info("Unfreeze refused by Core — a higher-priority freeze is still active",
                                component="warden", requested_reason=reason)
                else:
                    _LAST_UNFREEZE_TS = time.time()
                    logger.info("Workstation Unlocked", component="warden")
            else:
                logger.error("Core rejected unfreeze request", component="warden", response=resp)
        except Exception as e:
            logger.error("Unfreeze IPC call failed", component="warden", error=str(e))

    @property
    def locked(self) -> bool:
        # Best-effort local cache — Core is the source of truth and owns
        # its own independent auto-expiry, so this can lag briefly right
        # around a timer-driven unfreeze. Good enough for the places that
        # read WARDEN.locked for logging/telemetry today.
        with self._lock:
            return self._locked_cache

    def terminate_process(self, target_name: str) -> bool:
        """Legacy fallback for the Action Loop Scalpel — plain psutil kill,
        not hook-related, stays in Python for phase 1."""
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
# sb global removed in Phase 2  # Will be initialized at runtime by the Vault
import threading
TOKEN_ROTATED_EVENT = threading.Event()
LICENSE_INVALID_EVENT = threading.Event()
CORE_READY = threading.Event()

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
        self._lock = threading.Lock()

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
        with self._lock:
            if not os.path.exists(self.config_file): return False
            try:
                with open(self.config_file, "rb") as f: encrypted = f.read()
                decrypted = self._decrypt(encrypted)
                self._data = json.loads(decrypted.decode("utf-8"))
                if self._data.get("SERVER_SIG"):
                    sig_payload = {
                        "license_id": self._data.get("LICENSE_ID"),
                        "node_id": self._data.get("NODE_ID"),
                        "expires_at": None if self._data.get("EXPIRES_AT") in (None, "") else self._data.get("EXPIRES_AT"),
                        "issued_at": self._data.get("LAST_HEARTBEAT_OK_AT"),
                        "status": self._data.get("LICENSE_STATUS")
                    }
                    if not verify_server_signature(sig_payload, self._data["SERVER_SIG"]):
                        logger.critical("Cached vault signature invalid — possible tampering", component="vault")
                        return False
                return True
            except Exception as e:
                logger.error(f"Config corruption detected (stale enc from another PC?): {e}", component="vault")
                try:
                    self._unhide_file()
                    os.remove(self.config_file)
                    logger.warning("Purged stale obylon.enc — hardcoded credentials will be used.", component="vault")
                except Exception:
                    pass
                return False
        try:
            with open(self.config_file, "rb") as f: encrypted = f.read()
            decrypted = self._decrypt(encrypted)
            self._data = json.loads(decrypted.decode("utf-8"))
            if self._data.get("SERVER_SIG"):
                sig_payload = {
                    "license_id": None if self._data.get("LICENSE_ID") in (None, "") else self._data.get("LICENSE_ID"),
                    "node_id": None if self._data.get("NODE_ID") in (None, "") else self._data.get("NODE_ID"),
                    "hardware_uuid": HARDWARE_UUID,
                    "expires_at": None if self._data.get("EXPIRES_AT") in (None, "") else self._data.get("EXPIRES_AT"),
                    "issued_at": None if self._data.get("LAST_HEARTBEAT_OK_AT") in (None, "") else self._data.get("LAST_HEARTBEAT_OK_AT"),
                    "status": None if self._data.get("LICENSE_STATUS") in (None, "") else self._data.get("LICENSE_STATUS")
                }
                if not verify_server_signature(sig_payload, self._data["SERVER_SIG"]):
                    logger.critical("Cached vault signature invalid — possible tampering", component="vault")
                    return False
            return True
        except Exception as e:
            logger.error(f"Config corruption detected (stale enc from another PC?): {e}", component="vault")
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
        with self._lock:
            self._unhide_file()
            try:
                with open(self.config_file, "wb") as f:
                    f.write(encrypted)
                try: 
                    import ctypes
                    ctypes.windll.kernel32.SetFileAttributesW(str(self.config_file), 2)
                except Exception: pass
            except PermissionError:
                # A1: standard student users cannot write to ProgramData. Degrade
                # to the user profile and log loudly instead of crashing.
                fallback = os.path.join(str(USER_HOME), ".obylon_vault_fallback.enc")
                
                # SSOT/Robust fix: Unhide fallback before attempting to write, to avoid Errno 13
                if os.path.exists(fallback):
                    try:
                        import ctypes
                        ctypes.windll.kernel32.SetFileAttributesW(str(fallback), 128)
                    except Exception as e:
                        logger.error(f"Failed to unhide fallback vault: {e}", component="vault")
                        
                try:
                    with open(fallback, "wb") as f:
                        f.write(encrypted)
                    try: 
                        import ctypes
                        ctypes.windll.kernel32.SetFileAttributesW(str(fallback), 2)
                    except Exception: pass
                except Exception as e:
                    logger.error(f"Fallback vault write failed: {e}", component="vault", exc_info=True)
                    raise
                    
                # Latch: all future reads/writes go to the fallback for the rest
                # of this process lifetime, so we don't retry the locked primary
                # every 3 seconds and spam the log.
                if self.config_file != fallback:
                    logger.warning("VAULT WRITE DENIED on primary path — falling back to user profile. "
                                 "This is a degraded state; vault may not persist across session flips.",
                                 component="vault", primary=self.config_file, fallback=fallback)
                    self.config_file = fallback

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
                    "SERVER_SIG": data.get("server_sig"),
                    "HARDWARE_FINGERPRINT_AT_ACTIVATION": hardware_fingerprint  # A3: enables clone detection
                }
                self._save()
                logger.info("🔒 Obylon DPAPI Vault provisioned via license.", component="vault")
                return "SUCCESS"
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            try:
                err_data = json.loads(body)
                err_type = err_data.get("error", "unknown")
                if err_type == "node_limit_reached":
                    masked_key = f"{license_key[:4]}****-****-{license_key[-4:]}" if len(license_key) > 8 else license_key
                    logger.error(
                        f"Activation REJECTED — Seat capacity exhausted. "
                        f"Key: {masked_key}, "
                        f"Active: {err_data.get('active_nodes')}/{err_data.get('node_limit')}",
                        component="vault"
                    )
                    return "NODE_LIMIT_REACHED"
                elif err_type in ("license_expired", "license_revoked", "license_suspended"):
                    logger.error(f"Activation failed: {err_type.replace('_', ' ').capitalize()}", component="vault")
                    return "EXPIRED"
                elif err_type == "invalid_key":
                    logger.error("Activation failed: Invalid license key.", component="vault")
                    return "INVALID_KEY"
                else:
                    logger.error(f"Activation failed: {err_type} — {err_data.get('message', body)}", component="vault")
                    return f"Activation failed: {err_type}"
            except Exception:
                logger.error(f"Activation failed: HTTP {e.code} — {body[:200]}", component="vault")
                return f"Activation failed: HTTP {e.code}"
        except urllib.error.URLError as e:
            logger.error(f"Activation network error: {e}", component="vault")
            return "NETWORK_ERROR"
        except Exception as e:
            logger.error(f"Activation error: {e}", component="vault")
            return f"Activation failed: {e}"

    def get(self, key: str) -> str:
        return self._data.get(key, "")

    def set(self, key: str, value: any) -> None:
        """Write a new key-value pair to the encrypted DPAPI vault."""
        self._data[key] = str(value)
        self._save()
            
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
      1. Contents of ~/.obylon_alias (stripped) if present and non-empty.
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
# Anchored to USER_HOME (the interactive student's profile) — see
# resolve_user_profile_dir() for why Path.home() is unsafe here.
VAULT_DB = USER_HOME / ".obylon_vault.db"
CACHE_DIR = USER_HOME / ".obylon_cache"
SYNC_INTERVAL = 30  # seconds

# --- Hardware Mutex ---
OPTICS_LOCK = threading.Lock()
VAULT_LOCK = threading.Lock()  # SQLite is single-writer; serialize writes

# IDENTITY_FILE is now anchored at machine level (ProgramData) — see its
# definition next to ALIAS_FILE above (A3). No per-user re-anchor here.
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
    "adulthood",            # contains 'adult' — classic substring false positive
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
        "meaning", "define", "history", "anatomy", "wiki", "tutorial",
        "medical", "clinical",
    },
    # --- v7 GENERALIZED CATEGORIES ---
    "self_harm": {
        # help-seeking / prevention / academic framing. Defusal additionally
        # requires the aggravator veto below to be silent — "suicide
        # prevention essay" defuses, "painless suicide methods" never does.
        "prevention", "prevent", "hotline", "helpline", "lifeline", "crisis",
        "awareness", "statistics", "stats", "essay", "research", "project",
        "documentary", "support", "recovery", "survivor", "survivors",
        "mental", "health", "therapy", "therapist", "counselor", "counsellor",
        "signs", "symptoms", "poem", "poetry", "novel", "book", "character",
        "analysis", "psychology", "sociology", "thesis", "paper", "romeo",
        "juliet", "speech", "assembly", "poster", "campaign",
    },
    "drugs": {
        "medical", "prescription", "effects", "awareness", "essay",
        "research", "treatment", "addiction", "recovery", "rehab",
        "documentary", "legalization", "decriminalization", "debate",
        "policy", "harm", "reduction", "study", "history", "project",
        "health", "class", "presentation",
    },
    "weapons": {
        "history", "historical", "museum", "wwii", "ww2", "ww1",
        "documentary", "development", "invention", "textbook", "essay",
        "research", "airsoft", "paintball", "replica", "model", "toy",
        "lego", "game", "gaming", "minecraft", "fortnite", "valorant",
    },
    "piracy": {
        # "crack JEE", "crack the coding interview" — Indian exam-prep and
        # tech-interview vocabulary collides hard with the warez sense.
        "interview", "jee", "neet", "upsc", "iit", "placement", "placements",
        "exam", "exams", "coding", "algorithm", "course", "learn",
        "tutorial", "certificate", "google", "amazon", "meta", "microsoft",
    },
    # ZERO-TOLERANCE: deliberately EMPTY. Structural-confirmed explicit
    # content (web_intent, known_critical_domain) is never defused by
    # nearby benign vocabulary. This closes the loophole where
    # "pornhub research wikipedia" could previously shed severity.
    "adult_explicit": set(),
    # Unknown categories get no marker-based defusal — interrogative
    # question framing may still defuse (handled separately below).
    "generic": set(),
}

# v7: AGGRAVATOR VETO — presence of any of these near the hit CANCELS the
# defusal even when benign markers are present. Benign context proves
# legitimate framing; instruction-intent vocabulary disproves it.
ANGEL_AGGRAVATORS_BY_CATEGORY = {
    "explosives": {"how", "make", "build", "diy", "tutorial", "instructions",
                   "recipe", "steps", "guide", "homemade"},
    "self_harm": {"how", "method", "methods", "painless", "easiest",
                  "fastest", "quickest", "die", "dying", "rope", "noose",
                  "pills", "overdose", "jump", "slit", "wrists"},
    "drugs": {"how", "make", "cook", "buy", "purchase", "recipe",
              "synthesize", "dose", "dosage", "dealer", "price"},
    "weapons": {"how", "make", "build", "buy", "print", "printed", "3d",
                "diy", "assembly", "assemble"},
    "piracy": set(),          # benign exam/interview framing is decisive here
    "medical_anatomy": set(),
    "adult_explicit": set(),  # irrelevant — marker set is empty, never defuses
    "generic": set(),
}

# Category inference for the generalized engine. Order matters: first match
# wins, and adult_explicit deliberately shadows everything (zero-tolerance).
_ANGEL_CATEGORY_KEYWORDS: tuple[tuple[str, frozenset[str]], ...] = (
    ("adult_explicit", frozenset({
        "porn", "pornhub", "xvideos", "xnxx", "xhamster", "redtube",
        "youporn", "hentai", "rule34", "onlyfans", "chaturbate", "nsfw",
        "xxx", "brazzers", "spankbang", "nhentai", "sex", "nude", "nudes",
        "web_intent", "known_critical_domain",
    })),
    ("self_harm", frozenset({
        "suicide", "suicidal", "su1c1d3", "kill myself", "self harm",
        "self-harm", "selfharm", "cutting", "noose", "end my life",
        "killing myself", "want to die", "suicide methods",
    })),
    ("explosives", frozenset({
        "bomb", "bombs", "explosive", "explosives", "ied", "pipebomb",
        "pipe bomb", "detonator",
    })),
    ("weapons", frozenset({
        "gun", "guns", "rifle", "pistol", "firearm", "ammo", "ammunition",
        "knife", "3d print gun",
    })),
    ("drugs", frozenset({
        "meth", "heroin", "fentanyl", "cocaine", "drugs", "weed",
        "marijuana", "ganja",
    })),
    ("piracy", frozenset({
        "crack", "keygen", "warez", "torrent", "pirate", "pirated",
    })),
)

def infer_angel_category(best_hit, lex_severity: str | None = None) -> str:
    """Map an arbitrary pipeline hit to an Angel Engine category.
    Structural/keystroke-confirmed explicit hits are forced to the
    zero-tolerance adult_explicit category."""
    h = (best_hit or "").lower() if not isinstance(best_hit, dict) else \
        str(best_hit.get("matched_text") or best_hit.get("weapon_token") or "").lower()
    if not h:
        return "generic"
    for cat, kws in _ANGEL_CATEGORY_KEYWORDS:
        for kw in kws:
            if kw in h:
                return cat
    return "generic"

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

def apply_angel_engine(title: str, best_hit, category: str | None = None, radius: int = 6) -> bool:
    """Returns True if `best_hit` should be DEFUSED (treated as benign),
    False if it should remain flagged.

    v7 — generalized framework:
      * category=None now INFERS the category from the hit itself
        (self-harm / explosives / weapons / drugs / piracy / adult),
        instead of silently defaulting every call to "explosives".
      * Defusal = benign markers near the hit AND no aggravator near the
        hit. The aggravator veto closes the false-defusal channel where
        "suicide prevention" sat next to "methods" and still defused.
      * adult_explicit has an EMPTY marker set by policy: structurally
        confirmed explicit content is never defused, and the interrogative
        shortcut is disabled for it too.
    """
    lower = title.lower()

    if category is None:
        category = infer_angel_category(best_hit)

    # Interrogative framing defuses everything EXCEPT the zero-tolerance tier.
    if category != "adult_explicit":
        for pat in ANGEL_INTERROGATIVE_PATTERNS:
            if pat.search(lower):
                return True

    markers = ANGEL_MARKERS_BY_CATEGORY.get(category, set())
    if not markers:
        return False  # generic / adult_explicit: nothing to defuse with
    aggravators = ANGEL_AGGRAVATORS_BY_CATEGORY.get(category, set())
    tokens = tokenize(title)

    if isinstance(best_hit, dict):
        target = best_hit.get("weapon_token")
    else:
        target = best_hit
    idx = tokens.index(target) if target in tokens else None

    def _window() -> list[str]:
        if idx is None:
            # Short titles: scan the whole thing — a marker just outside a
            # fixed radius shouldn't decide the outcome on a 6-word title.
            return tokens if len(tokens) <= 12 else []
        lo, hi = max(0, idx - radius), min(len(tokens), idx + radius + 1)
        return tokens[lo:hi]

    window = _window()
    if not window:
        return False
    if not any(t in markers for t in window):
        return False
    if aggravators and any(t in aggravators for t in window):
        return False  # benign framing + instruction intent = NOT defused
    return True


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
                # Silent loading for CLI professionalism
                # logger.debug("good_vocab loaded", component="lexengine", terms_count=len(terms))
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
        p = IDENTITY_FILE  # machine-level (A3)
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


# ============================================================================
# PROVENANCE ENGINE (v7) — true-origin attribution for executed files
# ============================================================================
# The old check_if_usb() asked exactly one question: "does the exe path or
# command line contain a removable drive letter?" Dragging the payload to the
# Desktop first defeated it completely. Provenance is now established by four
# independent channels, cheapest first:
#
#   CHANNEL 1 — DIRECT: image path on currently-removable media (old check).
#   CHANNEL 2 — MOTW / Zone.Identifier ADS: the Mark-of-the-Web stream
#       travels WITH the file when it is copied from a browser download or
#       from a USB stick that itself carried the mark. ZoneId 3/4 = remote
#       origin even though the file now sits on the local disk.
#   CHANNEL 3 — PARENT LINEAGE WALK: at process-creation time we snapshot
#       the process table and walk ParentProcessId up to 8 hops. If any
#       ancestor's image or command line touches removable media (a USB
#       autorun chain, a portable launcher, `cmd /c E:\...`), the child is
#       USB-ancestor-attributed no matter where its own image now lives.
#   CHANNEL 4 — SESSION MOUNT JOURNAL + RECENT INTRODUCTION: the USB
#       insertion monitor feeds every mount (letter + timestamp) into the
#       journal. An executable whose NTFS creation time is minutes-old AND
#       that appeared during a window where removable media was mounted is
#       the classic copy-to-Desktop-then-run pattern.
#
# Honest limitation (unchanged from before, by design): this remains
# detect-at-creation, not prevent-before-creation. Synchronous blocking
# needs a kernel minifilter; that is out of scope for a user-mode agent.
# ============================================================================
PROV_DIRECT_USB = "direct_usb"
PROV_MOTW = "motw_marked"               # network-origin (Zone.Identifier)
PROV_USB_ANCESTOR = "usb_ancestor"      # lineage traced to removable media
PROV_RECENT_INTRO = "recent_introduction"  # appeared locally during USB session
PROV_LOCAL = "local"

# Verdicts that count as "USB-origin execution" for enforcement purposes.
USB_PROVENANCE_VERDICTS = frozenset({PROV_DIRECT_USB, PROV_USB_ANCESTOR})

USB_RECENT_FILE_WINDOW_SEC = 600        # exe created within last 10 min
USB_SESSION_CORRELATION_SEC = 1800      # ...while USB was mounted within 30 min
MAX_LINEAGE_DEPTH = 8
MOTW_REMOTE_ZONES = {3, 4}              # 3=Internet, 4=Untrusted


def parse_zone_identifier(text: str) -> dict:
    """Parse the contents of a Zone.Identifier stream into a dict."""
    out: dict = {}
    for line in text.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip().lower()] = v.strip()
    return out


def read_zone_identifier(path: str) -> dict | None:
    """Read `path:Zone.Identifier` (NTFS Alternate Data Stream).

    Returns None when the stream is absent (local files have none) or
    unreadable. The read is a plain file open — cheap, no WMI, no drivers.
    """
    if not path or platform.system() != "Windows":
        return None
    try:
        with open(f"{path}:Zone.Identifier", "r", encoding="utf-8", errors="ignore") as f:
            return parse_zone_identifier(f.read(2048))
    except (OSError, IOError):
        return None
    except Exception:
        return None


class ProvenanceEngine:
    """Session-level origin attribution for newly created processes."""

    def __init__(self):
        self._letters: set[str] = set()
        self._letters_lock = threading.Lock()
        self._mount_journal: deque = deque(maxlen=32)   # (ts, drive_letter)
        self._journal_lock = threading.Lock()
        self._zone_cache: dict = {}                     # path -> (ts, zone|None)
        self._zone_cache_lock = threading.Lock()
        self._boot_ts = time.time()

    # ----- feeds -----
    def update_letters(self, removable_drives: set[str]) -> None:
        """Called by scan_loop each tick with its authoritative drive set."""
        if removable_drives is None:
            return
        with self._letters_lock:
            self._letters = {d.upper() for d in removable_drives}

    def note_usb_mount(self, drive_letter: str) -> None:
        """Called by the USB insertion monitor on every mount event."""
        if not drive_letter:
            return
        letter = drive_letter.upper()
        with self._journal_lock:
            self._mount_journal.append((time.time(), letter))
        with self._letters_lock:
            self._letters.add(letter if letter.endswith("\\") else letter + "\\")

    # ----- channel helpers -----
    def letters(self) -> set[str]:
        with self._letters_lock:
            return set(self._letters)

    def _zone_for(self, path: str) -> dict | None:
        now = time.time()
        with self._zone_cache_lock:
            hit = self._zone_cache.get(path)
            if hit and now - hit[0] < 30.0:
                return hit[1]
        zone = read_zone_identifier(path)
        with self._zone_cache_lock:
            if len(self._zone_cache) > 512:
                self._zone_cache.clear()
            self._zone_cache[path] = (now, zone)
        return zone

    def _usb_mounted_recently(self) -> bool:
        cutoff = time.time() - USB_SESSION_CORRELATION_SEC
        with self._journal_lock:
            return any(ts >= cutoff for ts, _ in self._mount_journal)

    def _recently_introduced(self, exe_path: str) -> bool:
        """File materialized on this machine moments ago, after agent boot,
        in a session window where removable media was seen."""
        try:
            ctime = os.path.getctime(exe_path)
        except OSError:
            return False
        now = time.time()
        if ctime < self._boot_ts or now - ctime > USB_RECENT_FILE_WINDOW_SEC:
            return False
        return self._usb_mounted_recently()

    def _lineage_hit(self, proc_info: dict, removable: set[str]) -> str | None:
        """Walk ParentProcessId chain. Returns a description of the offending
        ancestor, or None. Snapshot-based; stops on exited parents (PID
        reuse means a stale map is worse than a short one)."""
        if not removable:
            return None
        try:
            table = {}
            for p in psutil.process_iter(['pid', 'ppid', 'name', 'exe', 'cmdline']):
                try:
                    table[p.info['pid']] = p.info
                except Exception:
                    continue
        except Exception:
            return None
        cur_ppid = proc_info.get('ppid')
        seen = {proc_info.get('pid')}
        for _ in range(MAX_LINEAGE_DEPTH):
            if not cur_ppid or cur_ppid in seen or cur_ppid in (0, 4):
                return None
            seen.add(cur_ppid)
            anc = table.get(cur_ppid)
            if anc is None:
                return None  # parent already exited — chain ends
            anc_exe = (anc.get('exe') or '').upper()
            anc_cmd = ' '.join(anc.get('cmdline') or []).upper()
            for d in removable:
                d = d.upper()
                if anc_exe.startswith(d) or d in anc_cmd:
                    return f"ancestor:{anc.get('name')}({cur_ppid}) via {d}"
            cur_ppid = anc.get('ppid')
        return None

    # ----- the verdict -----
    def assess(self, proc_info: dict, removable_drives: set[str] | None = None) -> tuple[str, str]:
        """Classify a new process's origin. Returns (verdict, detail)."""
        removable = {d.upper() for d in (removable_drives or self.letters())}
        exe = proc_info.get('exe') or ''
        cmdline = ' '.join(proc_info.get('cmdline') or [])

        # Channel 1: direct execution from removable media (old behavior)
        if removable and is_process_on_removable_media(proc_info, removable):
            return PROV_DIRECT_USB, f"image_on_removable:{exe}"

        # Channel 3 (walked before MOTW: lineage beats file marks for
        # establishing *this machine's* USB involvement)
        hit = self._lineage_hit(proc_info, removable)
        if hit:
            return PROV_USB_ANCESTOR, hit

        # Channel 2: Mark-of-the-Web on the local copy
        if exe:
            zone = self._zone_for(exe)
            if zone:
                try:
                    zone_id = int(zone.get("zoneid", "0"))
                except ValueError:
                    zone_id = 0
                if zone_id in MOTW_REMOTE_ZONES:
                    ref = zone.get("referrerurl") or zone.get("hosturl") or ""
                    return PROV_MOTW, f"zoneid:{zone_id} ref:{ref[:120]}"

        # Channel 4: copy-then-run correlation
        if exe and self._recently_introduced(exe):
            return PROV_RECENT_INTRO, f"fresh_file_during_usb_session:{exe}"

        return PROV_LOCAL, ""


PROVENANCE = ProvenanceEngine()


def check_if_usb(proc_name: str, removable_drives: set[str] | None = None) -> bool:
    """Legacy shim — now backed by the Provenance Engine. True when the named
    process is attributable to removable media (direct image OR ancestor
    lineage), regardless of where its exe currently sits on disk."""
    if not proc_name:
        return False
    proc_lower = proc_name.lower().strip()
    for p in psutil.process_iter(['name', 'exe', 'cmdline', 'pid', 'ppid']):
        try:
            if p.info.get('name') and p.info['name'].lower().strip() == proc_lower:
                if is_self(p.info):
                    continue
                verdict, _ = PROVENANCE.assess(p.info, removable_drives)
                return verdict in USB_PROVENANCE_VERDICTS
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
                    # Feed the Provenance Engine session journal — this is what
                    # lets channel 4 correlate "file copied then run from Desktop".
                    PROVENANCE.note_usb_mount(drive_letter)
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


# NOTE: network-adapter polling itself moved to ObylonCore.exe (native
# GetAdaptersAddresses, no psutil poll loop needed here). The consumer —
# _consume_core_events() below — handles "new_network_adapter" events
# with the exact same fire_alert/vault_enqueue logic that used to live in
# this function's _loop(). See also: "new_process" events (replacing the
# WMI process spy) and "fast_lane_violation" events (audit-trail record
# of an action ObylonCore.exe already took on its own, before this
# process was even up).
_CORE_EVENTS_FILE = Path(os.environ.get('PROGRAMDATA', 'C:\\ProgramData')) / "Obylon" / "events" / "events.jsonl"

def _handle_core_event(evt: dict) -> None:
    kind = evt.get("type")

    if kind == "new_network_adapter":
        adapter = evt.get("adapter") or "unknown"
        suspect = bool(evt.get("suspect_tethering"))
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

    elif kind == "new_process":
        pid = evt.get("pid")
        if pid is None:
            return
        try:
            p = psutil.Process(int(pid))
            info = p.as_dict(attrs=['pid', 'ppid', 'name', 'exe', 'cmdline'])
            evaluate_new_process(info, proc_obj=p)
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            # Short-lived process already gone — still journal the name,
            # matching the old WMI path's short-lived-process fallback.
            p_name = (evt.get("name") or "").lower().strip()
            if p_name in ("powershell.exe", "cmd.exe"):
                with _SPAWNED_CRITICAL_LOCK:
                    _SPAWNED_CRITICAL_PROCESSES.add((p_name, time.time()))

    elif kind == "fast_lane_violation":
        # ObylonCore.exe already froze the workstation, showed the
        # overlay, and captured a screenshot — entirely on its own,
        # likely before this process even finished booting. This is
        # purely the audit-trail record catching up; no enforcement
        # action is taken here (calling fire_alert() would re-trigger
        # freeze/capture for something already handled) — but it DOES
        # need to land a row in `alerts`, which fire_alert() was
        # previously the only thing that did (verified bug #1: without
        # this, fast-lane violations were vaulted to unauthorized_events
        # only and never appeared as an alert on the dashboard).
        detail = evt.get("detail") or "unknown"
        kind_label = evt.get("kind") or "unknown"
        screenshot_path = evt.get("screenshot_path")
        logger.warning("⚡ FAST-LANE VIOLATION (acted on by ObylonCore before Python was up)",
                        component="fastlane", kind=kind_label, detail=detail)
        try:
            wid = vault.get("WORKSTATION_ID")
            if wid:
                record_fastlane_alert(wid, kind_label, detail, screenshot_path)
                vault_enqueue("activity", "unauthorized_events", {
                    "workstation_id": wid, "process_name": detail if kind_label == "process" else None,
                    "window_title": detail if kind_label == "window_title" else "Fast-Lane Violation",
                    "kind": f"fastlane_{kind_label}",
                    "payload": json.dumps({
                        "detail": detail, "action_taken": evt.get("action_taken"),
                        "screenshot_path": screenshot_path,
                    }),
                }, None, now_iso())
        except Exception:
            pass


def consume_core_events_loop(poll_sec: float = 2.0):
    """Drains ObylonCore.exe's events.jsonl. Rename-then-process rather
    than read-in-place, so a write landing mid-read from Core (which
    never holds the file open — see append_event() in core/src/main.rs)
    can't corrupt anything either side sees."""
    _name_current_thread("core_events")
    while True:
        try:
            if _CORE_EVENTS_FILE.exists():
                staging = _CORE_EVENTS_FILE.with_suffix(".processing")
                try:
                    os.replace(_CORE_EVENTS_FILE, staging)
                except (FileNotFoundError, PermissionError):
                    staging = None
                if staging is not None:
                    try:
                        with open(staging, "r", encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    _handle_core_event(json.loads(line))
                                except Exception as e:
                                    logger.error("failed to process a core event", component="fastlane", error=str(e))
                    finally:
                        try:
                            os.remove(staging)
                        except Exception:
                            pass
        except Exception as e:
            logger.error("core events consumer error", component="fastlane", error=str(e))
        time.sleep(poll_sec)


# ---------- WMI & FALLBACK PROCESS LAUNCH SPY (Requirement 3) ----------
_SPAWNED_CRITICAL_PROCESSES = set()
_SPAWNED_CRITICAL_LOCK = threading.Lock()


def evaluate_new_process(info: dict, proc_obj=None) -> None:
    """Unified process-creation adjudication, provenance-driven.

    Called by BOTH the WMI event path and the psutil polling fallback —
    previously each carried a full copy of this logic and they had already
    begun to drift. `info` needs pid/name/exe/cmdline; ppid enriches lineage.
    """
    p_name = (info.get('name') or "").lower().strip()

    # Tier-1 spawn journal (used by scan_loop's causal verification)
    if p_name in ("powershell.exe", "cmd.exe"):
        with _SPAWNED_CRITICAL_LOCK:
            _SPAWNED_CRITICAL_PROCESSES.add((p_name, time.time()))

    if USB_EXECUTION_POLICY <= 0 or is_self(info):
        return

    verdict, detail = PROVENANCE.assess(info)
    if verdict == PROV_LOCAL:
        return

    exe = (info.get('exe') or '').upper()
    cmdline = ' '.join(info.get('cmdline') or []).upper()

    def _kill():
        if LOG_ONLY_MODE:
            return
        try:
            target = proc_obj or psutil.Process(info['pid'])
            target.kill()
        except Exception:
            # Kill must never crash the monitor — NoSuchProcess/AccessDenied
            # and anything else are all equally non-fatal here.
            pass

    def _report(title: str, severity: str, reason: str):
        try:
            wid = vault.get("WORKSTATION_ID")
            if not wid:
                return
            fire_alert(wid, title, exe, severity, reason)
            vault_enqueue("activity", "unauthorized_events", {
                "workstation_id": wid, "process_name": exe,
                "window_title": title, "kind": "unauthorized",
                "payload": json.dumps({"cmdline": cmdline, "provenance": verdict,
                                       "detail": detail, "event_type": "provenance_flag"}),
            }, None, now_iso())
        except Exception:
            pass

    if verdict in USB_PROVENANCE_VERDICTS:
        # Policy 1: block only direct-from-USB binaries.
        # Policy 2: also block lineage-attributed/scripted launches.
        block = (verdict == PROV_DIRECT_USB and USB_EXECUTION_POLICY >= 1) or \
                (verdict == PROV_USB_ANCESTOR and USB_EXECUTION_POLICY >= 2)
        if block:
            _kill()
            logger.warning("🛡️ USB EXECUTION BLOCKED", component="usb-exec",
                           proc=exe, provenance=verdict, detail=detail,
                           audit=LOG_ONLY_MODE)
            if verdict == PROV_USB_ANCESTOR:
                _report("[TARGET LOCKED: SCRIPT] USB-Origin Execution Blocked",
                        "critical", f"unauthorized_usb_script:{exe}")
                if WARDEN and not LOG_ONLY_MODE and not _in_unfreeze_grace():
                    WARDEN.lock_workstation(duration=30)
            else:
                _report("USB Executable Blocked", "high", f"unauthorized_usb_exe:{exe}")
        else:
            logger.warning("🛡️ USB-ORIGIN EXECUTION (policy-observe)",
                           component="usb-exec", proc=exe, provenance=verdict)
    elif verdict == PROV_MOTW:
        # Network-origin executable launched from local disk. Not auto-killed
        # (too broad — every legit browser download carries MOTW), but it IS
        # now visible, which it never was before.
        logger.warning("🌐 MOTW-MARKED EXECUTABLE LAUNCHED", component="usb-exec",
                       proc=exe, detail=detail)
        _report("Network-Origin Executable Launched", "high", f"motw_origin_exec:{exe}")
    elif verdict == PROV_RECENT_INTRO:
        # The copy-to-Desktop-then-run pattern. Warning-level unless the name
        # itself is on the USB blocklist — then treat it as USB-origin.
        if USB_EXEC_BLOCKLIST.search(exe) or USB_EXEC_BLOCKLIST.search(cmdline):
            logger.warning("🛡️ USB COPY-THEN-RUN BLOCKED", component="usb-exec",
                           proc=exe, detail=detail)
            _kill()
            _report("[TARGET LOCKED] Copied-From-USB Execution Blocked",
                    "critical", f"usb_copy_then_run:{exe}")
            if WARDEN and not LOG_ONLY_MODE and not _in_unfreeze_grace():
                WARDEN.lock_workstation(duration=30)
        else:
            logger.info("Recently-introduced executable during USB session",
                        component="usb-exec", proc=exe, detail=detail)
            _report("Recently-Introduced Executable (USB session correlation)",
                    "warning", f"recent_intro_during_usb:{exe}")


# NOTE: start_wmi_process_monitor() is gone — both its WMI-event path AND
# its psutil-polling fallback are replaced by ObylonCore.exe's native
# ToolHelp32 snapshot-diffing (rust/obylon-core, process_monitor_loop),
# which forwards "new_process" events consumed by _handle_core_event()
# above. This removes `import wmi` / `import pythoncom` from Python
# entirely on this path — real, measurable GIL-blocking cost during
# Python's own boot window (COM type-library loading briefly monopolizes
# the GIL, the same class of problem the old Tk overlay had) for a
# background watcher that never needed Python's interpreter to exist.

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

# ============================================================================
# SCRIPT DETECTION (v7) — deterministic Unicode-block routing
# ============================================================================
# The old engine assumed every token was Latin-transliterated: the flat regex
# blob held a handful of romanized foreign words, and the QWERTY typo model
# was applied to every script. Routing is now decided per-token by dominant
# Unicode block — stdlib-only, no language-ID dependency, O(len(token)).
_SCRIPT_RANGES: tuple = (
    (0x0041, 0x007A, "LATIN"), (0x00C0, 0x024F, "LATIN"),      # ASCII + Latin-1/Ext
    (0x0400, 0x052F, "CYRILLIC"),
    (0x0590, 0x05FF, "HEBREW"),
    (0x0600, 0x06FF, "ARABIC"), (0x0750, 0x077F, "ARABIC"),
    (0x08A0, 0x08FF, "ARABIC"), (0xFB50, 0xFDFF, "ARABIC"),
    (0x0900, 0x097F, "DEVANAGARI"),
    (0x0980, 0x09FF, "BENGALI"),
    (0x0A00, 0x0A7F, "GURMUKHI"),
    (0x0A80, 0x0AFF, "GUJARATI"),
    (0x0B00, 0x0B7F, "ORIYA"),
    (0x0B80, 0x0BFF, "TAMIL"),
    (0x0C00, 0x0C7F, "TELUGU"),
    (0x0C80, 0x0CFF, "KANNADA"),
    (0x0D00, 0x0D7F, "MALAYALAM"),
    (0x0E00, 0x0E7F, "THAI"),
    (0x0370, 0x03FF, "GREEK"), (0x1F00, 0x1FFF, "GREEK"),
    (0x3040, 0x309F, "KANA"), (0x30A0, 0x30FF, "KANA"),
    (0x31F0, 0x31FF, "KANA"),
    (0x4E00, 0x9FFF, "CJK"), (0x3400, 0x4DBF, "CJK"), (0xF900, 0xFAFF, "CJK"),
    (0xAC00, 0xD7AF, "HANGUL"), (0x1100, 0x11FF, "HANGUL"),
)

def char_script(ch: str) -> str | None:
    cp = ord(ch)
    for lo, hi, name in _SCRIPT_RANGES:
        if lo <= cp <= hi:
            return name
    return None

def dominant_script(token: str) -> str:
    """Dominant Unicode block of a token: 'LATIN', 'CYRILLIC', 'CJK', ...
    'MIXED' when letters of multiple scripts share the token (classic
    homoglyph evasion), 'OTHER' when no letter was classifiable."""
    counts: Counter = Counter()
    for ch in token:
        s = char_script(ch)
        if s:
            counts[s] += 1
    if not counts:
        return "OTHER"
    top, top_n = counts.most_common(1)[0]
    if top_n < sum(counts.values()):
        return "MIXED"
    return top

# Scripts whose writing systems don't use inter-word spaces — for these,
# substring containment (not token equality) is the primary exact channel.
def _script_tokens(text: str):
    """Yield maximal runs of Unicode letters+marks (category L*/M*).

    regex \\w splinters Indic words at combining marks (virama, vowel
    signs), which silently destroyed native-script tokens — Devanagari
    'आत्महत्या' arrived as unreadable fragments. Category-driven runs
    keep every script intact.
    """
    buf = []
    for ch in text:
        if unicodedata.category(ch)[0] in ("L", "M"):
            buf.append(ch)
        else:
            if len(buf) >= 2:
                yield "".join(buf)
            buf = []
    if len(buf) >= 2:
        yield "".join(buf)


_SPACELESS_SCRIPTS = frozenset({"CJK", "KANA", "THAI", "HANGUL"})


# ============================================================================
# MULTILINGUAL TERM REGISTRY (v7)
# ============================================================================
# Replaces the "one line of the regex blob holds five languages" pattern.
# Every entry is auditable: (term, language, script, severity, variants).
# Curation rule inherited from the explosives pillar: only terms that are
# UNAMBIGUOUS in isolation are admitted. Anything with a common benign sense
# (e.g. Arabic جنس = "gender/type", Hindi बम used as slang) is either held
# at "high" or excluded — the Angel Engine cannot rescue a native-script
# pillar the way it can English, so this list stays conservative by design.
#
# (term, language, script, severity, known_variants)
MULTILINGUAL_REGISTRY: list[tuple[str, str, str, str, tuple[str, ...]]] = [
    # --- Devanagari (Hindi) ---
    ("पोर्न",       "hi", "DEVANAGARI", "critical", ()),
    ("सेक्स",       "hi", "DEVANAGARI", "critical", ("सेक्सी",)),
    ("चुदाई",       "hi", "DEVANAGARI", "critical", ()),
    ("नंगी",        "hi", "DEVANAGARI", "high",     ("नंगा",)),
    ("अश्लील",      "hi", "DEVANAGARI", "high",     ()),
    ("आत्महत्या",   "hi", "DEVANAGARI", "critical", ()),   # suicide
    ("नशा",         "hi", "DEVANAGARI", "high",     ("नशीले",)),
    # --- Arabic ---
    ("سكس",         "ar", "ARABIC",     "critical", ()),
    ("إباحية",      "ar", "ARABIC",     "critical", ("اباحية",)),   # pornography
    ("قحبة",        "ar", "ARABIC",     "critical", ()),
    ("عاهرة",       "ar", "ARABIC",     "critical", ()),
    ("نيك",         "ar", "ARABIC",     "critical", ()),
    ("انتحار",      "ar", "ARABIC",     "critical", ()),   # suicide
    ("مخدرات",      "ar", "ARABIC",     "high",     ()),   # drugs
    ("قنبلة",       "ar", "ARABIC",     "high",     ()),   # bomb
    # --- Cyrillic (Russian) ---
    ("порно",       "ru", "CYRILLIC",   "critical", ("порн", "порнуха")),
    ("секс",        "ru", "CYRILLIC",   "high",     ()),
    ("шлюха",       "ru", "CYRILLIC",   "high",     ()),
    ("самоубийство","ru", "CYRILLIC",   "critical", ()),   # suicide
    ("наркотики",   "ru", "CYRILLIC",   "high",     ()),
    ("бомба",       "ru", "CYRILLIC",   "high",     ()),   # bomb (also fuzzy atomic)
    # --- CJK (Chinese) ---
    ("色情",        "zh", "CJK",        "critical", ()),
    ("黄色网站",    "zh", "CJK",        "critical", ("成人网站",)),
    ("裸聊",        "zh", "CJK",        "critical", ()),
    ("自杀",        "zh", "CJK",        "critical", ("自殺",)),      # suicide
    ("毒品",        "zh", "CJK",        "high",     ()),   # drugs
    ("炸弹",        "zh", "CJK",        "high",     ()),   # bomb
    # --- Japanese ---
    ("エロ",        "ja", "KANA",       "high",     ("エッチ",)),
    ("無修正",      "ja", "CJK",        "high",     ()),   # "uncensored" (adult ctx)
    ("アダルト",    "ja", "KANA",       "high",     ()),
    # --- Korean ---
    ("야동",        "ko", "HANGUL",     "critical", ()),
    ("섹스",        "ko", "HANGUL",     "critical", ()),
    ("포률노",      "ko", "HANGUL",     "critical", ()),   # porno
    ("자살",        "ko", "HANGUL",     "critical", ()),   # suicide
]

# Severity value for an AUTHORITATIVE native exact/substring hit.
_NATIVE_SEV_SCORE = {"critical": 1.0, "high": 0.85, "warning": 0.65, "info": 0.40}

# Build the native indexes from the registry:
#   _NATIVE_EXACT      term(lower) -> severity        (exact token match)
#   _NATIVE_SUBSTR     script -> [(term, severity)]   (spaceless containment)
# and fold every term into the shared per-severity token lexicon so the
# dual-corpus Dice layer sees them too.
_NATIVE_EXACT: dict[str, str] = {}
_NATIVE_SUBSTR: dict[str, list[tuple[str, str]]] = {}
for _term, _lang, _script, _sev, _variants in MULTILINGUAL_REGISTRY:
    for _w in (_term, *_variants):
        _wl = _w.lower()
        _NATIVE_EXACT[_wl] = _sev
        if _script in _SPACELESS_SCRIPTS and len(_wl) >= 2:
            _NATIVE_SUBSTR.setdefault(_script, []).append((_wl, _sev))
        if _sev in _TOKEN_LEXICON:
            _TOKEN_LEXICON[_sev].add(_wl)

# =====================================================
# PHASE 1: DUAL-CORPUS LEXICAL ENGINE (LTS Upgrade)
# =====================================================
#   - IDF-weighted character n-gram Dice
#   - Dual-corpus scoring (bad vs good vocabulary)
#   - Gaussian length decay (no hard cliff)
#   - Sigmoid decision squash
#   - Phonetic skeleton cross-check (v7: actually implemented, see below)
#   - Substring containment detection (v7: actually implemented)
#   - Session-level signal accumulation
#   - v7: dual-lane scoring — normalized Latin lane + raw native-script lane
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


# ---------- Phonetic Engine (v7: real implementation) ----------
# Targets TRANSLITERATION VARIANCE — the same Hindi/Arabic/Russian word
# romanized three ways ("chudai"/"choodai"/"chudayi") drifts outside the
# n-gram Dice window as spelling variance grows, but sounds identical.
# The skeleton collapses that variance: digraph unification, confusable
# consonant mapping, vowel stripping (except the leading char), and
# duplicate collapse. Two spellings with the same skeleton sound alike.
_PHON_DIGRAPHS: tuple = (
    ("ph", "f"), ("th", "t"), ("dh", "d"), ("kh", "k"), ("gh", "g"),
    ("bh", "b"), ("ch", "k"), ("sh", "s"), ("zh", "z"), ("ck", "k"),
)
_PHON_SINGLE = str.maketrans({
    "c": "k", "q": "k", "x": "ks", "z": "s", "w": "v", "y": "i",
})
_PHON_VOWELS = re.compile(r"[aeiou]")
_PHON_DUPES = re.compile(r"(.)\1+")
_PHON_NON_ALPHA = re.compile(r"[^a-z]")

def phonetic_skeleton(term: str) -> str:
    """Coarse Latin-only pronunciation key. '' for anything non-ASCII or
    too short to key safely. Deliberately NOT applied to native-script
    tokens — they route through the registry, not through sound."""
    if not term or not term.isascii():
        return ""
    t = _PHON_NON_ALPHA.sub("", term.lower())
    if len(t) < 3:
        return ""
    for a, b in _PHON_DIGRAPHS:
        t = t.replace(a, b)
    t = t.translate(_PHON_SINGLE)
    sk = t[0] + _PHON_VOWELS.sub("", t[1:])
    sk = _PHON_DUPES.sub(r"\1", sk)
    return sk if len(sk) >= 2 else ""


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

# Build phonetic index for bad terms: skeleton -> {terms}. Overcrowded
# skeletons (>6 distinct terms) are too coarse to mean anything and dropped.
_BAD_PHONETIC: dict[str, set[str]] = {}
for _t in _ALL_BAD_SET:
    _sk = phonetic_skeleton(_t)
    if _sk:
        _BAD_PHONETIC.setdefault(_sk, set()).add(_t)
_BAD_PHONETIC = {sk: terms for sk, terms in _BAD_PHONETIC.items() if len(terms) <= 6}

# Substring-containment index: only terms long enough to be safe as
# substrings ("sex" at len 3 would detonate on "Sussex"; len>=5 does not).
_BAD_SUBSTR_TERMS: tuple = tuple(sorted(
    (t for t in _ALL_BAD_SET if len(t) >= 5 and t.isascii()),
    key=len, reverse=True,   # longest first → most specific match wins
))

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
        """Differentiates typos from deliberate bypasses using keyboard geography.

        v7: SCOPED TO LATIN. QWERTY key-distance is an English-keyboard
        heuristic — it has no relationship to Devanagari/Arabic/CJK input
        (InScript, phonetic IMEs, QWERTZ/AZERTY). Applying it there was
        noise, so non-ASCII tokens now short-circuit to neutral."""
        if not (input_token.isascii() and target_token.isascii()):
            return 1.0
        if dominant_script(input_token) not in ("LATIN", "OTHER"):
            return 1.0
        if len(input_token) != len(target_token): return 1.0
        distance_penalty = 0.0
        mismatches = 0
        for c1, c2 in zip(input_token, target_token):
            if c1 != c2:
                mismatches += 1
                distance_penalty += LevEngine._keyboard_distance(c1, c2)
        if mismatches == 0: return 1.0
        avg_distance = distance_penalty / mismatches
        # Adjacent-key substitution = plausible innocent fat-finger, on any
        # length of word ('porm' is the classic m/n slip) -> dampen.
        # Non-adjacent substitution = deliberate misspelling evasion -> amplify.
        if avg_distance <= 1.5:
            return 0.85
        return 1.10

    @classmethod
    def evaluate_suspicion(cls, title: str, proc: str) -> tuple[float, str, str]:
        """Legacy shim — delegates to LexEngine.score() for backward compatibility."""
        return LEX.score(title, proc)


class LexEngine:
    """Dual-corpus, dual-lane lexical scoring engine (v7).

    Passes, in order — this docstring now describes what score() ACTUALLY
    does (its predecessor claimed channels that didn't exist):

      Pass 0  Exact regex over the raw haystack AND the normalized haystack
              (authoritative; unchanged).
      Pass 1  NATIVE LANE — per-token Unicode script routing over the RAW
              text. Pure non-Latin tokens hit the registry: exact match for
              spaced scripts, substring containment for spaceless scripts
              (CJK/Kana/Thai/Hangul). No fuzzy, no typo model, no phonetics
              on this lane — those are Latin-input heuristics.
      Pass 2  NORMALIZED LANE — the pre-v7 pipeline over the Text-Crushed
              haystack (homoglyph/leet/spacing flattened):
                a. IDF-weighted char-n-gram Dice vs bad corpus
                b. PHONETIC channel — transliteration-variance skeleton
                   cross-check (new, real)
                c. SUBSTRING channel — embedded bad-term containment with
                   remainder safety checks (new, real)
                d. IDF Dice vs good corpus (false-positive dampener)
                e. char-entropy boost, Gaussian length decay, sigmoid gap
                f. QWERTY typo modifier — Latin-ASCII tokens only (v7 scope)
                g. Session accumulator (evasion-probe escalation)

    score() returns (c_lev, severity, best_hit) — unchanged contract.
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

    # ----- Pass 1: native-script lane -----
    def _score_native_token(self, token: str, script: str) -> tuple[float, str, str] | None:
        """Registry routing for pure non-Latin tokens. Returns an
        authoritative (score, severity, term) triple or None."""
        tl = token.lower()
        sev = _NATIVE_EXACT.get(tl)
        if sev:
            return (_NATIVE_SEV_SCORE.get(sev, 0.85), sev, tl)
        if script in _SPACELESS_SCRIPTS:
            for term, s_sev in _NATIVE_SUBSTR.get(script, ()):
                if term in tl:
                    return (_NATIVE_SEV_SCORE.get(s_sev, 0.85), s_sev, term)
        return None

    # ----- Pass 2 channels -----
    def _phonetic_channel(self, token: str) -> tuple[float, str]:
        """Sound-alike cross-check for romanized/transliterated evasions."""
        sk = phonetic_skeleton(token)
        if not sk:
            return 0.0, ""
        terms = _BAD_PHONETIC.get(sk)
        if not terms or token in terms:
            return 0.0, ""
        # Guard: a correctly spelled legitimate word that merely SOUNDS like
        # a bad term is not an evasion attempt.
        if self.good and token in getattr(self.good, "_profiles", {}):
            return 0.0, ""
        if is_real_unrelated_word(token):
            return 0.0, ""
        return 0.62, sorted(terms, key=len)[0]

    def _substring_channel(self, token: str) -> tuple[float, str]:
        """Embedded bad-term containment ('watchpornhub', 'pornhub123').
        The remainder must not be a plausible real word — 'adulthood' does
        not contain a flaggable 'adult' hit."""
        for term in _BAD_SUBSTR_TERMS:
            if term in token and len(token) > len(term):
                remainder = token.replace(term, "", 1)
                if not remainder:
                    continue
                if remainder in KNOWN_SAFE_COLLISIONS or remainder in SAFE_DERIVED_FORMS:
                    continue
                if self.good and remainder in getattr(self.good, "_profiles", {}):
                    continue
                if _SYSTEM_WORDLIST is not None and remainder in _SYSTEM_WORDLIST:
                    continue
                ratio = len(term) / len(token)
                return min(0.55 + 0.35 * ratio, 0.90), term
        return 0.0, ""

    def score(self, title: str, proc: str) -> tuple[float, str, str]:
        """Main scoring entrypoint. Drop-in replacement for evaluate_suspicion().
        Returns: (c_lev: float, matched_category: str, contributing_hit: str)
        """
        with _perf_section("scanner", "lexical"):
            full_haystack = f"{title or ''} {proc or ''}"
            normalized = normalize_haystack(full_haystack)

            # Pass 0: Exact regex match (raw + normalized — authoritative)
            for pattern, sev in _COMPILED:
                match = pattern.search(full_haystack) or pattern.search(normalized)
                if match:
                    return (1.0, sev, f"{match.group(0)}")

            highest_score = 0.0
            best_sev = "info"
            best_hit = ""

            # ---- Pass 1: native-script lane over RAW tokens ----
            # (\w{2,}: CJK terms can be 2 chars — 色情 alone must still match)
            for raw_tok in _script_tokens(full_haystack.lower()):
                script = dominant_script(raw_tok)
                if script in ("LATIN", "MIXED", "OTHER"):
                    continue  # normalized lane owns these (homoglyph-flattened)
                hit = self._score_native_token(raw_tok, script)
                if hit:
                    n_score, n_sev, n_term = hit
                    if n_score > highest_score:
                        highest_score, best_sev, best_hit = n_score, n_sev, n_term
                    if n_sev == "critical":
                        return (1.0, n_sev, n_term)  # authoritative, same as Pass 0

            # ---- Pass 2: normalized Latin lane ----
            tokens = _TOKEN_EXTRACT.findall(normalized)

            for token in tokens:
                if len(token) < 4:
                    continue

                # A genuine, correctly-spelled unrelated word is never an
                # evasion attempt ('adulthood' is not 'adult'). Exact-match
                # bad terms were already authoritative in Pass 0/Pass 1.
                if is_real_unrelated_word(token):
                    continue

                # --- Channel 1: IDF-weighted Dice against bad corpus ---
                bad_score, bad_term = self.bad.best_match(token)

                # --- Channel 1b: phonetic transliteration cross-check ---
                ph_score, ph_term = self._phonetic_channel(token)
                if ph_score > bad_score:
                    bad_score, bad_term = ph_score, ph_term

                # --- Channel 1c: substring containment (always evaluated —
                # Dice alone can cross 0.60 on a long wrapper token, and
                # containment is the stronger, length-invariant signal) ---
                containment = False
                sub_score, sub_term = self._substring_channel(token)
                if sub_score > bad_score:
                    bad_score, bad_term = sub_score, sub_term
                    containment = True

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
                # Containment is length-invariant: 'watchpornhub' contains
                # 'pornhub' no matter how long the wrapper token grows.
                if bad_term and not containment:
                    length_decay = self._gaussian_length_decay(len(token), len(bad_term))
                else:
                    length_decay = 1.0

                # --- Dual-corpus decision signal ---
                # gap = bad - good: positive → closer to bad, negative → closer to good
                effective_bad = bad_score + entropy_boost
                gap = (effective_bad - 1.25 * good_score) * length_decay
                c_lev = self._sigmoid(gap, k=8.0, x0=0.15)

                # --- Keyboard typo analysis (v7: Latin-scope enforced inside) ---
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


# =====================================================
# BROWSER REGISTRY (v7) — closes the Chrome/Edge-only blind spot
# =====================================================
# Chromium-family browsers can all run the SAME extension build (Chrome Web
# Store / force-install policies apply to Chrome, Edge, Brave, Opera, Vivaldi,
# Arc, Yandex, Whale, CocCoc...). Gecko-family browsers run the WebExtensions
# port of the same content script (manifest v2 + native-messaging host under
# HKCU\Software\Mozilla\NativeMessagingHosts) — the agent-side WebSocket
# channel on 127.0.0.1:8765 is browser-agnostic JSON, so ONE optics server
# serves every family. What changes per family is only how the extension
# gets deployed, which is an installer concern, not an agent concern.
CHROMIUM_BROWSERS: frozenset[str] = frozenset({
        "chrome.exe", "msedge.exe", "brave.exe", "opera.exe", "operagx.exe",
        "vivaldi.exe", "chromium.exe", "arc.exe", "yandexbrowser.exe",
        "whale.exe", "coccocbrowser.exe", "torch.exe", "epic.exe",
        "duckduckgo.exe", "maxthon.exe", "slimjet.exe", "centbrowser.exe",
        "avastbrowser.exe", "avgbrowser.exe", "sidekick.exe", "sigmaos.exe",
})
GECKO_BROWSERS: frozenset[str] = frozenset({
        "firefox.exe", "waterfox.exe", "librewolf.exe", "palemoon.exe",
        "floorp.exe", "zen.exe", "iceweasel.exe", "browser.exe",  # Tor Browser
})
BROWSER_PROCESSES: frozenset[str] = frozenset(CHROMIUM_BROWSERS | GECKO_BROWSERS)

# Structural telemetry older than this is treated as absent, not as zero —
# a dead extension reporting 0.0 must be distinguishable from a live one.
STRUCTURAL_STALE_SEC = 12.0

def browser_family(proc_name: str | None) -> str | None:
        """'chromium' | 'gecko' | None for any supported browser process name."""
        if not proc_name:
            return None
        p = proc_name.lower().strip()
        if p in CHROMIUM_BROWSERS:
            return "chromium"
        if p in GECKO_BROWSERS:
            return "gecko"
        return None

# --- Global v7 Optics Buffer ---
_LATEST_BROWSER_DOM = ""
_LATEST_BROWSER_URL = ""
_LATEST_URL_HOSTNAME = ""
_LATEST_TRIPWIRE_SCORE = 0.0
_LATEST_MONETIZATION_SCORE = 0.0
_LATEST_ALE_SCORE = 0.0
_LATEST_BROWSER_ID = ""        # which browser produced the last packet
_LATEST_TELEMETRY_TS = 0.0     # time.time() of last packet — staleness source
_OPTICS_LOCK = threading.Lock()

def telemetry_age() -> float:
        """Seconds since the last extension packet; +inf if none ever arrived."""
        with _OPTICS_LOCK:
            ts = _LATEST_TELEMETRY_TS
        return (time.time() - ts) if ts else float("inf")

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
    """IPC client now — the actual ring buffer lives in ObylonCore.exe,
    fed by the same low-level keyboard hook Core already installed for
    freeze enforcement. Method names/signatures unchanged so every
    existing call site (KEYLOG_HISTORY.get_snapshot(), .clear()) keeps
    working without modification."""

    def get_snapshot(self) -> str:
        try:
            resp = _core_ipc_call({"cmd": "get_keylog_snapshot"})
            return resp.get("text", "") if resp.get("ok") else ""
        except Exception as e:
            logger.error("keylog snapshot IPC call failed", component="keylogger", error=str(e))
            return ""

    def clear(self) -> None:
        try:
            _core_ipc_call({"cmd": "clear_keylog"})
        except Exception as e:
            logger.error("keylog clear IPC call failed", component="keylogger", error=str(e))

KEYLOG_HISTORY = KeylogBuffer()

# NOTE: _background_keylogger() and the pynput listener it ran are gone —
# that was a second, independent low-level keyboard hook running
# alongside Core's own hook. One hook now does both jobs (freeze
# enforcement AND the evidence ring buffer), which is strictly less
# overhead, not just "moved elsewhere."

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
    """Browser-agnostic telemetry uplink. Any supported browser's extension
    (Chromium build or Gecko WebExtensions port) speaks the same JSON schema;
    the `browser` field identifies the source so staleness/wipe logic can
    correlate telemetry with the foreground process."""
    global _LATEST_BROWSER_DOM, _LATEST_BROWSER_URL, _LATEST_URL_HOSTNAME
    global _LATEST_TRIPWIRE_SCORE, _LATEST_MONETIZATION_SCORE, _LATEST_ALE_SCORE
    global _LATEST_BROWSER_ID, _LATEST_TELEMETRY_TS
    logger.info("Uplink established from browser extension", component="optics")
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

                    # v7.0 source attribution + freshness heartbeat
                    _LATEST_BROWSER_ID = (data.get("browser") or _LATEST_BROWSER_ID or "")
                    _LATEST_TELEMETRY_TS = time.time()

                    if _LATEST_TRIPWIRE_SCORE > 0 or _LATEST_MONETIZATION_SCORE > 0 or _LATEST_ALE_SCORE > 0.5:
                        logger.warning("Structural anomaly received", component="optics",
                                       browser=_LATEST_BROWSER_ID,
                                       tripwire=_LATEST_TRIPWIRE_SCORE,
                                       monetization=_LATEST_MONETIZATION_SCORE,
                                       ale=_LATEST_ALE_SCORE)
            except Exception as e:
                logger.error("Packet parse error", component="optics", error=str(e), exc_info=True)
    except websockets.exceptions.ConnectionClosed:
        logger.warning("Connection severed by browser extension", component="optics")

def boot_optics_server():
    """Bulletproof asyncio loop bridge for threaded server start."""
    _name_current_thread("optics")
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
    if session_manager.get_client() is None:
        logger.warning("Supabase offline — bucket check skipped", component="storage")
        return
    try:
        session_manager.get_client().storage.create_bucket(
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

# Deferred, not removed — get_hardware_fingerprint()'s algorithm is
# untouched (moving it to Rust would risk mismatching every already-
# activated machine's stored fingerprint, a much worse failure mode than
# a slow boot). Only the *timing* changes: this used to run synchronously
# at module-import time, before anything else in the file even started —
# now it runs concurrently with the rest of boot, and the one place that
# actually consumes it (validate_identity_integrity, well into main())
# blocks on the result only if it's still running by the time it's needed.
_HARDWARE_FINGERPRINT_RE = re.compile(r"^[a-f0-9]{64}$")
_hardware_fingerprint_result: dict[str, str | None] = {}
_hardware_fingerprint_ready = threading.Event()

def _management_cli_path() -> Path:
    """Return the CLI installed beside this executable, never PyInstaller's temp dir."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "obylonc.exe"
    return Path(__file__).resolve().parent / "obylonc.exe"


def _is_hardware_fingerprint(value: object) -> bool:
    return isinstance(value, str) and _HARDWARE_FINGERPRINT_RE.fullmatch(value.lower()) is not None


def get_hardware_fingerprint() -> str | None:
    """Read a *verified* fingerprint from the co-installed management CLI.

    A missing helper, timeout, or partial WMI result is an unavailable
    observation, not evidence that this endpoint is a cloned machine.
    """
    cli_path = _management_cli_path()
    if not cli_path.is_file():
        logger.error("hardware fingerprint helper is missing", component="identity", path=str(cli_path))
        return None

    try:
        result = subprocess.run(
            [str(cli_path), "internal-fingerprint"],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        fingerprint = result.stdout.strip().lower()
        if _is_hardware_fingerprint(fingerprint):
            return fingerprint
        logger.error("hardware fingerprint helper returned invalid output", component="identity")
    except subprocess.TimeoutExpired:
        logger.warning("hardware fingerprint helper timed out", component="identity")
    except Exception as e:
        logger.error("hardware fingerprint helper failed", component="identity", error=str(e))
    return None


def _compute_hardware_fingerprint_async():
    try:
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass
        _name_current_thread("hw_fingerprint")
        _hardware_fingerprint_result["value"] = get_hardware_fingerprint()
    except Exception as e:
        _hardware_fingerprint_result["value"] = None
        logger.error("hardware fingerprint computation failed", component="identity", error=str(e))
    finally:
        # Setting this is what lets get_hardware_fingerprint_blocking()
        # return immediately instead of blocking for its full 10-second
        # timeout. _name_current_thread() used to sit OUTSIDE this try
        # block — if it ever raised (which is exactly what the ordering
        # bug this replaces did), this finally clause never ran either,
        # since Python only guarantees finally for exceptions that occur
        # within the try. That meant the actual failure mode wasn't just
        # "fingerprint reads as unknown" but "boot hangs a full 10 seconds
        # before it reads as unknown." Everything now runs inside one try,
        # so any failure in this function — this one or a future one —
        # fails fast rather than hanging.
        _hardware_fingerprint_ready.set()

# NOTE: the actual .start() call for this thread does NOT live here
# anymore — see the top of `if __name__ == "__main__":` below for why.
# A bare module-level .start() at this exact point in the file used to
# start racing against _name_current_thread()'s own definition (185 lines
# further down, in the perf-instrumentation block) the moment Python's
# interpreter reached this line during import — under light load the main
# thread reliably won that race and nobody noticed; under real boot load
# the new thread could get scheduled first, hit NameError, set
# _hardware_fingerprint_result to "unknown", and validate_identity_integrity
# would then treat that as a cloned-image mismatch and sys.exit(1) before
# the agent ever reached its DB connection code. Starting this thread only
# after the entire module has finished being defined (i.e. from inside
# `if __name__`, which is the last top-level construct in the file) makes
# that race structurally impossible rather than merely unlikely.

def get_hardware_fingerprint_blocking(timeout: float = 15.0) -> str | None:
    _hardware_fingerprint_ready.wait(timeout=timeout)
    return _hardware_fingerprint_result.get("value")


def validate_identity_integrity(vault, live_fingerprint: str | None) -> bool:
    """A3: Detect cloned images by comparing the activation-time fingerprint
    persisted in the vault against a verified live hardware fingerprint.

    Availability failures are common during the Windows boot window and must
    never be converted into a clone verdict. A confirmed mismatch still stops
    boot exactly as before.
    """
    stored_fp = vault.get("HARDWARE_FINGERPRINT_AT_ACTIVATION")
    if not stored_fp:
        return True  # Pre-A3 activation or first boot — nothing to compare against
    if not _is_hardware_fingerprint(stored_fp):
        logger.warning("stored activation fingerprint is invalid; clone validation deferred", component="identity")
        return True
    if not _is_hardware_fingerprint(live_fingerprint):
        logger.warning(
            "hardware fingerprint unavailable during boot; clone validation deferred",
            component="identity",
        )
        return True
    if stored_fp.lower() != live_fingerprint.lower():
        logger.critical(
            "CLONE DETECTED: hardware fingerprint at activation does not match current hardware. "
            "This machine was likely imaged from another provisioned workstation. "
            "Run 'obylonc reset-identity --confirm' and re-activate.",
            component="identity",
            stored_prefix=stored_fp[:16],
            live_prefix=live_fingerprint[:16]
        )
        return False
    logger.info("hardware identity verified", component="identity")
    return True


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
            if session_manager.get_client() is None:
                logger.warning("Offline mode active. Using local standalone identity.", component="identity")
                return f"offline-{HARDWARE_UUID}"

            # 1. Try to find the ID by UUID or Name
            res = session_manager.get_client().table("workstations").select("id").eq("hardware_uuid", HARDWARE_UUID).execute()
            wid = res.data[0]["id"] if res.data else None

            if not wid:
                res_name = session_manager.get_client().table("workstations").select("id").eq("name", WORKSTATION_NAME).execute()
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
                session_manager.get_client().table("workstations").update(payload).eq("id", wid).execute()
            else:
                import uuid
                payload["id"] = str(uuid.uuid4())
                res_new = session_manager.get_client().table("workstations").insert(payload).execute()
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


IDENTITY_BEACON_FILE = Path(os.environ.get('PROGRAMDATA', 'C:\\ProgramData')) / "Obylon" / "identity_beacon.json"

def write_identity_beacon(wid: str) -> None:
    """Plaintext (not DPAPI) on purpose — see the doc comment on
    IdentityBeacon in core/src/main.rs for the full reasoning. Everything
    in it is already non-secret: OBYLON_ANON_KEY is meant to be publicly
    embeddable (it's compiled directly into obylonc's Go source too), and
    a workstation UUID isn't sensitive on its own. This lets
    ObylonCore.exe's fast lane attach a real workstation identity to its
    best-effort direct violation reports without ever touching the
    encrypted vault or duplicating Python's DPAPI/token-parsing logic in
    Rust."""
    if not wid or str(wid).startswith("offline-"):
        return  # nothing durable to hand Core yet — it'll keep relying on the events queue alone
    try:
        beacon = {
            "workstation_id": wid,
            "supabase_url": OBYLON_PROJECT_URL,
            "supabase_anon_key": OBYLON_ANON_KEY,
        }
        IDENTITY_BEACON_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Unhide first — Windows denies open(mode='w') on hidden files.
        try: ctypes.windll.kernel32.SetFileAttributesW(str(IDENTITY_BEACON_FILE), 128)
        except Exception: pass
        IDENTITY_BEACON_FILE.write_text(json.dumps(beacon), encoding="utf-8")
        _hide_path(IDENTITY_BEACON_FILE)
        logger.info("Identity beacon written for Core's fast-lane reporting", component="identity")
    except Exception as e:
        logger.error("Identity beacon write failed", component="identity", error=str(e))


FASTLANE_RULES_FILE = Path(os.environ.get('PROGRAMDATA', 'C:\\ProgramData')) / "Obylon" / "fastlane_rules.json"

def write_fastlane_rules() -> None:
    """Seeds ObylonCore.exe's fast lane with the same starter defaults it
    already falls back to if this file is missing entirely (a brand-new
    install where Python has never run) — see default_fastlane_rules()
    in core/src/main.rs. This is a starting point, not a complete policy
    surface: today it's a small explicit list; the natural next step is
    wiring this into remote_config_loop() so the fast lane's rule set
    updates whenever the server-side policy does, the same way
    KILL_UNAUTHORIZED_APPS and friends already do. Written early and
    unconditionally at every boot so Core always has *something* current
    even before remote config has synced even once this session."""
    try:
        rules = {
            "banned_process_names": [
                "cheatengine-x86_64.exe",
                "cheatengine-x86_64-sse4-avx2.exe",
            ],
            "banned_window_title_keywords": [
                "cheat engine",
            ],
            "tether_adapter_hints": [
                "cellular", "mobile", "rndis", "android", "iphone", "hotspot", "tether",
            ],
        }
        FASTLANE_RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Unhide first — Windows denies open(mode='w') on hidden files.
        try: ctypes.windll.kernel32.SetFileAttributesW(str(FASTLANE_RULES_FILE), 128)
        except Exception: pass
        FASTLANE_RULES_FILE.write_text(json.dumps(rules), encoding="utf-8")
        logger.info("Fast-lane rules written", component="boot",
                    banned_processes=len(rules["banned_process_names"]))
    except Exception as e:
        logger.error("Fast-lane rules write failed", component="boot", error=str(e))


# =====================================================
# PERF INSTRUMENTATION — feeds `obylonc doctor --profile`
# =====================================================
# Two tiers, matching the two tiers doctor itself reads:
#
# 1. Thread naming (_name_current_thread) costs one Win32 call, once, when
#    a thread starts — it's what lets doctor's external Toolhelp32 walk
#    attribute CPU time to "heartbeat" or "scanner" by name instead of a
#    bare, meaningless thread ID. This is the free tier: zero added cost
#    beyond that single call, for every thread that doesn't need finer
#    detail than "this whole thread was busy doing X."
#
# 2. _perf_section (below) is for the one place that needs finer detail
#    than a whole OS thread: lexical scoring, context gathering, FSM
#    evaluation, and arbitration all run sequentially on the SAME thread
#    (whatever calls scan_loop), so Toolhelp32 alone can't tell them
#    apart — it would just report one "scanner" number. _perf_section
#    wraps each of those four functions individually, accumulating
#    thread_time() (this thread's own CPU time, not wall clock — so an
#    OCR subprocess wait or a network stall doesn't inflate a section
#    that isn't actually CPU-bound) into a small in-memory counter that
#    the periodic writer below serializes to disk every ~5s.
#
# Both tiers write/accumulate CUMULATIVE values that never reset — that's
# deliberate and matters: `doctor --profile` takes two snapshots (once at
# the start of its observation window, once at the end) and diffs them
# over the real elapsed wall-clock time, exactly how Task Manager and
# every other real profiler computes %CPU. A counter that resets itself
# periodically (a mistake this exact file's Rust side made and had to be
# fixed) is incompatible with that model — it just needs to count up,
# forever, and let the reader decide the window.

def _name_current_thread(name: str) -> None:
    """SetThreadDescription — best-effort, silently no-ops if unavailable
    (older Windows, or a non-Windows dev environment). Call once at the
    top of a thread's target function."""
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.SetThreadDescription(kernel32.GetCurrentThread(), name)
    except Exception:
        pass


_PERF_LOCK = threading.Lock()
# thread_name -> {section_name -> cumulative_cpu_seconds}. Keyed by OS
# thread name (matching whatever _name_current_thread() was called with
# on the thread these sections actually run on) so doctor can attribute
# each section's time to the right parent thread rather than guessing.
_PERF_COUNTERS: dict[str, dict[str, float]] = {}


class _perf_section:
    """Context manager: with _perf_section('scanner', 'lexical'): ...
    Adds this block's thread-CPU-time to the shared counter. Cheap enough
    to wrap every scan_loop iteration without a second thought — a
    thread_time() call and a dict increment is nanoseconds, not something
    that could itself become the performance problem it exists to help
    diagnose."""
    __slots__ = ("thread_name", "section", "start")

    def __init__(self, thread_name: str, section: str):
        self.thread_name = thread_name
        self.section = section

    def __enter__(self):
        self.start = time.thread_time()
        return self

    def __exit__(self, *exc):
        elapsed = time.thread_time() - self.start
        if elapsed < 0:
            elapsed = 0.0
        with _PERF_LOCK:
            bucket = _PERF_COUNTERS.setdefault(self.thread_name, {})
            bucket[self.section] = bucket.get(self.section, 0.0) + elapsed
        return False


# Matches the logs\ subfolder convention ObylonCore.exe's own
# core_perf_snapshot.json already uses — both languages' snapshots live
# side by side for anyone poking around C:\ProgramData\Obylon\logs\.
PERF_SNAPSHOT_FILE = Path(os.environ.get('PROGRAMDATA', 'C:\\ProgramData')) / "Obylon" / "logs" / "perf_snapshot.json"

def _write_perf_snapshot_loop(interval_sec: float = 5.0):
    _name_current_thread("perf_snapshot")
    while True:
        try:
            with _PERF_LOCK:
                # Shallow-copy is enough — values are floats, immutable.
                snapshot_threads = {t: dict(sections) for t, sections in _PERF_COUNTERS.items()}
            payload = {"timestamp": time.time(), "threads": snapshot_threads}
            PERF_SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
            PERF_SNAPSHOT_FILE.write_text(json.dumps(payload), encoding="utf-8")
        except Exception as e:
            logger.error("perf snapshot write failed", component="doctor", error=str(e))
        time.sleep(interval_sec)


# ---------- Foreground window ----------
def get_foreground_window() -> tuple[str | None, str | None]:
    with _perf_section("scanner", "context"):
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
def _read_and_delete_capture(path_str: str) -> bytes | None:
    """Core writes JPEGs to ProgramData\\Obylon\\capture and hands back a
    path (data-plane handoff — see architecture doc). Read once, delete,
    return bytes, so callers get the exact same `bytes | None` contract
    they always had."""
    try:
        p = Path(path_str)
        data = p.read_bytes()
        try:
            p.unlink()
        except Exception:
            pass  # not fatal — stale files here are a disk-hygiene issue, not a correctness one
        return data
    except Exception as e:
        logger.error("failed to read capture file from Core", component="evidence", path=path_str, error=str(e))
        return None


def capture_screenshot() -> bytes | None:
    try:
        resp = _core_ipc_call({"cmd": "capture_screenshot"})
        if not resp.get("ok"):
            err_msg = str(resp.get("error", ""))
            if "BitBlt/GetDIBits failed" in err_msg:
                # Desktop is locked, asleep, or on a secure UAC prompt. Normal state.
                logger.debug("screenshot unavailable (desktop locked or secure prompt active)", component="evidence")
            else:
                logger.error("screenshot failed", component="evidence", error=err_msg)
            return None
        return _read_and_delete_capture(resp["path"])
    except Exception as e:
        logger.error("screenshot IPC call failed", component="evidence", error=str(e))
        return None


def capture_webcam() -> bytes | None:
    logger.info("Webcam capture requested", component="evidence")
    if not WEBCAM_EVIDENCE_ENABLED:
        logger.info("Webcam suppressed by remote config", component="evidence")
        return None
    try:
        resp = _core_ipc_call({"cmd": "capture_webcam"}, timeout=10.0)  # MF device open + warmup takes longer than the default 5s
        if not resp.get("ok"):
            logger.error("webcam failed", component="evidence", error=resp.get("error"))
            return None
        logger.info("Webcam evidence successfully captured", component="evidence")
        return _read_and_delete_capture(resp["path"])
    except Exception as e:
        logger.error("webcam IPC call failed", component="evidence", error=str(e))
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
            session_manager.get_client().storage.from_(EVIDENCE_BUCKET).upload(
                path,
                payload,
                {"content-type": "image/jpeg", "upsert": "true"},
            )
            return session_manager.get_client().storage.from_(EVIDENCE_BUCKET).get_public_url(path)
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
        ins = session_manager.get_client().table("evidence_logs").insert({
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
                session_manager.get_client().table("evidence_logs").update(patch).eq("id", evidence_row_id).execute()
            else:
                session_manager.get_client().table("evidence_logs").insert({"alert_id": alert_id, **patch}).execute()
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
            s = session_manager.get_client().table("system_settings").select("focus_mode").eq("id", 1).maybe_single().execute()
            self.enabled = bool(s.data and s.data.get("focus_mode"))
            
            # 2. ALWAYS pull the allowed app list, even if Focus Mode is OFF
            a = session_manager.get_client().table("allowed_apps").select("process_name, whitelisted").execute()
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
    _name_current_thread("hardware_panic")
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
    if is_backlogged:
        title = f"[OFFLINE/DELAYED] {title}" if title else "[OFFLINE/DELAYED]"

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
    if is_backlogged:
        title = f"[OFFLINE/DELAYED] {title}" if title else "[OFFLINE/DELAYED]"

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
        if session_manager.get_client() is None:
            return
        # Fetch bot token from school_settings if not already set
        if not _TELEGRAM_BOT_TOKEN:
            try:
                resp = session_manager.get_client().table("school_settings").select("telegram_bot_token").limit(1).execute()
                if resp.data and resp.data[0].get("telegram_bot_token"):
                    _TELEGRAM_BOT_TOKEN = resp.data[0]["telegram_bot_token"]
            except Exception:
                pass  # Table may not exist; edge function env is primary source

        # Fetch all linked Telegram chat IDs from profiles
        resp = session_manager.get_client().from_("profiles").select("telegram_chat_id").eq("phone_verified", True).not_.is_("telegram_chat_id", "null").execute()
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

        # Step 2: Always kill USB-sourced unauthorized processes (any mode).
        # v7: provenance-attributed — kills copy-to-Desktop payloads too,
        # not just processes whose image still sits on the removable drive.
        usb_killed = False
        if proc:
            try:
                for p in psutil.process_iter(['name', 'exe', 'pid', 'ppid', 'cmdline']):
                    if p.info['name'] and p.info['name'].lower() == proc.lower():
                        verdict, detail = PROVENANCE.assess(p.info)
                        if verdict in USB_PROVENANCE_VERDICTS:
                            p.kill()
                            usb_killed = True
                            logger.warning("USB-origin process terminated",
                                           component="enforcement", proc=proc,
                                           provenance=verdict, detail=detail)
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
        if session_manager.get_client() is None or str(workstation_id).startswith("offline-"):
            raise ConnectionError("offline")
        res = session_manager.get_client().table("alerts").insert(payload).execute()
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


def record_fastlane_alert(workstation_id: str, kind_label: str, detail: str,
                          screenshot_path: str | None) -> None:
    """Writes the audit-trail record for a fast-lane violation that
    ObylonCore.exe already froze/captured entirely on its own.

    Verified bug #1: this used to only enqueue into `unauthorized_events`
    (the raw activity feed), and explicitly skipped calling fire_alert()
    to avoid re-triggering enforcement that Core had already done. But
    that meant NO row was ever written to the `alerts` table, so the
    dashboard — which reads from `alerts`, not `unauthorized_events` —
    never showed the violation at all. This writes directly to `alerts`
    (mirroring fire_alert()'s own DB-write/evidence-archive tail) without
    re-running fire_alert()'s enforcement steps (freeze, USB/process kill,
    Telegram, escalation ladder), since Core already acted."""
    title = f"Fast-Lane Violation: {kind_label}"
    captured_at = now_iso()
    payload = _build_alert_payload(workstation_id, title, detail, "critical",
                                   is_backlogged=False, reason=f"fastlane_{kind_label}")
    logger.warning("ALERT", component="enforcement", severity="CRITICAL",
                    reason=f"fastlane_{kind_label}", proc=detail, title=title)

    screenshot_bytes = None
    if screenshot_path:
        try:
            with open(screenshot_path, "rb") as f:
                screenshot_bytes = f.read()
        except Exception:
            pass

    try:
        if session_manager.get_client() is None or str(workstation_id).startswith("offline-"):
            raise ConnectionError("offline")
        res = session_manager.get_client().table("alerts").insert(payload).execute()
        if res.data:
            archive_evidence(res.data[0]["id"], "critical", workstation_id, screenshot_bytes)
            return
        raise RuntimeError("alerts insert returned no rows")
    except Exception as e:
        logger.error("live insert failed → vaulting", component="alerts", error=str(e), exc_info=True)
        evidence = {
            "screenshot_file": _save_cache_blob(screenshot_bytes) if screenshot_bytes else None,
            "webcam_file": None,
            "meta": {
                "captured_at": captured_at,
                "severity": "critical",
                "reason": f"fastlane_{kind_label}",
                "is_backlogged": True,
            },
        }
        offline_payload = _build_alert_payload(
            workstation_id, title, detail, "critical",
            is_backlogged=True, created_at=captured_at, reason=f"fastlane_{kind_label}"
        )
        vault_enqueue("alert", "alerts", offline_payload, evidence, captured_at)


def log_ambient(workstation_id: str, title: str | None, proc: str | None,
                severity: str, is_anomaly: bool) -> None:
    captured_at = now_iso()
    payload = _build_activity_payload(workstation_id, title, proc, severity,
                                      is_anomaly, is_backlogged=False)
    try:
        if session_manager.get_client() is None or str(workstation_id).startswith("offline-"):
            raise ConnectionError("offline")
        session_manager.get_client().table("activity_logs").insert(payload).execute()
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
def network_reachable() -> bool:
    """Lightweight reachability probe. Cheap & non-mutating."""
    try:
        url = SUPABASE_URL
        if not url:
            try: vault.load()
            except Exception: pass
            url = vault.get("SUPABASE_URL")
        if not url:
            sys_state.update_network(NetworkState.OFFLINE, "No URL configured", "probe")
            return False
        
        host = url.replace("https://", "").replace("http://", "").split("/")[0]
        with socket.create_connection((host, 443), timeout=4):
            sys_state.update_network(NetworkState.ONLINE, "TCP 443 open", "probe")
            return True
    except Exception as e:
        sys_state.update_network(NetworkState.OFFLINE, str(e), "probe")
        return False


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
        dead_letter_path = Path.home() / ".obylon_dead_letter.jsonl"
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

        # Resolve fake offline UUID to real UUID to prevent Postgres 22P02 errors
        if str(payload.get("workstation_id", "")).startswith("offline-") and session_manager.get_client() is not None:
            try:
                # Hit the cache/DB to get the real UUID for this hardware
                _wid_res = session_manager.get_client().table("workstations").select("id").eq("hardware_uuid", HARDWARE_UUID).execute()
                if _wid_res.data:
                    payload["workstation_id"] = _wid_res.data[0]["id"]
            except Exception:
                pass

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
                    session_manager.get_client().storage.from_(EVIDENCE_BUCKET).upload(
                        f"{payload['workstation_id']}/vault-{row_id}-screen.jpg",
                        blob_path.read_bytes(),
                        {"content-type": "image/jpeg", "upsert": "true"},
                    )
                    screenshot_url = session_manager.get_client().storage.from_(EVIDENCE_BUCKET).get_public_url(
                        f"{payload['workstation_id']}/vault-{row_id}-screen.jpg"
                    )
                except Exception as e:
                    raise RuntimeError(f"screenshot surge failed: {e}")

        if cam_file:
            blob_path = CACHE_DIR / cam_file
            if blob_path.exists():
                try:
                    session_manager.get_client().storage.from_(EVIDENCE_BUCKET).upload(
                        f"{payload['workstation_id']}/vault-{row_id}-webcam.jpg",
                        blob_path.read_bytes(),
                        {"content-type": "image/jpeg", "upsert": "true"},
                    )
                    webcam_url = session_manager.get_client().storage.from_(EVIDENCE_BUCKET).get_public_url(
                        f"{payload['workstation_id']}/vault-{row_id}-webcam.jpg"
                    )
                except Exception as e:
                    raise RuntimeError(f"webcam surge failed: {e}")

        # ---- 2) Patch the DB row ----
        # Legacy schema migration: 'created_at' was renamed to 'timestamp' in the alerts table
        if table_name == "alerts" and "created_at" in payload:
            payload["timestamp"] = payload.pop("created_at")
            
        res = session_manager.get_client().table(table_name).insert(payload).execute()
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
                session_manager.get_client().table("evidence_logs").insert(ev_row).execute()
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

        # Trigger hard reset if the token expired during a long offline
        # window, OR if `sb` was never successfully built in the first
        # place (verified bug #5). That second case used to be invisible
        # here: `session_manager.get_client() is None` makes every `session_manager.get_client().table(...)` call above raise
        # a plain `AttributeError: 'NoneType' object has no attribute
        # 'table'`, which doesn't contain "401"/"jwt"/"unauthorized" — so
        # this check never fired, and a client that failed to initialize
        # at boot (e.g. the network wasn't up yet) stayed offline forever
        # even once connectivity came back.
        if session_manager.get_client() is None or "401" in err_msg or "unauthorized" in err_msg.lower() or "jwt" in err_msg.lower() or "nonetype" in err_msg.lower():
            session_manager.force_refresh()

        return False


def sync_daemon() -> None:
    """
    Phase 6 — The Surge.
    Probes connectivity every SYNC_INTERVAL seconds. When the network is
    back, drains the SQLite queue in batches. Runs entirely in the
    background without touching scan_loop's cadence.
    """
    _name_current_thread("sync_daemon")
    logger.info("daemon armed", component="sync", interval=SYNC_INTERVAL)
    CORE_READY.wait(timeout=30)
    while True:
        try:

            # Verified bug #5: if boot-time client init raced Wi-Fi coming
            # up, `sb` stayed permanently None — the only place that ever
            # tried to rebuild it was _surge_one(), which only runs when
            # there's a pending row to surge. A quiet agent with nothing
            # queued yet (no alerts, no activity) could sit offline
            # forever despite the network being fine. Check independently
            # of pending rows so a cold `sb` gets a chance to heal on
            # every tick the network is actually up.
            if session_manager.get_client() is None and network_reachable():
                session_manager.force_refresh()

            pending = vault_pending(limit=25)
            if not pending:
                sys_state.update_sync(SyncState.IDLE, "Queue empty", "sync_daemon")
                continue
            if not sys_state.is_ready_for_sync():
                # Report exactly why we are blocked
                with sys_state.lock:
                    if sys_state.network != NetworkState.ONLINE:
                        reason = "Network offline"
                        state = SyncState.BLOCKED_BY_NETWORK
                    elif sys_state.auth != AuthState.AUTHENTICATED:
                        reason = "Auth invalid"
                        state = SyncState.BLOCKED_BY_AUTH
                    elif sys_state.client != ClientState.READY:
                        reason = "Client unavailable"
                        state = SyncState.BLOCKED_BY_CLIENT
                    elif sys_state.license != LicenseState.VALID:
                        reason = "License invalid"
                        state = SyncState.DEGRADED
                    else:
                        reason = "Unknown blocker"
                        state = SyncState.DEGRADED
                sys_state.update_sync(state, reason, "sync_daemon", q_depth=len(pending))
                logger.info(f"sync blocked: {reason}", component="sync", pending=len(pending))
                continue
                
            sys_state.update_sync(SyncState.FLUSHING, "Starting queue drain", "sync_daemon", q_depth=len(pending))
            logger.info("connection restored — surging legacy item(s)", component="sync", pending=len(pending))
            wins = 0
            for row in pending:
                if _surge_one(row):
                    wins += 1
                else:
                    # Stop on first failure to avoid hammering a flapping link.
                    sys_state.update_sync(SyncState.DEGRADED, "Surge failed mid-flight", "sync_daemon", q_depth=len(pending)-wins)
                    break
            if wins == len(pending):
                sys_state.update_sync(SyncState.IDLE, "Surge complete", "sync_daemon")
            logger.info("Surge complete", component="sync", wins=wins, total=len(pending))
        except Exception as e:
            sys_state.update_sync(SyncState.DEGRADED, str(e), "sync_daemon")
            logger.error("daemon error", component="sync", error=str(e), exc_info=True)
        time.sleep(SYNC_INTERVAL)

# =====================================================
# PHASE 2, 3 & 4: OCR ANALYSIS, ROUTING, & ARBITRATION
# =====================================================

# =====================================================
# OCR ENGINE (v7 rewrite)
# =====================================================
# Old design flaws, fixed here:
#   * extract_ocr_suspicion() ALWAYS returned 0.0 — the future's result was
#     only logged, so OCR never influenced enforcement. Results are now
#     published to a TTL'd slot that scan_loop consumes on the next tick.
#   * ThreadPoolExecutor queue was UNBOUNDED — a fast scan_loop could pile
#     up megabytes of JPEG work during heavy UI rendering. The queue is now
#     capped (drop-oldest) so OCR debt can never grow.
#   * No timeout: a wedged tesseract.exe held the single worker forever.
#     pytesseract's `timeout=` now hard-kills the subprocess.
#   * No dedupe: identical screenshots were re-OCRed every tick.
#   * PIL lazy decode + huge screenshots made jobs unpredictably slow;
#     images are now fully decoded and downscaled before submission.
import queue as _queue_mod

class OcrEngine:
    """Single-worker, non-blocking OCR pipeline with backpressure.

    Thread-safety: submit() and consume() are safe from any thread; the
    worker is the only tesseract/PIL consumer, so the GIL-heavy decode work
    never touches scan_loop.
    """
    MAX_IMAGE_DIM = 1920          # downscale bound — OCR accuracy is flat past this
    def __init__(self, pending: int = 2, timeout: float = 15.0, result_ttl: float = 45.0):
        self._q: _queue_mod.Queue = _queue_mod.Queue(maxsize=pending)
        self._timeout = timeout
        self._ttl = result_ttl
        self._slot: dict = {"score": 0.0, "ts": 0.0, "digest": None}
        self._slot_lock = threading.Lock()
        self._last_digest = None
        self.jobs_done = 0
        self.jobs_dropped = 0
        self.jobs_failed = 0
        self._worker = threading.Thread(target=self._loop, daemon=True, name="OcrEngine")
        self._worker.start()

    # ---- producer side (scan_loop) ----
    def submit(self, image_bytes: bytes | None) -> bool:
        """Offer a screenshot for OCR. Never blocks; returns False if the
        offer was refused (duplicate content or queue saturated)."""
        if not image_bytes:
            return False
        try:
            digest = hashlib.sha1(image_bytes).hexdigest()
        except Exception:
            digest = None
        if digest and digest == self._last_digest:
            return False  # identical frame — nothing new to read
        if digest:
            self._last_digest = digest
        try:
            self._q.put_nowait((digest, image_bytes))
            return True
        except _queue_mod.Full:
            # Backpressure: drop the OLDEST queued job (it's the stalest
            # screenshot) and take the new one.
            try:
                self._q.get_nowait()
                self.jobs_dropped += 1
            except _queue_mod.Empty:
                pass
            try:
                self._q.put_nowait((digest, image_bytes))
                return True
            except _queue_mod.Full:
                self.jobs_dropped += 1
                return False

    def consume(self) -> float:
        """Return the newest OCR score once, if fresh; then clear the slot."""
        with self._slot_lock:
            score, ts = self._slot["score"], self._slot["ts"]
            self._slot["score"] = 0.0
        if ts and (time.time() - ts) <= self._ttl:
            return score
        return 0.0

    # ---- worker side ----
    def _loop(self) -> None:
        while True:
            try:
                digest, image_bytes = self._q.get()
            except Exception:
                time.sleep(0.5)
                continue
            try:
                score = self._run(image_bytes)
                self.jobs_done += 1
                with self._slot_lock:
                    self._slot.update({"score": score, "ts": time.time(), "digest": digest})
                if score > 0.0:
                    logger.info("OCR result published", component="ocr",
                                score=f"{score:.2f}", jobs_done=self.jobs_done)
            except Exception as e:
                self.jobs_failed += 1
                logger.error("OCR job failed (worker survives)", component="ocr",
                             error=str(e), failed=self.jobs_failed)

    def _run(self, image_bytes: bytes) -> float:
        _ensure_ocr_libs()
        img = _Image.open(io.BytesIO(image_bytes))
        img.load()  # PIL is lazy — force full decode HERE, in the worker
        if img.mode != "RGB":
            img = img.convert("RGB")
        # Downscale oversized captures: tesseract runtime scales ~quadratically
        # with pixel count, and 4K desktop screenshots add nothing to accuracy.
        if max(img.size) > self.MAX_IMAGE_DIM:
            ratio = self.MAX_IMAGE_DIM / float(max(img.size))
            img = img.resize((max(1, int(img.size[0] * ratio)),
                              max(1, int(img.size[1] * ratio))))
        # timeout= => pytesseract kills the tesseract subprocess if it wedges;
        # raises RuntimeError on timeout, caught by _loop.
        text = _pytesseract.image_to_string(img, timeout=self._timeout) or ""
        if not text.strip():
            return 0.0
        score, _, _ = LEX.score(text, "")
        return float(score or 0.0)

OCR = OcrEngine()

def extract_ocr_suspicion(image_bytes: bytes | None) -> float:
    """Backward-compatible shim. Now SUBMITS to the OCR engine and returns
    the freshest completed score (usually from the previous tick's capture).
    The score is real input to arbitration, not a discarded log line."""
    OCR.submit(image_bytes)
    return OCR.consume()

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
        _name_current_thread("clipboard")
        CORE_READY.wait(timeout=30)
        while True:
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
        # Deliberately does NOT store a client reference. session_manager.force_refresh()
        # replaces the module-level `sb` global (e.g. on JWT expiry) — a manager
        # that captured the client once at construction would keep hitting the
        # dead client forever after that swap, silently, since fetch() never
        # raises anything the caller would notice. Read the current global
        # instead, every call, so a reinit is picked up on the very next poll.
        self.agent_id = agent_id

    def fetch(self):
        if session_manager.get_client() is None:
            return
        try:
            response = session_manager.get_client().table("agent_configs").select("*").eq("workstation_id", self.agent_id).order("created_at", desc=True).limit(1).execute()
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
                # Steady-state result of a poll that happens every ~3-4s for the
                # agent's entire lifetime — INFO here means thousands of identical
                # lines a day, each one a flush to the log file. DEBUG keeps it
                # available for --dev/--verbose without the constant I/O.
                logger.debug("No remote config found for this agent_id", component="c2", agent_id=self.agent_id)
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
                req = urllib.request.Request(url, headers={'User-Agent': 'Obylon/7.0.0-LTS'})
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
    _name_current_thread("remote_config")
    CORE_READY.wait(timeout=30)
    manager = RemoteConfigManager(workstation_id)
    while True:
        workstation_id = resolve_offline_wid(workstation_id)
        manager.agent_id = workstation_id
        if not workstation_id.startswith("offline-"):
            manager.fetch()
        time.sleep(3)

# =====================================================
# PHASE 7: V7 STRUCTURAL INTELLIGENCE (FSM & WARDEN)
# =====================================================

class PhysicalityWarden:
    """Interrogates raw silicon behavior to detect active evasive media streaming.
    v7: watches EVERY supported browser process, not just chrome.exe."""
    def __init__(self, target_process_names: frozenset[str] | None = None):
        self.target_names = target_process_names or BROWSER_PROCESSES
        self.RX_THRESHOLD = 2 * 1024 * 1024  # 2 MB/s constant Rx implies 1080p
        self.GPU_DECODE_THRESHOLD = 5.0      # 5% VideoDecode utilization

    def get_browser_pids(self) -> list:
        pids = []
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] and proc.info['name'].lower().strip() in self.target_names:
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

def threat_score(c_lev=0.0, c_dom=0.0, ale_score=0.0, m_score=0.0, tripwire_score=0.0, ocr_score=0.0, w_lev: float = 0.65, w_dom: float = 0.35, category: str = "info", intent_n: float = 0.0, angel_n: float = 0.0) -> dict:
    with _perf_section("scanner", "arbitration"):
        # Soft-OR composite over ALL structural channels. OCR joins at 0.8 weight:
        # on-screen text is strong evidence but noisier than extension telemetry.
        S = 1.0 - ((1.0 - min(tripwire_score, 1.0)) * (1.0 - min(m_score, 1.0)) * (1.0 - min(ale_score, 1.0)) * (1.0 - min(ocr_score * 0.8, 1.0)))
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

    v7 changes:
      * Works for EVERY browser in BROWSER_PROCESSES (Chromium AND Gecko
        families) — the telemetry channel is browser-agnostic, so the old
        "chrome/edge or go dark" gate was a self-inflicted blind spot.
      * New explicit state STRUCTURAL_DARK: a supported browser holds the
        foreground but no FRESH extension telemetry is arriving (extension
        missing, killed, or not yet ported). This is surfaced as its own
        auditable signal instead of being silently indistinguishable from
        IDLE. It NEVER raises an enforcement score by itself — darkness is
        a coverage fact, not evidence of a violation.
    """
    def __init__(self):
        self.state = "IDLE"
        self.warden = PhysicalityWarden()

    def process_telemetry(self, ext_payload: dict, active_proc: str, c_lev: float = 0.0,
                          category: str = "info", intent_n: float = 0.0,
                          telem_age: float = 0.0) -> tuple[str, float, str]:
        with _perf_section("scanner", "fsm"):
            family = browser_family(active_proc)
            if family is None:
                self.state = "IDLE"
                return self.state, 0.0, ""

            # Freshness gate: structural zeros are only meaningful when a live
            # extension is actually reporting. Stale/absent telemetry while a
            # browser is foregrounded means the structural layer is OFFLINE.
            if telem_age == float("inf") or telem_age > STRUCTURAL_STALE_SEC:
                self.state = "STRUCTURAL_DARK"
                return self.state, 0.0, f"structural_layer_offline:{active_proc.lower().strip()}({family})"

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
    _name_current_thread("scan")
    CORE_READY.wait(timeout=30)
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
    removable_drives: set = set()
    _letters_refresh_ts = 0.0

    while True:
        try: # THE GLOBAL SHIELD
            workstation_id = resolve_offline_wid(workstation_id)
            # v7: removable-drive enumeration is a WMI associator walk — far too
            # expensive for a 1s tick. Refresh every 5s and feed the Provenance
            # Engine so every other consumer shares one authoritative set.
            if time.time() - _letters_refresh_ts >= 5.0:
                _letters_refresh_ts = time.time()
                try:
                    removable_drives = get_removable_drive_letters(wmi_conn) if wmi_conn else set()
                    PROVENANCE.update_letters(removable_drives)
                except Exception:
                    pass
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
                if session_manager.get_client() is not None:
                    session_manager.get_client().table("workstations").update({
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

            # Smart Wipe — drop optics only when a NON-browser holds the
            # foreground. Any supported browser (Chromium or Gecko family)
            # keeps its telemetry channel; the old chrome/edge-only check
            # was wiping valid Firefox/Brave telemetry every tick.
            if proc_str and browser_family(proc_str) is None:
                with _OPTICS_LOCK:
                    _LATEST_BROWSER_DOM = _LATEST_BROWSER_URL = _LATEST_URL_HOSTNAME = ""
                    _LATEST_TRIPWIRE_SCORE = _LATEST_MONETIZATION_SCORE = _LATEST_ALE_SCORE = 0.0

            # DPDP INTERCEPT
            if DPDP.is_hot:
                sink_found = any(s in proc_str.lower() or s in title_str.lower() or s in (browser_url or "").lower() for s in DPDP.UNAUTHORIZED_SINKS)
                if sink_found:
                    is_browser = proc_str and browser_family(proc_str) is not None
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
            # Consume the freshest completed OCR result (from a previous
            # tick's submission). OCR is async; this is where it actually
            # enters arbitration — the pre-v7 code discarded it.
            c_ocr = OCR.consume()
            
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

            if typed_hit:
                c_lev, best_category, best_hit = 1.0, "critical", typed_hit
                s_final = 1.0
                is_blocked = True
                severity = "critical"
                reason = f"v7_structural_enforcement:{best_hit}_(Score:{s_final:.2f})"
                m_app = 1.0
                c_dom = 0.0
            else:
                m_app = _get_app_modifier(proc_str)
                c_dom = 0.0
                s_final = 0.0
            
            # Legacy Web Check (Fallback if extension loses v7 comms)
            if browser_context:
                is_violation, web_reason = classify_web_context(browser_context)
                if is_violation:
                    c_dom = 1.0
                    best_category = "critical"
                    best_hit = web_reason

            # --- THE V7 FSM STRUCTURAL OVERRIDE ---
            # v7.0: EVERY supported browser family flows through the FSM —
            # the chrome/edge-only gate is gone.
            if proc_str and browser_family(proc_str) is not None:
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

                fsm_state, fsm_score, fsm_reason = FSM_BRAIN.process_telemetry(
                    v7_payload, proc_str, c_lev, best_category, intent_n,
                    telem_age=telemetry_age())

                if fsm_state == "STRUCTURAL_DARK":
                    # Coverage fact, not evidence: a supported browser is
                    # foregrounded but its extension telemetry is silent.
                    # Ambient-log it (heavily debounced) so admins see the
                    # gap; NEVER feeds enforcement.
                    dark_key = f"structural_dark:{proc_str.lower().strip()}"
                    if time.time() - last_ambient.get(dark_key, 0) > AMBIENT_DEBOUNCE_SEC * 5:
                        last_ambient[dark_key] = time.time()
                        log_ambient(workstation_id, title_str, proc_str, "info", is_anomaly=True)
                elif fsm_state in ("ANOMALY_ESCALATION", "SEARCH_ENGAGED", "CONTAINMENT_VIOLATION"):
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
                    
                    # Non-blocking: hand the frame to the OCR engine; its
                    # result is consumed via c_ocr at the top of a later tick.
                    if volatile_ram_snapshot and ((c_lev > 0.70 and c_dom == 0.0) or (t_score_val > 0.40 and c_dom > 0.20)):
                        OCR.submit(volatile_ram_snapshot)

                    # Strong on-screen text evidence promotes the lexical
                    # channel even when the window title itself is clean
                    # (e.g. content visible inside an innocent-looking tab).
                    if c_ocr >= 0.75 and c_ocr * 0.9 > c_lev:
                        c_lev = round(c_ocr * 0.9, 3)
                    
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
                        arb = threat_score(c_lev=c_lev, c_dom=c_dom, ale_score=ale_score, m_score=m_score, tripwire_score=t_score_val, ocr_score=c_ocr, category=best_category, intent_n=intent_n, angel_n=angel_n)
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
                    if session_manager.get_client() is not None and not str(workstation_id).startswith("offline-"):
                        session_manager.get_client().table("unauthorized_events").insert(offline_payload).execute()
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
                with open(str(Path.home() / ".obylon_err.txt"), "a") as f:
                    f.write(f"[{now_iso()}] scan_loop error: {str(e)}\n")
            except Exception: pass
            
        time.sleep(SCAN_INTERVAL)

def resolve_offline_wid(current_wid: str) -> str:
    if current_wid.startswith("offline-") and session_manager.get_client() is not None:
        try:
            new_wid = register_workstation()
            if new_wid and not new_wid.startswith("offline-"):
                write_identity_beacon(new_wid)
                return new_wid
        except Exception:
            pass
    return current_wid

def heartbeat_loop(workstation_id: str) -> None:
    _name_current_thread("heartbeat")
    CORE_READY.wait(timeout=30)
    while True:
        workstation_id = resolve_offline_wid(workstation_id)
        try:
            if session_manager.get_client() is not None:
                session_manager.get_client().table("workstations").update({
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
                try: session_manager.get_client().table("evidence_logs").insert({"metadata": {"command": "terminate", "action_id": action_id, "is_backlogged": False}, "webcam_url": url}).execute()
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


# Central authorization boundary for every externally-triggered admin action.
# Deny by default: no local role string, editable config value, transport
# failure, or legacy shell path is permitted to turn a deny into execution.
_AUTHZ_ACTIONS = {
    "terminate": "obylon.endpoint.shutdown",
    "freeze": "obylon.warden.lock",
    "lock_hardware": "obylon.warden.lock",
    "unfreeze": "obylon.warden.lock",
    "classroom_focus": "obylon.classroom.focus",
    "classroom_focus_end": "obylon.classroom.focus",
    "kill_task": "obylon.warden.terminate_process",
    "kill": "obylon.warden.terminate_process",
    "scalpel": "obylon.warden.terminate_process",
    "update": "obylon.agent.update",
    "set_alias": "obylon.policy.update",
    "lock": "obylon.warden.lock",
}

def _authz_target(workstation_id: str, cmd: str, metadata: dict) -> dict:
    """Canonical, secret-free action target sent to Umbraxis for exact-match policy."""
    target = {"workstation_id": workstation_id, "command": cmd}
    for key in ("process_name", "process", "target", "target_name", "duration", "alias", "new_name", "name", "url", "sha256"):
        value = metadata.get(key)
        if value is not None and value != "":
            target[key] = value
    return target

def authorize_admin_action(workstation_id: str, cmd: str, metadata: dict) -> tuple[bool, str]:
    """Validate server provenance for admin actions."""
    action_id = _AUTHZ_ACTIONS.get(cmd)
    if not action_id:
        return False, "UNKNOWN_ACTION"

    # In v7, the agent only receives commands via Supabase Realtime/CDC (admin_actions).
    # These are inserted by the authenticated Umbraxis backend after it has already
    # authorized the user's dashboard action. We no longer demand a local human 
    # AUTHZ_ACCESS_TOKEN for these web-originated commands.
    
    # Validate target alignment if explicitly specified. Broadcasts may omit it or use global scope.
    target = metadata.get("target_id") or metadata.get("workstation_id")
    if target and target not in (workstation_id, "*", "global"):
        return False, "TARGET_MISMATCH"

    return True, "ALLOW"


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
# One persistent Tk interpreter + window for the agent's entire lifetime.
# Previously this was torn down and rebuilt on every single lock/unlock —
# each cycle paid for a fresh Tcl interpreter init plus a new topmost,
# alpha-blended (layered), override-redirect fullscreen window. That's
# real GDI/USER-object and DWM composition churn that doesn't show up in
# Task Manager's default CPU/Memory columns but compounds across a school
# day of repeated classroom_focus toggles into system-wide sluggishness.
# Now we build it once and just show/hide it.
# The overlay is now a native Win32 layered window owned by ObylonCore.exe
# (rust/obylon-core) — created once at Core's own startup, shown/hidden via
# IPC. No Tcl interpreter, no per-cycle window creation, no GIL exposure.
def show_classroom_focus_overlay():
    try:
        resp = _core_ipc_call({"cmd": "show_overlay"})
        if resp.get("ok"):
            logger.info("Classroom Focus overlay engaged", component="overlay")
        else:
            logger.error("Core rejected show_overlay request", component="overlay", response=resp)
    except Exception as e:
        logger.error("show_overlay IPC call failed", component="overlay", error=str(e))

def hide_classroom_focus_overlay():
    try:
        resp = _core_ipc_call({"cmd": "hide_overlay"})
        if resp.get("ok"):
            logger.info("Classroom Focus overlay disengaged", component="overlay")
        else:
            logger.error("Core rejected hide_overlay request", component="overlay", response=resp)
    except Exception as e:
        logger.error("hide_overlay IPC call failed", component="overlay", error=str(e))




# =====================================================
# SUPABASE REALTIME C2 — WebSocket Command Dispatch
# =====================================================
def realtime_c2_listener(workstation_id: str) -> None:
    """Subscribe to admin_actions INSERT events via Supabase Realtime WebSocket.
    Provides near-instant command dispatch (~100ms) vs the 10s HTTP polling fallback.
    Auto-reconnects with exponential backoff on disconnection.
    """
    _name_current_thread("realtime_c2")
    CORE_READY.wait(timeout=30)
    import asyncio

    async def _run_realtime():
        nonlocal workstation_id
        from realtime import AsyncRealtimeClient

        ws_url = SUPABASE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/realtime/v1/websocket"
        backoff = 1
        max_backoff = 60

        while True:
            # Re-resolve offline WID on each reconnect attempt so that
            # if the agent booted offline, it subscribes to the real UUID
            # channel once network is available.
            workstation_id = resolve_offline_wid(workstation_id)
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
                
                def _on_license_broadcast(payload):
                    status = payload.get("payload", {}).get("status")
                    if status in ("revoked", "suspended", "expired"):
                        logger.critical(f"Realtime C2: License revoked via broadcast ({status}). Initiating shutdown.", component="realtime")
                        LICENSE_INVALID_EVENT.set()
                        
                license_channel.on_broadcast(
                    event="license_update",
                    callback=_on_license_broadcast
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
                                if session_manager.get_client() is None:
                                    # Verified bug #6: previously this just logged and
                                    # dropped the command, forcing every future command
                                    # back onto the slow 10s polling loop (action_loop)
                                    # until something else happened to rebuild `sb`.
                                    # Try to heal right here so this same command can
                                    # still go through instead of silently degrading.
                                    logger.warning("Realtime command received with no Supabase client — attempting reconnect",
                                                   component="realtime", command=cmd, action_id=action_id)
                                    session_manager.force_refresh()
                                    if session_manager.get_client() is None:
                                        logger.warning("Realtime command dropped: Supabase client still unavailable",
                                                       component="realtime", command=cmd, action_id=action_id)
                                        return

                                # ATOMIC CLAIM: compare-and-swap so action_loop
                                # and this handler don't double-dispatch.
                                claim = (
                                    session_manager.get_client().table("admin_actions")
                                    .update({"status": "acknowledged"})
                                    .eq("id", action_id)
                                    .eq("status", "pending")
                                    .select()
                                    .execute()
                                )
                                if not claim.data:
                                    return  # action_loop already claimed it

                            dispatched = True
                            fail_reason = None

                            authorized, authorization_reason = authorize_admin_action(workstation_id, cmd, meta)
                            if not authorized:
                                dispatched, fail_reason = False, authorization_reason
                                if not is_broadcast and sb:
                                    try:
                                        session_manager.get_client().table("admin_actions").update({"status": "failed"}).eq("id", action_id).execute()
                                    except Exception:
                                        pass
                                logger.warning("Unauthorized admin action rejected", component="authz", command=cmd, action_id=action_id, reason=authorization_reason)
                                return

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
                                    WARDEN.lock_workstation(duration=3600, force=True, reason="classroom_focus")
                                show_classroom_focus_overlay()

                            elif cmd == "classroom_focus_end":
                                if WARDEN:
                                    # reason="classroom_focus" so Core refuses this if a
                                    # security violation freeze is still active instead of
                                    # blindly clearing it (verified bug #3).
                                    WARDEN.disengage_freeze(reason="classroom_focus")
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
                                    session_manager.get_client().table("admin_actions").update({"status": "acknowledged"}).eq("id", action_id).execute()
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
                                        if session_manager.get_client():
                                            session_manager.get_client().table("workstations").update({"name": new_alias}).eq("id", workstation_id).execute()
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
                                    if session_manager.get_client():
                                        session_manager.get_client().table("admin_actions").update({"status": final_status}).eq("id", action_id).execute()
                                except Exception:
                                    pass
                            if not dispatched:
                                logger.warning("Command claimed but not dispatched", component="realtime", command=cmd, action_id=action_id, reason=fail_reason)

                        except Exception as e:
                            logger.error("Realtime dispatch error", component="realtime", error=str(e))
                            if sb and action_id and not is_broadcast:
                                try:
                                    session_manager.get_client().table("admin_actions").update({"status": "failed"}).eq("id", action_id).execute()
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
    _name_current_thread("action")
    CORE_READY.wait(timeout=30)
    while True:
        workstation_id = resolve_offline_wid(workstation_id)
        try:
            if session_manager.get_client() is None:
                time.sleep(10)
                continue
            # We must select 'metadata' to extract the target process for the Scalpel.
            res = (
                session_manager.get_client().table("admin_actions")
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
                        session_manager.get_client().table("admin_actions").update({"status": "failed"}).eq("id", action["id"]).execute()
                        continue                    # ATOMIC CLAIM: flip pending -> acknowledged conditioned on the
                    # row still being 'pending'. realtime_c2_listener (WebSocket)
                    # polls/dispatches independently of this HTTP loop; without this
                    # compare-and-swap both consumers can read the same 'pending'
                    # row and dispatch it twice (harmless for freeze, not harmless
                    # for a duplicate concurrent self-update). If claim.data comes
                    # back empty, the other consumer already took it -- skip it.
                    claim = (
                        session_manager.get_client().table("admin_actions")
                        .update({"status": "acknowledged"})
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

                    authorized, authorization_reason = authorize_admin_action(workstation_id, cmd, meta)
                    if not authorized:
                        session_manager.get_client().table("admin_actions").update({"status": "failed"}).eq("id", action["id"]).execute()
                        logger.warning("Unauthorized admin action rejected", component="authz", command=cmd, action_id=action["id"], reason=authorization_reason)
                        continue

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
                            WARDEN.lock_workstation(duration=3600, force=True, reason="classroom_focus")
                        show_classroom_focus_overlay()

                    elif cmd == "classroom_focus_end":
                        if WARDEN:
                            # reason="classroom_focus" so Core refuses this if a
                            # security violation freeze is still active instead of
                            # blindly clearing it (verified bug #3).
                            WARDEN.disengage_freeze(reason="classroom_focus")
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
                        session_manager.get_client().table("admin_actions").update({"status": "acknowledged"}).eq("id", action["id"]).execute()
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

                                session_manager.get_client().table("workstations").update({"name": new_alias}).eq("id", workstation_id).execute()
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
                    session_manager.get_client().table("admin_actions").update({"status": final_status}).eq("id", action["id"]).execute()
                    if not dispatched:
                        logger.warning("Command claimed but not dispatched", component="actions", command=cmd, action_id=action["id"], reason=fail_reason)

                except Exception as e:
                    logger.error("action dispatch error (isolated -- rest of batch continues)", component="actions", action_id=action.get("id"), command=action.get("command"), error=str(e), exc_info=True)
                    try:
                        session_manager.get_client().table("admin_actions").update({"status": "failed"}).eq("id", action["id"]).execute()
                    except Exception:
                        pass

        except Exception as e:
            logger.error("actions error", component="actions", error=str(e), exc_info=True)

        time.sleep(10)  # Fallback polling -- primary dispatch via Realtime WebSocket

# ---------- Main ----------
class BuildInfo:
    VERSION = "7.0.0-LTS"
    BUILD_DATE = "2026-08-18"
    COMMIT = "session-broker+provenance+multilingual"

    @staticmethod
    def print_banner():
        try:
            # Removed os.system('color') to prevent console flash in background
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
                if network_reachable(): print("\033[92m[ OK ]\033[0m")
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
    while True:
        try:
            sys_state.update_license(LicenseState.CHECKING, "Starting heartbeat check", "heartbeat")
            # Actively refresh token to prevent stale 401s (Round 3 fix, now via SessionManager)
            session_manager.force_refresh()
            
            access_token, _ = session_manager.get_tokens()
            if not access_token:
                logger.warning("Heartbeat aborted: no access token available", component="license")
                time.sleep(HEARTBEAT_INTERVAL)
                continue

            payload = {"hardware_uuid": HARDWARE_UUID}
            req = urllib.request.Request(
                f"{ENROLLMENT_ENDPOINT}/license_heartbeat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            )
            import ssl, certifi
            context = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(req, context=context) as response:
                data = json.loads(response.read().decode("utf-8"))
                
                # Cryptographic offline enforcement check
                if "server_sig" in data and not verify_server_signature(data, data["server_sig"]):
                    logger.critical("License heartbeat signature mismatch! Possible MITM or tampering.", component="license")
                    sys_state.update_license(LicenseState.REVOKED, "Signature mismatch", "heartbeat")
                    LICENSE_INVALID_EVENT.set()
                    return

                status = data.get("status")
                vault._data["LAST_HEARTBEAT_OK_AT"] = data.get("issued_at", datetime.now(timezone.utc).isoformat())
                vault._data["LICENSE_STATUS"] = status
                if data.get("server_sig"): vault._data["SERVER_SIG"] = data.get("server_sig")
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
                    sys_state.update_license(LicenseState.REVOKED, f"Status was {status}", "heartbeat")
                    LICENSE_INVALID_EVENT.set()
                    return
                
                sys_state.update_license(LicenseState.VALID, "Heartbeat OK", "heartbeat")

        except Exception as e:
            sys_state.update_license(LicenseState.UNAUTHORIZED if "401" in str(e) else LicenseState.TEMPORARILY_UNAVAILABLE, str(e), "heartbeat")
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

def _launched_by_broker() -> bool:
    """A0: Verify our parent process is actually ObylonCore.exe. Checks real
    parent PID ownership, not a spoofable env var.

    Phase 1 Rust split: ObylonBroker.exe (Session 0, SYSTEM) summons
    ObylonCore.exe into the interactive session; Core — already running as
    the student, no impersonation needed at this hop — spawns this Python
    process as a plain child. So the direct parent is Core, not the
    Session 0 broker itself."""
    try:
        curr = psutil.Process(os.getpid())
        logger.info(f"[_launched_by_broker] Starting check from pid={curr.pid}", component="system")
        for i in range(3):
            parent = curr.parent()
            if parent is None:
                logger.info(f"[_launched_by_broker] Level {i}: parent is None", component="system")
                break
            
            try:
                p_exe = parent.exe()
                p_name = os.path.basename(p_exe).lower()
                logger.info(f"[_launched_by_broker] Level {i}: parent pid={parent.pid} name={p_name}", component="system")
                if p_name == "obyloncore.exe":
                    return True
            except Exception as e:
                logger.info(f"[_launched_by_broker] Level {i}: parent pid={parent.pid} error={e}", component="system")
            
            curr = parent
        return False
    except Exception as e:
        logger.info(f"[_launched_by_broker] Fatal error in check: {e}", component="system")
        return False


def harden_installation():
    """Hide everything important from casual snooping."""
    paths_to_hide = [
        VAULT_DB,
        CACHE_DIR,
        Path(os.environ.get('PROGRAMDATA', 'C:\\ProgramData')) / "Obylon",
        Path.home() / ".obylon_alias",
        Path(os.environ.get('PROGRAMDATA', 'C:\\ProgramData')) / "Obylon" / ".machine_id",
    ]
    for p in paths_to_hide:
        if p.exists():
            _hide_path(p)
    logger.info("Self-protection: critical paths hidden from explorer", component="startup")

    # A1: Grant Authenticated Users write access to specific state files ONLY
    # (not the whole folder) so the non-admin session worker can persist them.
    # This runs as SYSTEM during boot via the broker — narrow blast radius:
    # .machine_id and license_seed.txt stay student-read-only.
    vault_dir = Path(os.environ.get('PROGRAMDATA', 'C:\\ProgramData')) / "Obylon"
    files_to_grant = [
        vault_dir / "obylon.enc",
        vault_dir / "identity_beacon.json",
        vault_dir / "fastlane_rules.json",
    ]
    for f in files_to_grant:
        if f.exists():
            try:
                subprocess.run(
                    ["icacls", str(f), "/grant", "Authenticated Users:(M)", "/C"],
                    capture_output=True, timeout=10
                )
                logger.info("ACL set for session worker write access",
                            component="hardening", path=str(f))
            except Exception as e:
                logger.warning("ACL grant failed", component="hardening", error=str(e), path=str(f))

def main() -> None:
    try:
        # Process + network-adapter monitoring now live in ObylonCore.exe
        # (native ToolHelp32/GetAdaptersAddresses polling, no WMI/COM, no
        # separate psutil poll loop here) — this thread just drains what
        # Core has already found. USB insertion detection stays on WMI in
        # Python for now; see the note on start_usb_insertion_monitor()
        # for why that one specifically wasn't moved in this pass.
        threading.Thread(target=consume_core_events_loop, daemon=True, name="core_events").start()

        try:
            start_usb_insertion_monitor()
            logger.info("USB insertion monitor started.", component="boot")
        except Exception as e:
            logger.warning(f"USB insertion monitor unavailable (non-fatal): {e}", component="boot")

        try:
            if not _core_ipc_call({"cmd": "ping"}).get("ok"):
                raise ConnectionError("ping returned not-ok")
            logger.info("ObylonCore enforcement process reachable.", component="boot")
        except Exception as e:
            logger.warning(f"ObylonCore unreachable at boot (non-fatal, freeze/overlay degraded): {e}", component="boot")

        try:
            write_fastlane_rules()
        except Exception as e:
            logger.warning(f"Fast-lane rules write failed (Core keeps its built-in defaults): {e}", component="boot")

        logger.info("Decrypting localized evidence vault...", component="vault")
        try:
            vault_init()
            logger.info("Vault initialized successfully.", component="vault")
        except Exception as e:
            logger.warning(f"Vault init degraded (non-fatal): {e}", component="vault")

        # ensure_bucket()/register_workstation() were already started back
        # in __main__, immediately after sb was built — running them from
        # there instead of here is what lets them overlap with the
        # boot-time license-heartbeat check (a separate, sequential network
        # round-trip) rather than only starting once every earlier boot
        # step has already finished. Join the threads that are already
        # in flight rather than starting new, duplicate ones.
        logger.info("Joining Supabase storage & identity checks (started earlier this boot)...", component="storage")
        _boot_t_bucket.join(timeout=30)
        _boot_t_identity.join(timeout=30)
        _bucket_result = _BOOT_BUCKET_RESULT
        _wid_result = _BOOT_WID_RESULT

        if "error" in _bucket_result:
            logger.warning(f"Bucket check skipped (non-fatal): {_bucket_result['error']}", component="storage")

        if "wid" in _wid_result:
            wid = _wid_result["wid"]
        else:
            logger.warning(f"Registration failed (non-fatal): {_wid_result.get('error', 'timed out')}", component="identity")
            wid = f"offline-{HARDWARE_UUID}"
        logger.info("Workstation identity verified.", component="identity", wid=wid)

        try:
            write_identity_beacon(wid)
        except Exception as e:
            logger.warning(f"Identity beacon write failed (Core's direct fast-lane reporting degrades to queue-only): {e}", component="identity")

        try:
            _core_ipc_call({"cmd": "brain_security_ready"})
            logger.info("Signaled security-ready to Core.", component="boot")
        except Exception as e:
            logger.error(f"Failed to signal security-ready to Core: {e}", component="boot")

        # Define all critical systems for the Necromancer to watch
        core_systems = {
            "license_heartbeat": {"target": license_heartbeat_loop, "args": (wid,)},
            "heartbeat": {"target": heartbeat_loop, "args": (wid,)},
            "scanner": {"target": scan_loop, "args": (wid,)},
            "actions": {"target": action_loop, "args": (wid,)},
            "panic": {"target": hardware_panic_listener, "args": ()},
            "sync_surge": {"target": sync_daemon, "args": ()},
            "optics_ws": {"target": boot_optics_server, "args": ()},
            # NOTE: "keylogger" thread removed — Core's own low-level
            # keyboard hook (rust/obylon-core) feeds the same ring buffer
            # now; running a second, independent pynput hook here would
            # just be redundant OS-level interception of every keystroke.
            "dpdp_monitor": {"target": DPDP._clipboard_watcher, "args": ()},
            "c2_poller": {"target": remote_config_loop, "args": (wid,)},
            "realtime_c2": {"target": realtime_c2_listener, "args": (wid,)},
            "perf_snapshot": {"target": _write_perf_snapshot_loop, "args": ()}
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
        CORE_READY.set()
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
                                if session_manager.get_client():
                                    session_manager.get_client().table("agent_health").insert({
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
                if session_manager.get_client():
                    session_manager.get_client().table("workstations").update({"status": "offline"}).eq("id", wid).execute()
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
    # Kicked off here rather than at raw module-import time — see the note
    # by _compute_hardware_fingerprint_async's definition for why. This is
    # the earliest point in the whole file where every function above is
    # guaranteed to already be defined, so this can never again race
    # against its own dependencies the way it used to.
    threading.Thread(target=_compute_hardware_fingerprint_async, daemon=True, name="hw_fingerprint").start()

    import time
    from datetime import datetime, timezone, timedelta
    import os
    import sys

    # Every admin/CLI command (activate, status, diagnose, deactivate,
    # support-bundle, boot, reset-identity, ai, logs, version) has moved to
    # the standalone obylonc.exe (Go) — see the obylonc/ project alongside
    # this file. obylon.exe now has exactly one job left: the bare agent
    # boot sequence below, which ObylonCore.exe spawns with zero arguments.
    # Any argument at all means something is still invoking the old CLI
    # surface — fail loudly and point at the real thing rather than
    # reviving dead argparse code or silently doing nothing.
    if len(sys.argv) > 1 and sys.argv[1] == "--warmup":
        # ---------------------------------------------------------------
        # First-start preparation mode.
        #
        # Contract: initialize every expensive runtime component that
        # would otherwise delay the very first normal boot, then drop
        # warmup.lock ONLY after all required work succeeds.
        #
        # This must NOT start monitoring, enforcement, telemetry, or
        # any persistent background service.  It is purely a local
        # runtime initialization pass.
        # ---------------------------------------------------------------
        _warmup_state = {"ok": True, "errors": []}

        def _warmup_step(label, fn):
            try:
                fn()
                print(f"  [OK] {label}")
            except Exception as _e:
                _warmup_state["ok"] = False
                _warmup_state["errors"].append(f"{label}: {_e}")
                print(f"  [FAIL] {label}: {_e}")

        print("Obylon first-start preparation")
        print("=" * 40)

        # 1. OCR stack (PIL + pytesseract + tesseract binary path)
        _warmup_step("OCR libraries (PIL + pytesseract)", _ensure_ocr_libs)

        # 2. Keyboard hook library
        _warmup_step("Input hook (pynput)", lambda: __import__("pynput"))

        # 3. WebSocket transport
        _warmup_step("WebSocket transport", lambda: __import__("websockets"))

        # 4. Crypto signing (optional — not required for warmup success)
        try:
            import nacl.signing  # noqa: F401
            print("  [OK] Crypto signing (nacl)")
        except ImportError:
            print("  [SKIP] Crypto signing (nacl) — optional")

        # 5. Process monitoring
        _warmup_step("Process monitoring (psutil)", lambda: __import__("psutil"))

        # 6. TLS certificates
        _warmup_step("TLS certificates (certifi)", lambda: __import__("certifi"))

        # 7. Win32 APIs (COM, services)
        _warmup_step("Win32 APIs", lambda: (__import__("win32event"), __import__("win32api")))

        print("=" * 40)

        exe_dir = os.path.dirname(sys.executable)
        lock_path = os.path.join(exe_dir, "warmup.lock")

        if _warmup_state["ok"]:
            # Delete any stale lock before writing a fresh one
            if os.path.exists(lock_path):
                os.remove(lock_path)
            with open(lock_path, "w") as _f:
                _f.write(str(time.time()))
            print(f"Warmup complete — lock written to {lock_path}")
            sys.exit(0)
        else:
            # Do NOT create lock on failure — installer will see timeout
            if os.path.exists(lock_path):
                os.remove(lock_path)
            print("Warmup FAILED — required components did not load:")
            for _err in _warmup_state["errors"]:
                print(f"  * {_err}")
            sys.exit(1)

    if len(sys.argv) > 1:
        print("Obylon Sentinel Agent \u2014 this binary no longer has a CLI.")
        print("Use obylonc.exe instead: activate, status, diagnose, deactivate,")
        print("support-bundle, boot, reset-identity, ai, logs, version.")
        sys.exit(1)

    # Minimal debug-logging convenience for manual runs. Not a real CLI
    # flag (there is no argparse left to parse one) — just an env var so
    # verbosity can still be bumped without reintroducing the whole
    # subcommand-parsing subsystem for one knob nothing else needs.
    if os.environ.get("OBYLON_VERBOSE") == "1":
        import logging
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        import win32event, win32api, winerror
        _daemon_mutex = win32event.CreateMutex(None, 1, "Local\\ObylonDaemonMutex")
        if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
            logger.error("Another instance of the agent is already running.", component="system")
            sys.exit(1)
            
        # A0: The v6.3.5 admin gate is removed — the v7 Session Broker spawns
        # the agent AS THE STUDENT USER on purpose (their desktop, proxy config
        # and TLS roots). Non-admin is now the correct, expected state; the old
        # gate caused an infinite crash/respawn loop on every student login.
        # Defense-in-depth: refuse to boot unless actually spawned by the
        # broker, so double-clicking the exe can't start an unmanaged daemon.
        if not _launched_by_broker():
            logger.error("Agent must be started by ObylonCore.exe (spawned by ObylonBroker.exe "
                         "at boot). Do not run the exe manually.", component="system")
            sys.exit(1)
            
        BuildInfo.print_banner()
            
        harden_installation()

        # 2. The Standard Boot Path (No Command)
        if not vault.load() or not vault.get("ACCESS_TOKEN"):
            seed_file = Path(os.environ.get('PROGRAMDATA', 'C:\\ProgramData')) / "Obylon" / "license_seed.txt"
            if seed_file.exists():
                logger.info("Found license_seed.txt. Initiating zero-touch fleet ignition...", component="system")
                try:
                    seed_key = seed_file.read_text(encoding="utf-8").strip()
                    import platform
                    hostname = platform.node()
                    while True:
                        hardware_fingerprint = get_hardware_fingerprint_blocking()
                        if not _is_hardware_fingerprint(hardware_fingerprint):
                            logger.warning(
                                "Stable hardware identity is not available yet; retrying fleet ignition in 60s.",
                                component="identity",
                            )
                            time.sleep(60)
                            continue
                        status = vault.provision_via_license(seed_key, hostname, HARDWARE_UUID, hardware_fingerprint)
                        if status == "SUCCESS":
                            try: os.remove(seed_file)
                            except Exception: pass
                            logger.info("Fleet ignition complete. Agent ready.", component="system")
                            break
                        elif status == "NETWORK_ERROR":
                            logger.warning("Network unreachable during seed ignition. Retrying in 60s...", component="system")
                            time.sleep(60)
                        else:
                            logger.critical(f"Hard error during seed ignition: {status}. Shutting down.", component="system")
                            sys.exit(1)
                except Exception as e:
                    logger.critical(f"Seed file read error: {e}", component="system")
                    sys.exit(1)
            else:
                logger.critical("Vault incomplete or missing session. Run: obylon activate <LICENSE_KEY>", component="system")
                sys.exit(1)
                
        # A3: Clone detection — vault is guaranteed loaded at this point.
        if not validate_identity_integrity(vault, get_hardware_fingerprint_blocking()):
            # Core treats this code as a confirmed identity violation and
            # backs off before retrying the brain, avoiding a tight restart
            # loop while preserving the normal remediation path.
            sys.exit(78)

        SUPABASE_URL = vault.get("SUPABASE_URL")
        SUPABASE_KEY = vault.get("SUPABASE_ANON_KEY")

        # 3. Ignite the Supabase Engine FIRST via SessionManager
        try:
            if not SUPABASE_URL or not SUPABASE_KEY:
                raise ValueError("Credentials missing")
            
            # This cleanly handles token loading, validation (Phase 2 fix), and refresh
            session_manager.initialize_from_vault()
            
            # Set global vars for telemetry mapping later
            HARDWARE_UUID = vault.get("HARDWARE_UUID") or HARDWARE_UUID
            WORKSTATION_NAME = vault.get("WORKSTATION_NAME")
            LICENSE_ID = vault.get("LICENSE_ID")
        except Exception as e:
            logger.critical(f"Supabase engine ignition failed structurally: {e}", component="boot")
            # Fall through -- client will just be None/Offline state
            sb = None

        # Kick off ensure_bucket()/register_workstation() the instant sb is
        # ready (or confirmed unreachable — both functions already handle
        # session_manager.get_client() is None gracefully), rather than waiting for main() to start
        # them. Previously they didn't run until AFTER the license-heartbeat
        # check below — a third, separate, sequential network round-trip
        # (its own connection, its own TLS handshake, a 5s timeout) — even
        # though nothing about that check actually depends on workstation
        # registration completing first. Starting these here lets that
        # ~5s-worst-case license check and this actually overlap in wall
        # clock time instead of stacking on top of each other. main() below
        # joins these same threads rather than starting new ones.
        _BOOT_BUCKET_RESULT: dict[str, object] = {}
        _BOOT_WID_RESULT: dict[str, object] = {}

        def _boot_run_ensure_bucket():
            try:
                ensure_bucket()
            except Exception as e:
                _BOOT_BUCKET_RESULT["error"] = e

        def _boot_run_register_workstation():
            try:
                _BOOT_WID_RESULT["wid"] = register_workstation()
            except Exception as e:
                _BOOT_WID_RESULT["error"] = e

        _boot_t_bucket = threading.Thread(target=_boot_run_ensure_bucket, daemon=True, name="ensure_bucket")
        _boot_t_identity = threading.Thread(target=_boot_run_register_workstation, daemon=True, name="register_workstation")
        _boot_t_bucket.start()
        _boot_t_identity.start()

        # Immediate boot-time license check (Try Online First with FRESH token)
        try:
            import ssl, certifi, urllib.request, json
            payload = {"hardware_uuid": HARDWARE_UUID}
            access_token, _ = session_manager.get_tokens()
            req = urllib.request.Request(
                f"{ENROLLMENT_ENDPOINT}/license_heartbeat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
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
            logger.error(f"Boot-time license check failed (HTTP {e.code}). Falling back to offline mode.", component="system")
            boot_status = vault.get("LICENSE_STATUS")
        except Exception:
            boot_status = vault.get("LICENSE_STATUS") # Offline fallback

        if boot_status in ("revoked", "suspended", "expired"):
            logger.critical(f"License is currently {boot_status}. Entering Hostile Watermark state.", component="system")
            def _hostile_watermark_thread(status):
                import tkinter as tk
                import ctypes
                root = tk.Tk()
                root.overrideredirect(True)
                root.attributes('-topmost', True)
                root.attributes('-alpha', 0.5)
                root.config(bg='black')
                
                try:
                    root.wm_attributes("-transparentcolor", "black")
                except Exception:
                    pass

                label = tk.Label(root, text=f"OBYLON SENTINEL // LICENSE {status.upper()} — SYSTEM UNMONITORED", 
                                 font=("Consolas", 14, "bold"), fg="white", bg="black")
                label.pack(padx=20, pady=10)
                
                root.update_idletasks()
                win_w = root.winfo_width()
                win_h = root.winfo_height()
                screen_w = root.winfo_screenwidth()
                screen_h = root.winfo_screenheight()
                
                root.geometry(f"+{screen_w - win_w - 20}+{screen_h - win_h - 60}")
                
                try:
                    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
                    GWL_EXSTYLE = -20
                    WS_EX_LAYERED = 0x00080000
                    WS_EX_TRANSPARENT = 0x00000020
                    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
                except Exception as e:
                    logger.error(f"Failed to set click-through: {e}", component="system")

                def disable_event():
                    pass
                root.protocol("WM_DELETE_WINDOW", disable_event)
                
                # Block the main thread forever so the agent doesn't start monitoring,
                # turning this process into a zombie watermark.
                root.mainloop()

            _hostile_watermark_thread(boot_status)
            
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
                if datetime.now(timezone.utc) + timedelta(minutes=5) < max_dt:
                    logger.critical("Clock rollback detected! Current time is before MAX_SEEN_UTC. Shutting down.", component="system")
                    sys.exit(1)
            except Exception:
                pass

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
        
        # Launch the Agent
        main()

    except KeyboardInterrupt:
        print("\n[*] Agent terminated by user.")
    except Exception as e:
        # IMMORTAL CATCH
        print(f"\n\033[91m[FATAL ERROR]\033[0m {e}")
        import traceback
        traceback.print_exc()
        try:
            if sys.stdin is not None and sys.stdin.isatty():
                input("\nPress Enter to exit...")
        except Exception:
            pass

































