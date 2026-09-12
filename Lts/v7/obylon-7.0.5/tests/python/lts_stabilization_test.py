from __future__ import annotations

import ast
import threading
import time
import socket
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "brain" / "Obylon.py"


def _extract(names):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    assert {n.name for n in nodes} == set(names)
    module = ast.Module(body=nodes, type_ignores=[])
    ns = {"threading": threading, "time": time, "socket": socket}
    exec(compile(module, str(SOURCE), "exec"), ns)
    return ns


def test_action_claim_is_single_winner_and_success_is_deduped():
    ns = _extract({"_claim_admin_action", "_finish_admin_action"})
    ns["_ACTION_CLAIM_LOCK"] = threading.RLock()
    ns["_ACTION_CLAIMED"] = {}
    ns["_ACTION_COMPLETED"] = {}
    ns["COMMAND_TTL_SEC"] = 60
    ns["_ACTION_CLAIM_LEASE_SEC"] = 30.0
    wins = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        if ns["_claim_admin_action"]("action-1"):
            wins.append(1)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert len(wins) == 1

    ns["_finish_admin_action"]("action-1", True)
    assert ns["_claim_admin_action"]("action-1") is False


def test_node_name_normalization_is_never_empty():
    ns = _extract({"_normalized_node_name"})
    assert ns["_normalized_node_name"]("   ") == "OBYLON-ENDPOINT"
    assert ns["_normalized_node_name"](None, "FALLBACK") == "FALLBACK"
    assert len(ns["_normalized_node_name"]("x" * 500)) == 128


def test_stable_node_id_is_deterministic_and_license_scoped():
    ns = _extract({"_stable_node_id"})
    a = ns["_stable_node_id"]("HW-1", "LIC-1")
    assert a == ns["_stable_node_id"]("HW-1", "LIC-1")
    assert a != ns["_stable_node_id"]("HW-1", "LIC-2")
    assert a != ns["_stable_node_id"]("HW-2", "LIC-1")


def test_registration_source_no_longer_uses_name_only_identity():
    source = SOURCE.read_text(encoding="utf-8")
    start = source.index("def register_workstation() -> str:")
    end = source.index("\n\nIDENTITY_BEACON_FILE =", start)
    reg = source[start:end]
    assert '.eq("name", WORKSTATION_NAME)' not in reg
    assert 'uuid.uuid4()' not in reg
    assert 'vault.get("NODE_ID") or NODE_ID' in reg
    assert '_stable_node_id(HARDWARE_UUID' in reg


class _Response:
    def __init__(self, data=None):
        self.data = data or []


class _Query:
    def __init__(self, db, table, op):
        self.db, self.table, self.op = db, table, op
        self.filters = {}
        self.payload = None
        self._limit = None

    def select(self, *_): return self
    def update(self, payload): self.payload = payload; self.op = "update"; return self
    def insert(self, payload): self.payload = payload; self.op = "insert"; return self
    def eq(self, key, value): self.filters[key] = value; return self
    def limit(self, value): self._limit = value; return self
    def execute(self):
        rows = self.db.setdefault(self.table, [])
        if self.op == "select":
            out = [r.copy() for r in rows if all(r.get(k) == v for k, v in self.filters.items())]
            return _Response(out[: self._limit] if self._limit else out)
        if self.op == "update":
            matched = []
            for row in rows:
                if all(row.get(k) == v for k, v in self.filters.items()):
                    row.update(self.payload); matched.append(row.copy())
            return _Response(matched)
        if self.op == "insert":
            if any(r.get("id") == self.payload.get("id") for r in rows):
                raise RuntimeError("duplicate key")
            rows.append(dict(self.payload)); return _Response([dict(self.payload)])
        raise AssertionError(self.op)


class _Client:
    def __init__(self, db): self.db = db; self.inserts = 0
    def table(self, name):
        q = _Query(self.db, name, "select")
        original_execute = q.execute
        def execute():
            if q.op == "insert": self.inserts += 1
            return original_execute()
        q.execute = execute
        return q


class _Vault:
    def __init__(self, data): self._data = dict(data); self.saves = 0
    def get(self, key, default=None): return self._data.get(key, default)
    def _save(self): self.saves += 1


class _Session:
    def __init__(self, client): self.client = client
    def get_client(self): return self.client


