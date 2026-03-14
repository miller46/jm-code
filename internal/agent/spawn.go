package agent

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"time"
)

// GatewayURL returns the OpenClaw gateway URL from env or default.
func GatewayURL() string {
	if url := os.Getenv("OPENCLAW_GATEWAY_URL"); url != "" {
		return url
	}
	return "http://127.0.0.1:18789"
}

// GatewayToken returns the OpenClaw gateway auth token.
func GatewayToken() string {
	return os.Getenv("OPENCLAW_GATEWAY_TOKEN")
}

// SpawnRequest is the payload for spawning an agent via the OpenClaw gateway.
type SpawnRequest struct {
	Tool    string         `json:"tool"`
	Action  string         `json:"action"`
	Args    map[string]any `json:"args"`
	Session string         `json:"sessionKey,omitempty"`
}

// SpawnResult is the response from the gateway.
type SpawnResult struct {
	Success bool   `json:"success"`
	Error   string `json:"error,omitempty"`
	Data    any    `json:"data,omitempty"`
}

// SpawnAgent dispatches an agent via the OpenClaw gateway HTTP API.
func SpawnAgent(label, prompt, agentID string, timeout int) (*SpawnResult, error) {
	if timeout == 0 {
		timeout = 1800
	}

	payload := SpawnRequest{
		Tool:   "sessions_spawn",
		Action: "json",
		Args: map[string]any{
			"label":   label,
			"prompt":  prompt,
			"agentId": agentID,
			"timeout": timeout,
			"cleanup": "keep",
		},
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("marshaling spawn request: %w", err)
	}

	url := GatewayURL() + "/tools/invoke"
	req, err := http.NewRequest("POST", url, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("creating request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	if token := GatewayToken(); token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}

	client := &http.Client{Timeout: time.Duration(timeout+60) * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("spawning agent: %w", err)
	}
	defer resp.Body.Close()

	var result SpawnResult
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("decoding spawn response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("gateway returned %d: %s", resp.StatusCode, result.Error)
	}

	return &result, nil
}

// SelectDevAgent picks the best dev agent for an issue.
// Checks the DB cache first, then calls the "main" agent to decide.
func SelectDevAgent(
	repo string,
	issueNumber int,
	title string,
	labels []string,
	availableAgents []string,
	getCached func(repo string, number int) (string, error),
	cacheSelection func(repo string, number int, agentID string) error,
) (string, error) {
	// Check cache
	if cached, err := getCached(repo, issueNumber); err == nil && cached != "" {
		return cached, nil
	}

	// Simple heuristic selection (matches Python's suggest_agent)
	selected := selectByHeuristic(title, labels, availableAgents)

	// Cache the selection
	if issueNumber > 0 {
		cacheSelection(repo, issueNumber, selected)
	}

	return selected, nil
}

func selectByHeuristic(title string, labels []string, available []string) string {
	if len(available) == 0 {
		return "backend-dev"
	}

	// Check for frontend indicators
	frontendKeywords := []string{"frontend", "ui", "ux", "css", "react", "component", "button", "layout", "design"}
	text := title
	for _, l := range labels {
		text += " " + l
	}

	for _, kw := range frontendKeywords {
		if contains(text, kw) {
			for _, a := range available {
				if contains(a, "frontend") {
					return a
				}
			}
		}
	}

	return available[0]
}

func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(s) > 0 && containsLower(s, substr))
}

func containsLower(s, substr string) bool {
	s = toLower(s)
	substr = toLower(substr)
	return len(s) >= len(substr) && findSubstring(s, substr)
}

func toLower(s string) string {
	b := make([]byte, len(s))
	for i := range s {
		c := s[i]
		if c >= 'A' && c <= 'Z' {
			c += 'a' - 'A'
		}
		b[i] = c
	}
	return string(b)
}

func findSubstring(s, sub string) bool {
	for i := 0; i <= len(s)-len(sub); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}
