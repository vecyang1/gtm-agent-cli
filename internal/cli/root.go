package cli

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/spf13/cobra"
	"github.com/vecyang1/gtm-agent-cli/internal/plan"
	"github.com/vecyang1/gtm-agent-cli/internal/runner"
	"github.com/vecyang1/gtm-agent-cli/internal/snapshot"
)

type Options struct {
	Out       io.Writer
	Err       io.Writer
	Runner    runner.Runner
	GTMBinary string
}

type runtime struct {
	options Options
	asJSON  bool
}

func NewRoot(options Options) *cobra.Command {
	if options.Out == nil {
		options.Out = os.Stdout
	}
	if options.Err == nil {
		options.Err = os.Stderr
	}
	if options.Runner == nil {
		options.Runner = runner.Exec{}
	}
	if options.GTMBinary == "" {
		options.GTMBinary = "gtm"
	}
	rt := &runtime{options: options}
	cmd := &cobra.Command{
		Use:           "gtm-agent",
		Short:         "Agent-safe Google Tag Manager control plane based on @owntag/gtm-cli",
		SilenceUsage:  true,
		SilenceErrors: true,
	}
	cmd.SetOut(options.Out)
	cmd.SetErr(options.Err)
	cmd.PersistentFlags().BoolVar(&rt.asJSON, "json", false, "Output JSON")
	cmd.PersistentFlags().StringVar(&rt.options.GTMBinary, "gtm-bin", options.GTMBinary, "Upstream gtm binary path")
	cmd.AddCommand(rt.installCmd())
	cmd.AddCommand(rt.doctorCmd())
	cmd.AddCommand(rt.inventoryCmd())
	cmd.AddCommand(rt.snapshotCmd())
	cmd.AddCommand(rt.diffCmd())
	cmd.AddCommand(rt.planCmd())
	cmd.AddCommand(rt.applyCmd())
	cmd.AddCommand(rt.backupCmd())
	cmd.AddCommand(rt.rawCmd())
	cmd.AddCommand(rt.guideCmd())
	return cmd
}

func (rt *runtime) planCmd() *cobra.Command {
	cmd := &cobra.Command{Use: "plan", Short: "Plan helpers"}
	validate := &cobra.Command{
		Use:   "validate <plan.yaml>",
		Short: "Validate and summarize a declarative GTM plan",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			raw, err := os.ReadFile(args[0])
			if err != nil {
				return err
			}
			p, err := plan.Parse(raw)
			if err != nil {
				return err
			}
			commands, err := p.Commands(plan.Options{AllowPublish: true, ConfirmContainerID: p.ContainerID})
			if err != nil {
				return err
			}
			return writeJSON(cmd.OutOrStdout(), map[string]any{
				"valid":        true,
				"accountId":    p.AccountID,
				"containerId":  p.ContainerID,
				"workspaceId":  p.WorkspaceID,
				"actionCount":  len(p.Actions),
				"commandCount": len(commands),
			})
		},
	}
	var outPath string
	template := &cobra.Command{
		Use:   "template",
		Short: "Write a starter declarative GTM plan",
		RunE: func(cmd *cobra.Command, args []string) error {
			if outPath == "" {
				_, err := fmt.Fprint(cmd.OutOrStdout(), planTemplate)
				return err
			}
			if err := os.MkdirAll(filepath.Dir(outPath), 0o755); err != nil {
				return err
			}
			if err := os.WriteFile(outPath, []byte(planTemplate), 0o600); err != nil {
				return err
			}
			return writeAny(cmd.OutOrStdout(), rt.asJSON, map[string]any{"path": outPath})
		},
	}
	template.Flags().StringVar(&outPath, "out", "", "Template output path")
	cmd.AddCommand(validate)
	cmd.AddCommand(template)
	return cmd
}

func (rt *runtime) installCmd() *cobra.Command {
	var execute bool
	cmd := &cobra.Command{
		Use:   "install",
		Short: "Install or print the pinned upstream GTM wheel install command",
		RunE: func(cmd *cobra.Command, args []string) error {
			install := "npm install -g @owntag/gtm-cli@1.5.8"
			if !execute {
				return writeAny(cmd.OutOrStdout(), rt.asJSON, map[string]any{
					"dryRun":  true,
					"command": install,
					"note":    "Run with --execute to install the pinned upstream gtm wheel.",
				})
			}
			result, err := rt.options.Runner.Run(cmd.Context(), "npm", "install", "-g", "@owntag/gtm-cli@1.5.8")
			if err != nil {
				return err
			}
			_, err = fmt.Fprint(cmd.OutOrStdout(), result.Stdout)
			return err
		},
	}
	cmd.Flags().BoolVar(&execute, "execute", false, "Actually run npm install")
	return cmd
}

