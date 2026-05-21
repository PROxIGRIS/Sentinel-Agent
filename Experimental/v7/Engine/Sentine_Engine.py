"""
╔══════════════════════════════════════════════════════════════════════════════╗
║       NEXUS SENTINEL — Engine Refactor v8.0 (Arbitration Overhaul)          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  DROP-IN REPLACEMENT FOR MODIFIED SECTIONS IN sentinel_agent_v8.py          ║
║                                                                              ║
║  Changes from v7.x → v8.0:                                                  ║
║                                                                              ║
║  [REQ-1] Context-Aware Arbitration (Verdict System)                         ║
║          Fuzzy-match alone → Warning only. Strike requires behavioral        ║
║          correlation between two or more independent signal kinds.           ║
║          New: Verdict class, VERDICT_RULES table, evaluate_verdict().        ║
║                                                                              ║
║  [REQ-2] Significance Multiplier                                             ║
║          BENIGN_PROCESS_WHITELIST + SIGNIFICANCE_MULTIPLIER table.           ║
║          Whitelisted procs (VS Code, Office, PowerToys, Browsers) carry      ║
║          a multiplier of 0.0 — axiom_push_signal no-ops for them.           ║
║                                                                              ║
║  [REQ-3] Contextual Decay                                                    ║
║          Critical signals: 600 s decay window (permanent spike).             ║
║          Warning signals:  120 s decay window (fast evaporation).            ║
║          Low-level warning accumulation with no critical anchor decays       ║
║          the ATS naturally back to zero without triggering any layer.        ║
║                                                                              ║
║  [REQ-4] scan_loop Refactor                                                  ║
║          Old: if Match → Strike                                               ║
║          New: if Match → _check_behavioral_context() → if bad → Strike       ║
║               else → Warning / Bus-only                                      ║
║                                                                              ║
║  [REQ-5] Self-Healing Thread Wrappers                                        ║
║          self_healing_thread(): catches ImportError → prints                 ║
║          "Feature Disabled" → calls watchdog_disable() → exits.             ║
║          The watchdog no longer loops on permanently-disabled threads.       ║
║                                                                              ║
║  [REQ-6] Log Sanitization (Verbose / Operational)                            ║
║          Operational mode (default): only prints confirmed anomalies.        ║
║          Verbose mode (SENTINEL_LOG_MODE=verbose): full diagnostic stream.   ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝

INTEGRATION GUIDE
─────────────────
Each section is clearly labelled with:
  • REPLACES: <original function/block name>
  • ADD AFTER: <line or symbol in original>

Search for those markers to find the correct insertion point.
"""

from __future__ import annotations

import os
import re
import sys
import time
import threading
from typing import Optional


# ══════════════════════════════════════════════════════════════════════════════
# [REQ-6]  SENTINEL LOG — VERBOSE vs OPERATIONAL MODE
# ──────────────────────────────────────────────────────────────────────────────
# ADD AFTER: the imports block (before any print() calls in engine code)
# ══════════════════════════════════════════════════════════════════════════════

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


# Backward-compat shim: existing code that calls print() directly still works.
# Only NEW engine code uses sentinel_log().


# ══════════════════════════════════════════════════════════════════════════════
# [REQ-2]  BENIGN PROCESS REGISTRY & SIGNIFICANCE MULTIPLIER
# ──────────────────────────────────────────────────────────────────────────────
# ADD AFTER: _OS_BYPASS definition (around line 460 in original)
# ══════════════════════════════════════════════════════════════════════════════

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
        if key in _OS_BYPASS:           # type: ignore[name-defined]
            return -1.0
    except NameError:
        pass

    return 1.0


