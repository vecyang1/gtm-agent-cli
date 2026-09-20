---
name: gtm-agent
description: >
  Use when managing Google Tag Manager from an agent. Provides a safe workflow
  around gtm-agent and @owntag/gtm-cli: doctor, inventory, snapshots, diffs,
  declarative dry-run plans, guarded publish, backups, and raw upstream passthrough.
---

# gtm-agent

## Skill Metadata

- **Origin:** `local`
- **Source:** https://github.com/vecyang1/gtm-agent-cli
- **Author:** Vec; Maintainer: Vec + Codex
- **Created:** 2026-07-21
- **Updated:** 2026-08-10
- **Review status:** `reviewed`

Use this skill for Google Tag Manager operations.

## Rules

- Wheel first: use `gtm-agent`, which wraps `@owntag/gtm-cli`.
- If `gtm-agent doctor --json` says `gtm` is missing, install the pinned upstream wheel with `gtm-agent install --execute` before diagnosing auth or config.
- After installation, rerun `doctor` and then one read-only `inventory` or upstream `tags list` smoke check. A single immediate upstream-process failure is not proof of an auth or container problem: retry that same read-only command once, and diagnose only if it persists. Never change GTM resources to work around it.
- Read-only discovery first: `gtm-agent doctor --json`, then `inventory` or `snapshot`.
- Before a GTM handoff, account migration, or material change, run `python3 skills/gtm-agent/scripts/check_account_admins.py --account-id <account-id>`. Treat `ready` as verified only when the script finds at least two distinct account-level administrators; container-level `publish` access does not qualify. The script emits counts only, never administrator identities.
- A `needs_admin` result exits `2`: ask the account owner to name an independent backup administrator before any access mutation. An `unknown` result exits `3`: request or restore a credential with the `tagmanager.manage.users` scope and rerun; never infer administrative recovery from container access or continue as if the account is recoverable.
- A missing `gtm-agent` wrapper subcommand is not evidence that the GTM API is unavailable. For account user management, first inspect the installed upstream wheel with `gtm user-permissions --help`; this is the explicit upstream route when the declarative safety layer has no user-permission operation. With the owner's exact account and email, create an account administrator through `gtm user-permissions create --account-id <account-id> --email <email> --account-access admin --output json --quiet`.
- The `accounts.user_permissions.create` response sends a **pending invitation**. Its creation receipt is not proof of active access: require a GTM UI accepted status (or invitee authenticated access) and the separate two-admin result from `check_account_admins.py` before treating redundancy as restored or publishing. The upstream `create` command can emit a human-readable success receipt even when `--output json` is requested, so do not pipe that mutation directly to `jq` or retry because of a local parse failure. The active-user `user-permissions list` may omit pending invitations; verify the pending state in the GTM UI before a new create attempt. Account admin does not by itself grant `publish` on an existing container; request container access only when the owner explicitly needs it. If the owner withdraws a pending invitation, delete that exact permission ID and rerun the list/count readback.
- Mutations must start with dry-run `gtm-agent apply <plan> --json`.
- Real mutation requires `--execute`.
- Publishing requires `--allow-publish --confirm <container-id>`.
- When `analytics-tracking` has approved a growth-first measurement plan, treat
  its ordinary non-PII tags, triggers, variables, and parameters as one reviewed
  change set. Do not reopen approved measurement-policy or per-resource
  questions merely because the plan creates several GTM resources.
- GTM mutation gates are implementation safety controls, not visitor-consent
  prompts. Keep dry-run, exact-target, execute, publish, backup, and rollback
  gates even when the operator has standing authority for the measurement plan.
- Never paste or commit service-account JSON, OAuth tokens, live snapshots, or backups.
- A site must already load the GTM container snippet, or the CMS/app must support adding it, before CLI-created tags can fire on that site.
- Prefer a dedicated GTM workspace for changes.
- Use `gtm-agent raw -- ...` only when the declarative safety layer lacks a needed upstream command.
- Mutating raw commands require `--allow-mutation`; raw publish requires `--allow-publish --confirm <container-id>`.
- Declarative trigger plans support `config`; tag plans support either `firingTriggerId` / `firingTriggerIds` or `blockingTriggerId` / `blockingTriggerIds`, using quoted positive-decimal IDs only. For promotional widgets and third-party trackers, enforce blocking triggers on conversion-critical paths (`cart`, `checkout`, `thank-you`, `order-received`, `receipt`, `customer-dashboard`) to protect conversion rates and third-party quotas.
- When a tag needs a newly created trigger, use two plans: create the trigger, inventory the workspace to obtain its assigned ID, then create the tag. Before each create, inspect inventory for an exact-name match.

