#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export FAKE_GTM_STATE="$TMP/state"
mkdir -p "$FAKE_GTM_STATE"

cat > "$TMP/gtm" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
STATE="${FAKE_GTM_STATE:?}"
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
    if [[ -f "$STATE/tag-created" ]]; then
      echo '[{"tagId":"1","name":"GA4 purchase","type":"gaawe"},{"tagId":"30","name":"GA4 - article_product_click","type":"gaawe"}]'
    else
      echo '[{"tagId":"1","name":"GA4 purchase","type":"gaawe"}]'
    fi
    ;;
  "triggers list --account-id 123 --container-id 456 --workspace-id 7 --output json")
    if [[ -f "$STATE/trigger-created" ]]; then
      echo '[{"triggerId":"2","name":"All Pages","type":"pageview"},{"triggerId":"20","name":"CE - article_product_click","type":"CUSTOM_EVENT"}]'
    else
      echo '[{"triggerId":"2","name":"All Pages","type":"pageview"}]'
    fi
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
  triggers\ create\ --name\ CE\ -\ article_product_click\ --type\ CUSTOM_EVENT\ --config\ *\ --account-id\ 123\ --container-id\ 456\ --workspace-id\ 7\ --output\ json)
    touch "$STATE/trigger-created"
    echo '{"triggerId":"20","name":"CE - article_product_click"}'
    ;;
  "tags create --name GA4 - article_product_click --type gaawe --firing-trigger-id 20 --account-id 123 --container-id 456 --workspace-id 7 --output json")
    [[ -f "$STATE/trigger-created" ]]
    touch "$STATE/tag-created"
    echo '{"tagId":"30","name":"GA4 - article_product_click"}'
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

if "$TMP/gtm-agent" inventory --account-id 123 --container-id 456 --workspace-id 7 --json | grep -q 'CE - article_product_click'; then
  echo "trigger unexpectedly existed before the trigger plan" >&2
  exit 1
fi

cat > "$TMP/trigger-plan.yaml" <<'YAML'
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
YAML
"$TMP/gtm-agent" plan validate "$TMP/trigger-plan.yaml" --json | grep -q '"valid": true'
"$TMP/gtm-agent" apply "$TMP/trigger-plan.yaml" --json | grep -q '"dryRun": true'
"$TMP/gtm-agent" apply "$TMP/trigger-plan.yaml" --execute --json | grep -q '"triggerId": "20"'
"$TMP/gtm-agent" inventory --account-id 123 --container-id 456 --workspace-id 7 --json | grep -q 'CE - article_product_click'

cat > "$TMP/tag-plan.yaml" <<'YAML'
accountId: "123"
containerId: "456"
workspaceId: "7"
actions:
  - kind: createTag
    name: "GA4 - article_product_click"
    type: "gaawe"
    firingTriggerIds: ["20"]
YAML
"$TMP/gtm-agent" plan validate "$TMP/tag-plan.yaml" --json | grep -q '"valid": true'
"$TMP/gtm-agent" apply "$TMP/tag-plan.yaml" --json | grep -q -- '--firing-trigger-id 20'
"$TMP/gtm-agent" apply "$TMP/tag-plan.yaml" --execute --json | grep -q '"tagId": "30"'

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
