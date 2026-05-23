# GTM Agent CLI

`gtm-agent` is an agent-safe Google Tag Manager control-plane CLI built on top of the maintained [`@owntag/gtm-cli`](https://github.com/owntag/gtm-cli) wheel and Google Tag Manager API v2.

It does not try to replace the upstream GTM CLI. It adds the missing operational layer agents need before changing marketing infrastructure: doctor checks, snapshots, stable diffs, declarative plans, dry-run-first execution, publish gates, backups, raw passthrough, and an included agent skill.

## Install

Build locally:

```bash
go build -o ./gtm-agent ./cmd/gtm-agent
```

Install the upstream GTM wheel:

```bash
./gtm-agent install
./gtm-agent install --execute
```

Or install directly:

```bash
npm install -g @owntag/gtm-cli@1.5.8
```

Authenticate with the upstream wheel:

```bash
gtm auth login
```

For automation, prefer a service account:

```bash
gtm auth login --service-account /path/to/service-account-key.json
```

Grant the service account access inside Google Tag Manager before using it.

## Commands

```bash
gtm-agent doctor --json
gtm-agent --version
gtm-agent inventory --account-id 123 --container-id 456 --workspace-id 7 --json
gtm-agent snapshot --account-id 123 --container-id 456 --workspace-id 7 --out snapshots/before.json
gtm-agent diff snapshots/before.json snapshots/after.json --json
gtm-agent plan template --out plan.yaml --json
gtm-agent plan validate plan.yaml --json
gtm-agent apply plan.yaml --json
gtm-agent apply plan.yaml --execute --json
gtm-agent backup --account-id 123 --container-id 456 --out backups/live.json --json
gtm-agent raw -- tags list --account-id 123 --container-id 456 --workspace-id 7 --output json
gtm-agent guide
```

## Safety Model

- `apply` is dry-run by default.
- No plan mutation executes unless `--execute` is present.
- Publishing requires both `--allow-publish` and `--confirm <container-id>`.
- `raw -- ...` is intentionally available for full upstream coverage, but it is clearly labeled as passthrough.
- Mutating `raw -- ...` commands require `--allow-mutation`; raw publish also requires `--allow-publish --confirm <container-id>`.
- Snapshots, backups, service-account JSON, tokens, and env files are ignored by default.
- Snapshot/backup outputs inside the repo must live under `snapshots/` or `backups/`, or use `.snapshot.json` / `.backup.json` suffixes unless `--allow-unsafe-out` is present.
- Unit and E2E tests use a fake upstream `gtm` binary and never touch a real GTM account.

## Declarative Plan

```yaml
accountId: "123"
containerId: "456"
workspaceId: "7"
actions:
  - kind: enableBuiltInVariables
    types: ["pageUrl", "clickText"]
  - kind: createTrigger
    name: "All Pages"
    type: "pageview"
  - kind: createTag
    name: "GA4 purchase"
    type: "gaawe"
    config:
      parameter:
        - type: template
          key: eventName
          value: purchase
  - kind: createVersion
    name: "agent release"
    notes: "Created by gtm-agent"
```

Publish action:

```yaml
accountId: "123"
containerId: "456"
workspaceId: "7"
actions:
  - kind: publishVersion
    versionId: "42"
```

Run it only with both gates:

```bash
gtm-agent apply publish.yaml --execute --allow-publish --confirm 456 --json
```

## Included Skill

The repo includes `skills/gtm-agent/SKILL.md`. For Codex/Gemini/Claude-style local skill trees, symlink it with:

```bash
./scripts/link-skill.sh
```

The script creates or refreshes symlinks in:

- `~/.agents/skills/gtm-agent`
- `~/.codex/skills/gtm-agent`
- `~/.gemini/antigravity/skills/gtm-agent`
- `~/.claude/skills/gtm-agent`

## Verification

```bash
go mod verify
go test ./...
go vet ./...
go build -o ./gtm-agent ./cmd/gtm-agent
./scripts/e2e-fake-gtm.sh
```

Optional:

```bash
govulncheck ./...
```

## Upstream Contribution Strategy

Keep `gtm-agent` as the safety/control-plane layer. Contribute focused upstream improvements to [`owntag/gtm-cli`](https://github.com/owntag/gtm-cli) when they belong to the raw GTM command surface, such as JSON consistency, additional resource coverage, command help, or broadly useful agent guide improvements.

## Credits

Powered by:

- [`@owntag/gtm-cli`](https://github.com/owntag/gtm-cli)
- [Google Tag Manager API v2](https://developers.google.com/tag-platform/tag-manager/api/reference/rest)
- [`@googleapis/tagmanager`](https://www.npmjs.com/package/@googleapis/tagmanager)

This project is unofficial and is not affiliated with, endorsed by, or supported by Google.

## License

MIT.