## Enough Or Extend

Use the existing toolchain first. `gtm-agent` is enough for normal agent-safe GTM work: doctor, inventory, snapshots, diffs, backups, basic declarative tag/trigger/variable/version plans, and guarded publish.

Drop to `gtm-agent raw -- ...` when the upstream `@owntag/gtm-cli` already has a command that the declarative plan layer does not expose. Add code to `gtm-agent` only when a repeated workflow needs safer declarative plans, stronger validation, idempotent upsert behavior, or a reusable site-specific guardrail.

## Measurement And Funnel Boundaries

- Use `analytics-tracking` first when the business decision, event taxonomy,
  conversion authority, parameter allowlist, or reporting receipt is not yet
  explicit. This skill executes the reviewed GTM change; it does not redefine
  measurement policy, ask the operator to approve ordinary signals again, or
  turn a provider mutation gate into a generic consent discussion.
- Use `google-analytics-ops` for read-only GA4 property discovery or reporting.
  Use `google-search-console-ops` for search visibility, indexed-version,
  sitemap, or Search Analytics evidence. A GTM change does not authorize a
  GA4 or Search Console configuration change.
- Use `funnel-planner` when the conversion path, offer, page journey, or
  customer-facing CTA is still undecided. Keep cross-page decisions in the
  canonical funnel owner (usually `docs/funnel.md`), not in GTM resources or
  this skill; honor a linked hub when `PROJECT_LINKS.md` delegates that owner.
- After a GTM change, return the published version and relevant
  tag/trigger/variable readback to `analytics-tracking`, including the exact
  event name, firing trigger conditions, and parameter-to-variable mapping, so
  it can close or leave open the measurement reporting receipt. Use an explicit
  allowlist for parameter mappings, never a wholesale dataLayer pass-through;
  record excluded identifier, raw URL, and raw country sources when they
  coexist in the application event.
- Before proposing a GTM Custom HTML consent command, inspect the active CMS or
  app GTM integration for native Consent Mode v2 support. When that maintained
  integration can inject the approved default before its sole container loader,
  use it as the consent owner rather than rebuilding the lifecycle in GTM.
  Readback its saved configuration and public command-before-loader order, then
  return that external receipt to `analytics-tracking`. This is a prerequisite
  outside this CLI's workspace mutation authority; never add a parallel GTM
  consent tag merely because the CLI cannot manage the CMS setting.
- For an operator-approved direct-collection branch, the CMS-owned default is
  `granted` for the relevant Consent Mode categories: normal analytics,
  attribution, funnel, and conversion collection begins immediately without a
  visitor banner. “External precondition” means this CLI must not duplicate the
  WordPress/app injection; it does **not** mean pause ordinary collection.

## Paid-Media And Retargeting Preflight

Apply this preflight separately to **every brand and advertising destination**
before creating or changing a Google Ads tag, Conversion Linker, audience
bridge, or conversion-forwarding tag. An existing GTM container, GA4 Google
tag, Meta Pixel, or another brand's Ads account is never evidence that this
brand has the required Google Ads destination.

Keep these routes distinct:

- **GA4 audience export:** an `AW-` ID is not required merely to define a GA4
  audience. To use that audience for Google Ads retargeting, however, the exact
  GA4 property must be linked to a verified active Google Ads account and the
  selected link must permit personalised advertising. Audience membership and
  the Google Ads list must be read back before calling retargeting ready.
- **Direct Google Ads conversion tag:** requires the account-specific Google
  Ads Conversion ID (`AW-...`) and the conversion-action-specific label. Bind
  it only to the reviewed authoritative outcome. For a sale, send the stable
  `transaction_id`, real value, and currency through explicit variables so Ads
  can deduplicate; never substitute a button click, checkout start, or form
  dispatch. When this direct route is selected, make Conversion Linker
  presence/configuration an explicit Google Ads attribution gate. Do not add
  Conversion Linker to a GA4-only ecommerce bridge. No Analytics destination
  is a prerequisite for this direct route.
