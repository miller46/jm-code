package github

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"os/exec"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/jack/go-cli/internal/db"
)

// ApprovalRules mirrors config.ApprovalRules for use in review evaluation.
type ApprovalRules struct {
	Mode              string   `json:"mode"`
	MinApprovals      int      `json:"min_approvals"`
	RequiredReviewers []string `json:"required_reviewers"`
	VetoPowers        []string `json:"veto_powers"`
}

// DispatchState holds the last-dispatched SHAs for dedup checking.
type DispatchState struct {
	LastReviewDispatchSHA    string
	LastFixDispatchSHA       string
	LastMergeDispatchSHA     string
	LastConflictDispatchSHA  string
	LastStatusFixDispatchSHA string
}

// EvaluateReviews processes a list of reviews to determine approval status.
// Reviews are sorted by submittedAt ascending; the latest review per reviewer wins.
func EvaluateReviews(reviews []Review, requiredReviewers []string, rules *ApprovalRules) ReviewEvaluation {
	// Sort by submittedAt ascending
	sorted := make([]Review, len(reviews))
	copy(sorted, reviews)
	sort.Slice(sorted, func(i, j int) bool {
		return sorted[i].SubmittedAt < sorted[j].SubmittedAt
	})

	// Latest decision per reviewer (ignoring COMMENTED and DISMISSED)
	latestDecision := make(map[string]ReviewState)
	reviewSHA := make(map[string]string)
	for _, r := range sorted {
		if r.State == ReviewCommented || r.State == ReviewDismissed {
			continue
		}
		latestDecision[r.Author] = r.State
		reviewSHA[r.Author] = r.CommitOID
	}

	// Count approvals
	approvalCount := 0
	anyChanges := false
	for _, state := range latestDecision {
		if state == ReviewApproved {
			approvalCount++
		}
		if state == ReviewChangesRequested {
			anyChanges = true
		}
	}

	// Check veto powers
	if rules != nil {
		for _, vetoer := range rules.VetoPowers {
			if latestDecision[vetoer] == ReviewChangesRequested {
				anyChanges = true
			}
		}
	}

	// Check required reviewers
	allRequired := true
	if len(requiredReviewers) > 0 {
		for _, req := range requiredReviewers {
			if latestDecision[req] != ReviewApproved {
				allRequired = false
				break
			}
		}
	}

	// Check min approvals
	minApprovals := 1
	if rules != nil && rules.MinApprovals > 0 {
		minApprovals = rules.MinApprovals
	}
	meetsMinApprovals := approvalCount >= minApprovals

	// Find the latest review SHA overall
	var latestSHA string
	if len(sorted) > 0 {
		latestSHA = sorted[len(sorted)-1].CommitOID
	}

	return ReviewEvaluation{
		AllRequiredApproved:      allRequired && meetsMinApprovals,
		AnyChangesRequested:      anyChanges,
		LatestReviewSHA:          latestSHA,
		LatestDecisionByReviewer: latestDecision,
		ReviewSHAByReviewer:      reviewSHA,
	}
}

// HasFailingChecks returns true if any status check has failed.
func HasFailingChecks(checks []StatusCheck) bool {
	for _, c := range checks {
		switch c.TypeName {
		case "CheckRun":
			if c.Conclusion == "FAILURE" || c.Conclusion == "TIMED_OUT" || c.Conclusion == "CANCELLED" {
				return true
			}
		case "StatusContext":
			if c.State == "FAILURE" || c.State == "ERROR" {
				return true
			}
		}
	}
	return false
}

