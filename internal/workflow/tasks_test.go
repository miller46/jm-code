package workflow_test

import (
	"testing"

	"github.com/jack/go-cli/internal/db"
)

func TestMergePR_UpdatesStatusToMerged(t *testing.T) {
	store, err := db.Open(":memory:")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer store.Close()

	// Insert a PR that is ready to merge.
	item := db.WorkflowItem{
		ID:                       "owner/repo#pr#42",
		Type:                     "pr",
		Repo:                     "owner/repo",
		Number:                   42,
		Title:                    "Test PR",
		GitHubState:              "open",
		RepoScopedID:             "pr#42",
		Status:                   "approved",
		Action:                   "ready_to_merge",
		HeadSHA:                  "abc123",
		ReviewerSHAsJSON:         "{}",
		ReviewerDispatchSHAsJSON: "{}",
		StatusCheckRollup:        "[]",
		MaxIterations:            3,
		CreatedAt:                db.Now(),
		UpdatedAt:                db.Now(),
		LastSync:                 db.Now(),
	}
	if err := store.UpsertWorkflowItem(item); err != nil {
		t.Fatalf("UpsertWorkflowItem: %v", err)
	}

	// Simulate what MergePRs does after a successful merge.
	store.MarkDispatched(item.ID, "merge", item.HeadSHA)
	store.UpdateItemStatus(item.ID, "merged", "none")

	// Verify the item is no longer returned for the ready_to_merge queue.
	items, err := store.QueryWorkflowItems("pr", "ready_to_merge", "", 10)
	if err != nil {
		t.Fatalf("QueryWorkflowItems: %v", err)
	}
	if len(items) != 0 {
		t.Fatalf("expected 0 items in ready_to_merge queue, got %d", len(items))
	}

	// Verify the item has merged status.
	got, err := store.GetWorkflowItem(item.ID)
	if err != nil {
		t.Fatalf("GetWorkflowItem: %v", err)
	}
	if got.Status != "merged" {
		t.Errorf("expected status 'merged', got %q", got.Status)
	}
	if got.Action != "none" {
		t.Errorf("expected action 'none', got %q", got.Action)
	}
}