- **GA4 key-event import:** is a separate Google Ads/GA4 Admin route. It needs
  the exact linked property and Ads account, an enabled key event, and a
  receipt that the business outcome reaches that property. It is not a GTM
  conversion tag and must not be paired with a duplicate direct Ads conversion
  unless the reviewed reporting design names the deduplication and primary
  conversion owner.

Before any paid-media GTM or linked GA4/Ads Admin mutation, record in the
canonical measurement or funnel owner the literal brand, verified Ads account,
chosen route, primary conversion authority, safe campaign/click parameters,
and expected readback. Add only the evidence belonging to the selected route:
the exact GA4 property/destination and audience include/exclude rules for GA4
audience export; the Ads Conversion ID, label, and Conversion Linker state for
a direct Ads tag; or the exact linked GA4 property and key-event receipt for a
GA4 import. A missing verified `AW-` ID blocks a direct Google Ads conversion
tag; it does not justify inventing an ID or block ordinary non-Ads GA4
collection. GA4 Admin links, audience export settings, personalised-advertising
settings, and conversion imports are not GTM mutations: route them to their
named Google Ads/GA4 configuration owner, then return the resulting receipt to
`analytics-tracking`.

## SureCart GA4 Ecommerce Forwarding Profile

Use this profile when a WordPress + SureCart site deliberately uses the web
GTM container as its only GA4 owner. SureCart can emit native recommended
commerce events into `dataLayer`, but it does not configure the site's GTM
resources; without this profile those events remain local dataLayer entries.

Before mutation, read the existing Google tag destination and inspect the
current SureCart/app source event list. Do not infer the list from a SureCart
marketing claim or add a parallel standalone `gtag.js`. A common approved
allowlist is:

```text
view_item_list, search, view_item, add_to_cart, remove_from_cart, view_cart,
begin_checkout, add_payment_info, add_shipping_info, purchase
```

Create one versioned, narrowly scoped pair in the existing GTM web container:

- a Custom Event trigger whose regex matches only the approved native event
  names; and
- a GA4 Event tag with `eventName = {{Event}}`, configured to forward the
  built-in `ecommerce` object from `dataLayer` to the existing intended GA4
  destination.

**SureCart GA4 ecommerce is a required deployment gate** for every new
WordPress + SureCart site where this GTM container owns GA4, and an audit gate
for existing sites before checkout or paid-traffic work. Do not label the
site's ecommerce measurement ready until the pair is present in the published
container and its receipt state is recorded. Use `not_applicable` only when
the reviewed GA4 route is deliberately direct, this container does not own
GA4, and a direct property receipt exists; never use it to create a duplicate
direct-plus-GTM route.

Built-in ecommerce forwarding is limited to the reviewed `ecommerce` object;
it is not permission to pass arbitrary root-level dataLayer values to GA4.
Do not add Conversion Linker for this purpose: it addresses Google Ads click
attribution, not event forwarding. Do not rely on Enhanced Measurement: it
does not consume custom ecommerce events.

Dry-run, snapshot, diff, publish, and preserve rollback as normal. Then return
the container version, trigger regex, tag event-name mapping, ecommerce-source
setting, and GA4 destination to `analytics-tracking`. A GTM preview that shows
the tag firing proves only the transport configuration; leave the `purchase`
receipt open until a safe post-release paid order is reconciled in the exact
GA4 property after the reporting-delay grace period. Never expect a later
version to backfill a paid order that occurred before publication.

## First-Party And Server-Side Execution Boundary

Implement the architecture selected by `analytics-tracking`; do not collapse
these distinct resources into a vague "server-side GTM" claim:

- **Cloudflare Google Tag Gateway** is a zone-wide, first-party Google
  script/request gateway that can be initiated from Google/Cloudflare settings.
  It is not a programmable GTM server container, and ordinary tag/trigger plans
  in this CLI do not prove that Cloudflare gateway state.
- **server GTM** is a separate Tag Manager container plus a tagging server.
  Stape is the preferred managed-hosting wheel when selected; Google Cloud is
  the direct hosting route. A Cloudflare Worker/CDN path may provide
  same-origin forwarding, but Cloudflare routing remains outside this CLI's GTM
  workspace mutation authority.
- **Cloudflare Zaraz** is a separate edge tag runtime. Do not silently run it as
  a second control plane beside web GTM/server GTM.

