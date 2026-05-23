package cli_test

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/vecyang1/gtm-agent-cli/internal/cli"
	"github.com/vecyang1/gtm-agent-cli/internal/runner"
)

func TestCLIDoctorInventorySnapshotDiffApplyAndRaw(t *testing.T) {
	fake := runner.NewFake(map[string]runner.Result{
		"gtm --version": {Stdout: "gtm version 1.5.8\n"},
		"gtm auth status --output json": {
			Stdout: `{"authenticated":true,"method":"service-account"}` + "\n",
		},
		"gtm config get --output json": {
			Stdout: `{"defaultAccountId":"123","defaultContainerId":"456","defaultWorkspaceId":"7"}` + "\n",
		},
		"gtm accounts list --output json": {
			Stdout: `[{"accountId":"123","name":"Main"}]` + "\n",
		},
		"gtm containers list --account-id 123 --output json": {
			Stdout: `[{"containerId":"456","name":"Web"}]` + "\n",
		},
		"gtm workspaces list --account-id 123 --container-id 456 --output json": {
			Stdout: `[{"workspaceId":"7","name":"Default Workspace"}]` + "\n",
		},
		"gtm tags list --account-id 123 --container-id 456 --workspace-id 7 --output json": {
			Stdout: `[{"tagId":"1","name":"GA4 purchase","type":"gaawe"}]` + "\n",
		},
		"gtm triggers list --account-id 123 --container-id 456 --workspace-id 7 --output json": {
			Stdout: `[{"triggerId":"2","name":"All Pages","type":"pageview"}]` + "\n",
		},
		"gtm variables list --account-id 123 --container-id 456 --workspace-id 7 --output json": {
			Stdout: `[]` + "\n",
		},
		"gtm built-in-variables list --account-id 123 --container-id 456 --workspace-id 7 --output json": {
			Stdout: `[{"type":"pageUrl","name":"Page URL"}]` + "\n",
		},
		"gtm version-headers list --account-id 123 --container-id 456 --output json": {
			Stdout: `[{"containerVersionId":"42","name":"live"}]` + "\n",
		},
		"gtm tags list --output json": {
			Stdout: `[]` + "\n",
		},
	})

	tmp := t.TempDir()
	doctor := runCLI(t, fake, "doctor", "--json")
	if !strings.Contains(doctor, `"upstreamVersion": "gtm version 1.5.8"`) {
		t.Fatalf("doctor missing upstream version: %s", doctor)
	}

	inventory := runCLI(t, fake, "inventory", "--account-id", "123", "--container-id", "456", "--workspace-id", "7", "--json")
	if !strings.Contains(inventory, `"tags"`) || !strings.Contains(inventory, "GA4 purchase") {
		t.Fatalf("inventory missing resources: %s", inventory)
	}

	snapshotPath := filepath.Join(tmp, "snapshot.json")
	runCLI(t, fake, "snapshot", "--account-id", "123", "--container-id", "456", "--workspace-id", "7", "--out", snapshotPath)
	data, err := os.ReadFile(snapshotPath)
	if err != nil {
		t.Fatalf("snapshot was not written: %v", err)
	}
	if !bytes.Contains(data, []byte(`"schemaVersion": "1"`)) {
		t.Fatalf("snapshot missing schema version: %s", string(data))
	}

	changedPath := filepath.Join(tmp, "changed.json")
	changed := strings.ReplaceAll(string(data), `"GA4 purchase"`, `"GA4 purchase updated"`)
	if err := os.WriteFile(changedPath, []byte(changed), 0o600); err != nil {
		t.Fatalf("write changed snapshot: %v", err)
	}
	diff := runCLI(t, fake, "diff", snapshotPath, changedPath, "--json")
	if !strings.Contains(diff, `"changed"`) || !strings.Contains(diff, "GA4 purchase updated") {
		t.Fatalf("diff missing changed resource: %s", diff)
	}

	planPath := filepath.Join(tmp, "plan.yaml")
	if err := os.WriteFile(planPath, []byte(`accountId: "123"
containerId: "456"
workspaceId: "7"
actions:
  - kind: createTrigger
    name: "All Pages"
    type: "pageview"
`), 0o600); err != nil {
		t.Fatalf("write plan: %v", err)
	}
	dryRun := runCLI(t, fake, "apply", planPath, "--json")
	if !strings.Contains(dryRun, `"dryRun": true`) || !strings.Contains(dryRun, "triggers") {
		t.Fatalf("dry-run did not print command plan: %s", dryRun)
	}

	raw := runCLI(t, fake, "raw", "--", "tags", "list", "--output", "json")
	if strings.TrimSpace(raw) != "[]" {
		t.Fatalf("raw passthrough returned %q", raw)
	}
}