// DeterminePRAction computes the status and action for a PR based on its state.
// Returns (status, action, allApproved, anyChangesRequested, reviewEval).
func DeterminePRAction(
	pr PRDetail,
	existing *db.WorkflowItem,
	requiredReviewers []string,
	rules *ApprovalRules,
) (Status, Action, bool, bool, *ReviewEvaluation) {
	// 1. MERGED
	if pr.State == "MERGED" {
		return StatusMerged, ActionNone, false, false, nil
	}

	// 2. CONFLICTS
	if pr.Mergeable == "CONFLICTING" {
		return StatusConflicting, ActionNeedsConflictResolution, false, false, nil
	}

	// 2.5. CHECKS FAILING
	if HasFailingChecks(pr.StatusChecks) {
		return StatusChecksFailing, ActionNeedsStatusFix, false, false, nil
	}

	// Evaluate reviews
	eval := EvaluateReviews(pr.Reviews, requiredReviewers, rules)
	shaMatches := eval.LatestReviewSHA == pr.HeadRefOid

	// 3. ALL APPROVED + SHA MATCHES -> ready to merge
	if eval.AllRequiredApproved && shaMatches {
		return StatusApproved, ActionReadyToMerge, true, false, &eval
	}

	// 4. ALL APPROVED + SHA MISMATCH -> needs re-review
	if eval.AllRequiredApproved && !shaMatches {
		return StatusPendingReview, ActionNeedsReview, true, false, &eval
	}

	// 5. CHANGES REQUESTED + SHA MATCHES -> needs fix
	if eval.AnyChangesRequested && shaMatches {
		return StatusChangesRequested, ActionNeedsFix, false, true, &eval
	}

	// 6. CHANGES REQUESTED + SHA MISMATCH -> needs re-review
	if eval.AnyChangesRequested && !shaMatches {
		return StatusPendingReview, ActionNeedsReview, false, true, &eval
	}

	// 7. DEFAULT -> needs review
	return StatusPendingReview, ActionNeedsReview, false, false, &eval
}

// DetermineIssueAction computes the status and action for an issue.
func DetermineIssueAction(issue Issue, existing *db.WorkflowItem, linkedPRNumber int) (Status, Action) {
	if issue.State == "closed" {
		return StatusClosed, ActionNone
	}
	if linkedPRNumber > 0 {
		return StatusPRCreated, ActionNone
	}
	if existing != nil && existing.Status == string(StatusInProgress) {
		return StatusInProgress, ActionNone
	}
	return StatusOpen, ActionNeedsDev
}

// ApplyDispatchDedupe returns ActionNone if this action for this SHA was already dispatched.
func ApplyDispatchDedupe(action Action, headSHA string, state DispatchState) Action {
	if action == ActionNone {
		return ActionNone
	}

	var lastSHA string
	switch action {
	case ActionNeedsReview:
		lastSHA = state.LastReviewDispatchSHA
	case ActionNeedsFix:
		lastSHA = state.LastFixDispatchSHA
	case ActionReadyToMerge:
		lastSHA = state.LastMergeDispatchSHA
	case ActionNeedsConflictResolution:
		lastSHA = state.LastConflictDispatchSHA
	case ActionNeedsStatusFix:
		lastSHA = state.LastStatusFixDispatchSHA
	default:
		return action
	}

	if lastSHA != "" && lastSHA == headSHA {
		return ActionNone
	}
	return action
}

// UpdateIteration checks if a fix action has exceeded max iterations.
func UpdateIteration(action Action, iteration, maxIterations int) (int, Action) {
	if action == ActionNeedsFix && iteration >= maxIterations {
		return iteration, ActionMaxIterationsReached
	}
	return iteration, action
}

var linkedIssueRe = regexp.MustCompile(`(?i)(?:closes|fixes|resolves)\s+#(\d+)`)

// FindLinkedIssue looks for "closes #N", "fixes #N", or "resolves #N" in the body/title.
func FindLinkedIssue(body, title string) int {
	text := body + " " + title
	m := linkedIssueRe.FindStringSubmatch(text)
	if m == nil {
		return 0
	}
	n, _ := strconv.Atoi(m[1])
	return n
}

// FindLinkedPRs searches PRs for one that references the given issue number.
func FindLinkedPRs(prs []PRDetail, issueNumber int) int {
	pattern := fmt.Sprintf(`(?i)(?:closes|fixes|resolves)\s+#%d\b`, issueNumber)
	re := regexp.MustCompile(pattern)
	for _, pr := range prs {
		if re.MatchString(pr.Body) || re.MatchString(pr.Title) {
			return pr.Number
		}
	}
	return 0
}

// GHClient wraps gh CLI calls for testability.
type GHClient interface {
	// ListIssues returns open issues for a repo.
	ListIssues(ctx context.Context, repo string) ([]Issue, error)
	// ListPRsWithDetails returns open PRs with review and status check details.
	ListPRsWithDetails(ctx context.Context, repo string) ([]PRDetail, error)
}

// CLIClient implements GHClient by shelling out to the gh CLI.
type CLIClient struct{}

