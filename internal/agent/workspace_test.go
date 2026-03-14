package agent_test

import (
	"os"
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

func TestWriteTaskFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "test_task.md")

	err := agent.WriteTaskFile(path, "# Test\nHello world")
	if err != nil {
		t.Fatalf("WriteTaskFile: %v", err)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}
	if string(data) != "# Test\nHello world" {
		t.Errorf("content = %q, want %q", string(data), "# Test\nHello world")
	}
}
