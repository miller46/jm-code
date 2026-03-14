package db

import "time"

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
