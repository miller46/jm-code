// Package github provides the state machine for syncing issues/PRs from GitHub.
package github

// ItemType distinguishes issues from pull requests.
type ItemType string

const (
	ItemTypeIssue ItemType = "issue"
	ItemTypePR    ItemType = "pr"
)

// Status represents the current state of a workflow item.
type Status string

const (
	// Issue statuses
	StatusOpen       Status = "open"
	StatusInProgress Status = "in_progress"
	StatusPRCreated  Status = "pr_created"
	StatusClosed     Status = "closed"

	// PR statuses
	StatusPendingReview    Status = "pending_review"
	StatusChangesRequested Status = "changes_requested"
	StatusApproved         Status = "approved"
	StatusMerged           Status = "merged"
	StatusConflicting      Status = "conflicting"
	StatusChecksFailing    Status = "checks_failing"
)

// Action represents the next action needed for a workflow item.
type Action string

const (
	ActionNone                   Action = "none"
	ActionNeedsDev               Action = "needs_dev"
	ActionNeedsReview            Action = "needs_review"
	ActionInReview               Action = "in_review"
	ActionNeedsFix               Action = "needs_fix"
	ActionNeedsConflictResolution Action = "needs_conflict_resolution"
	ActionNeedsStatusFix         Action = "needs_status_fix"
	ActionReadyToMerge           Action = "ready_to_merge"
	ActionMaxIterationsReached   Action = "max_iterations_reached"
	ActionDispatched             Action = "dispatched"
)

// ReviewState mirrors GitHub's review states.
type ReviewState string

const (
	ReviewApproved         ReviewState = "APPROVED"
	ReviewChangesRequested ReviewState = "CHANGES_REQUESTED"
	ReviewCommented        ReviewState = "COMMENTED"
	ReviewDismissed        ReviewState = "DISMISSED"
)

// Review represents a single PR review from the GraphQL response.
type Review struct {
	Author      string      `json:"author"`
	State       ReviewState `json:"state"`
	SubmittedAt string      `json:"submittedAt"`
	CommitOID   string      `json:"commitOid"`
}

// ReviewEvaluation is the result of evaluating all reviews on a PR.
type ReviewEvaluation struct {
	AllRequiredApproved    bool
	AnyChangesRequested    bool
	LatestReviewSHA        string
	LatestDecisionByReviewer map[string]ReviewState
	ReviewSHAByReviewer      map[string]string
}

// PRDetail represents the fields we need from a PR's GraphQL response.
type PRDetail struct {
	Number        int      `json:"number"`
	Title         string   `json:"title"`
	State         string   `json:"state"`       // "OPEN", "CLOSED", "MERGED"
	HeadRefOid    string   `json:"headRefOid"`
	HeadRefName   string   `json:"headRefName"`
	Mergeable     string   `json:"mergeable"`    // "MERGEABLE", "CONFLICTING", "UNKNOWN"
	MergeState    string   `json:"mergeStateStatus"`
	Body          string   `json:"body"`
	Author        string   `json:"author"`
	CreatedAt     string   `json:"createdAt"`
	UpdatedAt     string   `json:"updatedAt"`
	Reviews       []Review `json:"reviews"`
	StatusChecks  []StatusCheck `json:"statusChecks"`
}

// StatusCheck represents a CI check from statusCheckRollup.
type StatusCheck struct {
	TypeName   string `json:"__typename"` // "CheckRun" or "StatusContext"
	Name       string `json:"name"`       // for CheckRun
	Context    string `json:"context"`    // for StatusContext
	Conclusion string `json:"conclusion"` // for CheckRun: SUCCESS, FAILURE, etc.
	Status     string `json:"status"`     // for CheckRun: COMPLETED, IN_PROGRESS, etc.
	State      string `json:"state"`      // for StatusContext: SUCCESS, FAILURE, etc.
}

// Issue represents the fields we need from an issue's JSON output.
type Issue struct {
	Number    int      `json:"number"`
	Title     string   `json:"title"`
	State     string   `json:"state"` // "open", "closed"
	Labels    []string `json:"labels"`
	Body      string   `json:"body"`
	CreatedAt string   `json:"createdAt"`
	UpdatedAt string   `json:"updatedAt"`
}