// ListIssues fetches open issues via `gh issue list`.
func (c *CLIClient) ListIssues(ctx context.Context, repo string) ([]Issue, error) {
	cmd := exec.CommandContext(ctx, "gh", "issue", "list",
		"--repo", repo, "--state", "open", "--json", "number,title,state,labels,body,createdAt,updatedAt",
		"--limit", "200",
	)
	out, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("gh issue list: %w", err)
	}

	// gh outputs labels as objects with "name" field
	var raw []struct {
		Number    int    `json:"number"`
		Title     string `json:"title"`
		State     string `json:"state"`
		Body      string `json:"body"`
		CreatedAt string `json:"createdAt"`
		UpdatedAt string `json:"updatedAt"`
		Labels    []struct {
			Name string `json:"name"`
		} `json:"labels"`
	}
	if err := json.Unmarshal(out, &raw); err != nil {
		return nil, fmt.Errorf("parsing issues: %w", err)
	}

	issues := make([]Issue, len(raw))
	for i, r := range raw {
		labels := make([]string, len(r.Labels))
		for j, l := range r.Labels {
			labels[j] = l.Name
		}
		issues[i] = Issue{
			Number:    r.Number,
			Title:     r.Title,
			State:     strings.ToLower(r.State),
			Labels:    labels,
			Body:      r.Body,
			CreatedAt: r.CreatedAt,
			UpdatedAt: r.UpdatedAt,
		}
	}
	return issues, nil
}

// prGraphQLQuery is the GraphQL query for fetching PRs with reviews and status checks.
const prGraphQLQuery = `
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: OPEN, first: 100, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title state headRefOid headRefName
        mergeable mergeStateStatus createdAt updatedAt body
        author { login }
        reviews(last: 100) {
          nodes {
            author { login }
            state
            submittedAt
            commit { oid }
          }
        }
        commits(last: 1) {
          nodes {
            commit {
              statusCheckRollup {
                contexts(first: 100) {
                  nodes {
                    ... on CheckRun {
                      __typename name conclusion status
                    }
                    ... on StatusContext {
                      __typename context state
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
`

// ListPRsWithDetails fetches open PRs with details via gh api graphql.
func (c *CLIClient) ListPRsWithDetails(ctx context.Context, repo string) ([]PRDetail, error) {
	parts := strings.SplitN(repo, "/", 2)
	if len(parts) != 2 {
		return nil, fmt.Errorf("invalid repo format: %q (want owner/repo)", repo)
	}

	var allPRs []PRDetail
	var cursor string

	for {
		args := []string{"api", "graphql",
			"-f", fmt.Sprintf("owner=%s", parts[0]),
			"-f", fmt.Sprintf("name=%s", parts[1]),
			"-f", fmt.Sprintf("query=%s", prGraphQLQuery),
		}
		if cursor != "" {
			args = append(args, "-f", fmt.Sprintf("cursor=%s", cursor))
		}

		cmd := exec.CommandContext(ctx, "gh", args...)
		out, err := cmd.Output()
		if err != nil {
			return nil, fmt.Errorf("gh api graphql: %w", err)
		}

		var resp struct {
			Data struct {
				Repository struct {
					PullRequests struct {
						PageInfo struct {
							HasNextPage bool   `json:"hasNextPage"`
							EndCursor   string `json:"endCursor"`
						} `json:"pageInfo"`
						Nodes []struct {
							Number      int    `json:"number"`
							Title       string `json:"title"`
							State       string `json:"state"`
							HeadRefOid  string `json:"headRefOid"`
							HeadRefName string `json:"headRefName"`
							Mergeable   string `json:"mergeable"`
							MergeState  string `json:"mergeStateStatus"`
							Body        string `json:"body"`
							CreatedAt   string `json:"createdAt"`
							UpdatedAt   string `json:"updatedAt"`
							Author      struct {
								Login string `json:"login"`
							} `json:"author"`
							Reviews struct {
								Nodes []struct {
									Author struct {
										Login string `json:"login"`
									} `json:"author"`
									State       string `json:"state"`
									SubmittedAt string `json:"submittedAt"`
									Commit      struct {
										OID string `json:"oid"`
									} `json:"commit"`
								} `json:"nodes"`
							} `json:"reviews"`
							Commits struct {
								Nodes []struct {
									Commit struct {
										StatusCheckRollup *struct {
											Contexts struct {
												Nodes []struct {
													TypeName   string `json:"__typename"`
													Name       string `json:"name"`
													Conclusion string `json:"conclusion"`
													Status     string `json:"status"`
													Context    string `json:"context"`
													State      string `json:"state"`
												} `json:"nodes"`
											} `json:"contexts"`
										} `json:"statusCheckRollup"`
									} `json:"commit"`
								} `json:"nodes"`
							} `json:"commits"`
						} `json:"nodes"`
					} `json:"pullRequests"`
				} `json:"repository"`
			} `json:"data"`
		}

		if err := json.Unmarshal(out, &resp); err != nil {
			return nil, fmt.Errorf("parsing GraphQL response: %w", err)
		}

		prs := resp.Data.Repository.PullRequests
		for _, node := range prs.Nodes {
			pr := PRDetail{
				Number:      node.Number,
				Title:       node.Title,
				State:       node.State,
				HeadRefOid:  node.HeadRefOid,
				HeadRefName: node.HeadRefName,
				Mergeable:   node.Mergeable,
				MergeState:  node.MergeState,
				Body:        node.Body,
				Author:      node.Author.Login,
				CreatedAt:   node.CreatedAt,
				UpdatedAt:   node.UpdatedAt,
			}

			for _, r := range node.Reviews.Nodes {
				pr.Reviews = append(pr.Reviews, Review{
					Author:      r.Author.Login,
					State:       ReviewState(r.State),
					SubmittedAt: r.SubmittedAt,
					CommitOID:   r.Commit.OID,
				})
			}

			if len(node.Commits.Nodes) > 0 && node.Commits.Nodes[0].Commit.StatusCheckRollup != nil {
				for _, ctx := range node.Commits.Nodes[0].Commit.StatusCheckRollup.Contexts.Nodes {
					pr.StatusChecks = append(pr.StatusChecks, StatusCheck{
						TypeName:   ctx.TypeName,
						Name:       ctx.Name,
						Conclusion: ctx.Conclusion,
						Status:     ctx.Status,
						Context:    ctx.Context,
						State:      ctx.State,
					})
				}
			}

			allPRs = append(allPRs, pr)
		}

		if !prs.PageInfo.HasNextPage {
			break
		}
		cursor = prs.PageInfo.EndCursor
	}

	return allPRs, nil
}

