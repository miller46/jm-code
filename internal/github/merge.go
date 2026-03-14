package github

import (
	"context"
	"fmt"
	"os/exec"
)

// MergeResult represents the outcome of a PR merge attempt.
type MergeResult struct {
	Success  bool   `json:"success"`
	Repo     string `json:"repo"`
	PRNumber int    `json:"pr_number"`
	Error    string `json:"error,omitempty"`
}

// MergePR merges a PR using the gh CLI.
// Strategy can be "merge", "squash", or "rebase".
func MergePR(ctx context.Context, repo string, prNumber int, strategy string) MergeResult {
	if strategy == "" {
		strategy = "merge"
	}

	args := []string{"pr", "merge", fmt.Sprintf("%d", prNumber),
		"--repo", repo, "--" + strategy,
	}

	cmd := exec.CommandContext(ctx, "gh", args...)
	if out, err := cmd.CombinedOutput(); err != nil {
		return MergeResult{
			Success:  false,
			Repo:     repo,
			PRNumber: prNumber,
			Error:    fmt.Sprintf("%s: %s", err, string(out)),
		}
	}

	return MergeResult{
		Success:  true,
		Repo:     repo,
		PRNumber: prNumber,
	}
}
