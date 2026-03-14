// Package config loads JSON configuration files for repos, agents, reviewers, and workflow.
package config

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// RepoConfig describes a single tracked repository.
type RepoConfig struct {
	Enabled      bool   `json:"enabled"`
	Priority     int    `json:"priority"`
	MaxPerRun    int    `json:"max_per_run"`
	DefaultAgent string `json:"defaultAgent"`
}

// ReposConfig is the top-level repos.json structure.
type ReposConfig struct {
	GlobalLimit int                   `json:"globalLimit"`
	Repos       map[string]RepoConfig `json:"repos"`
}

// EnabledRepos returns the names of repos where Enabled is true.
func (rc *ReposConfig) EnabledRepos() []string {
	var out []string
	for name, r := range rc.Repos {
		if r.Enabled {
			out = append(out, name)
		}
	}
	return out
}

// AgentConfig describes a single agent.
type AgentConfig struct {
	ID      string `json:"id"`
	Name    string `json:"name"`
	Agent   string `json:"agent"`
	Enabled bool   `json:"enabled"`
}

// AgentsConfig is the top-level agents.json structure.
type AgentsConfig struct {
	Agents []AgentConfig `json:"agents"`
}

// EnabledAgents returns agents where Enabled is true.
func (ac *AgentsConfig) EnabledAgents() []AgentConfig {
	var out []AgentConfig
	for _, a := range ac.Agents {
		if a.Enabled {
			out = append(out, a)
		}
	}
	return out
}

// ReviewerConfig describes a single reviewer.
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

// ApprovalRules defines the review policy.
type ApprovalRules struct {
	Mode              string   `json:"mode"`
	MinApprovals      int      `json:"min_approvals"`
	RequiredReviewers []string `json:"required_reviewers"`
	VetoPowers        []string `json:"veto_powers"`
}

// ReviewersConfig is the top-level reviewers.json structure.
type ReviewersConfig struct {
	Reviewers     []ReviewerConfig `json:"reviewers"`
	ApprovalRules ApprovalRules    `json:"approval_rules"`
}

// ReviewerNames returns the names of all reviewers.
func (rc *ReviewersConfig) ReviewerNames() []string {
	out := make([]string, len(rc.Reviewers))
	for i, r := range rc.Reviewers {
		out[i] = r.Name
	}
	return out
}

// EnabledReviewers returns reviewers where Enabled is true.
func (rc *ReviewersConfig) EnabledReviewers() []ReviewerConfig {
	var out []ReviewerConfig
	for _, r := range rc.Reviewers {
		if r.Enabled {
			out = append(out, r)
		}
	}
	return out
}

// WorkflowAgentConfig describes an agent used in the workflow (e.g. merge agent).
type WorkflowAgentConfig struct {
	ID      string `json:"id"`
	Name    string `json:"name"`
	Agent   string `json:"agent"`
	Enabled bool   `json:"enabled"`
}

// WorkflowConfig is the top-level workflow.json structure.
type WorkflowConfig struct {
	MergeAgent WorkflowAgentConfig `json:"merge_agent"`
}

// loadJSON reads and unmarshals a JSON file into dst.
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

// LoadRepos loads repos.json from the given config directory.
func LoadRepos(configDir string) (*ReposConfig, error) {
	var cfg ReposConfig
	if err := loadJSON(filepath.Join(configDir, "repos.json"), &cfg); err != nil {
		return nil, err
	}
	return &cfg, nil
}

// LoadAgents loads agents.json from the given config directory.
func LoadAgents(configDir string) (*AgentsConfig, error) {
	var cfg AgentsConfig
	if err := loadJSON(filepath.Join(configDir, "agents.json"), &cfg); err != nil {
		return nil, err
	}
	return &cfg, nil
}

// LoadReviewers loads reviewers.json from the given config directory.
func LoadReviewers(configDir string) (*ReviewersConfig, error) {
	var cfg ReviewersConfig
	if err := loadJSON(filepath.Join(configDir, "reviewers.json"), &cfg); err != nil {
		return nil, err
	}
	return &cfg, nil
}

// LoadReviewersForRepo loads repo-specific reviewers.json, falling back to the global one.
// Repo-specific config lives at configDir/{owner}/{repo}/reviewers.json.
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

// LoadAgentsForRepo loads repo-specific agents.json, falling back to the global one.
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

// LoadWorkflow loads workflow.json from the given config directory.
func LoadWorkflow(configDir string) (*WorkflowConfig, error) {
	var cfg WorkflowConfig
	if err := loadJSON(filepath.Join(configDir, "workflow.json"), &cfg); err != nil {
		return nil, err
	}
	return &cfg, nil
}
