package agent_test

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"github.com/jack/go-cli/internal/agent"
)

func TestAgentHomeDir(t *testing.T) {
	dir := agent.AgentHomeDir("test-agent")
	if dir == "" {
		t.Fatal("expected non-empty dir")
	}
	if !filepath.IsAbs(dir) {
		t.Errorf("expected absolute path, got %q", dir)
	}
}

func TestWorkspacePath(t *testing.T) {
	base := t.TempDir()
	path := agent.WorkspacePath(base, "owner/repo")
	if !filepath.IsAbs(path) {
		t.Errorf("expected absolute path, got %q", path)
	}
	// Should sanitize the slash
	if filepath.Base(path) != "owner_repo.git" {
		t.Errorf("expected sanitized repo name, got %q", filepath.Base(path))
	}
}

func TestTaskFilePath(t *testing.T) {
	base := t.TempDir()
	path := agent.TaskFilePath(base, "owner/repo", 42, "TASK")
	if !filepath.IsAbs(path) {
		t.Errorf("expected absolute path, got %q", path)
	}
	expected := "owner_repo_42_TASK.md"
	if filepath.Base(path) != expected {
		t.Errorf("filepath.Base = %q, want %q", filepath.Base(path), expected)
	}
}

// TestEnsureBareCloneFetchesNewBranches verifies that EnsureBareClone fetches
// new remote branches on subsequent calls (not just the first call).
func TestEnsureBareCloneFetchesNewBranches(t *testing.T) {
	agent.ResetCloneCache()
	t.Cleanup(agent.ResetCloneCache)

	ctx := context.Background()

	// Create a "remote" bare repo to act as origin
	remoteDir := t.TempDir()
	remoteRepo := filepath.Join(remoteDir, "origin.git")
	run(t, "git", "init", "--bare", remoteRepo)

	// Seed it with a commit on main so clone works
	seedDir := t.TempDir()
	run(t, "git", "clone", remoteRepo, seedDir)
	run(t, "git", "-C", seedDir, "commit", "--allow-empty", "-m", "init")
	run(t, "git", "-C", seedDir, "push", "origin", "HEAD:refs/heads/main")

	// First call: clones + fetches
	baseDir := t.TempDir()
	// Override repo URL by pre-cloning with the local remote
	barePath := agent.WorkspacePath(baseDir, "test/repo")
	run(t, "git", "clone", "--bare", remoteRepo, barePath)
	run(t, "git", "-C", barePath, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
	run(t, "git", "-C", barePath, "fetch", "--prune", "origin")

	// Mark as done so next call exercises the "already cloned" path
	agent.MarkCloneDone(barePath)

	// Now push a new branch to origin (simulating dev agent pushing PR branch)
	run(t, "git", "-C", seedDir, "checkout", "-b", "feature/issue-151")
	run(t, "git", "-C", seedDir, "commit", "--allow-empty", "-m", "feature work")
	run(t, "git", "-C", seedDir, "push", "origin", "feature/issue-151")

	// Verify the new branch is NOT in the bare clone yet
	err := exec.Command("git", "-C", barePath, "rev-parse", "--verify", "refs/remotes/origin/feature/issue-151").Run()
	if err == nil {
		t.Fatal("expected branch to not exist before re-fetch")
	}

	// Second call to EnsureBareClone: should fetch and pick up the new branch
	got, err := agent.EnsureBareClone(ctx, "test/repo", baseDir)
	if err != nil {
		t.Fatalf("EnsureBareClone: %v", err)
	}
	if got != barePath {
		t.Fatalf("got path %q, want %q", got, barePath)
	}

	// Now the branch should exist
	out, err := exec.Command("git", "-C", barePath, "rev-parse", "--verify", "refs/remotes/origin/feature/issue-151").CombinedOutput()
	if err != nil {
		t.Fatalf("expected branch to exist after EnsureBareClone, but got: %s: %v", out, err)
	}
}

func run(t *testing.T, name string, args ...string) {
	t.Helper()
	cmd := exec.Command(name, args...)
	cmd.Env = append(os.Environ(),
		"GIT_AUTHOR_NAME=test", "GIT_AUTHOR_EMAIL=test@test.com",
		"GIT_COMMITTER_NAME=test", "GIT_COMMITTER_EMAIL=test@test.com",
	)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("%s %v failed: %s: %v", name, args, out, err)
	}
}

