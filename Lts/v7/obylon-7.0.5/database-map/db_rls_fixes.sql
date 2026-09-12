-- ============================================================================
-- Obylon — RLS Lockdown Migration
-- ============================================================================
-- Problem: obylon_master_template.sql grants the public `anon` role
-- (the non-secret key embedded in obylonc.exe / Obylon.py) direct
-- read/write access to admin_actions, evidence_logs, workstations,
-- system_settings, and unauthorized_events via `USING (true)` /
-- `WITH CHECK (true))` policies. Anyone with the anon key and network
-- access to the project's REST endpoint — no device activation, no
-- Windows session, no role — can today:
--   * read every workstation's pending/complete admin_actions and flip
--     their status (silently suppress a freeze/shutdown/lock command
--     issued against their own machine before the agent claims it)
--   * insert or rewrite evidence_logs rows (fabricate or tamper with
--     the screenshot/webcam evidence a disciplinary case relies on)
--   * insert/update/select workstations rows, and read/write
--     system_settings
--   * delete unauthorized_events outright (wipe violation history)
--
-- Verified safe to require `authenticated` instead of `anon`: every
-- write the real agent makes goes through SessionManager.get_client()
-- in Obylon.py, which always calls client.auth.set_session(access_token,
-- refresh_token) before touching any of these tables (see class
-- SessionManager, ~line 317). The agent never uses the anon role for
-- these operations, so it never needed these anon policies in the
-- first place — they look like leftovers from before SessionManager
-- existed (note "Agent anon insert evidence" and "Agent anon insert
-- evidence_logs" are near-duplicate policies, as are several others,
-- consistent with an unmanaged policy history).
--
-- IMPORTANT — run this against EVERY already-provisioned per-school
-- Supabase project, not just this template. Editing
-- obylon_master_template.sql only changes what NEW school projects get
-- from obylon-provisioning; existing schools keep the vulnerable
-- policies until this migration is applied to each of them directly.
--
-- Run PHASE 1 now — it only removes anon access and is a drop-in
-- replacement for current authenticated-role behavior, so nothing the
-- agent does today should break. Read the banner before touching
-- PHASE 2.
-- ============================================================================

BEGIN;

-- -----------------------------------------------------------------------
-- admin_actions
-- -----------------------------------------------------------------------
DROP POLICY IF EXISTS "Agent anon select admin_actions" ON public.admin_actions;
DROP POLICY IF EXISTS "Agent anon update admin_actions" ON public.admin_actions;

CREATE POLICY "Agent select admin_actions" ON public.admin_actions
  FOR SELECT TO authenticated USING (true);

CREATE POLICY "Agent update admin_actions" ON public.admin_actions
  FOR UPDATE TO authenticated USING (true) WITH CHECK (true);

-- -----------------------------------------------------------------------
-- evidence_logs
-- -----------------------------------------------------------------------
DROP POLICY IF EXISTS "Agent anon insert evidence" ON public.evidence_logs;
DROP POLICY IF EXISTS "Agent anon insert evidence_logs" ON public.evidence_logs;
DROP POLICY IF EXISTS "Agent anon update evidence" ON public.evidence_logs;
DROP POLICY IF EXISTS "Agent anon update evidence_logs" ON public.evidence_logs;

CREATE POLICY "Agent insert evidence_logs" ON public.evidence_logs
  FOR INSERT TO authenticated WITH CHECK (true);

CREATE POLICY "Agent update evidence_logs" ON public.evidence_logs
  FOR UPDATE TO authenticated USING (true) WITH CHECK (true);

-- -----------------------------------------------------------------------
-- workstations
-- -----------------------------------------------------------------------
DROP POLICY IF EXISTS "Agent anon insert workstations" ON public.workstations;
DROP POLICY IF EXISTS "Agent anon select workstations" ON public.workstations;
DROP POLICY IF EXISTS "Agent anon update workstations" ON public.workstations;
-- This one was already scoped `TO authenticated, anon` — drop and
-- re-add authenticated-only rather than trying to ALTER the role list.
DROP POLICY IF EXISTS "Agent select workstations" ON public.workstations;

CREATE POLICY "Agent select workstations" ON public.workstations
  FOR SELECT TO authenticated USING (true);

CREATE POLICY "Agent insert workstations" ON public.workstations
  FOR INSERT TO authenticated WITH CHECK (true);

CREATE POLICY "Agent update workstations" ON public.workstations
  FOR UPDATE TO authenticated USING (true) WITH CHECK (true);

-- -----------------------------------------------------------------------
-- system_settings
-- -----------------------------------------------------------------------
-- Obylon.py only ever does .table("system_settings").select("focus_mode")
-- (line ~4789) — it never writes this table. So unlike the others, the
-- UPDATE policy gets no authenticated replacement at all: only "Admins
-- manage settings" (has_role(auth.uid(),'admin')) should be able to write
-- this singleton row going forward.
DROP POLICY IF EXISTS "Agent anon select system_settings" ON public.system_settings;
DROP POLICY IF EXISTS "Agent anon update system_settings" ON public.system_settings;

CREATE POLICY "Agent select settings" ON public.system_settings
  FOR SELECT TO authenticated USING (true);

-- -----------------------------------------------------------------------
-- unauthorized_events
-- -----------------------------------------------------------------------
-- Obylon.py never calls .table("unauthorized_events").delete(...)
-- anywhere, so DELETE gets no replacement policy at all — removing it
-- (previously grantable to `anon` *and* `authenticated`) closes a
-- mass-evidence-destruction path with no legitimate downside.
DROP POLICY IF EXISTS "Agent delete unauthorized events" ON public.unauthorized_events;
DROP POLICY IF EXISTS "Agent insert unauthorized events" ON public.unauthorized_events;
DROP POLICY IF EXISTS "Agent select unauthorized events" ON public.unauthorized_events;
DROP POLICY IF EXISTS "Allow anon insert" ON public.unauthorized_events;

