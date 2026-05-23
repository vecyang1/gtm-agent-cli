---
name: gtm-agent
description: Use when managing Google Tag Manager from an agent. Provides a safe workflow around gtm-agent and @owntag/gtm-cli: doctor, inventory, snapshots, diffs, declarative dry-run plans, guarded publish, backups, and raw upstream passthrough.
---

# gtm-agent

Use this skill for Google Tag Manager operations.

## Rules

- Wheel first: use `gtm-agent`, which wraps `@owntag/gtm-cli`.
- Read-only discovery first: `gtm-agent doctor --json`, then `inventory` or `snapshot`.
- Mutations must start with dry-run `gtm-agent apply <plan> --json`.
- Real mutation requires `--execute`.
- Publishing requires `--allow-publish --confirm <container-id>`.
- Never paste or commit service-account JSON, OAuth tokens, live snapshots, or backups.
- Prefer a dedicated GTM workspace for changes.
- Use `gtm-agent raw -- ...` only when the declarative safety layer lacks a needed upstream command.
- Mutating raw commands require `--allow-mutation`; raw publish requires `--allow-publish --confirm <container-id>`.

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
