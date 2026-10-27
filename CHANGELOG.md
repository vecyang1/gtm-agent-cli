# Changelog

## [1.3.0] - 2026-10-27

### Added
- **Web Supply Chain & Third-Party Script Security Engine (`portfolio_gtm_audit.py`)**:
  - `extract_domains_from_html()`: parses Custom HTML tags for `<script src="...">`, inline string URLs, and protocol-relative endpoints.
  - `HIJACKED_OR_DEPRECATED_DOMAINS` Watchlist: gatekeeper blocking abandoned or hijacked vendor CDNs (e.g. `cdn.taku-app.com`, `taku-app.com`).
  - `APPROVED_VENDOR_DOMAINS` Catalog: whitelist verifying trusted tracking, analytics, and CRM vendors across Google, Meta, Clarity, Claspo, Taku, Encharge, NetroSEO, Leadsourcing, VisitorTracking, CX Genie, Chaport, Growify, and Nuwtonic.
  - **Tag Pause State Visibility**: audits and reports whether third-party tags are actively firing (`▶️ ACTIVE`) or safely paused/dormant (`⏸️ PAUSED`), honoring the invariant that deprecated scripts should be paused in GTM rather than duplicated to CMS drafts.
  - **Single Source of Truth (SSOT) Invariant**: documented and enforced rule that all third-party scripts reside in GTM as independent tags, eliminating double-firing hazards from WPCode/Divi drafts.
  - **Markdown Report & JSON Matrix Enhancement**: generates the `## Web Supply Chain & External Script Security Audit` matrix across all 6 portfolio brands in `reports/runs/gtm-portfolio-audit.md`.
- **Unit Test Coverage (`tests/test_supply_chain_audit.py`)**:
  - Added 5 new unit tests (33/33 total passing in test suite) validating domain extraction from `<script src="...">`, inline DOM injection strings, protocol-relative URLs, hijacked domain flagging, and partner whitelist categorization.

## Unreleased

- **Added Automated Tracking Self-Healing & Auto-Build Engine (`gtm_autobuild.py`)**:
  - Implemented multi-resource automated plan synthesis covering GA4 Google Tags (`googtag` with nested parameter schema invariant), Conversion Linker (`gclidw`), E-Commerce event forwarders (`gaawe` bound to Custom Event regex trigger with `getEcommerceDataFrom: dataLayer` and `measurementIdOverride`), Lead generation forwarders (`generate_lead` with `measurementIdOverride`), Meta Pixel base code (`html` with fbq integration), Google Ads base Google Tag, and conversion-critical blocking triggers (`(cart|checkout|order-received|thank-you|receipt)`).
  - Built comprehensive safety gates: uninitialized container mutation refusal (`--allow-legacy-init`) with explicit API error discrimination, idempotency checks against existing live/workspace tags and triggers (normalizing customEvent filters and reusing existing trigger IDs), workspace isolation (`AutoFix-*` or verified clean workspace), automated pre-mutation live container rollback backup (`backups/{date}-{public_id}-v{version}-before-autofix.json`), and double-gated publishing (`--allow-publish --confirm <container-id>`).
  - Hardened execution resilience: strict error checking on every mutation step (aborts immediately before creating container version if any tag/trigger/variable creation fails), robust publish response verification (rejects false "published" statuses on API error), and zero-action skip guard.
  - Added transient retry with backoff in `portfolio_gtm_audit.py` to protect against CLI/Deno process socket timeouts during multi-container sequential sweeps.
  - Added unified Python CLI entrypoint `skills/gtm-agent/scripts/gtm_agent.py` (`python3 scripts/gtm_agent.py --help`, `audit`, `autobuild`, `raw`).
  - Integrated `--auto-build` / `--auto-fix` into `portfolio_gtm_audit.py` supporting dry-run inspection, live execution, post-publish verification, and an automated Self-Healing Ledger in markdown reports.
  - Automatically resolved and deployed BelovedPals (`GTM-MSW8GJXP`) GA4 Google Tag (`G-1L9JEX0TBN`) to live version 11, elevating portfolio tracking health to **100% (6/6 brands PASS)**.
  - Added test suite `skills/gtm-agent/tests/test_autobuild.py` covering plan generation, schema invariants, idempotency deduplication, safety gates, rollback backups, dry-run mode, mutation error halts, and publish confirmation.
