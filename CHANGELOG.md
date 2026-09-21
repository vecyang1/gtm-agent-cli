# Changelog

## Unreleased

- Fixed Conversion Linker cross-domain parameter hygiene in Container `GTM-5G7SFL9R` (Version 25): pruned self-referencing root domain `worldinspirelab.com` and subdomains from `linkerDomains`, restricting cross-domain tracking strictly to verified external destinations (`zylvie.com, buildfast.fyi`) to eliminate unwanted `_gl` URL decorations.
- Sanitized local machine absolute paths in README and SKILL documentation; added private file rules to .gitignore.

- **`inventory` and `snapshot` now refuse a workspace the container no longer
  lists, instead of silently returning an empty one.** Publishing consumes the
  workspace it was published from — GTM deletes it and creates a fresh Default
  Workspace under a new ID — and the upstream list commands answer a dead
  workspace ID with `[]` and exit 0. That made the Standard Workflow's own
  post-publish `snapshot`/`diff` pair report every real tag and built-in variable
  as `removed`: a false mass-deletion report inviting a destructive "restore".
  The check reuses the workspaces list the inventory already fetches, so it costs
  no extra API call, runs before the five per-workspace calls, and never leaves a
  misleading zero-resource file behind. Its error carries the remedy (compare
  published versions). Fails open when the container lists no workspaces at all,
  which is an unreadable container rather than a missing workspace.
- Documented the positive route that an error message cannot carry: verify a
  publish by comparing the previously live and new container versions plus the
  deployed `gtm.js` payload, matching a stable literal because GTM minifies
  Custom HTML. Recorded that a workspace can be *older* than the live container,
  so a workspace listing is not the container's current state. Added the
  pre-version `workspaces status` step so a publish cannot sweep another
  session's unfinished edit live.
- Added a skill-local, read-only GTM account-administrator redundancy check. It
  proves at least two distinct account administrators without printing their
  identities, rejects container-level publish access as a substitute, and
  reports a separate unknown state when user-permission read access is absent.
- Added a per-brand paid-media and retargeting preflight that distinguishes
  GA4-audience export, direct Google Ads conversion tags, and GA4 key-event
  imports. It requires exact account/destination/outcome evidence and retains
  the configuration-owner boundary; documentation and contract test only.
- Documented the post-install read-only smoke check and one-retry rule so a
  transient upstream process failure is not misdiagnosed as a GTM auth/container
  incident or worked around with an unsafe mutation.
- Made reviewed growth-first measurement plans executable as one GTM change set
  without reopening per-resource approval questions, while retaining every
  dry-run, publish, backup, and rollback guard.
- Distinguished Cloudflare Google Tag Gateway, Stape/Google Cloud server GTM,
  and Cloudflare Zaraz ownership; added architecture-specific receipts,
  consent-state proof, and browser/server deduplication only for dual-delivery
  routes.
- Added the SureCart GA4 ecommerce forwarding profile: a narrowly allowlisted
  Custom Event trigger plus GA4 Event tag when GTM is the sole GA4 owner, with
  receipt/reconciliation and no-backfill rules. It is now the required
  deployment/audit gate for every WordPress + SureCart site in that ownership
  mode. Documentation only; no CLI behavior changed.

## 0.2.0 - 2026-07-21

- Clarified GTM skill readiness checks, site-snippet prerequisite, and when to use raw upstream commands versus extending `gtm-agent`.
- Added validated `createTrigger.config` compilation and `createTag` trigger bindings through singular `firingTriggerId` or plural `firingTriggerIds`, while preserving dry-run and publish gates.

## 0.1.0 - 2026-05-24

- Added `gtm-agent` CLI with doctor, install, inventory, snapshot, diff, plan, apply, backup, raw passthrough, and guide commands.
- Added dry-run-first declarative plans with double-gated publish actions.
- Added fake-upstream E2E verification and included agent skill.
