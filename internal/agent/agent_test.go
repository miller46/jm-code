package agent_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/jack/go-cli/internal/agent"
)

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

	_, err := agent.SpawnAgent(context.Background(), "test-label", "do stuff", "bad-agent", 30)
	if err == nil {
		t.Fatal("expected error for success=false response, got nil")
	}
	if !strings.Contains(err.Error(), "agent not found") {
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

	result, err := agent.SpawnAgent(context.Background(), "test-label", "do stuff", "good-agent", 30)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.Success {
		t.Error("expected Success=true")
	}
}

func TestSpawnAgent_ContextCancelAborts(t *testing.T) {
	started := make(chan struct{})
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(started)
		<-release
	}))
	defer srv.Close()
	defer close(release)

	os.Setenv("OPENCLAW_GATEWAY_URL", srv.URL)
	os.Setenv("OPENCLAW_GATEWAY_TOKEN", "test-token")
	defer os.Unsetenv("OPENCLAW_GATEWAY_URL")
	defer os.Unsetenv("OPENCLAW_GATEWAY_TOKEN")

	ctx, cancel := context.WithCancel(context.Background())

	errCh := make(chan error, 1)
	go func() {
		_, err := agent.SpawnAgent(ctx, "test-label", "do stuff", "agent", 1800)
		errCh <- err
	}()

	<-started
	cancel()

	select {
	case err := <-errCh:
		if err == nil {
			t.Fatal("expected error after context cancel, got nil")
		}
		if !strings.Contains(err.Error(), "context canceled") {
			t.Errorf("error = %q, want it to mention 'context canceled'", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("SpawnAgent did not return after context cancel")
	}
}

func TestSpawnAgent_ShortClientTimeoutEnforced(t *testing.T) {
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		<-release
	}))
	defer srv.Close()
	defer close(release)

	os.Setenv("OPENCLAW_GATEWAY_URL", srv.URL)
	os.Setenv("OPENCLAW_GATEWAY_TOKEN", "test-token")
	defer os.Unsetenv("OPENCLAW_GATEWAY_URL")
	defer os.Unsetenv("OPENCLAW_GATEWAY_TOKEN")

	prev := agent.HTTPClientTimeout
	agent.HTTPClientTimeout = 50 * time.Millisecond
	defer func() { agent.HTTPClientTimeout = prev }()

	start := time.Now()
	_, err := agent.SpawnAgent(context.Background(), "test-label", "do stuff", "agent", 1800)
	elapsed := time.Since(start)

	if err == nil {
		t.Fatal("expected timeout error, got nil")
	}
	if elapsed > 2*time.Second {
		t.Fatalf("request took %v; client timeout was not enforced (still coupled to runTimeoutSeconds?)", elapsed)
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

