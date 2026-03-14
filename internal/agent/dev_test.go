package agent

import (
	"strings"
	"testing"
)

func TestGetDevPrompt_UsesAbsoluteBinaryPath(t *testing.T) {
	cfg := DevPromptConfig{
		AgentID:       "backend-dev",
		Repo:          "owner/repo",
		TaskFile:      "/home/.openclaw/agents/backend-dev/tasks/task.md",
		IssueNumber:   42,
		Workspace:     "/home/.openclaw/agents/backend-dev/workspaces/feature/issue-42",
		SubmitPRTool:  "/usr/local/bin/orchestrator submit-pr",
		GitCommitTool: "/usr/local/bin/orchestrator git-commit",
	}

	prompt := GetDevPrompt(cfg)

	if !strings.Contains(prompt, "/usr/local/bin/orchestrator git-commit") {
		t.Error("prompt should contain absolute binary path for git-commit")
	}
	if !strings.Contains(prompt, "/usr/local/bin/orchestrator submit-pr") {
		t.Error("prompt should contain absolute binary path for submit-pr")
	}
	// Should NOT contain bare tool name without path
	if strings.Contains(prompt, " git_commit ") {
		t.Error("prompt should not contain bare git_commit tool name")
	}
}

func TestGetPRFixPrompt_UsesAbsoluteBinaryPath(t *testing.T) {
	cfg := DevPromptConfig{
		AgentID:       "backend-dev",
		Repo:          "owner/repo",
		TaskFile:      "/tmp/task.md",
		Workspace:     "/tmp/workspace",
		GitCommitTool: "/usr/local/bin/orchestrator git-commit",
	}

	prompt := GetPRFixPrompt(cfg, 10, "feature/fix")

	if !strings.Contains(prompt, "/usr/local/bin/orchestrator git-commit") {
		t.Error("prompt should contain absolute binary path for git-commit")
	}
}

func TestGetPRConflictsPrompt_UsesAbsoluteBinaryPath(t *testing.T) {
	prompt := GetPRConflictsPrompt("dev", "owner/repo", "feature/x", "/tmp/ws", "/usr/local/bin/orchestrator git-commit")

	if !strings.Contains(prompt, "/usr/local/bin/orchestrator git-commit") {
		t.Error("prompt should contain absolute binary path for git-commit")
	}
}

func TestGetReviewerPrompt_UsesAbsoluteBinaryPath(t *testing.T) {
	prompt := GetReviewerPrompt("reviewer1", "owner/repo", 5, "/tmp/ws", "/tmp/task.md", "/usr/local/bin/orchestrator submit-review")

	if !strings.Contains(prompt, "/usr/local/bin/orchestrator submit-review") {
		t.Error("prompt should contain absolute binary path for submit-review")
	}
}