func (rt *runtime) doctorCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "doctor",
		Short: "Check upstream gtm, auth, and config state",
		RunE: func(cmd *cobra.Command, args []string) error {
			gtmBinary := rt.gtmBinary(cmd.Context())
			report := map[string]any{"gtmBinary": gtmBinary}
			version, versionErr := rt.options.Runner.Run(cmd.Context(), gtmBinary, "--version")
			report["upstreamVersion"] = strings.TrimSpace(version.Stdout)
			report["upstreamOK"] = versionErr == nil
			if versionErr != nil {
				report["upstreamError"] = versionErr.Error()
			}
			auth, authErr := rt.options.Runner.Run(cmd.Context(), gtmBinary, "auth", "status", "--output", "json")
			report["authOK"] = authErr == nil
			report["auth"] = parseJSONOrText(auth.Stdout)
			if authErr != nil {
				report["authError"] = authErr.Error()
			}
			config, configErr := rt.options.Runner.Run(cmd.Context(), gtmBinary, "config", "get", "--output", "json")
			report["configOK"] = configErr == nil
			report["config"] = parseJSONOrText(config.Stdout)
			if configErr != nil {
				report["configError"] = configErr.Error()
			}
			return writeAny(cmd.OutOrStdout(), rt.asJSON, report)
		},
	}
}

func (rt *runtime) inventoryCmd() *cobra.Command {
	var accountID, containerID, workspaceID string
	cmd := &cobra.Command{
		Use:   "inventory",
		Short: "Collect a stable JSON inventory from GTM",
		RunE: func(cmd *cobra.Command, args []string) error {
			inv, err := rt.collectInventory(cmd.Context(), accountID, containerID, workspaceID)
			if err != nil {
				return err
			}
			return writeJSON(cmd.OutOrStdout(), inv)
		},
	}
	addScopeFlags(cmd, &accountID, &containerID, &workspaceID)
	return cmd
}

func (rt *runtime) snapshotCmd() *cobra.Command {
	var accountID, containerID, workspaceID, outPath string
	var allowUnsafeOut bool
	cmd := &cobra.Command{
		Use:   "snapshot",
		Short: "Write a timestamped GTM inventory snapshot",
		RunE: func(cmd *cobra.Command, args []string) error {
			if outPath == "" {
				return fmt.Errorf("--out is required")
			}
			if err := guardArtifactPath(outPath, "snapshot", allowUnsafeOut); err != nil {
				return err
			}
			inv, err := rt.collectInventory(cmd.Context(), accountID, containerID, workspaceID)
			if err != nil {
				return err
			}
			if err := os.MkdirAll(filepath.Dir(outPath), 0o755); err != nil {
				return err
			}
			data, err := json.MarshalIndent(inv, "", "  ")
			if err != nil {
				return err
			}
			if err := os.WriteFile(outPath, append(data, '\n'), 0o600); err != nil {
				return err
			}
			return writeAny(cmd.OutOrStdout(), rt.asJSON, map[string]any{"path": outPath, "resources": len(inv.Resources)})
		},
	}
	addScopeFlags(cmd, &accountID, &containerID, &workspaceID)
	cmd.Flags().StringVar(&outPath, "out", "", "Snapshot output path")
	cmd.Flags().BoolVar(&allowUnsafeOut, "allow-unsafe-out", false, "Allow writing a snapshot to a path that is easy to commit")
	return cmd
}

func (rt *runtime) diffCmd() *cobra.Command {
	var allowDifferentScope bool
	cmd := &cobra.Command{
		Use:   "diff <before.json> <after.json>",
		Short: "Compare two GTM snapshots",
		Args:  cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			before, err := readSnapshot(args[0])
			if err != nil {
				return err
			}
			after, err := readSnapshot(args[1])
			if err != nil {
				return err
			}
			if !allowDifferentScope {
				if err := validateComparableSnapshots(before, after); err != nil {
					return err
				}
			}
			return writeJSON(cmd.OutOrStdout(), snapshot.Diff(before, after))
		},
	}
	cmd.Flags().BoolVar(&allowDifferentScope, "allow-different-scope", false, "Allow comparing snapshots from different account/container/workspace scopes")
	return cmd
}

