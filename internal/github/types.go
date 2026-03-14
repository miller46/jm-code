package github

type ItemType string

const (
	ItemTypeIssue ItemType = "issue"
	ItemTypePR    ItemType = "pr"
)

type Status string

const (
	StatusOpen       Status = "open"
	StatusInProgress Status = "in_progress"
	StatusPRCreated  Status = "pr_created"
	StatusClosed     Status = "closed"

	StatusPendingReview    Status = "pending_review"
	StatusChangesRequested Status = "changes_requested"
	StatusApproved         Status = "approved"
	StatusMerged           Status = "merged"
	StatusConflicting      Status = "conflicting"
	StatusChecksFailing    Status = "checks_failing"
)

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

type ReviewState string

const (
	ReviewApproved         ReviewState = "APPROVED"
	ReviewChangesRequested ReviewState = "CHANGES_REQUESTED"
	ReviewCommented        ReviewState = "COMMENTED"
	ReviewDismissed        ReviewState = "DISMISSED"
)

type Review struct {
	Author      string      `json:"author"`
	State       ReviewState `json:"state"`
	SubmittedAt string      `json:"submittedAt"`
	CommitOID   string      `json:"commitOid"`
}

type ReviewEvaluation struct {
	AllRequiredApproved    bool
	AnyChangesRequested    bool
	LatestReviewSHA        string
	LatestDecisionByReviewer map[string]ReviewState
	ReviewSHAByReviewer      map[string]string
}

type PRDetail struct {
	Number        int      `json:"number"`
	Title         string   `json:"title"`
	State         string   `json:"state"`
	HeadRefOid    string   `json:"headRefOid"`
	HeadRefName   string   `json:"headRefName"`
	Mergeable     string   `json:"mergeable"`
	MergeState    string   `json:"mergeStateStatus"`
	Body          string   `json:"body"`
	Author        string   `json:"author"`
	CreatedAt     string   `json:"createdAt"`
	UpdatedAt     string   `json:"updatedAt"`
	Reviews       []Review `json:"reviews"`
	StatusChecks  []StatusCheck `json:"statusChecks"`
}

type StatusCheck struct {
	TypeName   string `json:"__typename"`
	Name       string `json:"name"`
	Context    string `json:"context"`
	Conclusion string `json:"conclusion"`
	Status     string `json:"status"`
	State      string `json:"state"`
}

type Issue struct {
	Number    int      `json:"number"`
	Title     string   `json:"title"`
	State     string   `json:"state"`
	Labels    []string `json:"labels"`
	Body      string   `json:"body"`
	CreatedAt string   `json:"createdAt"`
	UpdatedAt string   `json:"updatedAt"`
}
