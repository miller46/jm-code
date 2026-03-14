package agent

import (
	"fmt"
	"os"
	"path/filepath"
)

// BinaryPath returns the absolute path of the orchestrator binary.
//
// Resolution order:
//  1. ORCHESTRATOR_BIN env var (must be absolute)
//  2. os.Executable() with symlink resolution
//
// This ensures agents can invoke tool subcommands from any working directory,
// regardless of OS (Linux, macOS, etc.).
func BinaryPath() string {
	if envPath := os.Getenv("ORCHESTRATOR_BIN"); envPath != "" && filepath.IsAbs(envPath) {
		return envPath
	}

	exe, err := os.Executable()
	if err != nil {
		// This should not happen in production; log-worthy but don't panic.
		return exe
	}
	resolved, err := filepath.EvalSymlinks(exe)
	if err != nil {
		return exe
	}
	return resolved
}

// ToolCommand returns the full command string for invoking a subcommand
// of the orchestrator binary (e.g. "/home/jack/jm-code/orchestrator git-commit").
func ToolCommand(subcommand string) string {
	return fmt.Sprintf("%s %s", BinaryPath(), subcommand)
}
