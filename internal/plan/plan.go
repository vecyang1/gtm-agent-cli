package plan

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strconv"
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
	Kind             string         `json:"kind" yaml:"kind"`
	Name             string         `json:"name,omitempty" yaml:"name,omitempty"`
	Type             string         `json:"type,omitempty" yaml:"type,omitempty"`
	Types            []string       `json:"types,omitempty" yaml:"types,omitempty"`
	Config           map[string]any `json:"config,omitempty" yaml:"config,omitempty"`
	FiringTriggerID  *string        `json:"firingTriggerId,omitempty" yaml:"firingTriggerId,omitempty"`
	FiringTriggerIDs *[]string      `json:"firingTriggerIds,omitempty" yaml:"firingTriggerIds,omitempty"`
	VersionID        string         `json:"versionId,omitempty" yaml:"versionId,omitempty"`
	Notes            string         `json:"notes,omitempty" yaml:"notes,omitempty"`
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
	if err := validateActionFieldNodes(raw); err != nil {
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
		if action.Config != nil {
			encoded, err := encodeConfig(action.Config)
			if err != nil {
				return nil, err
			}
			args = append(args, "--config", encoded)
		}
		args = append(args, workspaceBase...)
		return withOutput(args), nil
	case "createVariable":
		args := []string{"variables", "create", "--name", action.Name, "--type", action.Type}
		if action.Config != nil {
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
		if action.Config != nil {
			encoded, err := encodeConfig(action.Config)
			if err != nil {
				return nil, err
			}
			args = append(args, "--config", encoded)
		}
		triggerIDs, err := firingTriggerIDs(action)
		if err != nil {
			return nil, err
		}
		if len(triggerIDs) > 0 {
			args = append(args, "--firing-trigger-id", strings.Join(triggerIDs, ","))
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
	if action.Kind != "createTag" && (action.FiringTriggerID != nil || action.FiringTriggerIDs != nil) {
		return fmt.Errorf("firingTriggerId and firingTriggerIds are only valid for createTag")
	}
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
		if action.Config != nil {
			if err := validateConfigKeys(action); err != nil {
				return err
			}
			if _, err := encodeConfig(action.Config); err != nil {
				return fmt.Errorf("config must be valid JSON: %w", err)
			}
		}
		if action.Kind == "createTag" {
			if _, err := firingTriggerIDs(action); err != nil {
				return err
			}
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

func validateConfigKeys(action Action) error {
	reserved := map[string]struct{}{
		"name": {},
		"type": {},
	}
	if action.Kind == "createTag" {
		reserved["firingTriggerId"] = struct{}{}
		reserved["firingTriggerIds"] = struct{}{}
	}
	for key := range action.Config {
		if _, found := reserved[key]; found {
			return fmt.Errorf("config key %q must use the declarative action field instead", key)
		}
	}
	return nil
}

func firingTriggerIDs(action Action) ([]string, error) {
	if action.FiringTriggerID != nil && action.FiringTriggerIDs != nil {
		return nil, fmt.Errorf("use either firingTriggerId or firingTriggerIds, not both")
	}
	var ids []string
	switch {
	case action.FiringTriggerID != nil:
		ids = []string{*action.FiringTriggerID}
	case action.FiringTriggerIDs != nil:
		ids = append([]string{}, (*action.FiringTriggerIDs)...)
		if len(ids) == 0 {
			return nil, fmt.Errorf("firingTriggerIds must contain at least one ID")
		}
	default:
		return nil, nil
	}
	seen := make(map[string]struct{}, len(ids))
	for i, id := range ids {
		if strings.TrimSpace(id) != id || id == "" {
			return nil, fmt.Errorf("firing trigger ID at index %d must be a non-empty decimal ID without surrounding whitespace", i)
		}
		if id[0] == '0' {
			return nil, fmt.Errorf("firing trigger ID at index %d must be a positive decimal ID", i)
		}
		if _, err := strconv.ParseUint(id, 10, 64); err != nil {
			return nil, fmt.Errorf("firing trigger ID at index %d must be a positive decimal ID", i)
		}
		if _, duplicate := seen[id]; duplicate {
			return nil, fmt.Errorf("firing trigger ID %q is duplicated", id)
		}
		seen[id] = struct{}{}
	}
	return ids, nil
}

func validateActionFieldNodes(raw []byte) error {
	var document yaml.Node
	if err := yaml.Unmarshal(raw, &document); err != nil {
		return err
	}
	if len(document.Content) != 1 || document.Content[0].Kind != yaml.MappingNode {
		return nil
	}
	root := document.Content[0]
	for i := 0; i+1 < len(root.Content); i += 2 {
		if root.Content[i].Value != "actions" {
			continue
		}
		actions := root.Content[i+1]
		if actions.Kind != yaml.SequenceNode {
			return nil
		}
		for actionIndex, action := range actions.Content {
			if action.Kind != yaml.MappingNode {
				continue
			}
			for fieldIndex := 0; fieldIndex+1 < len(action.Content); fieldIndex += 2 {
				name := action.Content[fieldIndex].Value
				value := action.Content[fieldIndex+1]
				switch name {
				case "type":
					if value.Kind != yaml.ScalarNode || value.Tag != "!!str" {
						return fmt.Errorf("actions[%d]: type must be a string", actionIndex)
					}
				case "firingTriggerId":
					if value.Kind != yaml.ScalarNode || value.Tag != "!!str" {
						return fmt.Errorf("actions[%d]: firingTriggerId must be a quoted string", actionIndex)
					}
				case "firingTriggerIds":
					if value.Kind != yaml.SequenceNode {
						return fmt.Errorf("actions[%d]: firingTriggerIds must be a list of quoted strings", actionIndex)
					}
					for idIndex, id := range value.Content {
						if id.Kind != yaml.ScalarNode || id.Tag != "!!str" {
							return fmt.Errorf("actions[%d]: firingTriggerIds[%d] must be a quoted string", actionIndex, idIndex)
						}
					}
				}
			}
		}
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