Before applying a server GTM plan, inventory the exact web and server container
IDs separately and preserve the client/server handoff contract: hydrated
consent state, safe attribution parameters, backend-authoritative outcomes, and
stable `event_id` or `transaction_id` deduplication. Server delivery must not
reinterpret denied consent as granted, send raw PII through GA4/dataLayer, or
promote HTTP acceptance into a conversion.

Return architecture-specific receipts: the web container version; the server
container version only for server GTM; the tagging-server/gateway owner and
endpoint class; destination observation; consent-state proof; dedupe proof only
for dual-delivery routes; and the rollback owner. For Google Tag Gateway-only
delivery, record server-container and browser/server-dedupe receipts as
`not_applicable`, with first-party request-path evidence. Use the appropriate
Cloudflare/Stape/Google owner for gateway, hosting, DNS, or same-origin routing;
`gtm-agent` continues to own only the GTM workspace resources it can read back.

An application/edge-owned regional policy or consent prelude is a GTM
precondition, not a GTM receipt. Keep its country input outside the dataLayer
and GTM mappings. Require the owning application's deploy/version evidence plus
public no-store/cache proof and fail-safe branch evidence separately from any
GTM inventory or publish record.

## Standard Workflow

```bash
gtm-agent doctor --json
python3 skills/gtm-agent/scripts/check_account_admins.py --account-id <account>
gtm-agent snapshot --account-id <account> --container-id <container> --workspace-id <workspace> --out snapshots/before.json
gtm-agent plan validate plan.yaml --json
gtm-agent apply plan.yaml --json
gtm-agent apply plan.yaml --execute --json
gtm-agent snapshot --account-id <account> --container-id <container> --workspace-id <workspace> --out snapshots/after.json
gtm-agent diff snapshots/before.json snapshots/after.json --json
```

That `snapshot`/`diff` pair describes a **pre-publish workspace edit only**. Before
creating a version, confirm the workspace carries only your change, so a publish
cannot sweep another session's unfinished edit live:

```bash
gtm-agent raw -- workspaces status --account-id <account> --container-id <container> --workspace-id <workspace> --output json
```

Publish only after review:

```bash
gtm-agent apply publish.yaml --execute --allow-publish --confirm <container-id> --json
```

### Verify A Publish By Comparing Versions, Not Workspaces

Publishing consumes the workspace: GTM deletes the workspace you published from
and creates a fresh Default Workspace with a new ID. The `snapshot`/`diff` pair
above therefore describes a **pre-publish workspace edit only** — it cannot
describe a publish, and the workspace it named is gone once the publish lands.

`gtm-agent` enforces this rather than leaving it to be read: `inventory` and
`snapshot` refuse a workspace the container no longer lists, instead of
returning the empty result the upstream API gives for a dead workspace ID.
Seeing that refusal after a publish means the publish worked; nothing was lost.

To prove a publish was safe, compare the previously live version with the new one:

```bash
gtm-agent raw -- versions get --account-id <account> --container-id <container> --version-id <previous-live> --output json
gtm-agent raw -- versions get --account-id <account> --container-id <container> --version-id <new-live> --output json
```

A correct single-resource change shows exactly that resource added and nothing
removed. Then confirm the deployed payload by fetching
`https://www.googletagmanager.com/gtm.js?id=<public-id>`: every pre-existing
destination ID must still appear, and the new marker must appear exactly once.
GTM compiles Custom HTML through its minifier, so match on a stable literal such
as an app or measurement ID, never on the source formatting you submitted.

A workspace can also be **older than the live container**: it keeps the base it
was created from, so `tags list --workspace-id <workspace>` may legitimately show
fewer resources than the live version holds. Observed 2026-08-10: a workspace was
missing a tag the live version already had, while the version created from that
workspace still came out correct, because GTM versions the live container plus
the workspace delta rather than the workspace's stale view. Read the live version
(or `workspaces sync`) before treating any workspace listing as the container's
current state or as a duplicate check.

## Verification

From the repo:

```bash
python3 skills/gtm-agent/tests/test_contract.py
python3 skills/gtm-agent/tests/test_account_admin_check.py
go test ./...
go vet ./...
./scripts/e2e-fake-gtm.sh
```

## References

- [Google Ads API Integration & Tooling Reference](references/google_ads_api_integration.md) (Developer Token requirements and comparison of Composio vs. google-ads-open-cli)
