package snapshot

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"time"
)

type Snapshot struct {
	SchemaVersion string                `json:"schemaVersion"`
	CreatedAt     time.Time             `json:"createdAt"`
	AccountID     string                `json:"accountId"`
	ContainerID   string                `json:"containerId"`
	WorkspaceID   string                `json:"workspaceId"`
	Resources     map[string][]Resource `json:"resources"`
}

type Resource struct {
	Kind        string         `json:"kind"`
	ID          string         `json:"id"`
	Name        string         `json:"name,omitempty"`
	Type        string         `json:"type,omitempty"`
	Fingerprint string         `json:"fingerprint"`
	Raw         map[string]any `json:"raw,omitempty"`
}

type DiffResult struct {
	Added   []Resource        `json:"added"`
	Removed []Resource        `json:"removed"`
	Changed []ChangedResource `json:"changed"`
}

type ChangedResource struct {
	Before Resource `json:"before"`
	After  Resource `json:"after"`
}

func New(accountID, containerID, workspaceID string, resources map[string][]Resource) Snapshot {
	if resources == nil {
		resources = map[string][]Resource{}
	}
	for kind := range resources {
		SortResources(resources[kind])
	}
	return Snapshot{
		SchemaVersion: "1",
		CreatedAt:     time.Now().UTC(),
		AccountID:     accountID,
		ContainerID:   containerID,
		WorkspaceID:   workspaceID,
		Resources:     resources,
	}
}

func ResourcesFromJSON(kind string, raw []byte) ([]Resource, error) {
	var items []map[string]any
	if len(strings.TrimSpace(string(raw))) == 0 {
		return nil, nil
	}
	if err := json.Unmarshal(raw, &items); err != nil {
		var envelope map[string][]map[string]any
		if err2 := json.Unmarshal(raw, &envelope); err2 != nil {
			return nil, err
		}
		for _, values := range envelope {
			items = values
			break
		}
	}
	resources := make([]Resource, 0, len(items))
	for _, item := range items {
		resource := Resource{
			Kind:        kind,
			ID:          resourceID(kind, item),
			Name:        stringField(item, "name"),
			Type:        firstStringField(item, "type", "tagType", "triggerType", "variableType"),
			Fingerprint: fingerprint(item),
			Raw:         item,
		}
		if resource.ID == "" {
			resource.ID = resource.Name
		}
		resources = append(resources, resource)
	}
	SortResources(resources)
	return resources, nil
}

func SortResources(resources []Resource) {
	sort.Slice(resources, func(i, j int) bool {
		if resources[i].Kind != resources[j].Kind {
			return resources[i].Kind < resources[j].Kind
		}
		return resources[i].ID < resources[j].ID
	})
}

func Diff(before, after Snapshot) DiffResult {
	result := DiffResult{}
	kinds := map[string]bool{}
	for kind := range before.Resources {
		kinds[kind] = true
	}
	for kind := range after.Resources {
		kinds[kind] = true
	}
	for kind := range kinds {
		left := index(before.Resources[kind])
		right := index(after.Resources[kind])
		for id, afterResource := range right {
			beforeResource, ok := left[id]
			if !ok {
				result.Added = append(result.Added, afterResource)
				continue
			}
			if beforeResource.Fingerprint != afterResource.Fingerprint || beforeResource.Name != afterResource.Name || beforeResource.Type != afterResource.Type {
				result.Changed = append(result.Changed, ChangedResource{Before: beforeResource, After: afterResource})
			}
		}
		for id, beforeResource := range left {
			if _, ok := right[id]; !ok {
				result.Removed = append(result.Removed, beforeResource)
			}
		}
	}
	SortResources(result.Added)
	SortResources(result.Removed)
	sort.Slice(result.Changed, func(i, j int) bool {
		if result.Changed[i].Before.Kind != result.Changed[j].Before.Kind {
			return result.Changed[i].Before.Kind < result.Changed[j].Before.Kind
		}
		return result.Changed[i].Before.ID < result.Changed[j].Before.ID
	})
	return result
}

func index(resources []Resource) map[string]Resource {
	out := make(map[string]Resource, len(resources))
	for _, resource := range resources {
		out[resource.ID] = resource
	}
	return out
}

func resourceID(kind string, item map[string]any) string {
	fields := map[string][]string{
		"accounts":          {"accountId", "path", "name"},
		"containers":        {"containerId", "path", "name"},
		"workspaces":        {"workspaceId", "path", "name"},
		"tags":              {"tagId", "path", "name"},
		"triggers":          {"triggerId", "path", "name"},
		"variables":         {"variableId", "path", "name"},
		"builtInVariables":  {"type", "path", "name"},
		"versionHeaders":    {"containerVersionId", "path", "name"},
		"containerVersions": {"containerVersionId", "path", "name"},
	}
	for _, field := range fields[kind] {
		if value := stringField(item, field); value != "" {
			return value
		}
	}
	return ""
}

func fingerprint(item map[string]any) string {
	encoded, err := json.Marshal(item)
	if err != nil {
		return fmt.Sprintf("marshal-error:%v", err)
	}
	sum := sha256.Sum256(encoded)
	return hex.EncodeToString(sum[:])
}

func stringField(item map[string]any, field string) string {
	value, ok := item[field]
	if !ok || value == nil {
		return ""
	}
	switch v := value.(type) {
	case string:
		return v
	case float64:
		return fmt.Sprintf("%.0f", v)
	default:
		return fmt.Sprintf("%v", v)
	}
}

func firstStringField(item map[string]any, fields ...string) string {
	for _, field := range fields {
		if value := stringField(item, field); value != "" {
			return value
		}
	}
	return ""
}