func (rt *runtime) applyCmd() *cobra.Command {
	var execute, allowPublish bool
	var confirm string
	cmd := &cobra.Command{
		Use:   "apply <plan.yaml>",
		Short: "Compile and optionally execute a GTM declarative plan",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			raw, err := os.ReadFile(args[0])
			if err != nil {
				return err
			}
			p, err := plan.Parse(raw)
			if err != nil {
				return err
			}
			commands, err := p.Commands(plan.Options{AllowPublish: allowPublish, ConfirmContainerID: confirm})
			if err != nil {
				return err
			}
			if !execute {
				return writeJSON(cmd.OutOrStdout(), map[string]any{"dryRun": true, "commands": commands})
			}
			results := make([]map[string]any, 0, len(commands))
			for _, compiled := range commands {
				result, err := rt.options.Runner.Run(cmd.Context(), rt.gtmBinary(cmd.Context()), compiled.Args...)
				if err != nil {
					return err
				}
				results = append(results, map[string]any{
					"command": compiled.Shell,
					"output":  parseJSONOrText(result.Stdout),
				})
			}
			return writeJSON(cmd.OutOrStdout(), map[string]any{"dryRun": false, "results": results})
		},
	}
	cmd.Flags().BoolVar(&execute, "execute", false, "Actually run the compiled upstream gtm commands")
	cmd.Flags().BoolVar(&allowPublish, "allow-publish", false, "Permit publishVersion actions")
	cmd.Flags().StringVar(&confirm, "confirm", "", "Container ID confirmation required for publishVersion")
	return cmd
}

func (rt *runtime) backupCmd() *cobra.Command {
	var accountID, containerID, outPath string
	var allowUnsafeOut bool
	cmd := &cobra.Command{
		Use:   "backup",
		Short: "Save the live GTM container version before risky changes",
		RunE: func(cmd *cobra.Command, args []string) error {
			if accountID == "" || containerID == "" || outPath == "" {
				return fmt.Errorf("--account-id, --container-id, and --out are required")
			}
			if err := guardArtifactPath(outPath, "backup", allowUnsafeOut); err != nil {
				return err
			}
			result, err := rt.options.Runner.Run(cmd.Context(), rt.gtmBinary(cmd.Context()), "versions", "live", "--account-id", accountID, "--container-id", containerID, "--output", "json")
			if err != nil {
				return err
			}
			if err := os.MkdirAll(filepath.Dir(outPath), 0o755); err != nil {
				return err
			}
			if err := os.WriteFile(outPath, []byte(result.Stdout), 0o600); err != nil {
				return err
			}
			return writeAny(cmd.OutOrStdout(), rt.asJSON, map[string]any{"path": outPath})
		},
	}
	cmd.Flags().StringVar(&accountID, "account-id", "", "GTM account ID")
	cmd.Flags().StringVar(&containerID, "container-id", "", "GTM container ID")
	cmd.Flags().StringVar(&outPath, "out", "", "Backup output path")
	cmd.Flags().BoolVar(&allowUnsafeOut, "allow-unsafe-out", false, "Allow writing a backup to a path that is easy to commit")
	return cmd
}

func (rt *runtime) rawCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:                "raw -- <gtm args...>",
		Short:              "Pass through to the upstream gtm CLI",
		DisableFlagParsing: true,
		Args:               cobra.ArbitraryArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			rawOptions, args, err := parseRawOptions(args)
			if err != nil {
				return err
			}
			if len(args) > 0 && args[0] == "--" {
				args = args[1:]
			}
			if len(args) == 0 {
				return fmt.Errorf("raw requires upstream gtm arguments")
			}
			if err := guardRaw(args, rawOptions.allowMutation, rawOptions.allowPublish, rawOptions.confirm); err != nil {
				return err
			}
			result, err := rt.options.Runner.Run(cmd.Context(), rt.gtmBinary(cmd.Context()), args...)
			if err != nil {
				return err
			}
			_, err = fmt.Fprint(cmd.OutOrStdout(), result.Stdout)
			return err
		},
	}
	return cmd
}

