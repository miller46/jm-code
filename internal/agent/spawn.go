package agent

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"strings"
	"time"
)

func GatewayURL() string {
	if url := os.Getenv("OPENCLAW_GATEWAY_URL"); url != "" {
		return url
	}
	return "http://127.0.0.1:18789"
}

func GatewayToken() (string, error) {
	token := os.Getenv("OPENCLAW_GATEWAY_TOKEN")
	if token == "" {
		return "", fmt.Errorf("OPENCLAW_GATEWAY_TOKEN environment variable is not set")
	}
	return token, nil
}

type SpawnRequest struct {
	Tool    string         `json:"tool"`
	Action  string         `json:"action"`
	Args    map[string]any `json:"args"`
	Session string         `json:"sessionKey,omitempty"`
}

type SpawnResult struct {
	Success bool            `json:"ok"`
	Error   json.RawMessage `json:"error,omitempty"`
	Data    any             `json:"result,omitempty"`
}

// Handles both string and object error responses from the gateway.
func (r *SpawnResult) ErrorString() string {
	if len(r.Error) == 0 {
		return ""
	}
	var s string
	if json.Unmarshal(r.Error, &s) == nil {
		return s
	}
	return string(r.Error)
}

func SpawnAgent(label, prompt, agentID string, timeout int) (*SpawnResult, error) {
	if timeout == 0 {
		timeout = 1800
	}

	token, err := GatewayToken()
	if err != nil {
		return nil, err
	}

	payload := SpawnRequest{
		Tool:   "sessions_spawn",
		Action: "json",
		Args: map[string]any{
			"label":              label,
			"task":               prompt,
			"agentId":            agentID,
			"runTimeoutSeconds":  timeout,
			"cleanup":            "keep",
		},
	}

	slog.Info("spawning agent", "label", label, "agentId", agentID, "timeout", timeout)

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
	req.Header.Set("Authorization", "Bearer "+token)

	client := &http.Client{Timeout: time.Duration(timeout+60) * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("spawning agent: %w", err)
	}
	defer resp.Body.Close()

	rawBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("reading spawn response: %w", err)
	}

	var result SpawnResult
	if err := json.Unmarshal(rawBody, &result); err != nil {
		return nil, fmt.Errorf("decoding spawn response (status %d, body: %s): %w", resp.StatusCode, rawBody, err)
	}

	if resp.StatusCode != http.StatusOK {
		errMsg := result.ErrorString()
		if errMsg == "" {
			errMsg = string(rawBody)
		}
		return nil, fmt.Errorf("gateway returned %d: %s", resp.StatusCode, errMsg)
	}

	if !result.Success {
		errMsg := result.ErrorString()
		if errMsg == "" {
			errMsg = string(rawBody)
		}
		return nil, fmt.Errorf("spawn failed: %s", errMsg)
	}

	return &result, nil
}

func SelectDevAgent(
	repo string,
	issueNumber int,
	title string,
	labels []string,
	availableAgents []string,
	getCached func(repo string, number int) (string, error),
	cacheSelection func(repo string, number int, agentID string) error,
) (string, error) {
	if cached, err := getCached(repo, issueNumber); err == nil && cached != "" {
		for _, a := range availableAgents {
			if a == cached {
				return cached, nil
			}
		}
		// Cached agent no longer in available list; re-select
	}

	selected := selectByHeuristic(title, labels, availableAgents)

	if issueNumber > 0 {
		cacheSelection(repo, issueNumber, selected)
	}

	return selected, nil
}

func selectByHeuristic(title string, labels []string, available []string) string {
	if len(available) == 0 {
		return "backend-dev"
	}

	frontendKeywords := []string{"frontend", "ui", "ux", "css", "react", "component", "button", "layout", "design"}
	text := title
	for _, l := range labels {
		text += " " + l
	}

	for _, kw := range frontendKeywords {
		if containsIgnoreCase(text, kw) {
			for _, a := range available {
				if containsIgnoreCase(a, "frontend") {
					return a
				}
			}
		}
	}

	return available[0]
}

func containsIgnoreCase(s, substr string) bool {
	return strings.Contains(strings.ToLower(s), strings.ToLower(substr))
}