- Added `portfolio_gtm_audit.py` with multi-brand tracking matrix, automated live container auditing for GA4, Google Ads, Meta Pixel, Conversion Linker, Ecommerce, and Leads, with automated state and receipt writeback for `CAD-20261019-portfolio-gtm-ga4-weekly-audit`.
- Fixed Conversion Linker cross-domain parameter hygiene in Container `GTM-5G7SFL9R` (Version 25): pruned self-referencing root domain `example.com` and subdomains from `linkerDomains`, restricting cross-domain tracking strictly to verified external destinations (`zylvie.com, buildfast.fyi`) to eliminate unwanted `_gl` URL decorations.
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

## [2026-10-25] - 2026-10-25

### Automated Cadence
- Executed weekly Portfolio GTM & GA4 Tracking & Conversion Audit (`CAD-20261019-portfolio-gtm-ga4-weekly-audit`).
- Verified 6/6 portfolio containers at 100% health with live HTTP snippet detection across all brands.
- Recorded live version advance on Global Growth Co (`GTM-MKP5HFBS` v9 -> v10) with zero tracking drift.

## [2026-10-22] - 2026-10-22

### Documentation
- Document GA4 tag schema invariants and choosing the rung analysis (`0d98ccb`)
- Record 100% compliant portfolio audit ledger and run receipts (`494b115`)

## [2026-10-19] - 2026-10-19

### Maintenance
- Enforce GitHub Actions quota hygiene (ubuntu-latest default, concurrency, paths-ignore) (`1d32485`)

## [2026-10-04] - 2026-10-04

### Maintenance
- Ignore .pytest_cache in gitignore (`8ecf05b`)

## [2026-10-02] - 2026-10-02

### Added
- Deployed Growify Purchase Conversion Tag on SureCart Purchase Event (Container `GTM-P8VTXJ65`, Version 20) for `example.com`:
  - Tag Name: `Growify - Purchase Conversion` (Tag ID `38`, Custom HTML, firing on `CE - SureCart Purchase` / Trigger `22`, `oncePerEvent`).
  - Extracted orderId, tax, shipping, and products array from SureCart dataLayer with robust fallback handling.
  - Verified live runtime execution: dispatched gzipped beacon to `https://us-central1-growify-346505.cloudfunctions.net/grpV2` with `ev: "purchase"`, order details, and attribution bridges (`gaid`, `fbid`, `gr_user_id`).
- Deployed Growify PowerPixel base code on All Pages (Container `GTM-P8VTXJ65`, Version 19) for `example.com`:
  - Tag Name: `Growify Pixel` (Tag ID `37`, Custom HTML, priority `99`, `oncePerLoad`, support `document.write`).
  - Website ID: `89a6a3fc1c52480a6e33eae72dfafcb8:12d6a1e6361940df362b8974c9f8a0d35ba465c9b6e91edb53ebc9eef886c5eb3580f6dafc57d634714f5805267ce659`.
  - Verified live runtime execution: `pixel.min.js` 200 OK, event dispatched to `https://us-central1-growify-346505.cloudfunctions.net/grpV2`, and `__grp_grp_uid` cookie persisted on `example.com`.

## [2026-09-28] - 2026-09-28

### Documentation
- Document Google Ads base Google Tag requirement on All Pages (`ff4ddc7`)

## [2026-09-22] - 2026-09-22

### Documentation
- Add Conversion Linker and cross-domain linker hygiene section (`214b051`)
- Add upstream raw versions publish explicit long-form flags guidance (`-c` ambiguity resolution and unattended `--confirm` requirement) and Meta Pixel & CAPI client/server purchase deduplication profile (`{ eventID: {{DLV - ecommerce.transaction_id}} }`).

## 0.2.0 - 2026-07-21

- Clarified GTM skill readiness checks, site-snippet prerequisite, and when to use raw upstream commands versus extending `gtm-agent`.
- Added validated `createTrigger.config` compilation and `createTag` trigger bindings through singular `firingTriggerId` or plural `firingTriggerIds`, while preserving dry-run and publish gates.

## 0.1.0 - 2026-05-24

- Added `gtm-agent` CLI with doctor, install, inventory, snapshot, diff, plan, apply, backup, raw passthrough, and guide commands.
- Added dry-run-first declarative plans with double-gated publish actions.
- Added fake-upstream E2E verification and included agent skill.
