"""Stable, machine-scoped Obylon node identity binding.

The node UUID is the canonical remote identity. Hardware evidence is a
secondary binding signal used to recover that identity after reinstall or
loss of the local machine-id file. Display names are labels, never identity
keys.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
FINGERPRINT_RE_LEN = 64


@dataclass(frozen=True)
class NodeBinding:
    node_id: str
    hardware_uuid: str
    hardware_fingerprint: str | None
    display_name: str
    schema_version: int = SCHEMA_VERSION


def normalize_fingerprint(value: object) -> str | None:
    value = str(value or "").strip().lower()
    if len(value) == FINGERPRINT_RE_LEN and all(c in "0123456789abcdef" for c in value):
        return value
    return None


def normalize_name(value: object, fallback: str = "OBYLON-ENDPOINT") -> str:
    value = str(value or "").strip()
    fallback = str(fallback or "OBYLON-ENDPOINT").strip() or "OBYLON-ENDPOINT"
    return (value or fallback)[:128]


def machine_binding_path(programdata: str | os.PathLike[str] | None = None) -> Path:
    root = Path(programdata or os.environ.get("PROGRAMDATA", str(Path.home())))
    return root / "Obylon" / "node_binding.json"


def machine_name_path(programdata: str | os.PathLike[str] | None = None) -> Path:
    root = Path(programdata or os.environ.get("PROGRAMDATA", str(Path.home())))
    return root / "Obylon" / "node_name"


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def load_binding(programdata: str | os.PathLike[str] | None = None) -> NodeBinding | None:
    path = machine_binding_path(programdata)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        node_id = str(raw.get("node_id") or "").strip()
        hardware_uuid = str(raw.get("hardware_uuid") or "").strip()
        if not node_id or not hardware_uuid:
            return None
        return NodeBinding(
            node_id=node_id,
            hardware_uuid=hardware_uuid,
            hardware_fingerprint=normalize_fingerprint(raw.get("hardware_fingerprint")),
            display_name=normalize_name(raw.get("display_name")),
            schema_version=int(raw.get("schema_version") or SCHEMA_VERSION),
        )
    except Exception:
        return None


def save_binding(binding: NodeBinding, programdata: str | os.PathLike[str] | None = None) -> bool:
    path = machine_binding_path(programdata)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "node_id": binding.node_id,
        "hardware_uuid": binding.hardware_uuid,
        "hardware_fingerprint": normalize_fingerprint(binding.hardware_fingerprint),
        "display_name": normalize_name(binding.display_name),
    }
    try:
        _atomic_json_write(path, payload)
        return True
    except Exception:
        return False


def load_machine_name(programdata: str | os.PathLike[str] | None = None) -> str | None:
    path = machine_name_path(programdata)
    try:
        if path.exists():
            value = normalize_name(path.read_text(encoding="utf-8"), "")
            return value if value != "OBYLON-ENDPOINT" else None
    except Exception:
        pass
    return None


def save_machine_name(name: str, programdata: str | os.PathLike[str] | None = None) -> bool:
    path = machine_name_path(programdata)
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(normalize_name(name))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        return True
    except Exception:
        if tmp:
            try:
                os.unlink(tmp)
            except Exception:
                pass
        return False


def server_identity_digest(hardware_fingerprint: str | None) -> str | None:
    """Return a second, non-reversible binding digest for server-side diagnostics."""
    fingerprint = normalize_fingerprint(hardware_fingerprint)
    if not fingerprint:
        return None
    return hashlib.sha256(f"obylon-binding:{fingerprint}".encode("utf-8")).hexdigest()


def deterministic_hardware_uuid(hardware_fingerprint: str | None) -> str | None:
    """Stable UUID for fresh installs when no persisted machine-id exists."""
    fingerprint = normalize_fingerprint(hardware_fingerprint)
    if not fingerprint:
        return None
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"obylon-hardware:{fingerprint}"))
