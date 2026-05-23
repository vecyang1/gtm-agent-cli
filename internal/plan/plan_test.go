package plan_test

import (
	"strings"
	"testing"

	"github.com/vecyang1/gtm-agent-cli/internal/plan"
)

func TestParsePlanBuildsSafeCommandSequence(t *testing.T) {
	raw := []byte(`
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
`)

	p, err := plan.Parse(raw)
	if err != nil {
		t.Fatalf("Parse returned error: %v", err)
	}
	commands, err := p.Commands(plan.Options{})
	if err != nil {
		t.Fatalf("Commands returned error: %v", err)
	}

	got := render(commands)
	wantSubstrings := []string{
		"built-in-variables enable --types pageUrl,clickText --account-id 123 --container-id 456 --workspace-id 7 --output json",
		"triggers create --name All Pages --type pageview --account-id 123 --container-id 456 --workspace-id 7 --output json",
		"tags create --name GA4 purchase --type gaawe --config",
		"versions create --name agent release --notes Created by gtm-agent --account-id 123 --container-id 456 --workspace-id 7 --output json",
	}
	for _, want := range wantSubstrings {
		if !strings.Contains(got, want) {
			t.Fatalf("command sequence missing %q\ncommands:\n%s", want, got)
		}
	}
}

func TestPublishRequiresExplicitGateAndContainerConfirmation(t *testing.T) {
	raw := []byte(`
accountId: "123"
containerId: "456"
workspaceId: "7"
actions:
  - kind: publishVersion
    versionId: "42"
`)
	p, err := plan.Parse(raw)
	if err != nil {
		t.Fatalf("Parse returned error: %v", err)
	}
	if _, err := p.Commands(plan.Options{}); err == nil {
		t.Fatalf("expected publish to fail without allow gate")
	}
	if _, err := p.Commands(plan.Options{AllowPublish: true, ConfirmContainerID: "wrong"}); err == nil {
		t.Fatalf("expected publish to fail with wrong confirmation")
	}
	commands, err := p.Commands(plan.Options{AllowPublish: true, ConfirmContainerID: "456"})
	if err != nil {
		t.Fatalf("expected publish with correct gates to pass: %v", err)
	}
	if got := render(commands); !strings.Contains(got, "versions publish --version-id 42 --account-id 123 --container-id 456 --output json") {
		t.Fatalf("unexpected publish command: %s", got)
	}
}

func TestPublishCommandDoesNotIncludeWorkspaceID(t *testing.T) {
	raw := []byte(`
accountId: "123"
containerId: "456"
workspaceId: "7"
actions:
  - kind: publishVersion
    versionId: "42"
`)
	p, err := plan.Parse(raw)
	if err != nil {
		t.Fatalf("Parse returned error: %v", err)
	}
	commands, err := p.Commands(plan.Options{AllowPublish: true, ConfirmContainerID: "456"})
	if err != nil {
		t.Fatalf("Commands returned error: %v", err)
	}
	if got := render(commands); strings.Contains(got, "--workspace-id") {
		t.Fatalf("publish command should not include workspace id: %s", got)
	}
}

func TestParseRejectsUnknownActions(t *testing.T) {
	_, err := plan.Parse([]byte(`{"accountId":"1","containerId":"2","workspaceId":"3","actions":[{"kind":"surprise"}]}`))
	if err == nil || !strings.Contains(err.Error(), "unsupported action kind") {
		t.Fatalf("expected unsupported action error, got %v", err)
	}
}

func TestParseRejectsUnknownFields(t *testing.T) {
	_, err := plan.Parse([]byte(`accountId: "1"
containerId: "2"
workspaceId: "3"
actions:
  - kind: createTag
    name: "GA4 purchase"
    type: "gaawe"
    confgi:
      parameter: []
`))
	if err == nil || !strings.Contains(err.Error(), "field confgi not found") {
		t.Fatalf("expected unknown field error, got %v", err)
	}
}

func TestCommandShellQuotesMetacharacters(t *testing.T) {
	raw := []byte(`accountId: "1"
containerId: "2"
workspaceId: "3"
actions:
  - kind: createTrigger
    name: "bad; touch /tmp/owned"
    type: "pageview"
`)
	p, err := plan.Parse(raw)
	if err != nil {
		t.Fatalf("Parse returned error: %v", err)
	}
	commands, err := p.Commands(plan.Options{})
	if err != nil {
		t.Fatalf("Commands returned error: %v", err)
	}
	if !strings.Contains(commands[0].Shell, "'bad; touch /tmp/owned'") {
		t.Fatalf("shell output missing quoted payload: %s", commands[0].Shell)
	}
}

func render(commands []plan.Command) string {
	var b strings.Builder
	for _, cmd := range commands {
		b.WriteString(strings.Join(cmd.Args, " "))
		b.WriteByte('\n')
	}
	return b.String()
}
