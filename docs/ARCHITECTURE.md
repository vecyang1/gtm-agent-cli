# GTM Agent CLI Design

Date: 2026-05-24

## Goal

Build a strong agent-friendly Google Tag Manager control-plane CLI without reinventing Google's API or the mature GTM command surface. The CLI is named `gtm-agent`; it wraps the maintained `@owntag/gtm-cli` wheel, keeps raw GTM coverage through passthrough commands, and adds the missing agent safety layer: install checks, doctor, inventory snapshots, stable diffs, declarative plans, dry-run-first apply, backup, publish gates, and a concise embedded guide.

## Wheels Used

- `@owntag/gtm-cli` 1.5.8: raw GTM account/container/workspace/tag/trigger/variable/version/publish command coverage, OAuth/service-account auth, JSON output, and `gtm agent guide`.
- Google Tag Manager API v2: official resource model and OAuth scopes for accounts, containers, workspaces, tags, triggers, variables, built-in variables, versions, and publish flows.
- `@googleapis/tagmanager` 14.2.0: official Node client for future direct API work if the wrapper needs to become a native API client later.

## Product Shape

`gtm-agent` is a safety and automation shell around the upstream `gtm` binary.

- `gtm-agent install`: explains or executes the pinned upstream install.
- `gtm-agent doctor`: checks upstream binary availability, auth status, version, config, and optional service-account environment.
- `gtm-agent inventory`: collects accounts, containers, workspaces, tags, triggers, variables, built-in variables, and versions through upstream `gtm` commands.
- `gtm-agent snapshot`: writes inventory to a timestamped JSON file with metadata and stable ordering.
- `gtm-agent diff`: compares two snapshot files and reports added/removed/changed resources.
- `gtm-agent apply`: reads a declarative YAML or JSON plan, prints commands by default, and only executes with `--execute`.
- `gtm-agent backup`: stores the live version JSON before risky changes.
- `gtm-agent raw -- ...`: passes through to the upstream `gtm` CLI for the full command surface.
- `gtm-agent guide`: prints the local agent playbook and credits the upstream wheel.

## Safety Contract

- No mutation happens without `--execute`.
- Publish actions require both `--allow-publish` and `--confirm <container-id>`.
- Plan commands are printed as JSON in dry-run mode so agents can inspect the exact blast radius.
- Real upstream `gtm` output is not post-processed in a way that can hide failures; non-zero exits bubble up.
- Tests run against a fake upstream binary so normal verification never mutates a real GTM account.

## Data Contract

Plans can be YAML or JSON:

Trigger phase:

```yaml
accountId: "123"
containerId: "456"
workspaceId: "7"
actions:
  - kind: createTrigger
    name: "CE - article_product_click"
    type: "CUSTOM_EVENT"
    config:
      customEventFilter:
        - type: EQUALS
          parameter:
            - {type: TEMPLATE, key: arg0, value: "{{_event}}"}
            - {type: TEMPLATE, key: arg1, value: article_product_click}
```

After execution and a fresh inventory read, the returned ID is used in a separate tag plan:

```yaml
accountId: "123"
containerId: "456"
workspaceId: "7"
actions:
  - kind: createTag
    name: "GA4 - article_product_click"
    type: "gaawe"
    firingTriggerIds: ["20"]
    config:
      parameter:
        - type: template
          key: eventName
          value: article_product_click
```

The first release intentionally supports the highest-value safe workflow primitives and leaves deep endpoint-specific authoring to raw upstream passthrough.

Trigger configuration is encoded into the upstream `--config` JSON argument. Reserved declarative fields (`name`, `type`, and tag firing-trigger fields) cannot be overridden inside config. A tag can bind to one `firingTriggerId` or several `firingTriggerIds`; the plan compiler validates quoted positive-decimal IDs and emits the upstream comma-separated `--firing-trigger-id` form. Because GTM generates IDs at mutation time, references to a newly created trigger use two reviewed plans with an inventory read between them. Offline plan compilation intentionally does not claim live exact-name uniqueness.

## Verification

Required checks before claiming completion:

- `go mod tidy`
- `go test ./...`
- `go vet ./...`
- `go build -o ./gtm-agent ./cmd/gtm-agent`
- Fake upstream E2E: install a temporary `gtm` script on `PATH`, run doctor, inventory, snapshot, diff, dry-run apply, guarded publish failure, allowed publish success, and raw passthrough.
- If real GTM credentials are already available safely, run read-only `auth status` / inventory smoke. Do not create or publish real GTM resources without an explicit safe target.