func (rt *runtime) guideCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "guide",
		Short: "Print the GTM Agent CLI playbook",
		RunE: func(cmd *cobra.Command, args []string) error {
			_, err := fmt.Fprint(cmd.OutOrStdout(), guideText)
			return err
		},
	}
}

func (rt *runtime) collectInventory(ctx context.Context, accountID, containerID, workspaceID string) (snapshot.Snapshot, error) {
	if accountID == "" || containerID == "" || workspaceID == "" {
		return snapshot.Snapshot{}, fmt.Errorf("--account-id, --container-id, and --workspace-id are required")
	}
	resources := map[string][]snapshot.Resource{}
	commands := []struct {
		kind string
		args []string
	}{
		{"accounts", []string{"accounts", "list", "--output", "json"}},
		{"containers", []string{"containers", "list", "--account-id", accountID, "--output", "json"}},
		{"workspaces", []string{"workspaces", "list", "--account-id", accountID, "--container-id", containerID, "--output", "json"}},
		{"tags", []string{"tags", "list", "--account-id", accountID, "--container-id", containerID, "--workspace-id", workspaceID, "--output", "json"}},
		{"triggers", []string{"triggers", "list", "--account-id", accountID, "--container-id", containerID, "--workspace-id", workspaceID, "--output", "json"}},
		{"variables", []string{"variables", "list", "--account-id", accountID, "--container-id", containerID, "--workspace-id", workspaceID, "--output", "json"}},
		{"builtInVariables", []string{"built-in-variables", "list", "--account-id", accountID, "--container-id", containerID, "--workspace-id", workspaceID, "--output", "json"}},
		{"versionHeaders", []string{"version-headers", "list", "--account-id", accountID, "--container-id", containerID, "--output", "json"}},
	}
	for _, command := range commands {
		result, err := rt.options.Runner.Run(ctx, rt.gtmBinary(ctx), command.args...)
		if err != nil {
			return snapshot.Snapshot{}, err
		}
		items, err := snapshot.ResourcesFromJSON(command.kind, []byte(result.Stdout))
		if err != nil {
			return snapshot.Snapshot{}, fmt.Errorf("%s inventory parse failed: %w", command.kind, err)
		}
		resources[command.kind] = items
	}
	return snapshot.New(accountID, containerID, workspaceID, resources), nil
}

func (rt *runtime) gtmBinary(ctx context.Context) string {
	if rt.options.GTMBinary != "gtm" {
		return rt.options.GTMBinary
	}
	if _, isFake := rt.options.Runner.(*runner.Fake); isFake {
		return rt.options.GTMBinary
	}
	if path, err := exec.LookPath("gtm"); err == nil {
		return path
	}
	result, err := rt.options.Runner.Run(ctx, "npm", "config", "get", "prefix")
	if err != nil {
		return rt.options.GTMBinary
	}
	candidate := filepath.Join(strings.TrimSpace(result.Stdout), "bin", "gtm")
	if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
		return candidate
	}
	return rt.options.GTMBinary
}

func guardRaw(args []string, allowMutation, allowPublish bool, confirm string) error {
	if len(args) < 2 {
		return nil
	}
	if hasHelpFlag(args) {
		return nil
	}
	resource, verb := args[0], args[1]
	mutating := map[string]bool{
		"create": true, "update": true, "delete": true, "revert": true, "enable": true, "disable": true,
		"sync": true, "publish": true, "set-latest": true, "reauthorize": true, "link": true,
	}
	if !mutating[verb] {
		return nil
	}
	if !allowMutation {
		return fmt.Errorf("raw mutating command %q requires --allow-mutation", strings.Join(args, " "))
	}
	if resource == "versions" && verb == "publish" {
		containerID := flagValue(args, "--container-id")
		if !allowPublish {
			return fmt.Errorf("raw publish requires --allow-publish and --confirm <container-id>")
		}
		if containerID == "" || confirm != containerID {
			return fmt.Errorf("raw publish confirmation mismatch: expected --confirm %s", containerID)
		}
	}
	return nil
}

func hasHelpFlag(args []string) bool {
	for _, arg := range args {
		if arg == "--help" || arg == "-h" || arg == "help" {
			return true
		}
	}
	return false
}

type rawOptions struct {
	allowMutation bool
	allowPublish  bool
	confirm       string
}

