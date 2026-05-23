#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/gtm" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
case "$*" in
  "--version")
    echo "gtm version 1.5.8"
    ;;
  "auth status --output json")
    echo '{"authenticated":true,"method":"fake"}'
    ;;
  "config get --output json")
    echo '{"defaultAccountId":"123","defaultContainerId":"456","defaultWorkspaceId":"7"}'
    ;;
  "accounts list --output json")
    echo '[{"accountId":"123","name":"Main"}]'
    ;;
  "containers list --account-id 123 --output json")
    echo '[{"containerId":"456","name":"Web"}]'
    ;;
  "workspaces list --account-id 123 --container-id 456 --output json")
    echo '[{"workspaceId":"7","name":"Default Workspace"}]'
    ;;
  "tags list --account-id 123 --container-id 456 --workspace-id 7 --output json")
    echo '[{"tagId":"1","name":"GA4 purchase","type":"gaawe"}]'
    ;;
  "triggers list --account-id 123 --container-id 456 --workspace-id 7 --output json")
    echo '[{"triggerId":"2","name":"All Pages","type":"pageview"}]'
    ;;
  "variables list --account-id 123 --container-id 456 --workspace-id 7 --output json")
    echo '[]'
    ;;
  "built-in-variables list --account-id 123 --container-id 456 --workspace-id 7 --output json")
    echo '[{"type":"pageUrl","name":"Page URL"}]'
    ;;
  "version-headers list --account-id 123 --container-id 456 --output json")
    echo '[{"containerVersionId":"42","name":"live"}]'
    ;;
  "triggers create --name All Pages --type pageview --account-id 123 --container-id 456 --workspace-id 7 --output json")
    echo '{"triggerId":"2","name":"All Pages"}'
    ;;
  "versions publish --version-id 42 --account-id 123 --container-id 456 --output json")
    echo '{"containerVersionId":"42","published":true}'
    ;;
  "tags list --output json")
    echo '[]'
    ;;
  *)
    echo "unexpected fake gtm command: $*" >&2
    exit 9
    ;;
esac
SH
chmod +x "$TMP/gtm"

export PATH="$TMP:$PATH"
cd "$ROOT"
go build -o "$TMP/gtm-agent" ./cmd/gtm-agent

"$TMP/gtm-agent" doctor --json | grep -q '"upstreamOK": true'
"$TMP/gtm-agent" inventory --account-id 123 --container-id 456 --workspace-id 7 --json | grep -q 'GA4 purchase'
"$TMP/gtm-agent" snapshot --account-id 123 --container-id 456 --workspace-id 7 --out "$TMP/before.json" --json | grep -q "$TMP/before.json"
cp "$TMP/before.json" "$TMP/after.json"
perl -0pi -e 's/GA4 purchase/GA4 purchase updated/g' "$TMP/after.json"
"$TMP/gtm-agent" diff "$TMP/before.json" "$TMP/after.json" --json | grep -q 'GA4 purchase updated'
"$TMP/gtm-agent" plan template --out "$TMP/template.yaml" --json | grep -q "$TMP/template.yaml"

cat > "$TMP/plan.yaml" <<'YAML'
accountId: "123"
containerId: "456"
workspaceId: "7"
actions:
  - kind: createTrigger
    name: "All Pages"
    type: "pageview"
YAML
"$TMP/gtm-agent" plan validate "$TMP/plan.yaml" --json | grep -q '"valid": true'
"$TMP/gtm-agent" apply "$TMP/plan.yaml" --json | grep -q '"dryRun": true'
"$TMP/gtm-agent" apply "$TMP/plan.yaml" --execute --json | grep -q '"triggerId": "2"'

cat > "$TMP/publish.yaml" <<'YAML'
accountId: "123"
containerId: "456"
workspaceId: "7"
actions:
  - kind: publishVersion
    versionId: "42"
YAML
if "$TMP/gtm-agent" apply "$TMP/publish.yaml" --execute >"$TMP/gtm-agent-publish.out" 2>"$TMP/gtm-agent-publish.err"; then
  echo "publish unexpectedly succeeded without gates" >&2
  exit 1
fi
"$TMP/gtm-agent" apply "$TMP/publish.yaml" --execute --allow-publish --confirm 456 --json | grep -q '"published": true'
if "$TMP/gtm-agent" raw -- versions publish --version-id 42 --container-id 456 >"$TMP/raw-publish.out" 2>"$TMP/raw-publish.err"; then
  echo "raw publish unexpectedly succeeded without gates" >&2
  exit 1
fi
"$TMP/gtm-agent" raw -- tags list --output json | grep -q '^\[\]$'

echo "fake GTM E2E passed"