// Syncer synchronizes GitHub issues and PRs into the database.
type Syncer struct {
	Store             *db.Store
	Client            GHClient
	RequiredReviewers func(repo string) []string
	ApprovalRules     func(repo string) *ApprovalRules
	MaxIterations     int
}

// SyncRepo fetches all issues and PRs for a repo and upserts them into the database.
func (s *Syncer) SyncRepo(ctx context.Context, repo string) (int, error) {
	slog.Info("syncing repo", "repo", repo)

	issues, err := s.Client.ListIssues(ctx, repo)
	if err != nil {
		return 0, fmt.Errorf("listing issues for %s: %w", repo, err)
	}

	prs, err := s.Client.ListPRsWithDetails(ctx, repo)
	if err != nil {
		return 0, fmt.Errorf("listing PRs for %s: %w", repo, err)
	}

	requiredReviewers := s.RequiredReviewers(repo)
	rules := s.ApprovalRules(repo)
	count := 0

	// Process issues
	for _, issue := range issues {
		linkedPR := FindLinkedPRs(prs, issue.Number)
		itemID := fmt.Sprintf("%s#issue#%d", repo, issue.Number)

		existing, _ := s.Store.GetWorkflowItem(itemID)
		status, action := DetermineIssueAction(issue, existing, linkedPR)

		// Apply dispatch dedup
		if existing != nil {
			action = ApplyDispatchDedupe(action, "", DispatchState{})
		}

		maxIter := s.MaxIterations
		if maxIter == 0 {
			maxIter = 3
		}

		item := db.WorkflowItem{
			ID:            itemID,
			Type:          string(ItemTypeIssue),
			Repo:          repo,
			Number:        issue.Number,
			Title:         issue.Title,
			GitHubState:   issue.State,
			RepoScopedID:  fmt.Sprintf("issue#%d", issue.Number),
			Status:        string(status),
			Action:        string(action),
			LinkedIssueNumber: linkedPR,
			MaxIterations: maxIter,
			CreatedAt:     issue.CreatedAt,
			UpdatedAt:     issue.UpdatedAt,
			LastSync:      db.Now(),
		}

		// Preserve dispatch state from existing item
		if existing != nil {
			item.LastReviewDispatchSHA = existing.LastReviewDispatchSHA
			item.LastFixDispatchSHA = existing.LastFixDispatchSHA
			item.LastMergeDispatchSHA = existing.LastMergeDispatchSHA
			item.LastConflictDispatchSHA = existing.LastConflictDispatchSHA
			item.LastStatusFixDispatchSHA = existing.LastStatusFixDispatchSHA
			item.Iteration = existing.Iteration
			item.AssignedAgent = existing.AssignedAgent
		}

		if err := s.Store.UpsertWorkflowItem(item); err != nil {
			slog.Error("upserting issue", "repo", repo, "number", issue.Number, "err", err)
			continue
		}
		count++
	}

	// Process PRs
	for _, pr := range prs {
		itemID := fmt.Sprintf("%s#pr#%d", repo, pr.Number)
		existing, _ := s.Store.GetWorkflowItem(itemID)

		status, action, allApproved, anyChanges, eval := DeterminePRAction(pr, existing, requiredReviewers, rules)

		// Apply iteration check
		iteration := 0
		if existing != nil {
			iteration = existing.Iteration
		}
		iteration, action = UpdateIteration(action, iteration, s.MaxIterations)

		// Apply dispatch dedup
		if existing != nil {
			action = ApplyDispatchDedupe(action, pr.HeadRefOid, DispatchState{
				LastReviewDispatchSHA:    existing.LastReviewDispatchSHA,
				LastFixDispatchSHA:       existing.LastFixDispatchSHA,
				LastMergeDispatchSHA:     existing.LastMergeDispatchSHA,
				LastConflictDispatchSHA:  existing.LastConflictDispatchSHA,
				LastStatusFixDispatchSHA: existing.LastStatusFixDispatchSHA,
			})
		}

		linkedIssue := FindLinkedIssue(pr.Body, pr.Title)

		// Build reviewer SHAs JSON
		reviewerSHAs := "{}"
		reviewerDispatchSHAs := "{}"
		if eval != nil {
			if data, err := json.Marshal(eval.ReviewSHAByReviewer); err == nil {
				reviewerSHAs = string(data)
			}
		}
		if existing != nil {
			reviewerDispatchSHAs = existing.ReviewerDispatchSHAsJSON
		}

		// Status check rollup JSON
		checksJSON := "[]"
		if data, err := json.Marshal(pr.StatusChecks); err == nil {
			checksJSON = string(data)
		}

		shaMatches := false
		if eval != nil {
			shaMatches = eval.LatestReviewSHA == pr.HeadRefOid
		}

		item := db.WorkflowItem{
			ID:            itemID,
			Type:          string(ItemTypePR),
			Repo:          repo,
			Number:        pr.Number,
			Title:         pr.Title,
			GitHubState:   strings.ToLower(pr.State),
			RepoScopedID:  fmt.Sprintf("pr#%d", pr.Number),
			Status:        string(status),
			Action:        string(action),
			HeadSHA:       pr.HeadRefOid,
			HeadRefName:   pr.HeadRefName,
			AllReviewersApproved: allApproved,
			AnyChangesRequested:  anyChanges,
			SHAMatchesReview:     shaMatches,
			HasConflicts:         pr.Mergeable == "CONFLICTING",
			ReviewerSHAsJSON:         reviewerSHAs,
			ReviewerDispatchSHAsJSON: reviewerDispatchSHAs,
			StatusCheckRollup:        checksJSON,
			LinkedIssueNumber:        linkedIssue,
			Iteration:                iteration,
			MaxIterations:            s.MaxIterations,
			CreatedAt:                pr.CreatedAt,
			UpdatedAt:                pr.UpdatedAt,
			LastSync:                 db.Now(),
		}

		// Preserve dispatch state
		if existing != nil {
			item.LastReviewDispatchSHA = existing.LastReviewDispatchSHA
			item.LastFixDispatchSHA = existing.LastFixDispatchSHA
			item.LastMergeDispatchSHA = existing.LastMergeDispatchSHA
			item.LastConflictDispatchSHA = existing.LastConflictDispatchSHA
			item.LastStatusFixDispatchSHA = existing.LastStatusFixDispatchSHA
			item.LastHeadSHASeen = existing.LastHeadSHASeen
			item.AssignedAgent = existing.AssignedAgent
		}

		if err := s.Store.UpsertWorkflowItem(item); err != nil {
			slog.Error("upserting PR", "repo", repo, "number", pr.Number, "err", err)
			continue
		}
		count++
	}

	slog.Info("sync complete", "repo", repo, "items", count)
	return count, nil
}
