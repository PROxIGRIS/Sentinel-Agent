# Prompt: Fix the Obylon license system (realtime, key generation, admin dashboard)

Paste everything below into Claude Code (or hand it to whichever AI is doing the work) in the repo root. It's written to be handed over as-is.

---

## Context

You're working on Nexus Sentinel / Obylon — a Windows endpoint monitoring agent for a school computer lab, with a companion web dashboard. There is currently **one Supabase project**, shared by the school's monitoring data (`workstations`, `alerts`, `evidence_logs`, `admin_actions`, `agent_configs`) and the licensing data (`licenses`, `license_nodes`). That's staying true — do not split it.

Two files matter for this task:
- The admin license dashboard — a TanStack Router route at `/admin/licenses` (file likely at `src/routes/admin/licenses.tsx`), containing `AdminLicenses`, `LicensesDashboard`, `LicenseRow`, `NodesInspector`, `IssueLicenseModal`, `BumpLimitModal`.
- `sentinel_agent.py` — the Windows agent. Relevant functions: `realtime_c2_listener(workstation_id)`, `action_loop(workstation_id)`, `license_heartbeat_loop(workstation_id)`, `controlled_shutdown(workstation_id, action_id)`.

## Hard scope boundary — read this before touching anything

**Do not build a separate control-plane database, a `schools` table, or split the web app.** That redesign exists as a future doc but has been explicitly deferred until there's a second paying school. Everything in this task stays inside the current single project. If you find yourself about to create a new Supabase project, a new deployment, or a `schools` table — stop, that's out of scope.

What you're fixing is four concrete, contained bugs. Do the smallest correct fix for each, don't restructure anything around them.

---

## Bug 1 — License status changes don't propagate in real time

**Root cause, precisely:** `handleUpdateStatus` in the dashboard does a real `licenses.update({status})` (correct, this should trigger Postgres CDC), but immediately afterward also fires:

```ts
supabase.channel(`licenses:${id}`).send({ type: 'broadcast', event: 'license_terminated', payload: {...} });
```

Nothing subscribes to a `broadcast` event named `license_terminated` anywhere in the agent. `sentinel_agent.py`'s `realtime_c2_listener` only listens for `postgres_changes` **UPDATE** on `licenses` (see the `license_channel.on_postgres_changes(...)` block, filtered to `id=eq.{LICENSE_ID}`, callback `_on_license_update`, which sets `LICENSE_INVALID_EVENT` when status is `revoked`/`suspended`/`expired`). That subscription already exists, is already wired to the correct project (there's only one project, so `SUPABASE_URL` is already right — **do not touch this function's URL handling**), and does not need new agent code.

So the actual failure is upstream of the agent. In order, check and fix:

1. **Is `licenses` in the realtime publication at all?** Run:
   ```sql
   select * from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'licenses';
   ```
   If it returns nothing:
   ```sql
   alter publication supabase_realtime add table licenses;
   ```

2. **Does the agent's authenticated session have RLS `SELECT` on its own license row?** `postgres_changes` only delivers a row to a client that could `SELECT` it under RLS — a missing policy here fails silently (the subscription connects, nothing ever arrives, which looks identical to "not real-time"). Check:
   ```sql
   select * from pg_policies where tablename = 'licenses';
   ```
   The agent authenticates with a session minted during activation (`client.set_auth(ACCESS_TOKEN)` in `realtime_c2_listener`) — find where that token is created (the `/activate` edge function, likely under `supabase/functions/activate`) and check whether it sets any claim identifying the license (e.g. `license_id` in `app_metadata`). If it does, write a policy scoped to that claim. If it doesn't, add one at token-mint time and scope the policy to it — don't leave `licenses` readable by every authenticated session as a permanent state, even though today there's only one school and one license row in the table.

3. **Delete both dead broadcast sends** — the one in `handleUpdateStatus` (`license_terminated`) and the one in `NodesInspector.handleDeactivate` (`kill_agent`, see Bug 2). They don't reach anything and they make the code look like it's doing something it isn't. `postgres_changes` on the real `UPDATE`/`INSERT` already covers both cases correctly once 1–2 are fixed.

4. **The admin's own browser tab doesn't live-update either.** There's no subscription driving the `admin_licenses` query — it only refetches when the admin's own click calls `queryClient.invalidateQueries`. Add a `postgres_changes` subscription (on `licenses` and `license_nodes`) inside `LicensesDashboard` that calls `queryClient.invalidateQueries({ queryKey: ["admin_licenses"] })` on any change, so the table reflects reality regardless of who or what changed it. Clean up the channel on unmount.

**Definition of done for this bug:** suspend a license from the dashboard, and — with a real agent running against this project — watch `LICENSE_INVALID_EVENT` fire within a couple seconds, not within the next 5-minute heartbeat cycle. Separately, open the dashboard in two tabs, change status in one, watch the other update without a manual refresh.

---

## Bug 2 — "Force Deactivate" doesn't actually deactivate anything

