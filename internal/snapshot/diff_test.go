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

func TestParseAndDiffRawContainerVersionsIgnoresVolatileMetadata(t *testing.T) {
	beforeRaw := []byte(`{
		"accountId": "123",
		"containerId": "456",
		"containerVersionId": "56",
		"name": "Pause ad vendor tags",
		"tag": [
			{"tagId": "6", "name": "GA4 config", "type": "googtag", "fingerprint": "100", "path": "accounts/123/containers/456/versions/56/tags/6"},
			{"tagId": "128", "name": "Legacy Conversion", "type": "awct", "fingerprint": "101"},
			{"tagId": "74", "name": "Ad Vendor - Basket Tag", "type": "html", "paused": false, "fingerprint": "102"}
		],
		"trigger": [
			{"triggerId": "5", "name": "e-purchase", "type": "customEvent", "fingerprint": "200"}
		],
		"customTemplate": [
			{"templateId": "16", "name": "Social Pixel", "templateData": "v1", "fingerprint": "300"}
		],
		"folder": [
			{"folderId": "73", "name": "Ad Vendor", "fingerprint": "400"}
		]
	}`)
	afterRaw := []byte(`{
		"exportFormatVersion": 2,
		"containerVersion": {
			"accountId": "123",
			"containerId": "456",
			"containerVersionId": "57",
			"name": "Swap Conversion Tag",
			"tag": [
				{"tagId": "6", "name": "GA4 config", "type": "googtag", "fingerprint": "999", "path": "accounts/123/containers/456/versions/57/tags/6", "tagManagerUrl": "https://tagmanager.google.com/#/v57"},
				{"tagId": "74", "name": "Ad Vendor - Basket Tag", "type": "html", "paused": true, "fingerprint": "998"},
				{"tagId": "138", "name": "AW - Conversion Tag B", "type": "awud", "fingerprint": "997"}
			],
			"trigger": [
				{"triggerId": "5", "name": "e-purchase", "type": "customEvent", "fingerprint": "201"}
			],
			"customTemplate": [
				{"templateId": "16", "name": "Social Pixel", "templateData": "v1", "fingerprint": "301"}
			],
			"folder": [
				{"folderId": "73", "name": "Ad Vendor", "fingerprint": "401"}
			]
		}
	}`)

	before, err := snapshot.Parse(beforeRaw)
	if err != nil {
		t.Fatalf("parse before container version: %v", err)
	}
	after, err := snapshot.Parse(afterRaw)
	if err != nil {
		t.Fatalf("parse after container version: %v", err)
	}
	if before.SchemaVersion != snapshot.SchemaVersionContainerVersion || after.SchemaVersion != snapshot.SchemaVersionContainerVersion {
		t.Fatalf("unexpected schema versions: %q, %q", before.SchemaVersion, after.SchemaVersion)
	}
	diff := snapshot.Diff(before, after)
	if len(diff.Added) != 1 || diff.Added[0].ID != "138" || diff.Added[0].Name != "AW - Conversion Tag B" {
		t.Fatalf("expected AW - Conversion Tag B added, got %+v", diff.Added)
	}
	if len(diff.Removed) != 1 || diff.Removed[0].ID != "128" || diff.Removed[0].Name != "Legacy Conversion" {
		t.Fatalf("expected Legacy Conversion removed, got %+v", diff.Removed)
	}
	if len(diff.Changed) != 1 || diff.Changed[0].After.ID != "74" {
		t.Fatalf("expected only tag 74 (paused flip) changed without volatile metadata noise, got %+v", diff.Changed)
	}
}

func TestParseRejectsUnrecognizedJSONSchema(t *testing.T) {
	if _, err := snapshot.Parse([]byte(`{"hello":"world"}`)); err == nil {
		t.Fatalf("expected unrecognized JSON schema error")
	}
}
