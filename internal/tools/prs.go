package tools

import (
	"encoding/json"
	"fmt"
	"time"

	"github.com/jack/go-cli/internal/db"
)

// PRResult represents a single PR in the queue response.
type PRResult struct {
	ItemID              string            `json:"itemId"`
	Repo                string            `json:"repo"`
	PRNumber            int               `json:"prNumber"`
	Title               string            `json:"title"`
	HeadSHA             string            `json:"headSha"`
	HeadRefName         string            `json:"headRefName"`
	Status              string            `json:"status"`
	DispatchType        string            `json:"dispatchType"`
	LinkedIssueNumber   int               `json:"linkedIssueNumber,omitempty"`
	HasConflicts        bool              `json:"hasConflicts"`
	AllReviewersApproved bool             `json:"allReviewersApproved"`
	AnyChangesRequested bool              `json:"anyChangesRequested"`
	Iteration           int               `json:"iteration"`
	ReviewerSHAs        map[string]string `json:"reviewerShas"`
	ReviewerDispatchSHAs map[string]string `json:"reviewerDispatchShas"`
	SuggestedDevAgent   string            `json:"suggestedDevAgent"`
}

// PRQueueResponse is the response from querying the PR queue.
type PRQueueResponse struct {
	GeneratedAt string     `json:"generatedAt"`
	Source      string     `json:"source"`
	Queue       string     `json:"queue"`
	Counts      struct {
		Scanned  int `json:"scanned"`
		Returned int `json:"returned"`
	} `json:"counts"`
	PRs []PRResult `json:"prs"`
}

// actionToDispatchType maps action strings to dispatch type strings.
var actionToDispatchType = map[string]string{
	"needs_review":              "review",
	"needs_fix":                 "fix",
	"ready_to_merge":            "merge",
	"needs_conflict_resolution": "conflict",
	"needs_status_fix":          "status_fix",
}

// PRQueueClient queries the database for PRs needing action.
type PRQueueClient struct {
	Store *db.Store
}

// Query returns PRs matching the given action filter.
func (c *PRQueueClient) Query(action string, limit int, repos []string) (*PRQueueResponse, error) {
	if limit == 0 {
		limit = 20
	}

	resp := &PRQueueResponse{
		GeneratedAt: time.Now().UTC().Format(time.RFC3339),
		Queue:       action,
	}

	items, err := c.Store.QueryWorkflowItems("pr", action, "", limit*2)
	if err != nil {
		return nil, fmt.Errorf("querying PRs: %w", err)
	}

	resp.Counts.Scanned = len(items)

	repoSet := make(map[string]bool)
	for _, r := range repos {
		repoSet[r] = true
	}

	for _, item := range items {
		if len(repos) > 0 && !repoSet[item.Repo] {
			continue
		}

		if resp.Counts.Returned >= limit {
			break
		}

		reviewerSHAs := make(map[string]string)
		json.Unmarshal([]byte(item.ReviewerSHAsJSON), &reviewerSHAs)

		reviewerDispatchSHAs := make(map[string]string)
		json.Unmarshal([]byte(item.ReviewerDispatchSHAsJSON), &reviewerDispatchSHAs)

		dispatchType := actionToDispatchType[action]

		resp.PRs = append(resp.PRs, PRResult{
			ItemID:               item.ID,
			Repo:                 item.Repo,
			PRNumber:             item.Number,
			Title:                item.Title,
			HeadSHA:              item.HeadSHA,
			HeadRefName:          item.HeadRefName,
			Status:               item.Status,
			DispatchType:         dispatchType,
			LinkedIssueNumber:    item.LinkedIssueNumber,
			HasConflicts:         item.HasConflicts,
			AllReviewersApproved: item.AllReviewersApproved,
			AnyChangesRequested:  item.AnyChangesRequested,
			Iteration:            item.Iteration,
			ReviewerSHAs:         reviewerSHAs,
			ReviewerDispatchSHAs: reviewerDispatchSHAs,
		})
		resp.Counts.Returned++
	}

	return resp, nil
}
