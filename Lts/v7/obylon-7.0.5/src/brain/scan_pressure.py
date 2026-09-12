"""Bounded adaptive scan-pressure controller for Obylon Sentinel.

The controller changes observation intensity, not enforcement authority. Local
ad-network reputation is contextual evidence only and never directly blocks.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import time


class ScanPressure(str, Enum):
    NORMAL = "normal"
    ELEVATED = "elevated"
    AGGRESSIVE = "aggressive"


@dataclass(frozen=True)
class PressureDecision:
    state: ScanPressure
    interval_sec: float
    ocr_due: bool
    evidence_due: bool
    score: float
    reason: str


class ScanPressureController:
    """Deterministic, hysteretic pressure controller with hard bounds."""

    MIN_INTERVAL = 0.35
    NORMAL_INTERVAL = 1.00
    ELEVATED_INTERVAL = 0.60
    AGGRESSIVE_INTERVAL = 0.35

    ENTER_ELEVATED = 0.32
    ENTER_AGGRESSIVE = 0.68
    EXIT_ELEVATED = 0.22
    EXIT_AGGRESSIVE = 0.48

    CLEAN_TICKS_TO_DECAY = 4
    HOLD_SEC = 4.0
    OCR_ELEVATED_EVERY = 2.0
    OCR_AGGRESSIVE_EVERY = 1.0
    EVIDENCE_AGGRESSIVE_EVERY = 2.5

    def __init__(self) -> None:
        self.state = ScanPressure.NORMAL
        self.clean_ticks = 0
        self.state_since = time.monotonic()
        self.last_ocr_ts = 0.0
        self.last_evidence_ts = 0.0

    @staticmethod
    def _u(value: object) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError):
            return 0.0
        if value != value or value in (float("inf"), float("-inf")):
            return 0.0
        return max(0.0, min(1.0, value))

    def _evidence_score(self, *, reputation: float, monetization: float,
                        lexical: float, dom: float, ale: float, tripwire: float,
                        ocr: float, telemetry_fresh: bool) -> float:
        # Reputation is intentionally capped and cannot dominate independently.
        rep = self._u(reputation) if telemetry_fresh else 0.0
        m = self._u(monetization)
        l = self._u(lexical)
        d = self._u(dom)
        a = self._u(ale)
        t = self._u(tripwire)
        o = self._u(ocr)

        structural = max(t, d, a)
        language = max(l, o)
        corroboration = (0.45 * language) + (0.35 * structural) + (0.20 * m)
        # Reputation adds observation pressure, but only as a bounded contextual
        # multiplier so an ad-network match alone never becomes an enforcement cue.
        score = corroboration + (0.20 * rep) + (0.10 * rep * max(language, structural))
        return max(0.0, min(1.0, score))

    def update(self, *, reputation: float = 0.0, monetization: float = 0.0,
               lexical: float = 0.0, dom: float = 0.0, ale: float = 0.0,
               tripwire: float = 0.0, ocr: float = 0.0,
               telemetry_age_sec: float = float("inf"), now: float | None = None
               ) -> PressureDecision:
        now = time.monotonic() if now is None else now
        telemetry_fresh = telemetry_age_sec >= 0.0 and telemetry_age_sec <= 8.0
        score = self._evidence_score(
            reputation=reputation,
            monetization=monetization,
            lexical=lexical,
            dom=dom,
            ale=ale,
            tripwire=tripwire,
            ocr=ocr,
            telemetry_fresh=telemetry_fresh,
        )

        independent_strong = max(self._u(lexical), self._u(dom), self._u(tripwire), self._u(ale), self._u(ocr))
        has_signal = score >= self.ENTER_ELEVATED

        if has_signal:
            self.clean_ticks = 0
        else:
            self.clean_ticks += 1

        elapsed = now - self.state_since
        previous = self.state

        if self.state is ScanPressure.NORMAL:
            if score >= self.ENTER_AGGRESSIVE and independent_strong >= 0.45:
                self.state = ScanPressure.AGGRESSIVE
            elif score >= self.ENTER_ELEVATED:
                self.state = ScanPressure.ELEVATED
        elif self.state is ScanPressure.ELEVATED:
            if score >= self.ENTER_AGGRESSIVE and independent_strong >= 0.45:
                self.state = ScanPressure.AGGRESSIVE
            elif self.clean_ticks >= self.CLEAN_TICKS_TO_DECAY and elapsed >= self.HOLD_SEC and score <= self.EXIT_ELEVATED:
                self.state = ScanPressure.NORMAL
        else:
            if self.clean_ticks >= self.CLEAN_TICKS_TO_DECAY and elapsed >= self.HOLD_SEC and score <= self.EXIT_AGGRESSIVE:
                self.state = ScanPressure.ELEVATED

        if self.state is not previous:
            self.state_since = now
            reason = f"{previous.value}->{self.state.value}"
        else:
            reason = f"hold:{self.state.value}"

        if self.state is ScanPressure.AGGRESSIVE:
            interval = self.AGGRESSIVE_INTERVAL
            ocr_every = self.OCR_AGGRESSIVE_EVERY
            evidence_every = self.EVIDENCE_AGGRESSIVE_EVERY
        elif self.state is ScanPressure.ELEVATED:
            interval = self.ELEVATED_INTERVAL
            ocr_every = self.OCR_ELEVATED_EVERY
            evidence_every = float("inf")
        else:
            interval = self.NORMAL_INTERVAL
            ocr_every = float("inf")
            evidence_every = float("inf")

        ocr_due = now - self.last_ocr_ts >= ocr_every
        evidence_due = now - self.last_evidence_ts >= evidence_every
        return PressureDecision(self.state, max(self.MIN_INTERVAL, interval), ocr_due, evidence_due, score, reason)

    def mark_ocr(self, now: float | None = None) -> None:
        self.last_ocr_ts = time.monotonic() if now is None else now

    def mark_evidence(self, now: float | None = None) -> None:
        self.last_evidence_ts = time.monotonic() if now is None else now
