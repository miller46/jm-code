package agent

import (
	"strings"
	"testing"
)

func TestBinaryPath_ReturnsAbsolutePath(t *testing.T) {
	path := BinaryPath()
	if path == "" {
		t.Fatal("BinaryPath() returned empty string")
	}
	if !strings.HasPrefix(path, "/") {
		t.Errorf("BinaryPath() = %q, want absolute path starting with /", path)
	}
}

func TestToolCommand_FormatsCorrectly(t *testing.T) {
	cmd := ToolCommand("git-commit")
	if !strings.HasSuffix(cmd, " git-commit") {
		t.Errorf("ToolCommand() = %q, want suffix ' git-commit'", cmd)
	}
	if !strings.HasPrefix(cmd, "/") {
		t.Errorf("ToolCommand() = %q, want absolute path prefix", cmd)
	}
}
