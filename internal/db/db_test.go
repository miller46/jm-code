package db_test

import (
	"encoding/json"
	"testing"
	"time"

	"github.com/jack/go-cli/internal/db"
)

func TestOpen_CreatesSchema(t *testing.T) {
	store, err := db.Open(":memory:")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer store.Close()

	// Verify all tables exist
	tables := []string{"workflow_items", "locks", "sync_log", "dispatch_events", "agent_selections"}
	for _, table := range tables {
		var name string
		err := store.DB().QueryRow(
			"SELECT name FROM sqlite_master WHERE type='table' AND name=?", table,
		).Scan(&name)
		if err != nil {
			t.Errorf("table %q not found: %v", table, err)
		}
	}
}

func TestUpsertWorkflowItem(t *testing.T) {
	store, err := db.Open(":memory:")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer store.Close()

	item := db.WorkflowItem{
		ID:            "owner/repo#issue#1",
		Type:          "issue",
		Repo:          "owner/repo",
		Number:        1,
		Title:         "Test issue",
		GitHubState:   "open",
		RepoScopedID: "issue#1",
		Status:        "open",
		Action:        "needs_dev",
		MaxIterations: 3,
		CreatedAt:     db.Now(),
		UpdatedAt:     db.Now(),
		LastSync:      db.Now(),
	}

	if err := store.UpsertWorkflowItem(item); err != nil {
		t.Fatalf("UpsertWorkflowItem: %v", err)
	}

	got, err := store.GetWorkflowItem("owner/repo#issue#1")
	if err != nil {
		t.Fatalf("GetWorkflowItem: %v", err)
	}
	if got.Title != "Test issue" {
		t.Errorf("Title = %q, want %q", got.Title, "Test issue")
	}
	if got.Action != "needs_dev" {
		t.Errorf("Action = %q, want %q", got.Action, "needs_dev")
	}
}

func TestUpsertWorkflowItem_Update(t *testing.T) {
	store, err := db.Open(":memory:")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer store.Close()

	item := db.WorkflowItem{
		ID:     "owner/repo#pr#5",
		Type:   "pr",
		Repo:   "owner/repo",
		Number: 5,
		Title:  "Original",
		Status: "pending_review",
		Action: "needs_review",
	}
	store.UpsertWorkflowItem(item)

	item.Title = "Updated"
	item.Status = "approved"
	item.Action = "ready_to_merge"
	store.UpsertWorkflowItem(item)

	got, err := store.GetWorkflowItem("owner/repo#pr#5")
	if err != nil {
		t.Fatalf("GetWorkflowItem: %v", err)
	}
	if got.Title != "Updated" {
		t.Errorf("Title = %q, want %q", got.Title, "Updated")
	}
	if got.Action != "ready_to_merge" {
		t.Errorf("Action = %q, want %q", got.Action, "ready_to_merge")
	}
}

func TestUpdateItemStatus(t *testing.T) {
	store, err := db.Open(":memory:")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer store.Close()

	item := db.WorkflowItem{
		ID:     "owner/repo#issue#10",
		Type:   "issue",
		Repo:   "owner/repo",
		Number: 10,
		Title:  "Test issue",
		Status: "open",
		Action: "needs_dev",
	}
	store.UpsertWorkflowItem(item)

	if err := store.UpdateItemStatus("owner/repo#issue#10", "in_progress", "none"); err != nil {
		t.Fatalf("UpdateItemStatus: %v", err)
	}

	got, err := store.GetWorkflowItem("owner/repo#issue#10")
	if err != nil {
		t.Fatalf("GetWorkflowItem: %v", err)
	}
	if got.Status != "in_progress" {
		t.Errorf("Status = %q, want %q", got.Status, "in_progress")
	}
	if got.Action != "none" {
		t.Errorf("Action = %q, want %q", got.Action, "none")
	}
}