func TestSnapshotRejectsCommitFriendlyOutputPath(t *testing.T) {
	fake := runner.NewFake(map[string]runner.Result{
		"gtm accounts list --output json":                                                                {Stdout: `[]` + "\n"},
		"gtm containers list --account-id 123 --output json":                                             {Stdout: `[]` + "\n"},
		"gtm workspaces list --account-id 123 --container-id 456 --output json":                          {Stdout: `[]` + "\n"},
		"gtm tags list --account-id 123 --container-id 456 --workspace-id 7 --output json":               {Stdout: `[]` + "\n"},
		"gtm triggers list --account-id 123 --container-id 456 --workspace-id 7 --output json":           {Stdout: `[]` + "\n"},
		"gtm variables list --account-id 123 --container-id 456 --workspace-id 7 --output json":          {Stdout: `[]` + "\n"},
		"gtm built-in-variables list --account-id 123 --container-id 456 --workspace-id 7 --output json": {Stdout: `[]` + "\n"},
		"gtm version-headers list --account-id 123 --container-id 456 --output json":                     {Stdout: `[]` + "\n"},
	})
	var out, errOut bytes.Buffer
	cmd := cli.NewRoot(cli.Options{Out: &out, Err: &errOut, Runner: fake})
	cmd.SetArgs([]string{"snapshot", "--account-id", "123", "--container-id", "456", "--workspace-id", "7", "--out", "live.json"})
	if err := cmd.ExecuteContext(context.Background()); err == nil {
		t.Fatalf("expected unsafe snapshot output path to be rejected")
	}
}

func TestDiffRejectsDifferentScopes(t *testing.T) {
	tmp := t.TempDir()
	beforePath := filepath.Join(tmp, "before.json")
	afterPath := filepath.Join(tmp, "after.json")
	before := `{"schemaVersion":"1","accountId":"123","containerId":"456","workspaceId":"7","resources":{}}`
	after := `{"schemaVersion":"1","accountId":"123","containerId":"DIFFERENT","workspaceId":"7","resources":{}}`
	if err := os.WriteFile(beforePath, []byte(before), 0o600); err != nil {
		t.Fatalf("write before: %v", err)
	}
	if err := os.WriteFile(afterPath, []byte(after), 0o600); err != nil {
		t.Fatalf("write after: %v", err)
	}
	var out, errOut bytes.Buffer
	cmd := cli.NewRoot(cli.Options{Out: &out, Err: &errOut, Runner: runner.NewFake(nil)})
	cmd.SetArgs([]string{"diff", beforePath, afterPath})
	if err := cmd.ExecuteContext(context.Background()); err == nil {
		t.Fatalf("expected diff to reject different container scopes")
	}
}

func TestDiffAllowsDifferentScopesWithExplicitFlag(t *testing.T) {
	tmp := t.TempDir()
	beforePath := filepath.Join(tmp, "before.json")
	afterPath := filepath.Join(tmp, "after.json")
	before := `{"schemaVersion":"1","accountId":"123","containerId":"456","workspaceId":"7","resources":{}}`
	after := `{"schemaVersion":"1","accountId":"123","containerId":"DIFFERENT","workspaceId":"7","resources":{}}`
	if err := os.WriteFile(beforePath, []byte(before), 0o600); err != nil {
		t.Fatalf("write before: %v", err)
	}
	if err := os.WriteFile(afterPath, []byte(after), 0o600); err != nil {
		t.Fatalf("write after: %v", err)
	}
	out := runCLI(t, runner.NewFake(nil), "diff", beforePath, afterPath, "--allow-different-scope", "--json")
	if !strings.Contains(out, `"added"`) {
		t.Fatalf("expected diff JSON output, got %s", out)
	}
}

func TestCLIApplyExecutesCommandsOnlyWhenExecuteIsSet(t *testing.T) {
	fake := runner.NewFake(map[string]runner.Result{
		"gtm triggers create --name All Pages --type pageview --account-id 123 --container-id 456 --workspace-id 7 --output json": {
			Stdout: `{"triggerId":"2","name":"All Pages"}` + "\n",
		},
	})
	tmp := t.TempDir()
	planPath := filepath.Join(tmp, "plan.yaml")
	if err := os.WriteFile(planPath, []byte(`accountId: "123"
containerId: "456"
workspaceId: "7"
actions:
  - kind: createTrigger
    name: "All Pages"
    type: "pageview"
`), 0o600); err != nil {
		t.Fatalf("write plan: %v", err)
	}

	out := runCLI(t, fake, "apply", planPath, "--execute", "--json")
	if !strings.Contains(out, `"dryRun": false`) || !strings.Contains(out, `"triggerId": "2"`) {
		t.Fatalf("execute output missing upstream result: %s", out)
	}
}

