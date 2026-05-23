package plan

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strings"

	"gopkg.in/yaml.v3"
)

type Plan struct {
	AccountID   string   `json:"accountId" yaml:"accountId"`
	ContainerID string   `json:"containerId" yaml:"containerId"`
	WorkspaceID string   `json:"workspaceId" yaml:"workspaceId"`
	Actions     []Action `json:"actions" yaml:"actions"`
}

type Action struct {
	Kind      string         `json:"kind" yaml:"kind"`
	Name      string         `json:"name,omitempty" yaml:"name,omitempty"`
	Type      string         `json:"type,omitempty" yaml:"type,omitempty"`
	Types     []string       `json:"types,omitempty" yaml:"types,omitempty"`
	Config    map[string]any `json:"config,omitempty" yaml:"config,omitempty"`
	VersionID string         `json:"versionId,omitempty" yaml:"versionId,omitempty"`
	Notes     string         `json:"notes,omitempty" yaml:"notes,omitempty"`
}

type Options struct {
	AllowPublish       bool
	ConfirmContainerID string
}

type Command struct {
	Args   []string `json:"args"`
	Shell  string   `json:"shell"`
	Mutate bool     `json:"mutate"`
}

func Parse(raw []byte) (Plan, error) {
	var p Plan
	decoder := yaml.NewDecoder(bytes.NewReader(raw))
	decoder.KnownFields(true)
	if err := decoder.Decode(&p); err != nil {
		return Plan{}, err
	}
	if strings.TrimSpace(p.AccountID) == "" {
		return Plan{}, fmt.Errorf("accountId is required")
	}
	if strings.TrimSpace(p.ContainerID) == "" {
		return Plan{}, fmt.Errorf("containerId is required")
	}
	if strings.TrimSpace(p.WorkspaceID) == "" {
		return Plan{}, fmt.Errorf("workspaceId is required")
	}
	if len(p.Actions) == 0 {
		return Plan{}, fmt.Errorf("actions must contain at least one action")
	}
	for i, action := range p.Actions {
		if err := validateAction(action); err != nil {
			return Plan{}, fmt.Errorf("actions[%d]: %w", i, err)
		}
	}
	return p, nil
}

func (p Plan) Commands(options Options) ([]Command, error) {
	var commands []Command
	for _, action := range p.Actions {
		args, err := p.argsFor(action, options)
		if err != nil {
			return nil, err
		}
		commands = append(commands, Command{
			Args:   args,
			Shell:  "gtm " + shellJoin(args),
			Mutate: true,
		})
	}
	return commands, nil
}

func (p Plan) argsFor(action Action, options Options) ([]string, error) {
	base := []string{"--account-id", p.AccountID, "--container-id", p.ContainerID}
	workspaceBase := append(append([]string{}, base...), "--workspace-id", p.WorkspaceID)
	withOutput := func(args []string) []string {
		return append(args, "--output", "json")
	}
	switch action.Kind {
	case "enableBuiltInVariables":
		types := append([]string{}, action.Types...)
		args := []string{"built-in-variables", "enable", "--types", strings.Join(types, ",")}
		args = append(args, workspaceBase...)
		return withOutput(args), nil
	case "createTrigger":
		args := []string{"triggers", "create", "--name", action.Name, "--type", action.Type}
		args = append(args, workspaceBase...)
		return withOutput(args), nil
	case "createVariable":
		args := []string{"variables", "create", "--name", action.Name, "--type", action.Type}
		if len(action.Config) > 0 {
			encoded, err := encodeConfig(action.Config)
			if err != nil {
				return nil, err
			}
			args = append(args, "--config", encoded)
		}
		args = append(args, workspaceBase...)
		return withOutput(args), nil
	case "createTag":
		args := []string{"tags", "create", "--name", action.Name, "--type", action.Type}
		if len(action.Config) > 0 {
			encoded, err := encodeConfig(action.Config)
			if err != nil {
				return nil, err
			}
			args = append(args, "--config", encoded)
		}
		args = append(args, workspaceBase...)
		return withOutput(args), nil
	case "createVersion":
		args := []string{"versions", "create", "--name", action.Name}
		if action.Notes != "" {
			args = append(args, "--notes", action.Notes)
		}
		args = append(args, workspaceBase...)
		return withOutput(args), nil
	case "publishVersion":
		if !options.AllowPublish {
			return nil, fmt.Errorf("publishVersion requires --allow-publish and --confirm %s", p.ContainerID)
		}
		if options.ConfirmContainerID != p.ContainerID {
			return nil, fmt.Errorf("publishVersion confirmation mismatch: expected --confirm %s", p.ContainerID)
		}
		args := []string{"versions", "publish", "--version-id", action.VersionID}
		args = append(args, base...)
		return withOutput(args), nil
	default:
		return nil, fmt.Errorf("unsupported action kind %q", action.Kind)
	}
}

func validateAction(action Action) error {
	switch action.Kind {
	case "enableBuiltInVariables":
		if len(action.Types) == 0 {
			return fmt.Errorf("types is required")
		}
	case "createTrigger", "createVariable", "createTag":
		if strings.TrimSpace(action.Name) == "" {
			return fmt.Errorf("name is required")
		}
		if strings.TrimSpace(action.Type) == "" {
			return fmt.Errorf("type is required")
		}
	case "createVersion":
		if strings.TrimSpace(action.Name) == "" {
			return fmt.Errorf("name is required")
		}
	case "publishVersion":
		if strings.TrimSpace(action.VersionID) == "" {
			return fmt.Errorf("versionId is required")
		}
	default:
		return fmt.Errorf("unsupported action kind %q", action.Kind)
	}
	return nil
}

func encodeConfig(config map[string]any) (string, error) {
	encoded, err := json.Marshal(config)
	if err != nil {
		return "", err
	}
	return string(encoded), nil
}

func shellJoin(args []string) string {
	quoted := make([]string, 0, len(args))
	for _, arg := range args {
		if strings.ContainsAny(arg, " \t\n'\"{}[],:;&|$`<>\\!*?()") {
			quoted = append(quoted, "'"+strings.ReplaceAll(arg, "'", "'\\''")+"'")
			continue
		}
		quoted = append(quoted, arg)
	}
	return strings.Join(quoted, " ")
}
