package snapshot_test

import (
	"testing"

	"github.com/vecyang1/gtm-agent-cli/internal/snapshot"
)

func TestDiffSnapshotsReportsAddedRemovedAndChangedResources(t *testing.T) {
	before := snapshot.Snapshot{
		Resources: map[string][]snapshot.Resource{
			"tags": {
				{ID: "1", Name: "Old tag", Fingerprint: "same"},
				{ID: "2", Name: "Removed tag", Fingerprint: "remove"},
				{ID: "3", Name: "Changed tag", Fingerprint: "before"},
			},
		},
	}
	after := snapshot.Snapshot{
		Resources: map[string][]snapshot.Resource{
			"tags": {
				{ID: "1", Name: "Old tag", Fingerprint: "same"},
				{ID: "3", Name: "Changed tag", Fingerprint: "after"},
				{ID: "4", Name: "Added tag", Fingerprint: "add"},
			},
		},
	}

	diff := snapshot.Diff(before, after)
	if len(diff.Added) != 1 || diff.Added[0].Name != "Added tag" {
		t.Fatalf("unexpected added diff: %+v", diff.Added)
	}
	if len(diff.Removed) != 1 || diff.Removed[0].Name != "Removed tag" {
		t.Fatalf("unexpected removed diff: %+v", diff.Removed)
	}
	if len(diff.Changed) != 1 || diff.Changed[0].Before.Name != "Changed tag" {
		t.Fatalf("unexpected changed diff: %+v", diff.Changed)
	}
}

func TestDiffChangedOrderingIsStableAcrossKinds(t *testing.T) {
	before := snapshot.Snapshot{
		Resources: map[string][]snapshot.Resource{
			"triggers": {{Kind: "triggers", ID: "1", Name: "Trigger", Fingerprint: "before"}},
			"tags":     {{Kind: "tags", ID: "1", Name: "Tag", Fingerprint: "before"}},
		},
	}
	after := snapshot.Snapshot{
		Resources: map[string][]snapshot.Resource{
			"triggers": {{Kind: "triggers", ID: "1", Name: "Trigger", Fingerprint: "after"}},
			"tags":     {{Kind: "tags", ID: "1", Name: "Tag", Fingerprint: "after"}},
		},
	}

	diff := snapshot.Diff(before, after)
	if len(diff.Changed) != 2 {
		t.Fatalf("expected two changed resources, got %+v", diff.Changed)
	}
	if diff.Changed[0].Before.Kind != "tags" || diff.Changed[1].Before.Kind != "triggers" {
		t.Fatalf("changed diff order is not stable by kind/id: %+v", diff.Changed)
	}
}
