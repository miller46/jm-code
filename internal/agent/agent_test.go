package agent_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
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

func TestSpawnAgent_SuccessFalse(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(agent.SpawnResult{
			Success: false,
			Error:   json.RawMessage(`"agent not found: bad-agent"`),
		})
	}))
	defer srv.Close()

	os.Setenv("OPENCLAW_GATEWAY_URL", srv.URL)
	os.Setenv("OPENCLAW_GATEWAY_TOKEN", "test-token")
	defer os.Unsetenv("OPENCLAW_GATEWAY_URL")
	defer os.Unsetenv("OPENCLAW_GATEWAY_TOKEN")

	_, err := agent.SpawnAgent("test-label", "do stuff", "bad-agent", 30)
	if err == nil {
		t.Fatal("expected error for success=false response, got nil")
	}
	if !contains(err.Error(), "agent not found") {
		t.Errorf("error = %q, want it to contain 'agent not found'", err)
	}
}

func TestSpawnAgent_SuccessTrue(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(agent.SpawnResult{
			Success: true,
		})
	}))
	defer srv.Close()

	os.Setenv("OPENCLAW_GATEWAY_URL", srv.URL)
	os.Setenv("OPENCLAW_GATEWAY_TOKEN", "test-token")
	defer os.Unsetenv("OPENCLAW_GATEWAY_URL")
	defer os.Unsetenv("OPENCLAW_GATEWAY_TOKEN")

	result, err := agent.SpawnAgent("test-label", "do stuff", "good-agent", 30)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.Success {
		t.Error("expected Success=true")
	}
}

func TestSelectDevAgent_StaleCacheIgnored(t *testing.T) {
	available := []string{"backend-dev", "frontend-dev"}

	getCached := func(repo string, number int) (string, error) {
		return "miller46backenddev", nil // stale cached value not in available list
	}
	cacheSelection := func(repo string, number int, agentID string) error {
		return nil
	}

	selected, err := agent.SelectDevAgent("owner/repo", 1, "fix login bug", nil, available, getCached, cacheSelection)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	// Should NOT return the stale cached value
	if selected == "miller46backenddev" {
		t.Fatal("returned stale cached agent ID instead of re-selecting from available list")
	}
	// Should return one of the available agents
	found := false
	for _, a := range available {
		if selected == a {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("selected = %q, want one of %v", selected, available)
	}
}

func TestSelectDevAgent_ValidCacheUsed(t *testing.T) {
	available := []string{"backend-dev", "frontend-dev"}

	getCached := func(repo string, number int) (string, error) {
		return "frontend-dev", nil // valid cached value
	}
	cacheSelection := func(repo string, number int, agentID string) error {
		return nil
	}

	selected, err := agent.SelectDevAgent("owner/repo", 1, "fix login bug", nil, available, getCached, cacheSelection)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if selected != "frontend-dev" {
		t.Errorf("selected = %q, want %q", selected, "frontend-dev")
	}
}

func contains(s, substr string) bool {
	return len(s) >= len(substr) && searchSubstring(s, substr)
}

func searchSubstring(s, sub string) bool {
	for i := 0; i <= len(s)-len(sub); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}
