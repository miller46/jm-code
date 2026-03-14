package agent

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
)

var (
	cloneMu   sync.Mutex
	cloneDone = make(map[string]bool)
)

func AgentHomeDir(agentID string) string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".openclaw", "agents", agentID)
}

func WorkspacePath(baseDir, repo string) string {
	slug := strings.ReplaceAll(repo, "/", "_")
	return filepath.Join(baseDir, slug+".git")
}

func TaskFilePath(baseDir, repo string, number int, suffix string) string {
	slug := strings.ReplaceAll(repo, "/", "_")
	name := fmt.Sprintf("%s_%d_%s.md", slug, number, suffix)
	tasksDir := filepath.Join(baseDir, "tasks")
	os.MkdirAll(tasksDir, 0755)
	return filepath.Join(tasksDir, name)
}

func WriteTaskFile(path, content string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return fmt.Errorf("creating task dir: %w", err)
	}
	return os.WriteFile(path, []byte(content), 0644)
}

// Thread-safe via sync.Mutex; each repo is cloned at most once per process.
func EnsureBareClone(ctx context.Context, repo, baseDir string) (string, error) {
	barePath := WorkspacePath(baseDir, repo)

	cloneMu.Lock()
	defer cloneMu.Unlock()

	if cloneDone[barePath] {
		return barePath, nil
	}

	if _, err := os.Stat(barePath); os.IsNotExist(err) {
		cmd := exec.CommandContext(ctx, "git", "clone", "--bare",
			fmt.Sprintf("https://github.com/%s.git", repo), barePath)
		if out, err := cmd.CombinedOutput(); err != nil {
			return "", fmt.Errorf("bare clone %s: %s: %w", repo, out, err)
		}
	}

	// Bare clones default refspec to refs/heads/*; fix to refs/remotes/origin/*
	cmd := exec.CommandContext(ctx, "git", "-C", barePath, "config",
		"remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
	cmd.Run() // best-effort

	// Must happen after refspec fix
	cmd = exec.CommandContext(ctx, "git", "-C", barePath, "fetch", "--prune", "origin")
	if out, err := cmd.CombinedOutput(); err != nil {
		return "", fmt.Errorf("fetch %s: %s: %w", repo, out, err)
	}

	cloneDone[barePath] = true
	return barePath, nil
}

func CreateWorktree(ctx context.Context, barePath, workDir, branch, startPoint string) (string, error) {
	wtPath := filepath.Join(workDir, branch)
	os.MkdirAll(filepath.Dir(wtPath), 0755)

	args := []string{"-C", barePath, "worktree", "add", "-B", branch, wtPath}
	if startPoint != "" {
		args = append(args, startPoint)
	}

	cmd := exec.CommandContext(ctx, "git", args...)
	if out, err := cmd.CombinedOutput(); err != nil {
		exec.CommandContext(ctx, "git", "-C", barePath, "worktree", "remove", "--force", wtPath).Run()
		os.RemoveAll(wtPath)
		cmd = exec.CommandContext(ctx, "git", args...)
		if retryOut, retryErr := cmd.CombinedOutput(); retryErr != nil {
			return "", fmt.Errorf("creating worktree: %s: %w", retryOut, retryErr)
		}
		_ = out
	}

	return wtPath, nil
}

func SetupAgentWorkspace(ctx context.Context, agentID, repo string, issueNumber int) (string, string, error) {
	homeDir := AgentHomeDir(agentID)
	barePath, err := EnsureBareClone(ctx, repo, homeDir)
	if err != nil {
		return "", "", err
	}

	branch := fmt.Sprintf("feature/issue-%d", issueNumber)
	workDir := filepath.Join(homeDir, "workspaces")
	wtPath, err := CreateWorktree(ctx, barePath, workDir, branch, "origin/main")
	if err != nil {
		return "", "", err
	}

	cmd := exec.CommandContext(ctx, "gh", "issue", "view", fmt.Sprintf("%d", issueNumber),
		"--repo", repo, "--json", "title,body,labels,comments")
	issueData, err := cmd.Output()
	if err != nil {
		return "", "", fmt.Errorf("fetching issue #%d: %w", issueNumber, err)
	}

	taskFile := TaskFilePath(homeDir, repo, issueNumber, "TASK")
	content := fmt.Sprintf("# Issue #%d\n\n%s", issueNumber, string(issueData))
	if err := WriteTaskFile(taskFile, content); err != nil {
		return "", "", err
	}

	return taskFile, wtPath, nil
}

func SetupReviewerWorkspace(ctx context.Context, agentID, repo string, prNumber int, headRefName string) (string, string, error) {
	homeDir := AgentHomeDir(agentID)
	barePath, err := EnsureBareClone(ctx, repo, homeDir)
	if err != nil {
		return "", "", err
	}

	workDir := filepath.Join(homeDir, "workspaces")
	wtPath, err := CreateWorktree(ctx, barePath, workDir, headRefName, "origin/"+headRefName)
	if err != nil {
		return "", "", err
	}

	cmd := exec.CommandContext(ctx, "gh", "pr", "view", fmt.Sprintf("%d", prNumber),
		"--repo", repo, "--json", "title,body,files,comments,reviews")
	prData, err := cmd.Output()
	if err != nil {
		return "", "", fmt.Errorf("fetching PR #%d: %w", prNumber, err)
	}

	taskFile := TaskFilePath(homeDir, repo, prNumber, "REVIEW")
	content := fmt.Sprintf("# PR #%d Review\n\n%s", prNumber, string(prData))
	if err := WriteTaskFile(taskFile, content); err != nil {
		return "", "", err
	}

	return taskFile, wtPath, nil
}

func SetupFixWorkspace(ctx context.Context, agentID, repo string, prNumber int, branch string) (string, string, error) {
	homeDir := AgentHomeDir(agentID)
	barePath, err := EnsureBareClone(ctx, repo, homeDir)
	if err != nil {
		return "", "", err
	}

	workDir := filepath.Join(homeDir, "workspaces")
	wtPath, err := CreateWorktree(ctx, barePath, workDir, branch, "origin/"+branch)
	if err != nil {
		return "", "", err
	}

	cmd := exec.CommandContext(ctx, "gh", "pr", "view", fmt.Sprintf("%d", prNumber),
		"--repo", repo, "--json", "title,body,files,comments,reviews")
	prData, err := cmd.Output()
	if err != nil {
		return "", "", fmt.Errorf("fetching PR #%d: %w", prNumber, err)
	}

	taskFile := TaskFilePath(homeDir, repo, prNumber, "FIX")
	content := fmt.Sprintf("# PR #%d Fix\n\n%s", prNumber, string(prData))
	if err := WriteTaskFile(taskFile, content); err != nil {
		return "", "", err
	}

	return taskFile, wtPath, nil
}

func SetupConflictWorkspace(ctx context.Context, agentID, repo, branch string) (string, error) {
	homeDir := AgentHomeDir(agentID)
	barePath, err := EnsureBareClone(ctx, repo, homeDir)
	if err != nil {
		return "", err
	}

	workDir := filepath.Join(homeDir, "workspaces")
	wtPath, err := CreateWorktree(ctx, barePath, workDir, branch, "origin/"+branch)
	if err != nil {
		return "", err
	}

	return wtPath, nil
}

func SetupStatusFixWorkspace(ctx context.Context, agentID, repo string, prNumber int, branch string) (string, string, error) {
	homeDir := AgentHomeDir(agentID)
	barePath, err := EnsureBareClone(ctx, repo, homeDir)
	if err != nil {
		return "", "", err
	}

	workDir := filepath.Join(homeDir, "workspaces")
	wtPath, err := CreateWorktree(ctx, barePath, workDir, branch, "origin/"+branch)
	if err != nil {
		return "", "", err
	}

	cmd := exec.CommandContext(ctx, "gh", "api",
		fmt.Sprintf("repos/%s/pulls/%d/comments", repo, prNumber))
	comments, _ := cmd.Output() // best-effort

	cmd = exec.CommandContext(ctx, "gh", "pr", "view", fmt.Sprintf("%d", prNumber),
		"--repo", repo, "--json", "title,body,files,comments,reviews")
	prData, err := cmd.Output()
	if err != nil {
		return "", "", fmt.Errorf("fetching PR #%d: %w", prNumber, err)
	}

	taskFile := TaskFilePath(homeDir, repo, prNumber, "STATUS_FIX")
	content := fmt.Sprintf("# PR #%d Status Fix\n\n%s\n\n## Inline Comments\n\n%s",
		prNumber, string(prData), string(comments))
	if err := WriteTaskFile(taskFile, content); err != nil {
		return "", "", err
	}

	return taskFile, wtPath, nil
}
