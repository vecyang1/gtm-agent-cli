# Changelog

## 0.2.0 - 2026-07-21

- Clarified GTM skill readiness checks, site-snippet prerequisite, and when to use raw upstream commands versus extending `gtm-agent`.
- Added validated `createTrigger.config` compilation and `createTag` trigger bindings through singular `firingTriggerId` or plural `firingTriggerIds`, while preserving dry-run and publish gates.

## 0.1.0 - 2026-05-24

- Added `gtm-agent` CLI with doctor, install, inventory, snapshot, diff, plan, apply, backup, raw passthrough, and guide commands.
- Added dry-run-first declarative plans with double-gated publish actions.
- Added fake-upstream E2E verification and included agent skill.
