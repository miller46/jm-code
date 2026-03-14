package agent

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestBinaryPath_ReturnsAbsolutePath(t *testing.T) {
	// Clear env override so we test os.Executable() path
	os.Unsetenv("ORCHESTRATOR_BIN")

	path := BinaryPath()
	if path == "" {
		t.Fatal("BinaryPath() returned empty string")
	}
	if !filepath.IsAbs(path) {
		t.Errorf("BinaryPath() = %q, want absolute path", path)
	}
}

func TestBinaryPath_RespectsEnvOverride(t *testing.T) {
	t.Setenv("ORCHESTRATOR_BIN", "/usr/local/bin/orchestrator")
	defer os.Unsetenv("ORCHESTRATOR_BIN")

	path := BinaryPath()
	if path != "/usr/local/bin/orchestrator" {
		t.Errorf("BinaryPath() = %q, want /usr/local/bin/orchestrator", path)
	}
}

func TestBinaryPath_EnvOverrideMustBeAbsolute(t *testing.T) {
	t.Setenv("ORCHESTRATOR_BIN", "relative/path/orchestrator")
	defer os.Unsetenv("ORCHESTRATOR_BIN")

	// Should ignore non-absolute env value and fall through to os.Executable()
	path := BinaryPath()
	if path == "relative/path/orchestrator" {
		t.Error("BinaryPath() should ignore non-absolute ORCHESTRATOR_BIN")
	}
	if !filepath.IsAbs(path) {
		t.Errorf("BinaryPath() = %q, want absolute path", path)
	}
}

func TestToolCommand_FormatsCorrectly(t *testing.T) {
	t.Setenv("ORCHESTRATOR_BIN", "/opt/orchestrator")
	defer os.Unsetenv("ORCHESTRATOR_BIN")

	cmd := ToolCommand("git-commit")
	if cmd != "/opt/orchestrator git-commit" {
		t.Errorf("ToolCommand() = %q, want '/opt/orchestrator git-commit'", cmd)
	}
}

func TestToolCommand_AbsolutePrefix(t *testing.T) {
	os.Unsetenv("ORCHESTRATOR_BIN")

	cmd := ToolCommand("submit-pr")
	if !strings.HasSuffix(cmd, " submit-pr") {
		t.Errorf("ToolCommand() = %q, want suffix ' submit-pr'", cmd)
	}
	if !filepath.IsAbs(strings.Fields(cmd)[0]) {
		t.Errorf("ToolCommand() binary path is not absolute: %q", cmd)
	}
}
