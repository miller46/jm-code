package config

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

type RepoConfig struct {
	Enabled      bool   `json:"enabled"`
	Priority     int    `json:"priority"`
	MaxPerRun    int    `json:"max_per_run"`
	DefaultAgent string `json:"defaultAgent"`
}

type ReposConfig struct {
	GlobalLimit int                   `json:"globalLimit"`
	Repos       map[string]RepoConfig `json:"repos"`
}

func (rc *ReposConfig) EnabledRepos() []string {
	var out []string
	for name, r := range rc.Repos {
		if r.Enabled {
			out = append(out, name)
		}
	}
	return out
}

type AgentConfig struct {
	ID      string `json:"id"`
	Name    string `json:"name"`
	Agent   string `json:"agent"`
	Enabled bool   `json:"enabled"`
}

type AgentsConfig struct {
	Agents []AgentConfig `json:"agents"`
}

func (ac *AgentsConfig) EnabledAgents() []AgentConfig {
	var out []AgentConfig
	for _, a := range ac.Agents {
		if a.Enabled {
			out = append(out, a)
		}
	}
	return out
}

type ReviewerConfig struct {
	Name       string `json:"name"`
	Agent      string `json:"agent"`
	GHConfigDir string `json:"gh_config_dir"`
	Timeout    int    `json:"timeout"`
	Focus      string `json:"focus"`
	Enabled    bool   `json:"enabled"`
	Weight     int    `json:"weight,omitempty"`
	Prompt     string `json:"prompt,omitempty"`
}

type ApprovalRules struct {
	Mode              string   `json:"mode"`
	MinApprovals      int      `json:"min_approvals"`
	RequiredReviewers []string `json:"required_reviewers"`
	VetoPowers        []string `json:"veto_powers"`
}

type ReviewersConfig struct {
	Reviewers     []ReviewerConfig `json:"reviewers"`
	ApprovalRules ApprovalRules    `json:"approval_rules"`
}

func (rc *ReviewersConfig) ReviewerNames() []string {
	out := make([]string, len(rc.Reviewers))
	for i, r := range rc.Reviewers {
		out[i] = r.Name
	}
	return out
}

func (rc *ReviewersConfig) EnabledReviewers() []ReviewerConfig {
	var out []ReviewerConfig
	for _, r := range rc.Reviewers {
		if r.Enabled {
			out = append(out, r)
		}
	}
	return out
}

type WorkflowAgentConfig struct {
	ID      string `json:"id"`
	Name    string `json:"name"`
	Agent   string `json:"agent"`
	Enabled bool   `json:"enabled"`
}

type WorkflowConfig struct {
	MergeAgent WorkflowAgentConfig `json:"merge_agent"`
}

func loadJSON(path string, dst any) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("reading %s: %w", path, err)
	}
	if err := json.Unmarshal(data, dst); err != nil {
		return fmt.Errorf("parsing %s: %w", path, err)
	}
	return nil
}

func LoadRepos(configDir string) (*ReposConfig, error) {
	var cfg ReposConfig
	if err := loadJSON(filepath.Join(configDir, "repos.json"), &cfg); err != nil {
		return nil, err
	}
	return &cfg, nil
}

func LoadAgents(configDir string) (*AgentsConfig, error) {
	var cfg AgentsConfig
	if err := loadJSON(filepath.Join(configDir, "agents.json"), &cfg); err != nil {
		return nil, err
	}
	return &cfg, nil
}

func LoadReviewers(configDir string) (*ReviewersConfig, error) {
	var cfg ReviewersConfig
	if err := loadJSON(filepath.Join(configDir, "reviewers.json"), &cfg); err != nil {
		return nil, err
	}
	return &cfg, nil
}

// Falls back to global reviewers.json if no repo-specific config exists at configDir/{owner}/{repo}/reviewers.json.
func LoadReviewersForRepo(configDir, repo string) (*ReviewersConfig, error) {
	parts := strings.SplitN(repo, "/", 2)
	if len(parts) == 2 {
		repoPath := filepath.Join(configDir, parts[0], parts[1], "reviewers.json")
		if _, err := os.Stat(repoPath); err == nil {
			var cfg ReviewersConfig
			if err := loadJSON(repoPath, &cfg); err != nil {
				return nil, err
			}
			return &cfg, nil
		}
	}
	return LoadReviewers(configDir)
}

// Falls back to global agents.json if no repo-specific config exists.
func LoadAgentsForRepo(configDir, repo string) (*AgentsConfig, error) {
	parts := strings.SplitN(repo, "/", 2)
	if len(parts) == 2 {
		repoPath := filepath.Join(configDir, parts[0], parts[1], "agents.json")
		if _, err := os.Stat(repoPath); err == nil {
			var cfg AgentsConfig
			if err := loadJSON(repoPath, &cfg); err != nil {
				return nil, err
			}
			return &cfg, nil
		}
	}
	return LoadAgents(configDir)
}

func LoadWorkflow(configDir string) (*WorkflowConfig, error) {
	var cfg WorkflowConfig
	if err := loadJSON(filepath.Join(configDir, "workflow.json"), &cfg); err != nil {
		return nil, err
	}
	return &cfg, nil
}