func TestCLIPlanValidateAndTemplate(t *testing.T) {
	tmp := t.TempDir()
	planPath := filepath.Join(tmp, "plan.yaml")
	if err := os.WriteFile(planPath, []byte(`accountId: "123"
containerId: "456"
workspaceId: "7"
actions:
  - kind: createVersion
    name: "agent release"
`), 0o600); err != nil {
		t.Fatalf("write plan: %v", err)
	}

	validate := runCLI(t, runner.NewFake(nil), "plan", "validate", planPath, "--json")
	if !strings.Contains(validate, `"valid": true`) || !strings.Contains(validate, `"commandCount": 1`) {
		t.Fatalf("validate output missing expected summary: %s", validate)
	}

	templatePath := filepath.Join(tmp, "template.yaml")
	template := runCLI(t, runner.NewFake(nil), "plan", "template", "--out", templatePath, "--json")
	if !strings.Contains(template, templatePath) {
		t.Fatalf("template output missing path: %s", template)
	}
	templateData, err := os.ReadFile(templatePath)
	if err != nil {
		t.Fatalf("read template: %v", err)
	}
	if !strings.Contains(string(templateData), "enableBuiltInVariables") || !strings.Contains(string(templateData), "createTag") {
		t.Fatalf("template missing expected action examples: %s", string(templateData))
	}
}

func TestCLIApplyRejectsPublishWithoutGates(t *testing.T) {
	tmp := t.TempDir()
	planPath := filepath.Join(tmp, "publish.yaml")
	if err := os.WriteFile(planPath, []byte(`accountId: "123"
containerId: "456"
workspaceId: "7"
actions:
  - kind: publishVersion
    versionId: "42"
`), 0o600); err != nil {
		t.Fatalf("write plan: %v", err)
	}
	var out, errOut bytes.Buffer
	cmd := cli.NewRoot(cli.Options{Out: &out, Err: &errOut, Runner: runner.NewFake(nil)})
	cmd.SetArgs([]string{"apply", planPath, "--execute"})
	if err := cmd.ExecuteContext(context.Background()); err == nil {
		t.Fatalf("expected publish plan to be rejected without gates")
	}
}

func TestCLIRawBlocksPublishWithoutUnsafeGate(t *testing.T) {
	var out, errOut bytes.Buffer
	cmd := cli.NewRoot(cli.Options{Out: &out, Err: &errOut, Runner: runner.NewFake(nil)})
	cmd.SetArgs([]string{"raw", "--", "versions", "publish", "--version-id", "42"})
	if err := cmd.ExecuteContext(context.Background()); err == nil {
		t.Fatalf("expected raw publish to be rejected without unsafe gate")
	}
}

func TestCLIRawAllowsHelpForMutatingCommands(t *testing.T) {
	fake := runner.NewFake(map[string]runner.Result{
		"gtm versions publish --help": {Stdout: "help\n"},
	})
	out := runCLI(t, fake, "raw", "--", "versions", "publish", "--help")
	if out != "help\n" {
		t.Fatalf("unexpected help output: %q", out)
	}
}

func TestCLIRawAllowsPublishWithUnsafeGateAndConfirmation(t *testing.T) {
	fake := runner.NewFake(map[string]runner.Result{
		"gtm versions publish --version-id 42 --container-id 456": {Stdout: `{"published":true}` + "\n"},
	})
	out := runCLI(t, fake, "raw", "--allow-mutation", "--allow-publish", "--confirm", "456", "--", "versions", "publish", "--version-id", "42", "--container-id", "456")
	if !strings.Contains(out, `"published":true`) {
		t.Fatalf("raw publish output missing upstream result: %s", out)
	}
}

func runCLI(t *testing.T, fake *runner.Fake, args ...string) string {
	t.Helper()
	var out, errOut bytes.Buffer
	cmd := cli.NewRoot(cli.Options{Out: &out, Err: &errOut, Runner: fake})
	cmd.SetArgs(args)
	if err := cmd.ExecuteContext(context.Background()); err != nil {
		t.Fatalf("gtm-agent %s failed: %v\nstdout:\n%s\nstderr:\n%s", strings.Join(args, " "), err, out.String(), errOut.String())
	}
	var js any
	if strings.Contains(strings.Join(args, " "), "--json") && json.Valid(out.Bytes()) {
		_ = json.Unmarshal(out.Bytes(), &js)
	}
	return out.String()
}