CREATE POLICY "Agent select unauthorized events" ON public.unauthorized_events
  FOR SELECT TO authenticated USING (true);

CREATE POLICY "Agent insert unauthorized events" ON public.unauthorized_events
  FOR INSERT TO authenticated, service_role WITH CHECK (true);

COMMIT;

-- -----------------------------------------------------------------------
-- Verification — should return zero rows.
-- -----------------------------------------------------------------------
SELECT schemaname, tablename, policyname, roles
FROM pg_policies
WHERE schemaname = 'public'
  AND 'anon' = ANY(roles)
  AND tablename IN (
    'admin_actions', 'evidence_logs', 'workstations',
    'system_settings', 'unauthorized_events'
  );


-- ============================================================================
-- PHASE 2 (OPTIONAL — VERIFY BEFORE RUNNING) — per-workstation row scoping
-- ============================================================================
-- Phase 1 requires a real Supabase Auth session but still lets ANY
-- authenticated principal (any activated workstation, or any other
-- authenticated user) read/write EVERY workstation's rows, not just its
-- own. Tightening that further to "only your own rows" needs two things
-- confirmed first, neither of which is visible in this code bundle:
--
--   1. Does the `/activate` edge function set workstations.owner_id to
--      the auth.uid() of the dedicated auth user it mints for that
--      workstation? (workstations.owner_id is uuid, nullable, and the
--      Python agent's own insert/update payload — Obylon.py ~line 4296
--      — never sets it, so this column is populated somewhere you
--      haven't shown me: almost certainly inside /activate.)
--   2. If you add owner_id scoping, Obylon.py's fallback insert branch
--      (~line 4323-4326, the `if not wid: ... client.table
--      ("workstations").insert(payload)` path, used when the row created
--      by /activate is missing/lost) will need
--      `payload["owner_id"] = <this workstation's own auth.uid()>`
--      added, or that recovery path will start failing the WITH CHECK
--      below the day it's actually exercised.
--
-- Delete the DO block immediately below only after you've checked both
-- of the above against the /activate source.

DO $$ BEGIN
  RAISE EXCEPTION 'Phase 2 not verified yet — read the comment above, then delete this DO block to proceed.';
END $$;

BEGIN;

DROP POLICY IF EXISTS "Agent select admin_actions" ON public.admin_actions;
DROP POLICY IF EXISTS "Agent update admin_actions" ON public.admin_actions;

CREATE POLICY "Agent select own admin_actions" ON public.admin_actions
  FOR SELECT TO authenticated
  USING (target_id IN (SELECT id FROM public.workstations WHERE owner_id = auth.uid()));

CREATE POLICY "Agent update own admin_actions" ON public.admin_actions
  FOR UPDATE TO authenticated
  USING (target_id IN (SELECT id FROM public.workstations WHERE owner_id = auth.uid()))
  WITH CHECK (target_id IN (SELECT id FROM public.workstations WHERE owner_id = auth.uid()));

DROP POLICY IF EXISTS "Agent select workstations" ON public.workstations;
DROP POLICY IF EXISTS "Agent update workstations" ON public.workstations;
DROP POLICY IF EXISTS "Agent insert workstations" ON public.workstations;

CREATE POLICY "Agent select own workstation" ON public.workstations
  FOR SELECT TO authenticated USING (owner_id = auth.uid());

CREATE POLICY "Agent update own workstation" ON public.workstations
  FOR UPDATE TO authenticated USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());

CREATE POLICY "Agent insert own workstation" ON public.workstations
  FOR INSERT TO authenticated WITH CHECK (owner_id = auth.uid());

DROP POLICY IF EXISTS "Agent insert evidence_logs" ON public.evidence_logs;
DROP POLICY IF EXISTS "Agent update evidence_logs" ON public.evidence_logs;

CREATE POLICY "Agent insert own evidence_logs" ON public.evidence_logs
  FOR INSERT TO authenticated
  WITH CHECK (
    alert_id IN (
      SELECT a.id FROM public.alerts a
      JOIN public.workstations w ON w.id = a.workstation_id
      WHERE w.owner_id = auth.uid()
    )
  );

CREATE POLICY "Agent update own evidence_logs" ON public.evidence_logs
  FOR UPDATE TO authenticated
  USING (
    alert_id IN (
      SELECT a.id FROM public.alerts a
      JOIN public.workstations w ON w.id = a.workstation_id
      WHERE w.owner_id = auth.uid()
    )
  )
  WITH CHECK (
    alert_id IN (
      SELECT a.id FROM public.alerts a
      JOIN public.workstations w ON w.id = a.workstation_id
      WHERE w.owner_id = auth.uid()
    )
  );

DROP POLICY IF EXISTS "Agent select unauthorized events" ON public.unauthorized_events;
DROP POLICY IF EXISTS "Agent insert unauthorized events" ON public.unauthorized_events;

CREATE POLICY "Agent select own unauthorized events" ON public.unauthorized_events
  FOR SELECT TO authenticated
  USING (workstation_id IN (SELECT id FROM public.workstations WHERE owner_id = auth.uid()));

CREATE POLICY "Agent insert own unauthorized events" ON public.unauthorized_events
  FOR INSERT TO authenticated, service_role
  WITH CHECK (workstation_id IN (SELECT id FROM public.workstations WHERE owner_id = auth.uid()));

COMMIT;
