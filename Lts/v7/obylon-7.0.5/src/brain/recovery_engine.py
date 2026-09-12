from __future__ import annotations

"""Obylon deterministic Recovery Intelligence / Recovery Orchestrator.

This module is deliberately independent from the Brain's business logic.  It
classifies observed failures, selects only pre-authorized repair plans, applies
bounded actions, validates post-conditions, and persists a small non-secret
journal.  It is not an LLM and it never executes arbitrary shell/code.
"""

import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Optional


class RecoveryClass(str, Enum):
    RECOVERABLE_AUTH = "recoverable_auth"
    RECOVERABLE_CLIENT = "recoverable_client"
    RECOVERABLE_LICENSE = "recoverable_license"
    RECOVERABLE_IDENTITY = "recoverable_identity"
    RECOVERABLE_VAULT = "recoverable_vault"
    RECOVERABLE_SYNC = "recoverable_sync"
    RECOVERABLE_REALTIME = "recoverable_realtime"
    RECOVERABLE_CONFIGURATION = "recoverable_configuration"
    THREAD_FAILURE = "thread_failure"
    SECURITY_TERMINAL = "security_terminal"
    HARDWARE_MISMATCH = "hardware_mismatch"
    LICENSE_REVOKED = "license_revoked"
    VAULT_TAMPERED = "vault_tampered"
    UNKNOWN = "unknown"


class RecoveryOutcome(str, Enum):
    RECOVERED = "recovered"
    NO_ACTION = "no_action"
    BLOCKED = "blocked"
    FAILED = "failed"
    COOLDOWN = "cooldown"
    BUDGET_EXHAUSTED = "budget_exhausted"
    INVALID_PLAN = "invalid_plan"


