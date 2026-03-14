package tools

import (
	"fmt"
	"time"

	"github.com/jack/go-cli/internal/db"
)

type IssueResult struct {
	ItemID         string   `json:"itemId"`
	Repo           string   `json:"repo"`
	IssueNumber    int      `json:"issueNumber"`
	Title          string   `json:"title"`
	Labels         []string `json:"labels"`
	Status         string   `json:"status"`
	Action         string   `json:"action"`
	HasLinkedPR    bool     `json:"hasLinkedPr"`
	Reason         string   `json:"reason"`
	SuggestedAgent string   `json:"suggestedAgent"`
}

type IssueQueueResponse struct {
	GeneratedAt string        `json:"generatedAt"`
	Source      string        `json:"source"`
	Counts      struct {
		Scanned  int `json:"scanned"`
		Eligible int `json:"eligible"`
		Returned int `json:"returned"`
	} `json:"counts"`
	Issues     []IssueResult `json:"issues"`
	NextCursor *int          `json:"nextCursor"`
}

type IssueQueueClient struct {
	Store *db.Store
}

func (c *IssueQueueClient) Query(limit int, repos []string) (*IssueQueueResponse, error) {
	if limit == 0 {
		limit = 50
	}

	resp := &IssueQueueResponse{
		GeneratedAt: time.Now().UTC().Format(time.RFC3339),
	}

	items, err := c.Store.QueryWorkflowItems("issue", "needs_dev", "", limit*2)
	if err != nil {
		return nil, fmt.Errorf("querying issues: %w", err)
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

		resp.Counts.Eligible++
		if resp.Counts.Returned >= limit {
			continue
		}

		resp.Issues = append(resp.Issues, IssueResult{
			ItemID:      item.ID,
			Repo:        item.Repo,
			IssueNumber: item.Number,
			Title:       item.Title,
			Status:      item.Status,
			Action:      item.Action,
			HasLinkedPR: item.LinkedIssueNumber > 0,
			Reason:      "needs_dev + no linked PR + not dispatched",
		})
		resp.Counts.Returned++
	}

	return resp, nil
}
