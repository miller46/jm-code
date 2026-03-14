package db

import (
	"strings"
	"time"
)

type WorkflowItem struct {
	ID          string `json:"id"`
	Type        string `json:"type"`
	Repo        string `json:"repo"`
	Number      int    `json:"number"`
	Title       string `json:"title"`
	GitHubState string `json:"github_state"`
	RepoScopedID string `json:"repo_scoped_id"`

	Status string `json:"status"`
	Action string `json:"action"`

	HeadSHA              string `json:"head_sha"`
	HeadRefName          string `json:"head_ref_name"`
	LastReviewedSHA      string `json:"last_reviewed_sha"`
	ReviewsJSON          string `json:"reviews_json"`
	AllReviewersApproved bool   `json:"all_reviewers_approved"`
	AnyChangesRequested  bool   `json:"any_changes_requested"`
	SHAMatchesReview     bool   `json:"sha_matches_review"`
	HasConflicts         bool   `json:"has_conflicts"`

	ReviewerSHAsJSON         string `json:"reviewer_shas_json"`
	ReviewerDispatchSHAsJSON string `json:"reviewer_dispatch_shas_json"`

	LastReviewDispatchSHA    string `json:"last_review_dispatch_sha"`
	LastFixDispatchSHA       string `json:"last_fix_dispatch_sha"`
	LastMergeDispatchSHA     string `json:"last_merge_dispatch_sha"`
	LastConflictDispatchSHA  string `json:"last_conflict_dispatch_sha"`
	LastStatusFixDispatchSHA string `json:"last_status_fix_dispatch_sha"`
	LastHeadSHASeen          string `json:"last_head_sha_seen"`

	StatusCheckRollup string `json:"status_check_rollup"`
	LinkedIssueNumber int    `json:"linked_issue_number"`

	Iteration     int `json:"iteration"`
	MaxIterations int `json:"max_iterations"`

	AssignedAgent string `json:"assigned_agent"`
	LockExpires   string `json:"lock_expires"`

	CreatedAt string `json:"created_at"`
	UpdatedAt string `json:"updated_at"`
	LastSync  string `json:"last_sync"`
}

type Lock struct {
	Name      string `json:"name"`
	Owner     string `json:"owner"`
	ExpiresAt string `json:"expires_at"`
}

type SyncLog struct {
	ID          int    `json:"id"`
	StartedAt   string `json:"started_at"`
	FinishedAt  string `json:"finished_at"`
	ItemsSynced int    `json:"items_synced"`
	Errors      string `json:"errors"`
}

type DispatchEvent struct {
	ID           int    `json:"id"`
	ItemID       string `json:"item_id"`
	StepID       string `json:"step_id"`
	HeadSHA      string `json:"head_sha"`
	Agent        string `json:"agent"`
	Status       string `json:"status"`
	DispatchedAt string `json:"dispatched_at"`
}

type AgentSelection struct {
	ID        int    `json:"id"`
	Repo      string `json:"repo"`
	Number    int    `json:"number"`
	AgentID   string `json:"agent_id"`
	CreatedAt string `json:"created_at"`
}

func Now() string {
	return time.Now().UTC().Format(time.RFC3339)
}

// workflowItemColumns is the single source of truth for column ordering.
const workflowItemColumns = `id, type, repo, number, title, github_state, repo_scoped_id,
	status, action,
	head_sha, head_ref_name, last_reviewed_sha, reviews_json,
	all_reviewers_approved, any_changes_requested, sha_matches_review, has_conflicts,
	reviewer_shas_json, reviewer_dispatch_shas_json,
	last_review_dispatch_sha, last_fix_dispatch_sha, last_merge_dispatch_sha,
	last_conflict_dispatch_sha, last_status_fix_dispatch_sha, last_head_sha_seen,
	status_check_rollup, linked_issue_number,
	iteration, max_iterations,
	assigned_agent, lock_expires,
	created_at, updated_at, last_sync`

// workflowItemPlaceholders is the matching ? list for workflowItemColumns.
var workflowItemPlaceholders = func() string {
	n := strings.Count(workflowItemColumns, ",") + 1
	return strings.Join(strings.Split(strings.Repeat("?,", n), ",")[:n], ", ")
}()

// values returns all field values in the same order as workflowItemColumns.
func (w *WorkflowItem) values() []any {
	return []any{
		w.ID, w.Type, w.Repo, w.Number, w.Title, w.GitHubState, w.RepoScopedID,
		w.Status, w.Action,
		w.HeadSHA, w.HeadRefName, w.LastReviewedSHA, w.ReviewsJSON,
		w.AllReviewersApproved, w.AnyChangesRequested, w.SHAMatchesReview, w.HasConflicts,
		w.ReviewerSHAsJSON, w.ReviewerDispatchSHAsJSON,
		w.LastReviewDispatchSHA, w.LastFixDispatchSHA, w.LastMergeDispatchSHA,
		w.LastConflictDispatchSHA, w.LastStatusFixDispatchSHA, w.LastHeadSHASeen,
		w.StatusCheckRollup, w.LinkedIssueNumber,
		w.Iteration, w.MaxIterations,
		w.AssignedAgent, w.LockExpires,
		w.CreatedAt, w.UpdatedAt, w.LastSync,
	}
}

// scanDest returns pointers to all fields in the same order as workflowItemColumns.
func (w *WorkflowItem) scanDest() []any {
	return []any{
		&w.ID, &w.Type, &w.Repo, &w.Number, &w.Title, &w.GitHubState, &w.RepoScopedID,
		&w.Status, &w.Action,
		&w.HeadSHA, &w.HeadRefName, &w.LastReviewedSHA, &w.ReviewsJSON,
		&w.AllReviewersApproved, &w.AnyChangesRequested, &w.SHAMatchesReview, &w.HasConflicts,
		&w.ReviewerSHAsJSON, &w.ReviewerDispatchSHAsJSON,
		&w.LastReviewDispatchSHA, &w.LastFixDispatchSHA, &w.LastMergeDispatchSHA,
		&w.LastConflictDispatchSHA, &w.LastStatusFixDispatchSHA, &w.LastHeadSHASeen,
		&w.StatusCheckRollup, &w.LinkedIssueNumber,
		&w.Iteration, &w.MaxIterations,
		&w.AssignedAgent, &w.LockExpires,
		&w.CreatedAt, &w.UpdatedAt, &w.LastSync,
	}
}