func TestQueryWorkflowItems(t *testing.T) {
	store, err := db.Open(":memory:")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer store.Close()

	items := []db.WorkflowItem{
		{ID: "r#issue#1", Type: "issue", Repo: "r", Number: 1, Action: "needs_dev"},
		{ID: "r#issue#2", Type: "issue", Repo: "r", Number: 2, Action: "none"},
		{ID: "r#pr#3", Type: "pr", Repo: "r", Number: 3, Action: "needs_review"},
	}
	for _, item := range items {
		store.UpsertWorkflowItem(item)
	}

	got, err := store.QueryWorkflowItems("issue", "needs_dev", "", 10)
	if err != nil {
		t.Fatalf("QueryWorkflowItems: %v", err)
	}
	if len(got) != 1 {
		t.Fatalf("len = %d, want 1", len(got))
	}
	if got[0].ID != "r#issue#1" {
		t.Errorf("ID = %q, want %q", got[0].ID, "r#issue#1")
	}
}

func TestQueryWorkflowItems_ByRepo(t *testing.T) {
	store, err := db.Open(":memory:")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer store.Close()

	store.UpsertWorkflowItem(db.WorkflowItem{ID: "a/b#issue#1", Type: "issue", Repo: "a/b", Number: 1, Action: "needs_dev"})
	store.UpsertWorkflowItem(db.WorkflowItem{ID: "c/d#issue#2", Type: "issue", Repo: "c/d", Number: 2, Action: "needs_dev"})

	got, err := store.QueryWorkflowItems("issue", "needs_dev", "a/b", 10)
	if err != nil {
		t.Fatalf("QueryWorkflowItems: %v", err)
	}
	if len(got) != 1 {
		t.Fatalf("len = %d, want 1", len(got))
	}
}

func TestMarkDispatched(t *testing.T) {
	store, err := db.Open(":memory:")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer store.Close()

	store.UpsertWorkflowItem(db.WorkflowItem{
		ID: "r#pr#1", Type: "pr", Repo: "r", Number: 1,
		Action: "needs_review", HeadSHA: "abc123",
	})

	if err := store.MarkDispatched("r#pr#1", "review", "abc123"); err != nil {
		t.Fatalf("MarkDispatched: %v", err)
	}

	got, _ := store.GetWorkflowItem("r#pr#1")
	if got.LastReviewDispatchSHA != "abc123" {
		t.Errorf("LastReviewDispatchSHA = %q, want %q", got.LastReviewDispatchSHA, "abc123")
	}
}

func TestMarkDispatched_Fix_IncrementsIteration(t *testing.T) {
	store, err := db.Open(":memory:")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer store.Close()

	store.UpsertWorkflowItem(db.WorkflowItem{
		ID: "r#pr#1", Type: "pr", Repo: "r", Number: 1,
		Action: "needs_fix", Iteration: 0,
	})

	store.MarkDispatched("r#pr#1", "fix", "sha1")
	got, _ := store.GetWorkflowItem("r#pr#1")
	if got.Iteration != 1 {
		t.Errorf("Iteration = %d, want 1", got.Iteration)
	}
	if got.LastFixDispatchSHA != "sha1" {
		t.Errorf("LastFixDispatchSHA = %q, want %q", got.LastFixDispatchSHA, "sha1")
	}
}

func TestMarkReviewerDispatched(t *testing.T) {
	store, err := db.Open(":memory:")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer store.Close()

	store.UpsertWorkflowItem(db.WorkflowItem{
		ID: "r#pr#1", Type: "pr", Repo: "r", Number: 1,
		ReviewerDispatchSHAsJSON: "{}",
	})

	if err := store.MarkReviewerDispatched("r#pr#1", "rev1", "sha1"); err != nil {
		t.Fatalf("MarkReviewerDispatched: %v", err)
	}

	got, _ := store.GetWorkflowItem("r#pr#1")
	var shas map[string]string
	json.Unmarshal([]byte(got.ReviewerDispatchSHAsJSON), &shas)
	if shas["rev1"] != "sha1" {
		t.Errorf("reviewer dispatch sha = %q, want %q", shas["rev1"], "sha1")
	}
}

func TestAcquireLock(t *testing.T) {
	store, err := db.Open(":memory:")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer store.Close()

	ok, err := store.AcquireLock("test-lock", "owner1", 300*time.Second)
	if err != nil {
		t.Fatalf("AcquireLock: %v", err)
	}
	if !ok {
		t.Error("expected lock acquisition to succeed")
	}

	// Second acquire should fail
	ok2, err := store.AcquireLock("test-lock", "owner2", 300*time.Second)
	if err != nil {
		t.Fatalf("AcquireLock: %v", err)
	}
	if ok2 {
		t.Error("expected second lock acquisition to fail")
	}
}