**Root cause:** `NodesInspector.handleDeactivate` correctly flips `license_nodes.status` to `deactivated` (seat reclaimed, that part's fine), then sends the same kind of dead broadcast as Bug 1 — `kill_agent` on `licenses:{licenseId}` — which nothing listens for. The agent has a real, working, already-hardened kill mechanism it should use instead: `admin_actions` rows with `command = "terminate"`, `target_id = <workstation_id>`, `status = "pending"`, which both `realtime_c2_listener`'s `postgres_changes` INSERT handler and the `action_loop` polling fallback pick up, with an atomic compare-and-swap claim so they can't double-fire. This is the exact mechanism every other command already uses.

**Fix:**

1. Replace the broadcast send with a real insert:
   ```ts
   await supabase.from("admin_actions").insert({
     target_id: node.id, // see step 2 — verify this is the right value
     command: "terminate",
     status: "pending",
     metadata: { reason: "license_force_deactivate" }
   });
   ```

2. **Verify before assuming:** `license_nodes.id` (the seat record) and the `workstation_id` the agent identifies itself by in `admin_actions.target_id` need to be the *same* UUID for this to target the right machine. Check whether that's already true (look at how a `license_nodes` row and a `workstations` row get created for the same physical machine — likely in the `/activate` edge function). If they're currently two different UUIDs for the same machine, that's a real bug to fix as part of this task: make the node identity minted at activation the shared primary key on both sides, so "deactivate this seat" and "kill this workstation" are unambiguously the same row.

**Definition of done:** clicking Force Deactivate on a node with a live agent running results in that specific machine's agent calling `controlled_shutdown` — confirm via the agent's logs, not just the seat flipping to `deactivated` in the dashboard.

---

## Bug 3 — The license key is fake

**Root cause, exactly as written today**, in `IssueLicenseModal.handleIssue`:

```ts
const keyStr = crypto.randomUUID().toUpperCase() + "-" + crypto.randomUUID().toUpperCase().slice(0, 8);
...
key_hash: keyStr,
```

Three stacked problems: it's not in the `OBY-xxxx-xxxx` format anyone expects; it's stored as **plaintext** in a column named `key_hash`, which isn't a hash at all — the name describes an intention the code never implements; and the modal closes on success without ever displaying the generated key to the admin, so there is no point in the current flow where you actually see the key you just made. The eye-toggle on the table row later reveals the raw stored value, but by then it's the wrong format and was never meant to be the "here's your key" moment.

**Fix (this can stay client-side — this is a `dev`/`superadmin`-gated internal tool, not a public surface, so a new edge function isn't required to do this correctly):**

1. Generate in the real format:
   ```ts
   const raw = "OBY-" + randomBase32(4) + "-" + randomBase32(4); // e.g. OBY-K7QX-9RTP
   ```
2. Hash it before it ever touches the database — Web Crypto is available in-browser:
   ```ts
   const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw));
   const keyHash = [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, "0")).join("");
   ```
3. Store `key_hash: keyHash` and add a `key_prefix` column (first 8 chars of `raw`, e.g. `OBY-K7QX`) — safe to display permanently, lets you visually identify a license without ever reconstructing the real key.
4. On success, **do not close the modal**. Show the raw key once, in a dedicated "copy this now, it won't be shown again" state, with a copy-to-clipboard button. This is the actual fix for "we can't even see the license key" — right now there's no such moment anywhere in the flow.
5. In `LicenseRow`, remove the eye-toggle and the `key_hash` display entirely — there's nothing left to reveal after step 2, by design. Show `key_prefix` instead, always visible, no toggle.
6. Wherever activation currently validates a submitted key (agent-side or edge function), it now needs to hash the incoming key with the same SHA-256 approach and match against `key_hash`, not do a direct string comparison.

**Definition of done:** issuing a license shows the real key exactly once with a working copy button; refreshing the page or reopening the row never shows it again anywhere; the stored `key_hash` value is a 64-character hex digest, not a UUID.

---

## Bug 4 — The admin dashboard itself: what "not production" actually means here

Be concrete, don't over-build. These are the real gaps, not a generic polish pass:

1. **Suspend, Revoke, and Force Deactivate all fire immediately on click, no confirmation.** These are destructive, live-impacting actions against a real deployed system — one misclick suspends a school's entire license or kills a specific machine's monitoring with zero chance to back out. Add a confirmation step (a simple `AlertDialog` is enough) before each of these three actions specifically. Reactivate and Bump Limit don't need one — they're not destructive.
2. **No record of who changed a license's status or when.** Add an `updated_at` timestamp (bump it in `handleUpdateStatus`) at minimum. If it's cheap, also capture which authenticated admin made the change. A full audit log table is out of scope for now — don't build one unless it's trivial.
3. **Fold in Bug 1's live-subscription fix here too** — a dashboard that requires a manual refresh to trust is a real "not production" symptom, not a nice-to-have.
4. Leave search, pagination, and layout as they are — they're fine at current scale (one school) and not what's actually broken.

---

## Constraints, restated

- One Supabase project, now and after this task. No `schools` table, no second project, no second web deployment.
- Every fix above is additive or corrective to existing tables/columns — no schema redesign.
- Don't touch `SUPABASE_URL` resolution, `provision_via_license`, or the heartbeat logic in `sentinel_agent.py` — none of that is broken, and Bug 1's root cause is entirely on the web/RLS/publication side, not the agent's connection handling.
- When you're done, walk through each "Definition of done" above against a real agent process, not just by reading the code back.
