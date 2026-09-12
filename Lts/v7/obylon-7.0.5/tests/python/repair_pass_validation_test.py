from __future__ import annotations

import ast
import json
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OBYLON = ROOT / "src" / "brain" / "Obylon.py"


def _source() -> str:
    return OBYLON.read_text(encoding="utf-8")


def _extract_vault_class():
    tree = ast.parse(_source(), filename=str(OBYLON))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ObylonVault")
    module = ast.Module(body=[node], type_ignores=[])
    namespace = {
        "os": __import__("os"),
        "json": json,
        "threading": __import__("threading"),
        "tempfile": tempfile,
        "time": time,
        "Path": Path,
        "USER_HOME": Path(tempfile.gettempdir()),
        "HARDWARE_UUID": "test-hardware",
        "logger": type("Logger", (), {
            "warning": staticmethod(lambda *a, **k: None),
            "error": staticmethod(lambda *a, **k: None),
            "critical": staticmethod(lambda *a, **k: None),
        })(),
        "verify_server_signature": lambda payload, sig: True,
        "win32crypt": type("Win32", (), {})(),
        "CRYPTPROTECT_LOCAL_MACHINE": 4,
    }
    exec(compile(module, str(OBYLON), "exec"), namespace)
    return namespace["ObylonVault"]


def test_source_contracts():
    src = _source()
    vault_start = src.index("class ObylonVault:")
    vault_end = src.index("def provision_via_license", vault_start)
    section = src[vault_start:vault_end]
    assert section.count("    def load(") == 1
    assert section.count("    def _save(") == 1
    assert "hardware_uuid" in section
    assert "os.replace(temp_path, target)" in section
    assert "os.fsync(f.fileno())" in section
    assert ".corrupt" in section
    assert "set_auth(ACCESS_TOKEN)" not in src
    assert "HardwareFingerprintWithStatus" in (ROOT / "obylonc/internal/platform/other.go").read_text()
    assert "const fingerprintTimeout = 12 * time.Second" in (ROOT / "obylonc/internal/platform/windows.go").read_text()
    assert "LEGACY_UNVERIFIED" in src


def test_atomic_vault_write_preserves_complete_previous_file():
    Vault = _extract_vault_class()
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "obylon.enc"
        vault = Vault.__new__(Vault)
        vault.config_dir = td
        vault.config_file = str(target)
        vault._data = {"generation": 1, "token": "A"}
        vault._lock = __import__("threading").Lock()
        vault._encrypt = lambda raw: raw
        vault._unhide_file_for_path = lambda path: None
        vault._save()
        first = target.read_bytes()
        assert json.loads(first.decode()) == {"generation": 1, "token": "A"}

        vault._data = {"generation": 2, "token": "B"}
        vault._save()
        second = target.read_bytes()
        assert json.loads(second.decode()) == {"generation": 2, "token": "B"}
        assert b'"generation":1' not in second
        assert not list(Path(td).glob(".obylon-vault-*.tmp"))


def test_corrupt_vault_is_quarantined_not_deleted():
    Vault = _extract_vault_class()
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "obylon.enc"
        target.write_bytes(b"corrupt")
        vault = Vault.__new__(Vault)
        vault.config_dir = td
        vault.config_file = str(target)
        vault._data = {"sentinel": "preserve"}
        vault._lock = __import__("threading").Lock()
        vault._decrypt = lambda raw: (_ for _ in ()).throw(ValueError("bad decrypt"))
        vault._unhide_file_for_path = lambda path: None
        vault._unhide_file = lambda: None
        assert vault.load() is False
        assert not target.exists()
        quarantined = list(Path(td).glob("obylon.enc.corrupt*"))
        assert quarantined, "corrupt evidence must be quarantined"
        assert quarantined[0].read_bytes() == b"corrupt"


if __name__ == "__main__":
    test_source_contracts()
    test_atomic_vault_write_preserves_complete_previous_file()
    test_corrupt_vault_is_quarantined_not_deleted()
    print("repair_pass_validation: PASS")
