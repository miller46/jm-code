package tools

import (
	"context"
	"fmt"
	"os/exec"
	"strings"
)

func SubmitReview(ctx context.Context, repo string, prNumber int, verdict, body, reviewerID, ghConfigDir string) (bool, error) {
	var flag string
	switch verdict {
	case "approve":
		flag = "--approve"
	case "request_changes":
		flag = "--request-changes"
	case "comment":
		flag = "--comment"
	default:
		return false, fmt.Errorf("invalid verdict: %q (must be approve, request_changes, or comment)", verdict)
	}

	args := []string{"pr", "review", fmt.Sprintf("%d", prNumber),
		"--repo", repo,
		flag,
		"--body", body,
	}

	cmd := exec.CommandContext(ctx, "gh", args...)
	if ghConfigDir != "" {
		cmd.Env = append(cmd.Environ(), "GH_CONFIG_DIR="+ghConfigDir)
	}

	out, err := cmd.CombinedOutput()
	if err != nil {
		return false, fmt.Errorf("submitting review: %s: %w", strings.TrimSpace(string(out)), err)
	}

	return true, nil
}
