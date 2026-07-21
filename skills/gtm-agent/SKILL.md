---
name: gtm-agent
description: Use when managing Google Tag Manager from an agent. Provides a safe workflow around gtm-agent and @owntag/gtm-cli: doctor, inventory, snapshots, diffs, declarative dry-run plans, guarded publish, backups, and raw upstream passthrough.
---

# gtm-agent

Use this skill for Google Tag Manager operations.

## Rules

- Wheel first: use `gtm-agent`, which wraps `@owntag/gtm-cli`.
- If `gtm-agent doctor --json` says `gtm` is missing, install the pinned upstream wheel with `gtm-agent install --execute` before diagnosing auth or config.
- Read-only discovery first: `gtm-agent doctor --json`, then `inventory` or `snapshot`.
- Mutations must start with dry-run `gtm-agent apply <plan> --json`.
- Real mutation requires `--execute`.
- Publishing requires `--allow-publish --confirm <container-id>`.
- Never paste or commit service-account JSON, OAuth tokens, live snapshots, or backups.
- A site must already load the GTM container snippet, or the CMS/app must support adding it, before CLI-created tags can fire on that site.
- Prefer a dedicated GTM workspace for changes.
- Use `gtm-agent raw -- ...` only when the declarative safety layer lacks a needed upstream command.
- Mutating raw commands require `--allow-mutation`; raw publish requires `--allow-publish --confirm <container-id>`.
- Declarative trigger plans support `config`; tag plans support either `firingTriggerId` or `firingTriggerIds`, using quoted positive-decimal IDs only.
- When a tag needs a newly created trigger, use two plans: create the trigger, inventory the workspace to obtain its assigned ID, then create the tag. Before each create, inspect inventory for an exact-name match.

## Enough Or Extend

Use the existing toolchain first. `gtm-agent` is enough for normal agent-safe GTM work: doctor, inventory, snapshots, diffs, backups, basic declarative tag/trigger/variable/version plans, and guarded publish.

Drop to `gtm-agent raw -- ...` when the upstream `@owntag/gtm-cli` already has a command that the declarative plan layer does not expose. Add code to `gtm-agent` only when a repeated workflow needs safer declarative plans, stronger validation, idempotent upsert behavior, or a reusable site-specific guardrail.

## Standard Workflow

```bash
gtm-agent doctor --json
gtm-agent snapshot --account-id <account> --container-id <container> --workspace-id <workspace> --out snapshots/before.json
gtm-agent plan validate plan.yaml --json
gtm-agent apply plan.yaml --json
gtm-agent apply plan.yaml --execute --json
gtm-agent snapshot --account-id <account> --container-id <container> --workspace-id <workspace> --out snapshots/after.json
gtm-agent diff snapshots/before.json snapshots/after.json --json
```

Publish only after review:

```bash
gtm-agent apply publish.yaml --execute --allow-publish --confirm <container-id> --json
```

## Verification

From the repo:

```bash
go test ./...
go vet ./...
./scripts/e2e-fake-gtm.sh
```

## References

- [Google Ads API Integration & Tooling Reference](file:///Users/vecsatfoxmailcom/.gemini/config/skills/gtm-agent/references/google_ads_api_integration.md) (Developer Token requirements and comparison of Composio vs. google-ads-open-cli)
