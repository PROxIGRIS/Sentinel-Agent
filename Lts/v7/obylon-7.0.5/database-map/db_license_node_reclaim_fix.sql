-- ============================================================================
-- Obylon — License Node Reclaim Fix
-- ============================================================================
-- Problem (reported by a tester): removing a node from the web dashboard
-- to relocate it does NOT stop the agent on that machine. It keeps running
-- indefinitely, and the freed hardware doesn't actually free a license
-- seat either — re-activating a replacement PC under the same license can
-- still hit node_limit_reached even though a seat was "removed."
--
-- Root cause: `public.workstations` and `public.license_nodes` are two
-- separate tables that happen to share the same UUID by convention
-- (activate_license_node() INSERTs both with the same id — see that
-- function below) but have NO foreign-key relationship to each other.
-- Every other operational table (activity_logs, admin_actions,
-- agent_configs, alerts, case_dossiers, unauthorized_events) has an
-- `ON DELETE CASCADE` to workstations.id, so "remove this device" in the
-- dashboard is almost certainly `DELETE FROM public.workstations WHERE
-- id = ...` — which correctly wipes all of that device's operational
-- history, but leaves its `license_nodes` row completely untouched, still
-- `status = 'active'`. The agent's license check (whatever calls
-- /license_heartbeat) is validating against license_nodes, not
-- workstations, so it never learns anything happened. license_nodes'
-- own status_check constraint already allows 'deactivated'/'reclaimed'
-- and license_events.event_type already allows 'reclaim' — the schema
-- was clearly built anticipating this lifecycle, the glue to actually
-- run it on removal was just never added.
--
-- Separately: license_nodes currently has `GRANT ALL ... TO anon` and
-- `GRANT ALL ... TO authenticated`, with a `nodes_self_managed` policy
-- that's FOR ALL (not just SELECT) — so a node's own agent, authenticated
-- as its own dedicated auth user, can currently UPDATE or DELETE its OWN
-- license_nodes row directly (e.g. flip itself back to 'active' after
-- being reclaimed). No legitimate code path needs this: every real write
-- to license_nodes goes through activate_license_node(), a SECURITY
-- DEFINER RPC called by the /activate and /license_heartbeat edge
-- functions using the service role, which bypasses RLS entirely. The
-- agent itself only ever needs to READ its own row (this fix adds exactly
-- that: a realtime subscription and a direct heartbeat-time read — see
-- license_heartbeat_loop / realtime_c2_listener in Obylon.py).
--
-- This migration:
--   1. Locks down license_nodes to SELECT-only for `authenticated`
--      (scoped to the node's own row, as before), and removes the `anon`
--      grant entirely — matching the pattern already applied to
--      workstations/admin_actions/etc. in db_rls_fixes.sql.
--   2. Adds an AFTER DELETE trigger on workstations that reclaims the
--      matching license_nodes row (status -> 'reclaimed', last_seen_at
--      bumped) and logs a license_events 'reclaim' row, whenever that
--      node was still 'active'.
--   3. Adds license_nodes to the supabase_realtime publication (it isn't
--      currently a member — Obylon.py's new per-node realtime listener,
--      see realtime_c2_listener, needs this to receive anything at all).
--
-- Verified safe: activate_license_node() is SECURITY DEFINER and always
-- runs as postgres, so it bypasses RLS regardless of what's granted to
-- authenticated/anon here — none of its INSERT/UPDATE/SELECT calls
-- against license_nodes are affected by this migration. Re-activating a
-- previously-reclaimed node still works exactly as before: step 3 of that
-- function re-counts `status = 'active'` rows for the node_limit check
-- (a reclaimed row no longer counts, freeing the seat as intended), and
-- step 4's UPDATE flips status back to 'active' on reactivation.
--
-- IMPORTANT — run this against EVERY already-provisioned per-school
-- Supabase project, not just this template (same caveat as
-- db_rls_fixes.sql). obylon_master_template.sql has been updated to
-- include all three pieces below for new school provisioning going
-- forward, but existing schools need this run against them directly.
-- ============================================================================

BEGIN;

-- -----------------------------------------------------------------------
-- 1. license_nodes: SELECT-only for authenticated, nothing for anon.
-- -----------------------------------------------------------------------
REVOKE ALL ON TABLE public.license_nodes FROM anon;
REVOKE ALL ON TABLE public.license_nodes FROM authenticated;
GRANT SELECT ON TABLE public.license_nodes TO authenticated;

DROP POLICY IF EXISTS nodes_self_managed ON public.license_nodes;
CREATE POLICY nodes_self_managed ON public.license_nodes
  FOR SELECT TO authenticated
  USING (auth.uid() = auth_user_id);

-- "Developer Manage Nodes" (dev/admin roles, all operations) is untouched
-- — that's internal tooling access, not the agent's own path, and isn't
-- part of this bug.

-- -----------------------------------------------------------------------
-- 2. Reclaim the license seat when its workstation is removed.
-- -----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.reclaim_license_node_on_workstation_delete()
RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE
  v_node record;
BEGIN
  -- workstations.id and license_nodes.id are the same UUID by convention
  -- (see activate_license_node() below) — there's no FK to join on, so
  -- this looks it up directly by id.
  SELECT * INTO v_node FROM public.license_nodes WHERE id = OLD.id;

  IF FOUND AND v_node.status = 'active' THEN
    UPDATE public.license_nodes
    SET status = 'reclaimed', last_seen_at = now()
    WHERE id = OLD.id;

    INSERT INTO public.license_events (license_id, node_id, event_type, detail)
    VALUES (
      v_node.license_id,
      v_node.id,
      'reclaim',
      jsonb_build_object(
        'reason', 'workstation_deleted',
        'hardware_uuid', v_node.hardware_uuid,
        'hostname', v_node.hostname
      )
    );
  END IF;

  RETURN OLD;
END;
$$;

ALTER FUNCTION public.reclaim_license_node_on_workstation_delete() OWNER TO postgres;

DROP TRIGGER IF EXISTS workstations_reclaim_license_node ON public.workstations;
CREATE TRIGGER workstations_reclaim_license_node
  AFTER DELETE ON public.workstations
  FOR EACH ROW EXECUTE FUNCTION public.reclaim_license_node_on_workstation_delete();

COMMIT;

-- -----------------------------------------------------------------------
-- 3. Realtime: add license_nodes so per-node reclaim events actually
--    reach the agent's new realtime_c2_listener subscription instead of
--    it connecting, subscribing, and silently never receiving anything.
--    Guarded because ALTER PUBLICATION errors if the table is already a
--    member, and this needs to be safe to re-run.
-- -----------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_publication_tables
    WHERE pubname = 'supabase_realtime'
      AND schemaname = 'public'
      AND tablename = 'license_nodes'
  ) THEN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.license_nodes;
  END IF;
