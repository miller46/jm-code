package agent_test

import (
	"testing"

	"github.com/jack/go-cli/internal/agent"
	"github.com/jack/go-cli/internal/tools"
)

func TestAgent_HasTools(t *testing.T) {
	a := agent.Agent{
		Name:  "test-agent",
		Tools: []tools.Tool{tools.ShellTool{}},
	}

	if a.Name != "test-agent" {
		t.Errorf("expected name %q, got %q", "test-agent", a.Name)
	}
	if len(a.Tools) != 1 {
		t.Fatalf("expected 1 tool, got %d", len(a.Tools))
	}
	if a.Tools[0].Name() != "shell" {
		t.Errorf("expected tool name %q, got %q", "shell", a.Tools[0].Name())
	}
}