# ══════════════════════════════════════════════════════════════════════════════
# [REQ-3]  CONTEXTUAL DECAY — DIFFERENTIAL DECAY WINDOWS
# ──────────────────────────────────────────────────────────────────────────────
# REPLACES: ATS_DECAY_WINDOW constant (original line ~968)
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
# [REQ-3]  REVISED _axiom_live_weight
# ──────────────────────────────────────────────────────────────────────────────
# REPLACES: _axiom_live_weight() (original line ~1041)
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
# [REQ-2 + REQ-3]  REVISED axiom_push_signal
# ──────────────────────────────────────────────────────────────────────────────
# REPLACES: axiom_push_signal() (original line ~1071)
# ══════════════════════════════════════════════════════════════════════════════

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
            weight = AXIOM_SIGNAL_WEIGHTS.get(kind, 0.05)  # type: ignore[name-defined]
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
        with _AXIOM_LOCK:                 # type: ignore[name-defined]
            _AXIOM_BUS.append(sig)        # type: ignore[name-defined]
    except NameError:
        pass

    sentinel_log(
        f"[axiom-bus] PUSH kind='{kind}' eff_w={effective_weight:.2f} "
        f"base_w={weight:.2f} mult={sig_mult:.1f} lev={lev_score:.2f} "
        f"decay={sig['decay_window']:.0f}s value='{(value or '')[:40]}'",
        level="debug",
    )


# ══════════════════════════════════════════════════════════════════════════════
# [REQ-1]  VERDICT SYSTEM
# ──────────────────────────────────────────────────────────────────────────────
# NEW — place after axiom_push_signal, before _axiom_layer2_arbitrate
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
# [REQ-1 + REQ-3]  REVISED _axiom_compute_ats
# ──────────────────────────────────────────────────────────────────────────────
# REPLACES: _axiom_compute_ats() (original line ~1052)
# ══════════════════════════════════════════════════════════════════════════════

def _axiom_compute_ats(now: float) -> float:
    """
    Compute the current Ambient Threat Score from the live signal bus.

    v8 change: uses per-signal decay windows (via _axiom_live_weight)
    so Critical and Warning signals decay at different rates.
    Expired signals are pruned in-place.  Result is clamped to [0, 1].
    """
    live, expired = [], []
    total = 0.0
    for sig in _AXIOM_BUS:       # type: ignore[name-defined]
        w = _axiom_live_weight(sig, now)
        if w <= 0.0:
            expired.append(sig)
        else:
            live.append(sig)
            total += w
    for s in expired:
        _AXIOM_BUS.remove(s)     # type: ignore[name-defined]
    return min(total, 1.0)


# ══════════════════════════════════════════════════════════════════════════════
# [REQ-1 + REQ-3]  REVISED _axiom_verdict_arbitrate
# ──────────────────────────────────────────────────────────────────────────────
# REPLACES: _axiom_layer2_arbitrate() (original line ~1103)
# ══════════════════════════════════════════════════════════════════════════════

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
        lev_engine = LEV                 # type: ignore[name-defined]
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
            with _AXIOM_LOCK:           # type: ignore[name-defined]
                for sig in _AXIOM_BUS:  # type: ignore[name-defined]
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


