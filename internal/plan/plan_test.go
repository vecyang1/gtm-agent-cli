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

func TestCreateTriggerCompilesConfigAsJSON(t *testing.T) {
	raw := []byte(`
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
            - type: TEMPLATE
              key: arg0
              value: "{{_event}}"
            - type: TEMPLATE
              key: arg1
              value: article_product_click
`)

	p, err := plan.Parse(raw)
	if err != nil {
		t.Fatalf("Parse returned error: %v", err)
	}
	commands, err := p.Commands(plan.Options{})
	if err != nil {
		t.Fatalf("Commands returned error: %v", err)
	}
	if len(commands) != 1 {
		t.Fatalf("expected one command, got %d", len(commands))
	}
	config := flagValue(commands[0].Args, "--config")
	if !strings.Contains(config, `"customEventFilter"`) || !strings.Contains(config, `"article_product_click"`) {
		t.Fatalf("trigger config was not compiled as JSON: %s", config)
	}
}

func TestCreateTagCompilesPluralFiringTriggerIDs(t *testing.T) {
	raw := []byte(`
accountId: "123"
containerId: "456"
workspaceId: "7"
actions:
  - kind: createTag
    name: "GA4 - article_product_click"
    type: "gaawe"
    firingTriggerIds: ["20", "21"]
`)

	p, err := plan.Parse(raw)
	if err != nil {
		t.Fatalf("Parse returned error: %v", err)
	}
	commands, err := p.Commands(plan.Options{})
	if err != nil {
		t.Fatalf("Commands returned error: %v", err)
	}
	if got := flagValue(commands[0].Args, "--firing-trigger-id"); got != "20,21" {
		t.Fatalf("unexpected firing trigger flag: %q", got)
	}
}

func TestCreateTagCompilesSingularFiringTriggerID(t *testing.T) {
	raw := []byte(`
accountId: "123"
containerId: "456"
workspaceId: "7"
actions:
  - kind: createTag
    name: "GA4 - article_product_click"
    type: "gaawe"
    firingTriggerId: "20"
`)

	p, err := plan.Parse(raw)
	if err != nil {
		t.Fatalf("Parse returned error: %v", err)
	}
	commands, err := p.Commands(plan.Options{})
	if err != nil {
		t.Fatalf("Commands returned error: %v", err)
	}
	if got := flagValue(commands[0].Args, "--firing-trigger-id"); got != "20" {
		t.Fatalf("unexpected firing trigger flag: %q", got)
	}
}

func TestParseRejectsMalformedFiringTriggerIDs(t *testing.T) {
	tests := []struct {
		name   string
		fields string
	}{
		{name: "empty singular", fields: `firingTriggerId: ""`},
		{name: "non numeric singular", fields: `firingTriggerId: "all-pages"`},
		{name: "comma separated singular", fields: `firingTriggerId: "20,21"`},
		{name: "zero singular", fields: `firingTriggerId: "0"`},
		{name: "empty plural", fields: `firingTriggerIds: []`},
		{name: "blank plural member", fields: `firingTriggerIds: ["20", " "]`},
		{name: "duplicate plural member", fields: `firingTriggerIds: ["20", "20"]`},
		{name: "both forms", fields: "firingTriggerId: \"20\"\n    firingTriggerIds: [\"21\"]"},
		{name: "wrong plural type", fields: `firingTriggerIds: "20"`},
		{name: "numeric singular type", fields: `firingTriggerId: 20`},
		{name: "numeric plural member type", fields: `firingTriggerIds: [20]`},
		{name: "null singular type", fields: `firingTriggerId: null`},
		{name: "null plural type", fields: `firingTriggerIds: null`},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			raw := []byte("accountId: \"123\"\n" +
				"containerId: \"456\"\n" +
				"workspaceId: \"7\"\n" +
				"actions:\n" +
				"  - kind: createTag\n" +
				"    name: \"GA4 event\"\n" +
				"    type: \"gaawe\"\n" +
				"    " + test.fields + "\n")
			if _, err := plan.Parse(raw); err == nil {
				t.Fatalf("expected malformed firing trigger IDs to be rejected")
			}
		})
	}
}

func TestParseRejectsFiringTriggerIDsOnNonTagActions(t *testing.T) {
	_, err := plan.Parse([]byte(`
accountId: "123"
containerId: "456"
workspaceId: "7"
actions:
  - kind: createTrigger
    name: "All Pages"
    type: "PAGEVIEW"
    firingTriggerId: "20"
`))
	if err == nil || !strings.Contains(err.Error(), "only valid for createTag") {
		t.Fatalf("expected scoped firing trigger validation error, got %v", err)
	}
}

func TestParseRejectsNonStringResourceTypes(t *testing.T) {
	tests := []struct {
		name      string
		kind      string
		typeValue string
	}{
		{name: "numeric trigger type", kind: "createTrigger", typeValue: "123"},
		{name: "boolean tag type", kind: "createTag", typeValue: "true"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			raw := []byte("accountId: \"123\"\n" +
				"containerId: \"456\"\n" +
				"workspaceId: \"7\"\n" +
				"actions:\n" +
				"  - kind: " + test.kind + "\n" +
				"    name: \"resource\"\n" +
				"    type: " + test.typeValue + "\n")
			if _, err := plan.Parse(raw); err == nil || !strings.Contains(err.Error(), "type must be a string") {
				t.Fatalf("expected non-string type to be rejected, got %v", err)
			}
		})
	}
}

func TestParseRejectsConfigThatOverridesDeclarativeFields(t *testing.T) {
	tests := []struct {
		name   string
		kind   string
		config string
	}{
		{name: "trigger name", kind: "createTrigger", config: `name: "hidden override"`},
		{name: "trigger type", kind: "createTrigger", config: `type: "hidden override"`},
		{name: "tag firing trigger", kind: "createTag", config: `firingTriggerId: ["20"]`},
		{name: "tag plural firing trigger", kind: "createTag", config: `firingTriggerIds: ["20"]`},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			raw := []byte("accountId: \"123\"\n" +
				"containerId: \"456\"\n" +
				"workspaceId: \"7\"\n" +
				"actions:\n" +
				"  - kind: " + test.kind + "\n" +
				"    name: \"resource\"\n" +
				"    type: \"safe-type\"\n" +
				"    config:\n" +
				"      " + test.config + "\n")
			if _, err := plan.Parse(raw); err == nil || !strings.Contains(err.Error(), "config key") {
				t.Fatalf("expected config override to be rejected, got %v", err)
			}
		})
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

func flagValue(args []string, name string) string {
	for i, arg := range args {
		if arg == name && i+1 < len(args) {
			return args[i+1]
		}
	}
	return ""
}
