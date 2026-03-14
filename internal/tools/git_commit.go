package tools

import (
	"context"
	"fmt"
	"os/exec"
	"strings"
)

type GitCommitResult struct {
	Success bool   `json:"success"`
	Details string `json:"details"`
}

func GitCommitAndPush(ctx context.Context, branch, message, workspace, ghConfigDir string) GitCommitResult {
	run := func(name string, args ...string) error {
		cmd := exec.CommandContext(ctx, name, args...)
		cmd.Dir = workspace
		if ghConfigDir != "" {
			cmd.Env = append(cmd.Environ(), "GH_CONFIG_DIR="+ghConfigDir)
		}
		out, err := cmd.CombinedOutput()
		if err != nil {
			return fmt.Errorf("%s %s: %s: %w", name, strings.Join(args, " "), strings.TrimSpace(string(out)), err)
		}
		return nil
	}

	if err := run("git", "add", "-A"); err != nil {
		return GitCommitResult{Success: false, Details: err.Error()}
	}

	if err := run("git", "commit", "-m", message); err != nil {
		return GitCommitResult{Success: false, Details: err.Error()}
	}

	// Branch may not exist remotely yet — that's OK
	if err := run("git", "fetch", "origin", branch); err != nil {
		_ = err
	}

	// Best-effort rebase; skip if no remote branch
	_ = run("git", "rebase", "origin/"+branch)

	if err := run("git", "push", "origin", branch); err != nil {
		return GitCommitResult{Success: false, Details: err.Error()}
	}

	return GitCommitResult{Success: true, Details: "committed and pushed to " + branch}
}