func TestInsertSyncLog(t *testing.T) {
	store, err := db.Open(":memory:")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer store.Close()

	id, err := store.InsertSyncLog(db.Now(), db.Now(), 42, "null")
	if err != nil {
		t.Fatalf("InsertSyncLog: %v", err)
	}
	if id == 0 {
		t.Error("expected non-zero sync log ID")
	}
}

func TestInsertDispatchEvent(t *testing.T) {
	store, err := db.Open(":memory:")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer store.Close()

	err = store.InsertDispatchEvent(db.DispatchEvent{
		ItemID:       "r#pr#1",
		StepID:       "review",
		HeadSHA:      "abc",
		Agent:        "code-snob",
		Status:       "dispatched",
		DispatchedAt: db.Now(),
	})
	if err != nil {
		t.Fatalf("InsertDispatchEvent: %v", err)
	}
}

func TestCacheAgentSelection(t *testing.T) {
	store, err := db.Open(":memory:")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer store.Close()

	err = store.CacheAgentSelection("owner/repo", 1, "backend-dev")
	if err != nil {
		t.Fatalf("CacheAgentSelection: %v", err)
	}

	agent, err := store.GetCachedAgentSelection("owner/repo", 1)
	if err != nil {
		t.Fatalf("GetCachedAgentSelection: %v", err)
	}
	if agent != "backend-dev" {
		t.Errorf("agent = %q, want %q", agent, "backend-dev")
	}
}

func TestPruneStaleItems(t *testing.T) {
	store, err := db.Open(":memory:")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer store.Close()

	// Insert 3 PRs for the same repo: one still open, one stale with active action, one already "none".
	for _, item := range []db.WorkflowItem{
		{ID: "r#pr#1", Type: "pr", Repo: "r", Number: 1, Status: "approved", Action: "ready_to_merge"},
		{ID: "r#pr#2", Type: "pr", Repo: "r", Number: 2, Status: "pending_review", Action: "needs_review"},
		{ID: "r#pr#3", Type: "pr", Repo: "r", Number: 3, Status: "merged", Action: "none"},
		{ID: "other#pr#1", Type: "pr", Repo: "other", Number: 1, Status: "approved", Action: "ready_to_merge"},
	} {
		if err := store.UpsertWorkflowItem(item); err != nil {
			t.Fatalf("UpsertWorkflowItem(%s): %v", item.ID, err)
		}
	}

	// Only PR #1 was seen in this sync cycle.
	pruned, err := store.PruneStaleItems("r", []string{"r#pr#1"})
	if err != nil {
		t.Fatalf("PruneStaleItems: %v", err)
	}
	// PR #2 had an active action and was not seen -> pruned.
	// PR #3 already had action=none -> not pruned.
	if pruned != 1 {
		t.Errorf("pruned = %d, want 1", pruned)
	}

	// PR #2 should now have action=none.
	item, err := store.GetWorkflowItem("r#pr#2")
	if err != nil {
		t.Fatalf("GetWorkflowItem: %v", err)
	}
	if item.Action != "none" {
		t.Errorf("action = %q, want 'none'", item.Action)
	}

	// PR #1 (seen) should be unchanged.
	item, err = store.GetWorkflowItem("r#pr#1")
	if err != nil {
		t.Fatalf("GetWorkflowItem: %v", err)
	}
	if item.Action != "ready_to_merge" {
		t.Errorf("action = %q, want 'ready_to_merge'", item.Action)
	}

	// Other repo should be unaffected.
	item, err = store.GetWorkflowItem("other#pr#1")
	if err != nil {
		t.Fatalf("GetWorkflowItem: %v", err)
	}
	if item.Action != "ready_to_merge" {
		t.Errorf("other repo action = %q, want 'ready_to_merge'", item.Action)
	}
}

func TestGetCachedAgentSelection_NotFound(t *testing.T) {
	store, err := db.Open(":memory:")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer store.Close()

	agent, err := store.GetCachedAgentSelection("owner/repo", 99)
	if err != nil {
		t.Fatalf("GetCachedAgentSelection: %v", err)
	}
	if agent != "" {
		t.Errorf("agent = %q, want empty", agent)
	}
}