@dataclass(frozen=True)
class RecoveryObservation:
    failure_class: RecoveryClass
    component: str
    signal: str
    reason: str
    severity: str = "warning"
    attempt_key: str = ""
    facts: Mapping[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class RecoveryPlan:
    plan_id: str
    failure_class: RecoveryClass
    action: str
    verify: str
    max_attempts: int = 3
    window_sec: float = 900.0
    cooldown_sec: float = 15.0
    terminal_on_verify_failure: bool = False
    requires_facts: tuple[str, ...] = ()
    forbidden_facts: tuple[str, ...] = ()


@dataclass
class RecoveryRecord:
    attempts: int = 0
    attempt_times: list[float] = field(default_factory=list)
    last_attempt: float = 0.0
    last_outcome: str = RecoveryOutcome.NO_ACTION.value
    successes: int = 0
    failures: int = 0
    last_signal: str = ""
    last_reason: str = ""


@dataclass(frozen=True)
class RecoveryDecision:
    plan: Optional[RecoveryPlan]
    score: float
    why: tuple[str, ...]


class RecoveryJournal:
    """Small, atomic, non-secret journal for successful recovery history."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {
            "schema": 1,
            "updated_at": 0.0,
            "records": {},
            "last_success": {},
        }
        self.load()

    def load(self) -> None:
        with self._lock:
            try:
                raw = self.path.read_text(encoding="utf-8")
                data = json.loads(raw)
                if not isinstance(data, dict) or data.get("schema") != 1:
                    raise ValueError("unsupported recovery journal schema")
                if not isinstance(data.get("records", {}), dict):
                    raise ValueError("invalid records section")
                self._data = data
            except FileNotFoundError:
                return
            except Exception:
                # Preserve forensic evidence. Do not destroy or silently
                # replace an unreadable journal.
                try:
                    quarantine = self.path.with_name(
                        f"{self.path.name}.corrupt.{int(time.time())}"
                    )
                    os.replace(self.path, quarantine)
                except Exception:
                    pass

    def get(self, key: str) -> RecoveryRecord:
        with self._lock:
            raw = self._data["records"].get(key, {})
            return RecoveryRecord(
                attempts=int(raw.get("attempts", 0)),
                attempt_times=[float(x) for x in raw.get("attempt_times", []) if isinstance(x, (int, float))],
                last_attempt=float(raw.get("last_attempt", 0.0)),
                last_outcome=str(raw.get("last_outcome", RecoveryOutcome.NO_ACTION.value)),
                successes=int(raw.get("successes", 0)),
                failures=int(raw.get("failures", 0)),
                last_signal=str(raw.get("last_signal", "")),
                last_reason=str(raw.get("last_reason", "")),
            )

    def put(self, key: str, record: RecoveryRecord) -> None:
        with self._lock:
            self._data["records"][key] = asdict(record)
            self._data["updated_at"] = time.time()
            self._atomic_write()

    def note_success(self, plan_id: str, metadata: Mapping[str, Any]) -> None:
        with self._lock:
            self._data["last_success"][plan_id] = {
                "timestamp": time.time(),
                "metadata": self._sanitize(metadata),
            }
            self._data["updated_at"] = time.time()
            self._atomic_write()

    @staticmethod
    def _sanitize(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(k): RecoveryJournal._sanitize(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [RecoveryJournal._sanitize(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    def _atomic_write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, separators=(",", ":"), sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, self.path)
        finally:
            try:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
            except OSError:
                pass


class RecoveryEngine:
    """Bounded, deterministic repair orchestrator.

    Actions and validators are injected by the Brain.  The engine itself has
    zero authority to execute system commands, change policy, or bypass a
    security state.  Every plan has explicit prerequisites, attempt budget,
    cooldown, and a post-condition validator.
    """

    def __init__(
        self,
        *,
        journal_path: str | os.PathLike[str],
        logger: Optional[Callable[..., Any]] = None,
        state_provider: Optional[Callable[[], Mapping[str, Any]]] = None,
        authorized_recovery: Optional[Callable[[RecoveryObservation, RecoveryPlan], bool]] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._journal = RecoveryJournal(journal_path)
        self._logger = logger or (lambda *args, **kwargs: None)
        self._state_provider = state_provider or (lambda: {})
        self._authorized_recovery = authorized_recovery or (lambda obs, plan: True)
        self._actions: dict[str, Callable[[RecoveryObservation], bool]] = {}
        self._validators: dict[str, Callable[[RecoveryObservation], bool]] = {}
        self._plans: dict[RecoveryClass, list[RecoveryPlan]] = {}
        self._install_default_plans()

    def register_action(self, name: str, action: Callable[[RecoveryObservation], bool]) -> None:
        with self._lock:
            self._actions[name] = action

    def register_validator(self, name: str, validator: Callable[[RecoveryObservation], bool]) -> None:
        with self._lock:
            self._validators[name] = validator

    def register_plan(self, plan: RecoveryPlan) -> None:
        if plan.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if plan.cooldown_sec < 0:
            raise ValueError("cooldown_sec must be >= 0")
        if plan.window_sec <= 0:
            raise ValueError("window_sec must be > 0")
        with self._lock:
            self._plans.setdefault(plan.failure_class, []).append(plan)

    def classify(self, signal: str, component: str, reason: str, facts: Mapping[str, Any] | None = None) -> RecoveryObservation:
        facts = dict(facts or {})
        normalized = f"{signal} {reason}".lower()
        if facts.get("security_terminal"):
            cls = RecoveryClass.SECURITY_TERMINAL
        elif facts.get("hardware_mismatch"):
            cls = RecoveryClass.HARDWARE_MISMATCH
        elif facts.get("license_revoked"):
            cls = RecoveryClass.LICENSE_REVOKED
        elif facts.get("vault_tampered"):
            cls = RecoveryClass.VAULT_TAMPERED
        elif facts.get("thread_failed"):
            # BUGFIX (2026-09): must be checked before the substring guesses
            # below. The Lazarus Watchdog already knows structurally that
            # this is a dead-thread observation (it sets thread_failed=True
            # itself) — it shouldn't be re-guessed from text. Previously, a
            # flatlined thread named e.g. "identity_verify" or a crash
            # reason that merely mentioned "identity"/"license"/"vault"/etc.
            # would match one of those substring branches first and get
            # routed to that domain's bounded recovery plan instead of the
            # generic thread-restart plan, even though nothing about the
            # actual failure was identity/license/vault-specific.
            cls = RecoveryClass.THREAD_FAILURE
        elif "realtime" in normalized or "websocket" in normalized:
            cls = RecoveryClass.RECOVERABLE_REALTIME
        elif "license" in normalized or "heartbeat" in normalized:
            cls = RecoveryClass.RECOVERABLE_LICENSE
        elif "identity" in normalized or "fingerprint" in normalized:
            cls = RecoveryClass.RECOVERABLE_IDENTITY
        elif "vault" in normalized:
            cls = RecoveryClass.RECOVERABLE_VAULT
        elif "sync" in normalized or "queue" in normalized:
            cls = RecoveryClass.RECOVERABLE_SYNC
        elif "client" in normalized or "supabase" in normalized:
            cls = RecoveryClass.RECOVERABLE_CLIENT
        elif "auth" in normalized or "token" in normalized or "401" in normalized:
            cls = RecoveryClass.RECOVERABLE_AUTH
        elif "thread" in normalized or "flatlined" in normalized:
            cls = RecoveryClass.THREAD_FAILURE
        elif "config" in normalized:
            cls = RecoveryClass.RECOVERABLE_CONFIGURATION
        else:
            cls = RecoveryClass.UNKNOWN
        return RecoveryObservation(cls, component, signal, reason, facts=facts)

    def decide(self, observation: RecoveryObservation) -> RecoveryDecision:
        with self._lock:
            candidates = []
            for plan in self._plans.get(observation.failure_class, []):
                if any(not observation.facts.get(key) for key in plan.requires_facts):
                    continue
                if any(observation.facts.get(key) for key in plan.forbidden_facts):
                    continue
                if plan.action not in self._actions or plan.verify not in self._validators:
                    continue
                record = self._journal.get(self._key(observation, plan))
                now = time.time()
                recent = [t for t in record.attempt_times if now - t <= plan.window_sec]
                if len(recent) >= plan.max_attempts:
                    continue
                age = now - record.last_attempt if record.last_attempt else None
                if age is not None and age < plan.cooldown_sec:
                    continue
                score, why = self._score(plan, observation, record)
                candidates.append((score, plan, why))
            if not candidates:
                return RecoveryDecision(None, 0.0, ("no eligible bounded plan",))
            candidates.sort(key=lambda item: (-item[0], item[1].plan_id))
            score, plan, why = candidates[0]
            return RecoveryDecision(plan, score, tuple(why))

    def attempt(self, observation: RecoveryObservation) -> RecoveryOutcome:
        decision = self.decide(observation)
        if decision.plan is None:
            key = f"{observation.failure_class.value}:{observation.component}:{observation.signal}"
            # Distinguish genuine terminal cases for diagnostics.
            if observation.failure_class in {
                RecoveryClass.SECURITY_TERMINAL,
                RecoveryClass.HARDWARE_MISMATCH,
                RecoveryClass.LICENSE_REVOKED,
                RecoveryClass.VAULT_TAMPERED,
            }:
                self._emit("recovery blocked", observation, None, outcome=RecoveryOutcome.BLOCKED.value)
                return RecoveryOutcome.BLOCKED
            record = self._journal.get(key)
            if record.last_attempt and time.time() - record.last_attempt < 1.0:
                return RecoveryOutcome.COOLDOWN
            return RecoveryOutcome.NO_ACTION

        plan = decision.plan
        key = self._key(observation, plan)
        with self._lock:
            record = self._journal.get(key)
            now = time.time()
            record.attempt_times = [t for t in record.attempt_times if now - t <= plan.window_sec]
            if len(record.attempt_times) >= plan.max_attempts:
                self._emit("recovery budget exhausted", observation, plan, outcome=RecoveryOutcome.BUDGET_EXHAUSTED.value)
                return RecoveryOutcome.BUDGET_EXHAUSTED
            record.attempt_times.append(now)
            record.attempts = len(record.attempt_times)
            record.last_attempt = now
            record.last_signal = observation.signal
            record.last_reason = observation.reason
            self._journal.put(key, record)

        try:
            if not self._authorized_recovery(observation, plan):
                record.last_outcome = RecoveryOutcome.BLOCKED.value
                self._journal.put(key, record)
                self._emit("recovery authorization denied", observation, plan, outcome=record.last_outcome)
                return RecoveryOutcome.BLOCKED

            action = self._actions.get(plan.action)
            validator = self._validators.get(plan.verify)
            if action is None or validator is None:
                record.last_outcome = RecoveryOutcome.INVALID_PLAN.value
                self._journal.put(key, record)
                return RecoveryOutcome.INVALID_PLAN

            self._emit("recovery action begin", observation, plan, outcome="begin")
            action_ok = bool(action(observation))
            if not action_ok:
                record.failures += 1
                record.last_outcome = RecoveryOutcome.FAILED.value
                self._journal.put(key, record)
                self._emit("recovery action failed", observation, plan, outcome=record.last_outcome)
                return RecoveryOutcome.FAILED

            verified = bool(validator(observation))
            if not verified:
                record.failures += 1
                record.last_outcome = RecoveryOutcome.FAILED.value
                self._journal.put(key, record)
                if plan.terminal_on_verify_failure:
                    self._emit("recovery verification failed; terminal", observation, plan, outcome=record.last_outcome)
                else:
                    self._emit("recovery verification failed", observation, plan, outcome=record.last_outcome)
                return RecoveryOutcome.FAILED

            record.successes += 1
            record.last_outcome = RecoveryOutcome.RECOVERED.value
            self._journal.put(key, record)
            self._journal.note_success(
                plan.plan_id,
                {
                    "component": observation.component,
                    "signal": observation.signal,
                    "reason": observation.reason,
                    "facts": dict(observation.facts),
                },
            )
            self._emit("recovery succeeded", observation, plan, outcome=record.last_outcome)
            return RecoveryOutcome.RECOVERED
        except Exception as exc:
            record.failures += 1
            record.last_outcome = RecoveryOutcome.FAILED.value
            self._journal.put(key, record)
            self._emit("recovery engine exception", observation, plan, outcome=record.last_outcome, error=str(exc))
            return RecoveryOutcome.FAILED

    def health(self) -> Mapping[str, Any]:
        state = dict(self._state_provider() or {})
        with self._lock:
            return {
                "engine": "recovery-intelligence",
                "schema": 1,
                "state": state,
                "plan_count": sum(len(v) for v in self._plans.values()),
                "registered_actions": sorted(self._actions),
                "registered_validators": sorted(self._validators),
            }

    def _score(self, plan: RecoveryPlan, observation: RecoveryObservation, record: RecoveryRecord) -> tuple[float, list[str]]:
        score = 50.0
        why = [f"class={observation.failure_class.value}", f"plan={plan.plan_id}"]
        if plan.action.startswith("recover_"):
            score += 10
            why.append("deterministic repair action")
        if observation.facts.get("previously_licensed"):
            score += 15
            why.append("previously licensed")
        if observation.facts.get("identity_verified"):
            score += 20
            why.append("identity verified")
        if observation.facts.get("same_machine"):
            score += 20
            why.append("same-machine evidence")
        if observation.facts.get("network_online"):
            score += 5
            why.append("network online")
        if record.successes:
            score += min(10, record.successes * 2)
            why.append("previously successful plan")
        score -= min(20, record.failures * 4)
        return score, why

    def _key(self, observation: RecoveryObservation, plan: RecoveryPlan) -> str:
        attempt_key = observation.attempt_key or observation.signal
        return f"{plan.plan_id}:{observation.component}:{attempt_key}"

    def _emit(self, message: str, observation: RecoveryObservation, plan: RecoveryPlan | None, **fields: Any) -> None:
        try:
            self._logger(
                message,
                component="recovery",
                recovery_class=observation.failure_class.value,
                signal=observation.signal,
                plan=(plan.plan_id if plan else None),
                **fields,
            )
        except Exception:
            pass

    def _install_default_plans(self) -> None:
        defaults = [
            RecoveryPlan("auth-refresh", RecoveryClass.RECOVERABLE_AUTH, "recover_auth", "verify_auth", max_attempts=3, window_sec=300, cooldown_sec=10),
            RecoveryPlan("client-rebuild", RecoveryClass.RECOVERABLE_CLIENT, "recover_client", "verify_client", max_attempts=3, window_sec=300, cooldown_sec=10),
            RecoveryPlan("license-refresh", RecoveryClass.RECOVERABLE_LICENSE, "recover_license", "verify_license", max_attempts=2, window_sec=600, cooldown_sec=30),
            RecoveryPlan("identity-retry", RecoveryClass.RECOVERABLE_IDENTITY, "recover_identity", "verify_identity", max_attempts=3, window_sec=600, cooldown_sec=20),
            RecoveryPlan("identity-reset-existing-license", RecoveryClass.RECOVERABLE_IDENTITY, "recover_identity_relink", "verify_identity_relinked", max_attempts=1, window_sec=3600.0, cooldown_sec=60.0, terminal_on_verify_failure=True, requires_facts=("same_machine", "previously_licensed", "identity_reset_authorized"), forbidden_facts=("identity_mismatch", "vault_tampered", "license_revoked")),
            RecoveryPlan("vault-repair", RecoveryClass.RECOVERABLE_VAULT, "recover_vault", "verify_vault", max_attempts=1, window_sec=3600.0, cooldown_sec=120.0, requires_facts=("identity_verified",), forbidden_facts=("vault_tampered",)),
            RecoveryPlan("sync-repair", RecoveryClass.RECOVERABLE_SYNC, "recover_sync", "verify_sync", max_attempts=3, window_sec=900, cooldown_sec=20),
            RecoveryPlan("realtime-restart", RecoveryClass.RECOVERABLE_REALTIME, "recover_realtime", "verify_realtime", max_attempts=4, window_sec=600, cooldown_sec=10),
            RecoveryPlan("configuration-reload", RecoveryClass.RECOVERABLE_CONFIGURATION, "recover_configuration", "verify_configuration", max_attempts=2, window_sec=900, cooldown_sec=30),
            RecoveryPlan("thread-restart", RecoveryClass.THREAD_FAILURE, "recover_thread", "verify_thread", max_attempts=3, window_sec=900, cooldown_sec=30.0),
        ]
        for plan in defaults:
            self.register_plan(plan)
