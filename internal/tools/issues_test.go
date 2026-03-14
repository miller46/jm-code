package tools_test

import (
	"testing"

	"github.com/jack/go-cli/internal/db"
	"github.com/jack/go-cli/internal/tools"
)

func TestIssueQueueClient_Query(t *testing.T) {
	store, err := db.Open(":memory:")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer store.Close()

	// Insert test issues
	store.UpsertWorkflowItem(db.WorkflowItem{
		ID: "r#issue#1", Type: "issue", Repo: "owner/repo", Number: 1,
		Title: "Bug fix", Status: "open", Action: "needs_dev",
	})
	store.UpsertWorkflowItem(db.WorkflowItem{
		ID: "r#issue#2", Type: "issue", Repo: "owner/repo", Number: 2,
		Title: "Done", Status: "closed", Action: "none",
	})
	store.UpsertWorkflowItem(db.WorkflowItem{
		ID: "r#issue#3", Type: "issue", Repo: "other/repo", Number: 3,
		Title: "Other repo", Status: "open", Action: "needs_dev",
	})

	client := &tools.IssueQueueClient{Store: store}

	t.Run("all repos", func(t *testing.T) {
		resp, err := client.Query(10, nil)
		if err != nil {
			t.Fatalf("Query: %v", err)
		}
		if len(resp.Issues) != 2 {
			t.Errorf("len(Issues) = %d, want 2", len(resp.Issues))
		}
	})

	t.Run("filtered by repo", func(t *testing.T) {
		resp, err := client.Query(10, []string{"owner/repo"})
		if err != nil {
			t.Fatalf("Query: %v", err)
		}
		if len(resp.Issues) != 1 {
			t.Errorf("len(Issues) = %d, want 1", len(resp.Issues))
		}
	})

	t.Run("limit", func(t *testing.T) {
		resp, err := client.Query(1, nil)
		if err != nil {
			t.Fatalf("Query: %v", err)
		}
		if len(resp.Issues) != 1 {
			t.Errorf("len(Issues) = %d, want 1", len(resp.Issues))
		}
	})
}

func TestPRQueueClient_Query(t *testing.T) {
	store, err := db.Open(":memory:")
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer store.Close()

	store.UpsertWorkflowItem(db.WorkflowItem{
		ID: "r#pr#1", Type: "pr", Repo: "owner/repo", Number: 1,
		Title: "PR needs review", Status: "pending_review", Action: "needs_review",
		HeadSHA: "sha1", HeadRefName: "feature/test",
		ReviewerSHAsJSON: `{"rev1":"sha1"}`, ReviewerDispatchSHAsJSON: "{}",
	})
	store.UpsertWorkflowItem(db.WorkflowItem{
		ID: "r#pr#2", Type: "pr", Repo: "owner/repo", Number: 2,
		Title: "PR ready", Status: "approved", Action: "ready_to_merge",
		HeadSHA: "sha2", ReviewerSHAsJSON: "{}", ReviewerDispatchSHAsJSON: "{}",
	})

	client := &tools.PRQueueClient{Store: store}

	t.Run("needs_review", func(t *testing.T) {
		resp, err := client.Query("needs_review", 10, nil)
		if err != nil {
			t.Fatalf("Query: %v", err)
		}
		if len(resp.PRs) != 1 {
			t.Fatalf("len(PRs) = %d, want 1", len(resp.PRs))
		}
		if resp.PRs[0].PRNumber != 1 {
			t.Errorf("PRNumber = %d, want 1", resp.PRs[0].PRNumber)
		}
		if resp.PRs[0].DispatchType != "review" {
			t.Errorf("DispatchType = %q, want %q", resp.PRs[0].DispatchType, "review")
		}
	})

	t.Run("ready_to_merge", func(t *testing.T) {
		resp, err := client.Query("ready_to_merge", 10, nil)
		if err != nil {
			t.Fatalf("Query: %v", err)
		}
		if len(resp.PRs) != 1 {
			t.Fatalf("len(PRs) = %d, want 1", len(resp.PRs))
		}
		if resp.PRs[0].PRNumber != 2 {
			t.Errorf("PRNumber = %d, want 2", resp.PRs[0].PRNumber)
		}
	})
}
