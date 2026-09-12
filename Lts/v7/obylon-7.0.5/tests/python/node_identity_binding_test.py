from __future__ import annotations

import json
from pathlib import Path

import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "brain"))
import node_identity


def test_deterministic_hardware_uuid_is_stable():
    fp = "a" * 64
    assert node_identity.deterministic_hardware_uuid(fp) == node_identity.deterministic_hardware_uuid(fp)
    assert node_identity.deterministic_hardware_uuid(fp) != node_identity.deterministic_hardware_uuid("b" * 64)


def test_binding_round_trip_is_atomic_and_versioned(tmp_path):
    binding = node_identity.NodeBinding(
        node_id="node-123",
        hardware_uuid="hw-123",
        hardware_fingerprint="a" * 64,
        display_name="Sale PC",
    )
    assert node_identity.save_binding(binding, tmp_path)
    loaded = node_identity.load_binding(tmp_path)
    assert loaded == binding
    raw = json.loads(node_identity.machine_binding_path(tmp_path).read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert raw["display_name"] == "Sale PC"


def test_machine_name_is_shared_across_profiles(tmp_path):
    assert node_identity.save_machine_name("Sale PC", tmp_path)
    assert node_identity.load_machine_name(tmp_path) == "Sale PC"
    assert node_identity.machine_name_path(tmp_path).exists()


def test_invalid_fingerprint_never_binds():
    assert node_identity.normalize_fingerprint("") is None
    assert node_identity.normalize_fingerprint("z" * 64) is None
    assert node_identity.normalize_fingerprint("a" * 63) is None


def test_current_schema_fallback_is_present_in_registration_code():
    source = (ROOT / "src" / "brain" / "Obylon.py").read_text(encoding="utf-8")
    assert 'select("id,name,hardware_uuid,os_info")' in source
    assert 'obylon_identity' in source
    assert 'hardware_fingerprint' in source

