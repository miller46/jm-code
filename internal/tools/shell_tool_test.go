package tools_test

import (
	"context"
	"strings"
	"testing"

	"github.com/jack/go-cli/internal/tools"
)

func TestShellTool_ImplementsTool(t *testing.T) {
	var _ tools.Tool = tools.ShellTool{}
}

func TestShellTool_Run(t *testing.T) {
	tool := tools.ShellTool{}
	out, err := tool.Run(context.Background(), "echo hello")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if strings.TrimSpace(out) != "hello" {
		t.Errorf("expected %q, got %q", "hello", out)
	}
}

func TestShellTool_RunError(t *testing.T) {
	tool := tools.ShellTool{}
	_, err := tool.Run(context.Background(), "exit 1")
	if err == nil {
		t.Fatal("expected error for failed command")
	}
}