# ══════════════════════════════════════════════════════════════════════════════
# [REQ-1]  REVISED axiom_evaluate
# ──────────────────────────────────────────────────────────────────────────────
# REPLACES: axiom_evaluate() (original line ~1282)
# ══════════════════════════════════════════════════════════════════════════════

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
    global _AXIOM_L2_LAST_RUN, _AXIOM_L3_LAST_RUN   # type: ignore[name-defined]

    now = time.time()
    try:
        with _AXIOM_LOCK:                            # type: ignore[name-defined]
            ats          = _axiom_compute_ats(now)
            live_signals = list(_AXIOM_BUS)          # type: ignore[name-defined]
    except NameError:
        return

    if ats < 0.10:
        return  # Completely quiet

    try:
        l2_cooldown_rem = max(0, _AXIOM_L2_COOLDOWN - (now - _AXIOM_L2_LAST_RUN))   # type: ignore[name-defined]
        l3_cooldown_rem = max(0, _AXIOM_L3_COOLDOWN - (now - _AXIOM_L3_LAST_RUN))   # type: ignore[name-defined]
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
            (now - _AXIOM_L2_LAST_RUN) >= _AXIOM_L2_COOLDOWN    # type: ignore[name-defined]
        )
        wake_l3 = (
            ats >= AXIOM_L3_THRESHOLD and
            (now - _AXIOM_L3_LAST_RUN) >= _AXIOM_L3_COOLDOWN    # type: ignore[name-defined]
        )
    except NameError:
        wake_l2 = wake_l3 = False

    if not wake_l2 and not wake_l3:
        return

    def _run_layers() -> None:
        global _AXIOM_L2_LAST_RUN, _AXIOM_L3_LAST_RUN   # type: ignore[name-defined]

        l2_verdict      = Verdict.CLEAR
        l2_reason       = ""
        confirmed_score = 0.0

        # ── Layer 2 ───────────────────────────────────────────────────────────
        if wake_l2:
            try:
                _AXIOM_L2_LAST_RUN = now              # type: ignore[name-defined]
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
                    ambient_debounce = AMBIENT_DEBOUNCE_SEC    # type: ignore[name-defined]
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
                        log_ambient(                           # type: ignore[name-defined]
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
            _AXIOM_L3_LAST_RUN = now                  # type: ignore[name-defined]
        except NameError:
            pass

        try:
            l3_verdict = _axiom_layer3_verify(        # type: ignore[name-defined]
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
            alert_debounce  = ALERT_DEBOUNCE_SEC      # type: ignore[name-defined]
            ambient_debounce = AMBIENT_DEBOUNCE_SEC   # type: ignore[name-defined]
        except NameError:
            alert_debounce = ambient_debounce = 60

        if l3_verdict == "strike":
            key = f"axiom_strike:{l2_reason}"
            if now - last_alerted.get(key, 0) > alert_debounce:
                last_alerted[key] = now
                try:
                    top     = max(live_signals, key=lambda s: s["weight"])
                    shot    = capture_screenshot()     # type: ignore[name-defined]
                    fire_alert(                        # type: ignore[name-defined]
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
                    log_ambient(                       # type: ignore[name-defined]
                        workstation_id,
                        f"[AXIOM WARN] Deep scan elevated risk "
                        f"(ATS={ats:.2f} confirmed={confirmed_score:.2f})",
                        None, "high", is_anomaly=True,
                    )
                except NameError:
                    pass

    threading.Thread(target=_run_layers, daemon=True).start()


# ══════════════════════════════════════════════════════════════════════════════
# [REQ-4]  REFACTORED scan_loop
# ──────────────────────────────────────────────────────────────────────────────
# REPLACES: scan_loop() (original line ~2735)
# ══════════════════════════════════════════════════════════════════════════════

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
    global ADMIN_BYPASS_ACTIVE, _LATEST_BROWSER_DOM, _LATEST_BROWSER_URL   # type: ignore[name-defined]

    last_alerted: dict = {}
    last_ambient:  dict = {}
    _debounce_prune_ts       = time.time()
    _DEBOUNCE_PRUNE_INTERVAL = 300

    while True:
        try:  # ── GLOBAL SHIELD ──────────────────────────────────────────────

            # Prune stale debounce entries
            now_ts = time.time()
            if now_ts - _debounce_prune_ts > _DEBOUNCE_PRUNE_INTERVAL:
                try:
                    cutoff = now_ts - max(ALERT_DEBOUNCE_SEC, AMBIENT_DEBOUNCE_SEC) * 2  # type: ignore[name-defined]
                except NameError:
                    cutoff = now_ts - 120
                last_alerted = {k: v for k, v in last_alerted.items() if v > cutoff}
                last_ambient  = {k: v for k, v in last_ambient.items()  if v > cutoff}
                _debounce_prune_ts = now_ts

            # ── 1. Resolve foreground identity ────────────────────────────────
            try:
                FOCUS.refresh_if_stale()      # type: ignore[name-defined]
            except NameError:
                pass

            try:
                bypass_active = ADMIN_BYPASS_ACTIVE   # type: ignore[name-defined]
            except NameError:
                bypass_active = False

            if bypass_active:
                try:
                    title, proc = SPOOF_DATA["title"], SPOOF_DATA["proc"]  # type: ignore[name-defined]
                except NameError:
                    title, proc = "", ""
            else:
                try:
                    title, proc = get_foreground_window()  # type: ignore[name-defined]
                except NameError:
                    title, proc = None, None

            title_str = title or ""
            proc_str  = proc  or ""

            # Update workstation record (best-effort, non-blocking)
            try:
                sb.table("workstations").update({          # type: ignore[name-defined]
                    "current_window":  title_str,
                    "current_process": proc_str,
                }).eq("id", workstation_id).execute()
            except Exception:
                pass

            if bypass_active:
                try:
                    time.sleep(SCAN_INTERVAL)             # type: ignore[name-defined]
                except NameError:
                    time.sleep(3)
                continue

            # ── 2. DOM context ────────────────────────────────────────────────
            try:
                with _OPTICS_LOCK:                        # type: ignore[name-defined]
                    browser_context = _LATEST_BROWSER_DOM # type: ignore[name-defined]
                    browser_url     = _LATEST_BROWSER_URL # type: ignore[name-defined]
                    _LATEST_BROWSER_DOM = _LATEST_BROWSER_URL = ""  # type: ignore[name-defined]
            except NameError:
                browser_context = browser_url = ""

            # ── 3. Keylog instant-strike check ────────────────────────────────
            typed_hit: Optional[str] = None
            try:
                current_keys    = KEYLOG_HISTORY.get_snapshot().lower()       # type: ignore[name-defined]
                normalized_keys = normalize_haystack(current_keys[-100:])      # type: ignore[name-defined]
                for word in INSTANT_STRIKE_LIST:                               # type: ignore[name-defined]
                    if (
                        re.search(rf"\b{re.escape(word)}\b", current_keys[-50:]) or
                        re.search(rf"\b{re.escape(word)}\b", normalized_keys)
                    ):
                        typed_hit = word
                        KEYLOG_HISTORY.clear()             # type: ignore[name-defined]
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
                clip_hit, clip_score = _check_clipboard_for_scan()  # type: ignore[name-defined]
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
                c_lev, best_category, best_hit = LEV.evaluate_suspicion(  # type: ignore[name-defined]
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
                with _AXIOM_LOCK:                              # type: ignore[name-defined]
                    current_bus_kinds = {s["kind"] for s in _AXIOM_BUS}  # type: ignore[name-defined]
            except NameError:
                pass

            # Determine what kind of signal this Lev result represents
            lev_signal_kind: Optional[str] = None
            if c_lev == 1.0 and best_category == "critical":
                lev_signal_kind = "lev_title_critical"
                if re.search(                                  # type: ignore[name-defined]
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
                m_app = _get_app_modifier(proc_str)           # type: ignore[name-defined]
            except NameError:
                m_app = 1.0
            c_dom = 0.0

            # ── 8. DOM classifier ─────────────────────────────────────────────
            if browser_context:
                try:
                    is_violation, web_reason = classify_web_context(browser_context)  # type: ignore[name-defined]
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
                net_viol, net_reason = network_audit()        # type: ignore[name-defined]
            except NameError:
                pass

            # ── 10. Resource entropy (CPU masquerade) ─────────────────────────
            try:
                resource_entropy_check(proc_str)              # type: ignore[name-defined]
            except NameError:
                pass

            # ── 11. Axiom Engine tick ─────────────────────────────────────────
            axiom_evaluate(workstation_id, last_alerted)

            # ── 12. [NEW v8] Context-gated enforcement ────────────────────────
            #
            # The old code had a direct path:
            #   if c_lev == 1.0 and best_category == "critical" → fire_alert()
            #
            # The new code requires a VERDICT from the rule table.  The
            # preliminary_verdict computed in step 6 (before Axiom evaluate)
            # is used here — the Axiom engine (step 11) handles its own
            # independent deferred-fire path via L2/L3.

            s_final              = 0.0
            severity             = "info"
            reason               = ""
            volatile_ram_snapshot: Optional[bytes] = None

            # ── Network direct path (unchanged: network violations are
            #    independently verifiable and fire regardless of proc name) ────
            if net_viol and net_reason:
                # Refresh the verdict with network signal included
                try:
                    with _AXIOM_LOCK:                          # type: ignore[name-defined]
                        current_bus_kinds = {s["kind"] for s in _AXIOM_BUS}  # type: ignore[name-defined]
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
                            c_ocr = extract_ocr_suspicion(volatile_ram_snapshot)  # type: ignore[name-defined]
                        except NameError:
                            pass
                    try:
                        s_final = _calculate_final_arbitration(c_lev, c_dom, c_ocr, m_app)  # type: ignore[name-defined]
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
                    with _AXIOM_LOCK:                          # type: ignore[name-defined]
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
                alert_debounce   = ALERT_DEBOUNCE_SEC     # type: ignore[name-defined]
                ambient_debounce = AMBIENT_DEBOUNCE_SEC   # type: ignore[name-defined]
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
                        fire_alert(                        # type: ignore[name-defined]
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
                        log_ambient(                       # type: ignore[name-defined]
                            workstation_id, title_str, proc_str,
                            severity, is_anomaly=True,
                        )
                    except NameError:
                        pass

            # ── 13. App policy / session tracker (unchanged) ──────────────────
            clean_proc = proc_str.strip().lower() if proc_str else ""
            try:
                focus_wl  = FOCUS.whitelist       # type: ignore[name-defined]
                os_bypass = _OS_BYPASS            # type: ignore[name-defined]
            except NameError:
                focus_wl = os_bypass = set()

            if (
                clean_proc
                and clean_proc not in focus_wl
                and clean_proc not in os_bypass
                and s_final < 0.60
            ):
                try:
                    sb.table("unauthorized_events").insert({   # type: ignore[name-defined]
                        "workstation_id": workstation_id,
                        "process_name":   clean_proc,
                        "window_title":   title_str,
                        "kind":           "unauthorized",
                    }).execute()
                except Exception:
                    pass

                try:
                    if FOCUS.enabled:                          # type: ignore[name-defined]
                        key = f"policy:{clean_proc}"
                        if time.time() - last_alerted.get(key, 0) > alert_debounce:
                            last_alerted[key] = time.time()
                            fire_alert(                        # type: ignore[name-defined]
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
            time.sleep(SCAN_INTERVAL)                         # type: ignore[name-defined]
        except NameError:
            time.sleep(3)


def _safe_capture_screenshot() -> Optional[bytes]:
    """Thin wrapper around capture_screenshot() that never raises."""
    try:
        return capture_screenshot()                           # type: ignore[name-defined]
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# [REQ-5]  SELF-HEALING THREAD WRAPPER
# ──────────────────────────────────────────────────────────────────────────────
# ADD AFTER: watchdog_register() (original line ~3236)
# ══════════════════════════════════════════════════════════════════════════════

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
        with _WATCHDOG_LOCK:                                  # type: ignore[name-defined]
            for entry in _WATCHDOG_REGISTRY:                  # type: ignore[name-defined]
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


# ══════════════════════════════════════════════════════════════════════════════
# [REQ-5]  REVISED sentinel_watchdog
# ──────────────────────────────────────────────────────────────────────────────
# REPLACES: sentinel_watchdog() (original line ~3260)
# ══════════════════════════════════════════════════════════════════════════════

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
        f"monitoring {len(_WATCHDOG_REGISTRY)} critical threads.",  # type: ignore[name-defined]
        level="error",   # operational-visible at startup
        force=True,
    )
    _CHECK_INTERVAL = 10  # seconds

    while True:
        try:
            time.sleep(_CHECK_INTERVAL)
            try:
                registry = _WATCHDOG_REGISTRY   # type: ignore[name-defined]
                lock     = _WATCHDOG_LOCK        # type: ignore[name-defined]
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
                                new_t = _watchdog_spawn(entry)  # type: ignore[name-defined]
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


# ══════════════════════════════════════════════════════════════════════════════
# [REQ-5]  REVISED wmi_process_monitor
# ──────────────────────────────────────────────────────────────────────────────
# REPLACES: wmi_process_monitor() (original line ~1395)
# ══════════════════════════════════════════════════════════════════════════════

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
                c_lev, category, hit = LEV.evaluate_suspicion(             # type: ignore[name-defined]
                    proc_name, proc_name
                )
            except NameError:
                c_lev, category, hit = 0.0, "info", ""

            try:
                suspicious_parents = _SUSPICIOUS_PARENTS                   # type: ignore[name-defined]
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
                        fire_alert(                                         # type: ignore[name-defined]
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


# ══════════════════════════════════════════════════════════════════════════════
# [REQ-5]  REVISED usb_and_adapter_monitor (wrapper only)
# ──────────────────────────────────────────────────────────────────────────────
# The internal _watch_* sub-functions are unchanged.
# REPLACES: the outer try/except ImportError block in usb_and_adapter_monitor()
# ══════════════════════════════════════════════════════════════════════════════

def _usb_and_adapter_monitor_inner(workstation_id: str) -> None:
    """
    Renamed from usb_and_adapter_monitor().  Contains the original
    implementation unchanged.  Called by the self-healing wrapper below.
    """
    # ─── PASTE THE ORIGINAL usb_and_adapter_monitor() BODY HERE ────────────
    # (All the _watch_usb, _watch_adapters, _watch_disks, etc. sub-functions
    # remain exactly as they are in the original file.  Only the ImportError
    # guard at the top is removed — it's handled by the wrapper below.)
    #
    # Original body starts at "try: import wmi ..." (line ~1582 in original).
    pass  # placeholder — see integration note above


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

    # Delegate to the original implementation body
    # (In the integrated file, just move the original body here directly,
    # removing the try/except ImportError wrapper that was previously there.)
    try:
        import wmi as _wmi
        c               = _wmi.WMI()
        usb_watcher     = c.Win32_USBControllerDevice.watch_for("creation")
        adapter_watcher = c.Win32_NetworkAdapter.watch_for("creation")
        disk_watcher    = c.Win32_LogicalDisk.watch_for("creation")
        sentinel_log("[usb] Smart USB + adapter monitor armed.", level="error", force=True)

        # ── Sub-watcher threads ───────────────────────────────────────────────
        # Original _watch_usb, _watch_adapters, _watch_disks, _watch_disks_removal,
        # and _watch_usb_execution closures go here unchanged.
        # Abbreviated below for clarity — copy verbatim from original.

        # threading.Thread(target=_watch_usb, ...).start()
        # threading.Thread(target=_watch_adapters, ...).start()
        # threading.Thread(target=_watch_disks, ...).start()
        # threading.Thread(target=_watch_disks_removal, ...).start()
        # threading.Thread(target=_watch_usb_execution, ...).start()

        # Keep main thread alive (WMI events are handled in sub-threads)
        threading.Event().wait()  # block forever — watchdog monitors this thread

    except Exception as e:
        sentinel_log(
            f"[usb] monitor startup failed: {e}",
            level="error",
            force=True,
        )
        raise  # let the watchdog restart


# ══════════════════════════════════════════════════════════════════════════════
# [REQ-5]  REVISED main() thread registration
# ──────────────────────────────────────────────────────────────────────────────
# REPLACES: the _CRITICAL_THREADS list in main() (original line ~3353)
# Shows the correct pattern for wrapping optional-library threads.
# ══════════════════════════════════════════════════════════════════════════════

# In main(), replace the _CRITICAL_THREADS definitions for wmi_monitor and
# usb_monitor with self_healing_thread wrappers:
#
#   _CRITICAL_THREADS = [
#       ("heartbeat",         heartbeat_loop,                    (wid,)),
#       ("scan_loop",         scan_loop,                         (wid,)),
#       ("action_loop",       action_loop,                       (wid,)),
#       ("sync_daemon",       sync_daemon,                       ()),
#       ("keylogger",         _background_keylogger,             ()),
#       ("clipboard_monitor", _background_clipboard_monitor,     ()),
#       #
#       # ── Self-healing wrappers for optional-library threads [REQ-5] ───────
#       # These use self_healing_thread() so a missing library → single
#       # "Feature Disabled" message + watchdog_disable(), not a restart loop.
#       #
#       ("wmi_monitor",       self_healing_thread,
#           ("wmi_monitor", wmi_process_monitor, (wid,), ["wmi"])),
#       ("usb_monitor",       self_healing_thread,
#           ("usb_monitor", usb_and_adapter_monitor, (wid,), ["wmi"])),
#   ]


# ══════════════════════════════════════════════════════════════════════════════
# END OF REFACTORED ENGINE v8.0
# ══════════════════════════════════════════════════════════════════════════════
#
# INTEGRATION CHECKLIST
# ─────────────────────
# 1. sentinel_log()              → paste after imports block
# 2. BENIGN_PROCESS_WHITELIST    → paste after _OS_BYPASS (~line 460)
# 3. SIGNIFICANCE_MULTIPLIER     → paste with above
# 4. get_significance_multiplier() → paste with above
# 5. ATS_CRITICAL/WARNING_DECAY_WINDOW  → replace ATS_DECAY_WINDOW (~line 968)
# 6. _CRITICAL/WARNING_SIGNAL_KINDS     → paste with above
# 7. _get_signal_decay_window()  → paste with above
# 8. _axiom_live_weight()        → replace original (~line 1041)
# 9. axiom_push_signal()         → replace original (~line 1071)
# 10. Verdict class              → paste before _axiom_layer2_arbitrate (~line 1103)
# 11. VERDICT_RULES              → paste with Verdict class
# 12. evaluate_verdict()         → paste with VERDICT_RULES
# 13. _axiom_compute_ats()       → replace original (~line 1052)
# 14. _axiom_verdict_arbitrate() → replace _axiom_layer2_arbitrate (~line 1103)
# 15. axiom_evaluate()           → replace original (~line 1282)
# 16. scan_loop()                → replace original (~line 2735)
# 17. _safe_capture_screenshot() → paste after scan_loop
# 18. watchdog_disable()         → paste after watchdog_register (~line 3236)
# 19. self_healing_thread()      → paste with watchdog_disable
# 20. sentinel_watchdog()        → replace original (~line 3260)
# 21. wmi_process_monitor()      → replace original (~line 1395)
# 22. usb_and_adapter_monitor()  → replace outer wrapper of original (~line 1569)
# 23. main() _CRITICAL_THREADS   → update per the comment block above
#
# SEARCH-AND-REPLACE in existing print() calls within engine functions:
#   print(f"[lev] ...")          → sentinel_log(..., level="debug")
#   print(f"[axiom-L2] ...")     → sentinel_log(..., level="debug")
#   print(f"[axiom-bus] PUSH")   → sentinel_log(..., level="debug")
#   print(f"[!!!] ALERT")        → sentinel_log(..., level="strike", force=True)
#   print(..., file=sys.stderr)  → sentinel_log(..., level="error", force=True)
