package config_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/jack/go-cli/internal/config"
)

func setupTestConfig(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()

	// repos.json
	os.WriteFile(filepath.Join(dir, "repos.json"), []byte(`{
		"globalLimit": 100,
		"repos": {
			"owner/repo1": {"enabled": true, "priority": 1, "max_per_run": 10, "defaultAgent": "backend-dev"},
			"owner/repo2": {"enabled": false, "priority": 0, "max_per_run": 5, "defaultAgent": "frontend-dev"}
		}
	}`), 0644)

	// agents.json
	os.WriteFile(filepath.Join(dir, "agents.json"), []byte(`{
		"agents": [
			{"id": "agent1", "name": "Agent One", "agent": "backend-dev", "enabled": true},
			{"id": "agent2", "name": "Agent Two", "agent": "frontend-dev", "enabled": false}
		]
	}`), 0644)

	// reviewers.json
	os.WriteFile(filepath.Join(dir, "reviewers.json"), []byte(`{
		"reviewers": [
			{"name": "rev1", "agent": "code-snob", "gh_config_dir": "/tmp/gh", "timeout": 900, "focus": "style", "enabled": true},
			{"name": "rev2", "agent": "architect", "gh_config_dir": "/tmp/gh2", "timeout": 600, "focus": "arch", "enabled": true}
		],
		"approval_rules": {
			"mode": "majority",
			"min_approvals": 2,
			"required_reviewers": ["rev1"],
			"veto_powers": ["rev1"]
		}
	}`), 0644)

	// workflow.json
	os.WriteFile(filepath.Join(dir, "workflow.json"), []byte(`{
		"merge_agent": {"id": "main-agent", "name": "Main", "agent": "main", "enabled": true}
	}`), 0644)

	return dir
}

func TestLoadRepos(t *testing.T) {
	dir := setupTestConfig(t)
	cfg, err := config.LoadRepos(dir)
	if err != nil {
		t.Fatalf("LoadRepos: %v", err)
	}

	if cfg.GlobalLimit != 100 {
		t.Errorf("GlobalLimit = %d, want 100", cfg.GlobalLimit)
	}
	if len(cfg.Repos) != 2 {
		t.Fatalf("len(Repos) = %d, want 2", len(cfg.Repos))
	}

	r1 := cfg.Repos["owner/repo1"]
	if !r1.Enabled {
		t.Error("repo1 should be enabled")
	}
	if r1.MaxPerRun != 10 {
		t.Errorf("repo1 MaxPerRun = %d, want 10", r1.MaxPerRun)
	}
}

func TestEnabledRepos(t *testing.T) {
	dir := setupTestConfig(t)
	cfg, err := config.LoadRepos(dir)
	if err != nil {
		t.Fatalf("LoadRepos: %v", err)
	}

	enabled := cfg.EnabledRepos()
	if len(enabled) != 1 {
		t.Fatalf("len(EnabledRepos) = %d, want 1", len(enabled))
	}
	if enabled[0] != "owner/repo1" {
		t.Errorf("EnabledRepos[0] = %q, want %q", enabled[0], "owner/repo1")
	}
}

func TestLoadAgents(t *testing.T) {
	dir := setupTestConfig(t)
	cfg, err := config.LoadAgents(dir)
	if err != nil {
		t.Fatalf("LoadAgents: %v", err)
	}

	if len(cfg.Agents) != 2 {
		t.Fatalf("len(Agents) = %d, want 2", len(cfg.Agents))
	}
	if cfg.Agents[0].ID != "agent1" {
		t.Errorf("Agents[0].ID = %q, want %q", cfg.Agents[0].ID, "agent1")
	}
}

func TestEnabledAgents(t *testing.T) {
	dir := setupTestConfig(t)
	cfg, err := config.LoadAgents(dir)
	if err != nil {
		t.Fatalf("LoadAgents: %v", err)
	}

	enabled := cfg.EnabledAgents()
	if len(enabled) != 1 {
		t.Fatalf("len(EnabledAgents) = %d, want 1", len(enabled))
	}
	if enabled[0].ID != "agent1" {
		t.Errorf("EnabledAgents[0].ID = %q, want %q", enabled[0].ID, "agent1")
	}
}

func TestLoadReviewers(t *testing.T) {
	dir := setupTestConfig(t)
	cfg, err := config.LoadReviewers(dir)
	if err != nil {
		t.Fatalf("LoadReviewers: %v", err)
	}

	if len(cfg.Reviewers) != 2 {
		t.Fatalf("len(Reviewers) = %d, want 2", len(cfg.Reviewers))
	}
	if cfg.ApprovalRules.MinApprovals != 2 {
		t.Errorf("MinApprovals = %d, want 2", cfg.ApprovalRules.MinApprovals)
	}
	if len(cfg.ApprovalRules.RequiredReviewers) != 1 {
		t.Errorf("len(RequiredReviewers) = %d, want 1", len(cfg.ApprovalRules.RequiredReviewers))
	}
}

func TestLoadWorkflow(t *testing.T) {
	dir := setupTestConfig(t)
	cfg, err := config.LoadWorkflow(dir)
	if err != nil {
		t.Fatalf("LoadWorkflow: %v", err)
	}

	if cfg.MergeAgent.ID != "main-agent" {
		t.Errorf("MergeAgent.ID = %q, want %q", cfg.MergeAgent.ID, "main-agent")
	}
	if !cfg.MergeAgent.Enabled {
		t.Error("MergeAgent should be enabled")
	}
}

func TestLoadReviewers_RepoOverride(t *testing.T) {
	dir := setupTestConfig(t)

	// Create repo-specific override
	repoDir := filepath.Join(dir, "owner", "repo1")
	os.MkdirAll(repoDir, 0755)
	os.WriteFile(filepath.Join(repoDir, "reviewers.json"), []byte(`{
		"reviewers": [
			{"name": "special-rev", "agent": "specialist", "gh_config_dir": "/tmp/special", "timeout": 300, "focus": "perf", "enabled": true}
		],
		"approval_rules": {
			"mode": "all",
			"min_approvals": 1,
			"required_reviewers": [],
			"veto_powers": []
		}
	}`), 0644)

	cfg, err := config.LoadReviewersForRepo(dir, "owner/repo1")
	if err != nil {
		t.Fatalf("LoadReviewersForRepo: %v", err)
	}

	if len(cfg.Reviewers) != 1 {
		t.Fatalf("len(Reviewers) = %d, want 1", len(cfg.Reviewers))
	}
	if cfg.Reviewers[0].Name != "special-rev" {
		t.Errorf("Reviewers[0].Name = %q, want %q", cfg.Reviewers[0].Name, "special-rev")
	}
}

func TestLoadReviewers_RepoFallback(t *testing.T) {
	dir := setupTestConfig(t)

	// No override for this repo — should fall back to global
	cfg, err := config.LoadReviewersForRepo(dir, "owner/no-override")
	if err != nil {
		t.Fatalf("LoadReviewersForRepo: %v", err)
	}

	if len(cfg.Reviewers) != 2 {
		t.Fatalf("len(Reviewers) = %d, want 2 (fallback)", len(cfg.Reviewers))
	}
}

func TestReviewerNames(t *testing.T) {
	dir := setupTestConfig(t)
	cfg, err := config.LoadReviewers(dir)
	if err != nil {
		t.Fatalf("LoadReviewers: %v", err)
	}

	names := cfg.ReviewerNames()
	if len(names) != 2 {
		t.Fatalf("len(ReviewerNames) = %d, want 2", len(names))
	}
}