END $$;

-- -----------------------------------------------------------------------
-- Verification.
-- -----------------------------------------------------------------------
-- Should return zero rows (no anon access left on license_nodes):
SELECT schemaname, tablename, policyname, roles
FROM pg_policies
WHERE schemaname = 'public' AND tablename = 'license_nodes' AND 'anon' = ANY(roles);

-- Should return exactly one row, cmd = 'SELECT' (nodes_self_managed):
SELECT policyname, cmd, roles FROM pg_policies
WHERE schemaname = 'public' AND tablename = 'license_nodes' AND policyname = 'nodes_self_managed';

-- Should return one row confirming realtime is now enabled:
SELECT schemaname, tablename FROM pg_publication_tables
WHERE pubname = 'supabase_realtime' AND schemaname = 'public' AND tablename = 'license_nodes';

-- Manual end-to-end check once applied: delete a test workstation row and
-- confirm its license_nodes row flips to 'reclaimed' and a license_events
-- 'reclaim' row appears —
--   DELETE FROM public.workstations WHERE id = '<test-node-uuid>';
--   SELECT status FROM public.license_nodes WHERE id = '<test-node-uuid>';
--   SELECT * FROM public.license_events WHERE node_id = '<test-node-uuid>' ORDER BY created_at DESC LIMIT 1;
