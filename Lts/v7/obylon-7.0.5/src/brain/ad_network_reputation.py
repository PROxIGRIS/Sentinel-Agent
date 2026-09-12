"""Local, deterministic ad-network reputation lookup for Oblyon.

The database is contextual telemetry only. It never performs network I/O and
never causes an automatic block by itself. Hostnames are normalized and matched
against explicit registrable-domain entries using label boundaries, avoiding
false positives such as ``nottrafficjunky.com``.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any


_HOST_RE = re.compile(r"^[a-z0-9.-]+$")
_MAX_HOSTNAME_LEN = 253
_MAX_DOMAIN_LEN = 253
_SUPPORTED_MATCH_TYPES = {"registrable_domain"}
_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class AdNetworkReputation:
    network_id: str
    name: str
    category: str
    confidence: float
    recommended_score: float
    mixed_usage: bool
    automatic_block: bool
    match_domain: str

    @property
    def contextual_score(self) -> float:
        """Return conservative reputation strength in [0, 1]."""
        return max(0.0, min(1.0, self.confidence * self.recommended_score))


class AdNetworkReputationDB:
    """Immutable-in-use, file-backed reputation index.

    Loading is best-effort: the core security/policy path remains fully
    functional when the optional reputation database is absent or invalid.
    Once loaded, lookups are pure in-memory operations and therefore do not
    introduce request latency or network failure modes into scanning.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None, logger: Any = None):
        self.path = Path(path) if path else self._default_path()
        self.logger = logger
        self._by_suffix: dict[str, tuple[AdNetworkReputation, ...]] = {}
        self.loaded = False
        self.entry_count = 0
        self.load_error: str | None = None

    @staticmethod
    def _default_path() -> Path:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            base = Path(sys._MEIPASS)
        elif getattr(sys, "frozen", False):
            base = Path(sys.executable).resolve().parent
        else:
            # Source checkout layout: src/brain -> repository root.
            base = Path(__file__).resolve().parents[2]
        return base / "assets" / "data" / "obylon_ad_networks.json"

    def _log(self, level: str, message: str, **kwargs: Any) -> None:
        if self.logger is None:
            return
        method = getattr(self.logger, level, None)
        if callable(method):
            try:
                method(message, component="ad-reputation", **kwargs)
            except Exception:
                pass

    @staticmethod
    def _normalize_hostname(hostname: str | None) -> str | None:
        if not isinstance(hostname, str):
            return None
        value = hostname.strip().lower().rstrip(".")
        if not value or len(value) > _MAX_HOSTNAME_LEN:
            return None
        # Extension payloads should already provide a hostname, but accepting a
        # URL here makes the helper safe to call from the agent's URL path too.
        if "://" in value:
            try:
                from urllib.parse import urlsplit
                value = (urlsplit(value).hostname or "").lower().rstrip(".")
            except Exception:
                return None
        if not value or len(value) > _MAX_HOSTNAME_LEN or not _HOST_RE.fullmatch(value):
            return None
        labels = value.split(".")
        if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in labels):
            return None
        try:
            # IDNA canonicalization gives one deterministic ASCII form.
            value = value.encode("idna").decode("ascii")
        except UnicodeError:
            return None
        return value

    @staticmethod
    def _normalize_domain(domain: str | None) -> str | None:
        value = AdNetworkReputationDB._normalize_hostname(domain)
        if value is None or "." not in value:
            return None
        if len(value) > _MAX_DOMAIN_LEN:
            return None
        return value

    @staticmethod
    def _finite_unit(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return number if math.isfinite(number) and 0.0 <= number <= 1.0 else default

    def _parse_entry(self, raw: Any) -> list[tuple[str, AdNetworkReputation]]:
        if not isinstance(raw, dict):
            return []
        network_id = raw.get("network_id")
        name = raw.get("name")
        category = raw.get("category")
        match_type = raw.get("match_type")
        domains = raw.get("domains")
        if not all(isinstance(x, str) and x.strip() for x in (network_id, name, category)):
            return []
        if match_type not in _SUPPORTED_MATCH_TYPES or not isinstance(domains, list):
            return []

        confidence = self._finite_unit(raw.get("confidence"))
        recommended_score = self._finite_unit(raw.get("recommended_score"))
        mixed_usage = bool(raw.get("mixed_usage", False))
        # The current source schema explicitly marks automatic_block. Preserve
        # the field, but lookup consumers are forbidden from using it as an
        # automatic enforcement trigger.
        automatic_block = bool(raw.get("automatic_block", False))

        parsed: list[tuple[str, AdNetworkReputation]] = []
        for domain in domains:
            normalized = self._normalize_domain(domain)
            if normalized is None:
                continue
            parsed.append((normalized, AdNetworkReputation(
                network_id=network_id.strip(),
                name=name.strip(),
                category=category.strip(),
                confidence=confidence,
                recommended_score=recommended_score,
                mixed_usage=mixed_usage,
                automatic_block=automatic_block,
                match_domain=normalized,
            )))
        return parsed

    def load(self) -> bool:
        self._by_suffix = {}
        self.entry_count = 0
        self.load_error = None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("schema_version") != _SCHEMA_VERSION:
                raise ValueError("unsupported reputation database schema")
            networks = raw.get("networks")
            if not isinstance(networks, list):
                raise ValueError("reputation database networks must be a list")

            by_suffix: dict[str, list[AdNetworkReputation]] = {}
            for entry in networks:
                for domain, reputation in self._parse_entry(entry):
                    by_suffix.setdefault(domain, []).append(reputation)

            self._by_suffix = {domain: tuple(items) for domain, items in by_suffix.items()}
            self.entry_count = sum(len(items) for items in self._by_suffix.values())
            self.loaded = True
            self._log("info", "Ad-network reputation database loaded", path=str(self.path), domains=self.entry_count)
            return True
        except Exception as exc:
            self.loaded = False
            self.load_error = str(exc)
            self._log("warning", "Ad-network reputation database unavailable; continuing without contextual reputation", path=str(self.path), error=str(exc))
            return False

    def lookup(self, hostname: str | None) -> AdNetworkReputation | None:
        normalized = self._normalize_hostname(hostname)
        if normalized is None or not self.loaded:
            return None

        # Longest exact domain wins. Domain-boundary matching prevents a known
        # domain from matching an unrelated hostname that merely contains the
        # same text.
        labels = normalized.split(".")
        for index in range(len(labels) - 1):
            candidate = ".".join(labels[index:])
            entries = self._by_suffix.get(candidate)
            if entries:
                return max(entries, key=lambda item: (item.confidence * item.recommended_score, item.confidence))
        return None

    def contextual_score(self, hostname: str | None) -> float:
        match = self.lookup(hostname)
        return match.contextual_score if match else 0.0

    def explain(self, hostname: str | None) -> dict[str, Any]:
        match = self.lookup(hostname)
        if not match:
            return {"matched": False, "score": 0.0, "automatic_block": False}
        return {
            "matched": True,
            "network_id": match.network_id,
            "name": match.name,
            "category": match.category,
            "confidence": match.confidence,
            "recommended_score": match.recommended_score,
            "contextual_score": match.contextual_score,
            # Always expose this as advisory. Enforcement must not rely on the
            # database's boolean flag alone.
            "automatic_block": False,
            "database_automatic_block": match.automatic_block,
            "domain": match.match_domain,
        }
