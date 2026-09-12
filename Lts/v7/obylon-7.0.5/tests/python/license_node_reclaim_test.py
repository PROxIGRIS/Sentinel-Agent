"""Regression tests for the 2026-09 node-removal license-enforcement fix.

A tester found two related bugs:
  1. Removing a single node from the web dashboard (to relocate it)
     didn't stop the agent on that machine. Root cause: `workstations` and
     `license_nodes` share a UUID by convention but have no FK between
     them, so deleting a workstation never touched its license_nodes row.
  2. Deleting a license OUTRIGHT also didn't stop the agent.
     license_nodes.license_id is ON DELETE CASCADE to licenses.id, so this
     hard-deletes the node's row entirely (there's no status to read) and
     /license_heartbeat returns a 404. The agent's exception handler
     couldn't tell "the internet is down" apart from "the server
     explicitly says you don't exist" — both landed in the same
     grace-period-eligible branch, so deleting a license outright left the
     agent running for up to GRACE_DAYS (14 by default).

These tests guard the fix across all the places it had to land: the DB
migration, the master provisioning template (so new schools get it too),
and the agent (which now cross-checks license_nodes directly instead of
only trusting whatever /license_heartbeat forwards, and treats a 404 or a
confirmed-absent row as fatal rather than a tolerable network hiccup).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRAIN = (ROOT / "src" / "brain" / "Obylon.py").read_text(encoding="utf-8")
MIGRATION = (ROOT / "database-map" / "db_license_node_reclaim_fix.sql").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "database-map" / "obylon_master_template.sql").read_text(encoding="utf-8")


def test_dead_workstation_id_vault_key_is_gone():
    # Was never written anywhere, only read — four alert paths (USB
    # insertion, new network adapter, fast-lane violation logging,
    # unauthorized-process-kill reporting) were silently no-op because of
    # it. Must be fully gone, not just reduced.
    assert 'vault.get("WORKSTATION_ID")' not in BRAIN
    # And the real key must be in use at (at least) the four known sites.
    assert BRAIN.count('wid = vault.get("NODE_ID")') >= 4


def test_license_heartbeat_recognizes_node_level_statuses():
    # "deactivated"/"reclaimed" are license_nodes' own status vocabulary
    # (see license_nodes_status_check) — distinct from licenses' own
    # revoked/suspended/expired. Both call sites need both vocabularies.
    needle = '("revoked", "suspended", "expired", "deactivated", "reclaimed")'
    assert BRAIN.count(needle) >= 2


def test_agent_cross_checks_license_nodes_directly():
    # Ground truth read, independent of whatever /license_heartbeat
    # chooses to forward — this is what makes the fix work even without
    # visibility into that edge function's own source.
    assert '.table("license_nodes")' in BRAIN
    assert '.eq("id", NODE_ID)' in BRAIN


def test_realtime_listener_watches_this_nodes_own_row():
    assert 'table="license_nodes"' in BRAIN
    assert 'filter=f"id=eq.{workstation_id}"' in BRAIN
    assert "_on_node_reclaimed" in BRAIN


def test_realtime_also_watches_for_this_nodes_row_being_deleted():
    # UPDATE-only wasn't enough: license_nodes.license_id is ON DELETE
    # CASCADE to licenses.id, so deleting the license hard-deletes this
    # node's row rather than updating its status — an UPDATE listener
    # alone has nothing to catch there.
    assert 'event="DELETE"' in BRAIN
    assert "_on_node_deleted" in BRAIN
    # Both listeners must be registered on the same node-scoped channel/filter.
    delete_idx = BRAIN.index("_on_node_deleted")
    window = BRAIN[delete_idx: delete_idx + 800]
    assert 'table="license_nodes"' in window
    assert 'filter=f"id=eq.{workstation_id}"' in window


def test_heartbeat_treats_404_as_fatal_not_as_offline_tolerance():
    # A 404 means the server looked this node/license up and found
    # nothing — permanent and authoritative, must bypass the grace-period
    # branch entirely rather than falling into the same bucket as a
    # generic connection error.
    assert "urllib.error.HTTPError" in BRAIN
    assert "e.code == 404" in BRAIN
    idx = BRAIN.index("e.code == 404")
    window = BRAIN[idx: idx + 700]
    assert "LICENSE_INVALID_EVENT.set()" in window
    assert "return" in window


def test_heartbeat_import_of_urllib_error_is_explicit():
    # urllib.error.HTTPError works transitively after `import
    # urllib.request` in CPython, but relying on that implicitly is
    # fragile — must be imported explicitly.
    assert "import urllib.error" in BRAIN


def test_direct_license_nodes_check_treats_confirmed_absent_row_as_fatal():
    # .maybe_single() returns data=None WITHOUT raising for zero rows —
    # that's "confirmed gone" (same CASCADE-delete scenario as the 404
    # case), not "the query failed." The original version of this check
    # only looked at status != "active", which is also None for a
    # missing row, so it silently did nothing for a deleted node.
    assert "node_row.data is None" in BRAIN
    idx = BRAIN.index("node_row.data is None")
    window = BRAIN[idx: idx + 400]
    assert "LICENSE_INVALID_EVENT.set()" in window
    assert "license_nodes row no longer exists" in window


def _assert_reclaim_migration_present(sql: str, label: str):
    assert "reclaim_license_node_on_workstation_delete" in sql, label
    assert "AFTER DELETE ON public.workstations" in sql, label
    assert "status = 'reclaimed'" in sql, label
    assert "'reclaim'" in sql, label


def test_db_migration_has_the_reclaim_trigger():
    _assert_reclaim_migration_present(MIGRATION, "db_license_node_reclaim_fix.sql")


def test_master_template_has_the_same_reclaim_trigger():
    # New school provisioning must get this too, not just already-
    # provisioned schools that get the standalone migration run against
    # them by hand.
    _assert_reclaim_migration_present(TEMPLATE, "obylon_master_template.sql")


def test_neither_sql_file_grants_anon_access_to_license_nodes():
    for sql, label in [(MIGRATION, "migration"), (TEMPLATE, "template")]:
        assert "GRANT ALL ON TABLE public.license_nodes TO anon" not in sql, label
        assert "GRANT SELECT ON TABLE public.license_nodes TO anon" not in sql, label


def test_nodes_self_managed_policy_is_select_only_in_both_files():
    for sql, label in [(MIGRATION, "migration"), (TEMPLATE, "template")]:
        # Anchor on the CREATE POLICY statement itself, not just any
        # mention of the policy name — both files also reference it in
        # prose (banner comments, DROP POLICY IF EXISTS) before the
        # actual statement.
        assert "CREATE POLICY nodes_self_managed" in sql, label
        idx = sql.index("CREATE POLICY nodes_self_managed")
        window = sql[idx: idx + 300]
        assert "FOR SELECT" in window, label
        assert "FOR ALL" not in window, label


def test_realtime_publication_includes_license_nodes_in_both_files():
    for sql, label in [(MIGRATION, "migration"), (TEMPLATE, "template")]:
        assert "ALTER PUBLICATION supabase_realtime ADD TABLE public.license_nodes" in sql, label