def test_registration_reconciles_existing_node_and_never_creates_a_second_one():
    ns = _extract({"_normalized_node_name", "_stable_node_id", "register_workstation", "_identity_os_info", "_server_rows_by_hardware_fingerprint"})
    ns["os"] = __import__("os")
    db = {"workstations": [{"id": "node-1", "hardware_uuid": "hw-1", "name": ""}]}
    client = _Client(db)
    ns.update({
        "_NODE_REGISTRATION_LOCK": threading.RLock(),
        "session_manager": _Session(client),
        "vault": _Vault({"NODE_ID": "node-1", "NODE_NAME": "SALE-PC"}),
        "NODE_ID": None,
        "HARDWARE_UUID": "hw-1",
        "WORKSTATION_NAME": "hostname",
        "LICENSE_ID": "lic-1",
        "logger": type("L", (), {
            "info": staticmethod(lambda *a, **k: None),
            "warning": staticmethod(lambda *a, **k: None),
            "error": staticmethod(lambda *a, **k: None),
        })(),
        "os_info": lambda: {"platform": "test"},
        "now_iso": lambda: "2026-09-06T00:00:00+00:00",
        "get_hardware_fingerprint_blocking": lambda timeout=5.0: None,
        "_promote_provisional_hardware_uuid": lambda fp: None,
        "node_identity": type("NI", (), {
            "normalize_fingerprint": staticmethod(lambda v: None),
            "server_identity_digest": staticmethod(lambda v: None),
            "save_machine_name": staticmethod(lambda *a, **k: True),
            "save_binding": staticmethod(lambda *a, **k: True),
            "NodeBinding": staticmethod(lambda **kwargs: kwargs),
            "SCHEMA_VERSION": 1,
        })(),
        "get_workstation_identity": lambda: "hostname",
    })
    assert ns["register_workstation"]() == "node-1"
    assert ns["register_workstation"]() == "node-1"
    assert client.inserts == 0
    assert db["workstations"][0]["name"] == "SALE-PC"


def test_registration_uses_deterministic_id_when_no_remote_row_exists():
    ns = _extract({"_normalized_node_name", "_stable_node_id", "register_workstation", "_identity_os_info", "_server_rows_by_hardware_fingerprint"})
    ns["os"] = __import__("os")
    db = {"workstations": []}
    client = _Client(db)
    ns.update({
        "_NODE_REGISTRATION_LOCK": threading.RLock(),
        "session_manager": _Session(client),
        "vault": _Vault({}),
        "NODE_ID": None,
        "HARDWARE_UUID": "hw-new",
        "WORKSTATION_NAME": "new-pc",
        "LICENSE_ID": "lic-new",
        "logger": type("L", (), {
            "info": staticmethod(lambda *a, **k: None),
            "warning": staticmethod(lambda *a, **k: None),
            "error": staticmethod(lambda *a, **k: None),
        })(),
        "os_info": lambda: {"platform": "test"},
        "now_iso": lambda: "2026-09-06T00:00:00+00:00",
        "get_hardware_fingerprint_blocking": lambda timeout=5.0: None,
        "_promote_provisional_hardware_uuid": lambda fp: None,
        "node_identity": type("NI", (), {
            "normalize_fingerprint": staticmethod(lambda v: None),
            "server_identity_digest": staticmethod(lambda v: None),
            "save_machine_name": staticmethod(lambda *a, **k: True),
            "save_binding": staticmethod(lambda *a, **k: True),
            "NodeBinding": staticmethod(lambda **kwargs: kwargs),
            "SCHEMA_VERSION": 1,
        })(),
        "get_workstation_identity": lambda: "hostname",
    })
    first = ns["register_workstation"]()
    second = ns["register_workstation"]()
    assert first == second
    assert client.inserts == 1
    assert len(db["workstations"]) == 1

def test_registration_can_relink_by_fingerprint_using_existing_os_info_schema():
    ns = _extract({"_normalized_node_name", "_stable_node_id", "register_workstation", "_identity_os_info", "_server_rows_by_hardware_fingerprint"})
    ns["os"] = __import__("os")
    fingerprint = "a" * 64
    db = {"workstations": [{
        "id": "legacy-node",
        "hardware_uuid": "old-hw",
        "name": "Sale PC",
        "os_info": {"obylon_identity": {"hardware_fingerprint": fingerprint}},
    }]}
    client = _Client(db)
    ns.update({
        "_NODE_REGISTRATION_LOCK": threading.RLock(),
        "session_manager": _Session(client),
        "vault": _Vault({}),
        "NODE_ID": None,
        "HARDWARE_UUID": "new-hw",
        "WORKSTATION_NAME": "hostname",
        "LICENSE_ID": "lic-1",
        "logger": type("L", (), {
            "info": staticmethod(lambda *a, **k: None),
            "warning": staticmethod(lambda *a, **k: None),
            "error": staticmethod(lambda *a, **k: None),
        })(),
        "os_info": lambda: {"platform": "test"},
        "now_iso": lambda: "2026-09-06T00:00:00+00:00",
        "get_hardware_fingerprint_blocking": lambda timeout=5.0: fingerprint,
        "_promote_provisional_hardware_uuid": lambda fp: None,
        "node_identity": type("NI", (), {
            "normalize_fingerprint": staticmethod(lambda v: v if isinstance(v, str) and len(v) == 64 else None),
            "server_identity_digest": staticmethod(lambda v: "digest"),
            "save_machine_name": staticmethod(lambda *a, **k: True),
            "save_binding": staticmethod(lambda *a, **k: True),
            "NodeBinding": staticmethod(lambda **kwargs: kwargs),
            "SCHEMA_VERSION": 1,
        })(),
        "get_workstation_identity": lambda: "hostname",
    })
    assert ns["register_workstation"]() == "legacy-node"
    assert len(db["workstations"]) == 1