func parseRawOptions(args []string) (rawOptions, []string, error) {
	var options rawOptions
	rest := make([]string, 0, len(args))
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--allow-mutation":
			options.allowMutation = true
		case "--allow-publish":
			options.allowPublish = true
		case "--confirm":
			if i+1 >= len(args) {
				return rawOptions{}, nil, fmt.Errorf("--confirm requires a value")
			}
			options.confirm = args[i+1]
			i++
		default:
			rest = append(rest, args[i:]...)
			return options, rest, nil
		}
	}
	return options, rest, nil
}

func flagValue(args []string, name string) string {
	for i, arg := range args {
		if arg == name && i+1 < len(args) {
			return args[i+1]
		}
	}
	return ""
}

func guardArtifactPath(path, kind string, allowUnsafe bool) error {
	if allowUnsafe {
		return nil
	}
	absPath, err := filepath.Abs(path)
	if err != nil {
		return err
	}
	cwd, err := os.Getwd()
	if err != nil {
		return err
	}
	absCWD, err := filepath.Abs(cwd)
	if err != nil {
		return err
	}
	rel, err := filepath.Rel(absCWD, absPath)
	if err != nil || strings.HasPrefix(rel, "..") || filepath.IsAbs(rel) {
		return nil
	}
	rel = filepath.ToSlash(rel)
	if strings.HasPrefix(rel, kind+"s/") || strings.HasSuffix(rel, "."+kind+".json") {
		return nil
	}
	return fmt.Errorf("%s output path %q is inside the repo but not in %ss/ and does not end with .%s.json; use --allow-unsafe-out to override", kind, path, kind, kind)
}

func readSnapshot(path string) (snapshot.Snapshot, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return snapshot.Snapshot{}, err
	}
	var snap snapshot.Snapshot
	if err := json.Unmarshal(data, &snap); err != nil {
		return snapshot.Snapshot{}, err
	}
	return snap, nil
}

func validateComparableSnapshots(before, after snapshot.Snapshot) error {
	if before.SchemaVersion != after.SchemaVersion {
		return fmt.Errorf("snapshot schema mismatch: %q vs %q", before.SchemaVersion, after.SchemaVersion)
	}
	if before.AccountID != after.AccountID {
		return fmt.Errorf("snapshot account mismatch: %q vs %q", before.AccountID, after.AccountID)
	}
	if before.ContainerID != after.ContainerID {
		return fmt.Errorf("snapshot container mismatch: %q vs %q", before.ContainerID, after.ContainerID)
	}
	if before.WorkspaceID != after.WorkspaceID {
		return fmt.Errorf("snapshot workspace mismatch: %q vs %q", before.WorkspaceID, after.WorkspaceID)
	}
	return nil
}

func addScopeFlags(cmd *cobra.Command, accountID, containerID, workspaceID *string) {
	cmd.Flags().StringVar(accountID, "account-id", "", "GTM account ID")
	cmd.Flags().StringVar(containerID, "container-id", "", "GTM container ID")
	cmd.Flags().StringVar(workspaceID, "workspace-id", "", "GTM workspace ID")
}

func writeAny(w io.Writer, asJSON bool, value map[string]any) error {
	if asJSON {
		return writeJSON(w, value)
	}
	for key, item := range value {
		if _, err := fmt.Fprintf(w, "%s: %v\n", key, item); err != nil {
			return err
		}
	}
	return nil
}

func writeJSON(w io.Writer, value any) error {
	encoded, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	_, err = w.Write(append(encoded, '\n'))
	return err
}

func parseJSONOrText(raw string) any {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil
	}
	var value any
	if err := json.Unmarshal([]byte(raw), &value); err == nil {
		return value
	}
	return raw
}

const guideText = `GTM Agent CLI guide

Recommended loop:
1. Run: gtm-agent doctor --json
2. Snapshot before edits: gtm-agent snapshot --account-id <id> --container-id <id> --workspace-id <id> --out snapshots/before.json
3. Write a YAML plan with scoped actions.
4. Dry-run: gtm-agent apply plan.yaml --json
5. Execute only after inspection: gtm-agent apply plan.yaml --execute --json
6. Snapshot after edits and diff snapshots.
7. Publish only with both gates: --allow-publish --confirm <container-id>

Raw escape hatch:
  gtm-agent raw -- <any upstream gtm command>

Powered by @owntag/gtm-cli and the official Google Tag Manager API v2.
`

const planTemplate = `accountId: "123"
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
`
