package tools

import (
	"context"
	"fmt"
	"os/exec"
	"strings"
)

// SubmitPRResult is the outcome of a PR creation attempt.
type SubmitPRResult struct {
	Success bool   `json:"success"`
	URL     string `json:"url,omitempty"`
	Error   string `json:"error,omitempty"`
}

// SubmitPR creates a pull request using the gh CLI.
func SubmitPR(ctx context.Context, repo, head, base, title, body string, ghConfigDir string, draft bool, labels []string) SubmitPRResult {
	if base == "" {
		base = "main"
	}

	body = CleanBody(body)

	args := []string{"pr", "create",
		"--repo", repo,
		"--head", head,
		"--base", base,
		"--title", title,
		"--body", body,
	}
	if draft {
		args = append(args, "--draft")
	}
	for _, l := range labels {
		args = append(args, "--label", l)
	}

	cmd := exec.CommandContext(ctx, "gh", args...)
	if ghConfigDir != "" {
		cmd.Env = append(cmd.Environ(), "GH_CONFIG_DIR="+ghConfigDir)
	}

	out, err := cmd.CombinedOutput()
	if err != nil {
		return SubmitPRResult{
			Success: false,
			Error:   fmt.Sprintf("%s: %s", err, strings.TrimSpace(string(out))),
		}
	}

	return SubmitPRResult{
		Success: true,
		URL:     strings.TrimSpace(string(out)),
	}
}

// CleanBody formats a PR body for proper rendering.
func CleanBody(body string) string {
	// Replace literal \n with newlines
	body = strings.ReplaceAll(body, `\n`, "\n")

	// Ensure blank lines before headers
	lines := strings.Split(body, "\n")
	var result []string
	for i, line := range lines {
		if strings.HasPrefix(line, "#") && i > 0 && result[len(result)-1] != "" {
			result = append(result, "")
		}
		result = append(result, line)
	}

	body = strings.Join(result, "\n")

	// Ensure Closes/Fixes/Resolves on its own line
	for _, keyword := range []string{"Closes", "Fixes", "Resolves"} {
		body = strings.ReplaceAll(body, " "+keyword+" #", "\n\n"+keyword+" #")
	}

	// Remove excessive blank lines (3+ consecutive)
	for strings.Contains(body, "\n\n\n") {
		body = strings.ReplaceAll(body, "\n\n\n", "\n\n")
	}

	return strings.TrimSpace(body)
}
