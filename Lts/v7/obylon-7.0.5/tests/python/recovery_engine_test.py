from __future__ import annotations

import tempfile
from pathlib import Path

from recovery_engine import (
    RecoveryClass,
    RecoveryEngine,
    RecoveryOutcome,
)


def make_engine(tmp: Path):
    state = {"auth": "failed", "client": "absent"}
    actions = {"auth": 0, "realtime": 0, "identity": 0}

    def log(*args, **kwargs):
        pass

    engine = RecoveryEngine(
        journal_path=tmp / "recovery.json",
        logger=log,
        state_provider=lambda: state,
        authorized_recovery=lambda obs, plan: not obs.facts.get("deny_recovery", False),
    )

    def auth(obs):
        actions["auth"] += 1
        state["auth"] = "authenticated"
        return True

    engine.register_action("recover_auth", auth)
    engine.register_validator("verify_auth", lambda obs: state["auth"] == "authenticated")
    return engine, actions, state


def test_auth_recovery_success():
    with tempfile.TemporaryDirectory() as d:
        engine, actions, _ = make_engine(Path(d))
        obs = engine.classify("401", "license", "auth token rejected")
        assert obs.failure_class == RecoveryClass.RECOVERABLE_AUTH
        assert engine.attempt(obs) == RecoveryOutcome.RECOVERED
        assert actions["auth"] == 1


def test_cooldown_blocks_immediate_repeat():
    with tempfile.TemporaryDirectory() as d:
        engine, actions, state = make_engine(Path(d))
        obs = engine.classify("401", "license", "auth token rejected")
        assert engine.attempt(obs) == RecoveryOutcome.RECOVERED
        state["auth"] = "failed"
        assert engine.attempt(obs) in {RecoveryOutcome.COOLDOWN, RecoveryOutcome.NO_ACTION}
        assert actions["auth"] == 1


def test_security_classes_have_no_default_repair():
    with tempfile.TemporaryDirectory() as d:
        engine, _, _ = make_engine(Path(d))
        mismatch = engine.classify(
            "identity", "identity", "hardware mismatch", {"hardware_mismatch": True}
        )
        tampered = engine.classify(
            "vault", "vault", "signature invalid", {"vault_tampered": True}
        )
        assert engine.attempt(mismatch) == RecoveryOutcome.BLOCKED
        assert engine.attempt(tampered) == RecoveryOutcome.BLOCKED


def test_identity_relink_requires_all_guards():
    with tempfile.TemporaryDirectory() as d:
        engine, _, _ = make_engine(Path(d))
        called = {"n": 0}
        verified = {"ok": False}

        engine.register_action("recover_identity_relink", lambda obs: called.__setitem__("n", called["n"] + 1) or True)
        engine.register_validator("verify_identity_relinked", lambda obs: verified["ok"])

        obs = engine.classify(
            "identity", "identity", "prior activation identity missing",
            {
                "same_machine": True,
                "previously_licensed": True,
                "identity_reset_authorized": True,
            },
        )
        assert engine.attempt(obs) == RecoveryOutcome.FAILED
        assert called["n"] == 1
        assert verified["ok"] is False


def test_denied_recovery_never_runs_action():
    with tempfile.TemporaryDirectory() as d:
        engine, actions, _ = make_engine(Path(d))
        obs = engine.classify("401", "license", "auth failure", {"deny_recovery": True})
        assert engine.attempt(obs) == RecoveryOutcome.BLOCKED
        assert actions["auth"] == 0
