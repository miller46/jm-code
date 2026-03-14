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

	"github.com/jack/go-cli/internal/config"
	"github.com/jack/go-cli/internal/db"
)

type ApprovalRules = config.ApprovalRules

type DispatchState struct {
	LastReviewDispatchSHA    string
	LastFixDispatchSHA       string
	LastMergeDispatchSHA     string
	LastConflictDispatchSHA  string
	LastStatusFixDispatchSHA string
}

// Sorted by submittedAt ascending; latest review per reviewer wins.
// COMMENTED and DISMISSED reviews are ignored.
func EvaluateReviews(reviews []Review, requiredReviewers []string, rules *ApprovalRules) ReviewEvaluation {
	sorted := make([]Review, len(reviews))
	copy(sorted, reviews)
	sort.Slice(sorted, func(i, j int) bool {
		return sorted[i].SubmittedAt < sorted[j].SubmittedAt
	})

	latestDecision := make(map[string]ReviewState)
	reviewSHA := make(map[string]string)
	for _, r := range sorted {
		if r.State == ReviewCommented || r.State == ReviewDismissed {
			continue
		}
		latestDecision[r.Author] = r.State
		reviewSHA[r.Author] = r.CommitOID
	}

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

	if rules != nil {
		for _, vetoer := range rules.VetoPowers {
			if latestDecision[vetoer] == ReviewChangesRequested {
				anyChanges = true
			}
		}
	}

	allRequired := true
	if len(requiredReviewers) > 0 {
		for _, req := range requiredReviewers {
			if latestDecision[req] != ReviewApproved {
				allRequired = false
				break
			}
		}
	}

	minApprovals := 1
	if rules != nil && rules.MinApprovals > 0 {
		minApprovals = rules.MinApprovals
	}
	meetsMinApprovals := approvalCount >= minApprovals

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

// Returns (status, action, allApproved, anyChangesRequested, reviewEval).
// Priority order: MERGED > CONFLICTS > CHECKS FAILING > review state.
func DeterminePRAction(
	pr PRDetail,
	existing *db.WorkflowItem,
	requiredReviewers []string,
	rules *ApprovalRules,
) (Status, Action, bool, bool, *ReviewEvaluation) {
	if pr.State == "MERGED" {
		return StatusMerged, ActionNone, false, false, nil
	}

	if pr.Mergeable == "CONFLICTING" {
		return StatusConflicting, ActionNeedsConflictResolution, false, false, nil
	}

	if HasFailingChecks(pr.StatusChecks) {
		return StatusChecksFailing, ActionNeedsStatusFix, false, false, nil
	}

	eval := EvaluateReviews(pr.Reviews, requiredReviewers, rules)
	shaMatches := eval.LatestReviewSHA == pr.HeadRefOid

	// ALL APPROVED + SHA MATCHES -> ready to merge
	if eval.AllRequiredApproved && shaMatches {
		return StatusApproved, ActionReadyToMerge, true, false, &eval
	}

	// ALL APPROVED + SHA MISMATCH -> needs re-review
	if eval.AllRequiredApproved && !shaMatches {
		return StatusPendingReview, ActionNeedsReview, true, false, &eval
	}

	// CHANGES REQUESTED + SHA MATCHES -> needs fix
	if eval.AnyChangesRequested && shaMatches {
		return StatusChangesRequested, ActionNeedsFix, false, true, &eval
	}

	// CHANGES REQUESTED + SHA MISMATCH -> needs re-review
	if eval.AnyChangesRequested && !shaMatches {
		return StatusPendingReview, ActionNeedsReview, false, true, &eval
	}

	return StatusPendingReview, ActionNeedsReview, false, false, &eval
}

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

func UpdateIteration(action Action, iteration, maxIterations int) (int, Action) {
	if action == ActionNeedsFix && iteration >= maxIterations {
		return iteration, ActionMaxIterationsReached
	}
	return iteration, action
}

// ReconcileDispatchSHAs clears dispatch SHAs for reviewers that were
// dispatched for the current head SHA but never actually reviewed it.
// This makes the system self-healing when a dispatch fails silently.
func ReconcileDispatchSHAs(existingJSON string, eval *ReviewEvaluation, headSHA string) string {
	dispatchMap := make(map[string]string)
	if err := json.Unmarshal([]byte(existingJSON), &dispatchMap); err != nil {
		return existingJSON
	}

	reviewMap := make(map[string]string)
	if eval != nil {
		reviewMap = eval.ReviewSHAByReviewer
	}

	for reviewer, dispatchSHA := range dispatchMap {
		if dispatchSHA == headSHA && reviewMap[reviewer] != headSHA {
			delete(dispatchMap, reviewer)
		}
	}

	data, err := json.Marshal(dispatchMap)
	if err != nil {
		return existingJSON
	}
	return string(data)
}

var linkedIssueRe = regexp.MustCompile(`(?i)(?:closes|fixes|resolves)\s+#(\d+)`)

func FindLinkedIssue(body, title string) int {
	text := body + " " + title
	m := linkedIssueRe.FindStringSubmatch(text)
	if m == nil {
		return 0
	}
	n, _ := strconv.Atoi(m[1])
	return n
}

func FindLinkedPRs(prs []PRDetail, issueNumber int) int {
	target := fmt.Sprintf("#%d", issueNumber)
	for _, pr := range prs {
		text := pr.Body + " " + pr.Title
		if !strings.Contains(text, target) {
			continue
		}
		if linkedIssueRe.MatchString(pr.Body) || linkedIssueRe.MatchString(pr.Title) {
			if FindLinkedIssue(pr.Body, pr.Title) == issueNumber {
				return pr.Number
			}
		}
	}
	return 0
}

type GHClient interface {
	ListIssues(ctx context.Context, repo string) ([]Issue, error)
	ListPRsWithDetails(ctx context.Context, repo string) ([]PRDetail, error)
}

type CLIClient struct{}

func (c *CLIClient) ListIssues(ctx context.Context, repo string) ([]Issue, error) {
	cmd := exec.CommandContext(ctx, "gh", "issue", "list",
		"--repo", repo, "--state", "open", "--json", "number,title,state,labels,body,createdAt,updatedAt",
		"--limit", "200",
	)
	out, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("gh issue list: %w", err)
	}

	// gh outputs labels as objects with "name" field, not plain strings
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

type Syncer struct {
	Store             *db.Store
	Client            GHClient
	RequiredReviewers func(repo string) []string
	ApprovalRules     func(repo string) *ApprovalRules
	MaxIterations     int
}

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

	for _, issue := range issues {
		linkedPR := FindLinkedPRs(prs, issue.Number)
		itemID := fmt.Sprintf("%s#issue#%d", repo, issue.Number)

		existing, err := s.Store.GetWorkflowItem(itemID)
		if err != nil && !db.IsNotFound(err) {
			slog.Error("reading existing issue", "repo", repo, "number", issue.Number, "err", err)
			continue
		}
		status, action := DetermineIssueAction(issue, existing, linkedPR)

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

	for _, pr := range prs {
		itemID := fmt.Sprintf("%s#pr#%d", repo, pr.Number)
		existing, err := s.Store.GetWorkflowItem(itemID)
		if err != nil && !db.IsNotFound(err) {
			slog.Error("reading existing PR", "repo", repo, "number", pr.Number, "err", err)
			continue
		}

		status, action, allApproved, anyChanges, eval := DeterminePRAction(pr, existing, requiredReviewers, rules)

		iteration := 0
		if existing != nil {
			iteration = existing.Iteration
		}
		iteration, action = UpdateIteration(action, iteration, s.MaxIterations)

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

		reviewerSHAs := "{}"
		reviewerDispatchSHAs := "{}"
		if eval != nil {
			if data, err := json.Marshal(eval.ReviewSHAByReviewer); err == nil {
				reviewerSHAs = string(data)
			}
		}
		if existing != nil {
			reviewerDispatchSHAs = ReconcileDispatchSHAs(
				existing.ReviewerDispatchSHAsJSON, eval, pr.HeadRefOid,
			)
		}

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
