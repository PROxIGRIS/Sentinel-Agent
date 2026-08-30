-- Verified bug #1 (part 2 of 2): ObylonCore.exe's fast-lane path posts
-- directly to POST {SUPABASE_URL}/rest/v1/fastlane_events as a latency
-- shortcut (see try_direct_report() in rust/core/src/main.rs) — ahead of
-- Python's own slower, durable path through the vault/events queue. That
-- table never existed, so every direct-report POST was rejected with a
-- 404/PGRST205 ("relation does not exist"). This was harmless (Core logs
-- the rejection and the violation still reaches `alerts` via Python's
-- record_fastlane_alert()), but it meant the fast path never worked and
-- every fast-lane violation showed up on the dashboard only as fast as
-- Python's normal polling/event-drain cadence.
--
-- Run this against your Supabase project (SQL Editor, or `supabase db
-- push` if you keep migrations under source control) to close that gap.
--
-- Columns match the exact JSON body in try_direct_report():
--   { "type", "kind", "detail", "timestamp" (unix seconds),
--     "screenshot_path", "action_taken", "workstation_id" }

create table if not exists public.fastlane_events (
    id uuid primary key default gen_random_uuid(),
    workstation_id text not null,
    type text not null,
    kind text not null,
    detail text,
    action_taken text,
    screenshot_path text,
    "timestamp" bigint not null,
    received_at timestamptz not null default now()
);

create index if not exists fastlane_events_workstation_id_idx
    on public.fastlane_events (workstation_id);

create index if not exists fastlane_events_received_at_idx
    on public.fastlane_events (received_at desc);

alter table public.fastlane_events enable row level security;

-- Core authenticates this POST with the public anon key (the same one
-- already compiled into obylonc and shipped in identity_beacon.json —
-- see the comment above IdentityBeacon in main.rs for why that's
-- intentional and not a secret leak). The anon role therefore needs
-- insert rights; it should NOT get select/update/delete, so a compromised
-- or spoofed client can only add rows, never read or tamper with
-- existing ones.
create policy "fastlane_events_insert_anon"
    on public.fastlane_events
    for insert
    to anon
    with check (true);

-- Dashboard/admin reads should go through your normal authenticated
-- role — adjust this to match however `alerts`/`unauthorized_events`
-- already scope reads to a school's own admins in your schema.
create policy "fastlane_events_select_authenticated"
    on public.fastlane_events
    for select
    to authenticated
    using (true);
