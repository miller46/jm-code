// Package workflow orchestrates the dispatch of agents for each workflow step.
package workflow

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"

	"github.com/jack/go-cli/internal/agent"
	"github.com/jack/go-cli/internal/config"
	"github.com/jack/go-cli/internal/db"
	gh "github.com/jack/go-cli/internal/github"
	"github.com/jack/go-cli/internal/tools"
)

// Dispatcher manages agent dispatch for all workflow steps.
type Dispatcher struct {
	Store     *db.Store
	ConfigDir string
}

// DevOpenIssues finds open issues needing dev and dispatches agents.
func (d *Dispatcher) DevOpenIssues(ctx context.Context) (int, error) {
	client := &tools.IssueQueueClient{Store: d.Store}
	resp, err := client.Query(50, nil)
	if err != nil {
		return 0, fmt.Errorf("querying issues: %w", err)
	}

	count := 0
	for _, issue := range resp.Issues {
		agentsCfg, err := config.LoadAgentsForRepo(d.ConfigDir, issue.Repo)
		if err != nil {
			slog.Error("loading agents config", "repo", issue.Repo, "err", err)
			continue
		}

		enabled := agentsCfg.EnabledAgents()
		agentIDs := make([]string, len(enabled))
		for i, a := range enabled {
			agentIDs[i] = a.ID
		}

		selectedAgent, err := agent.SelectDevAgent(
			issue.Repo, issue.IssueNumber, issue.Title, issue.Labels, agentIDs,
			d.Store.GetCachedAgentSelection,
			d.Store.CacheAgentSelection,
		)
		if err != nil {
			slog.Error("selecting agent", "issue", issue.IssueNumber, "err", err)
			continue
		}

		taskFile, workspace, err := agent.SetupAgentWorkspace(ctx, selectedAgent, issue.Repo, issue.IssueNumber)
		if err != nil {
			slog.Error("setting up workspace", "issue", issue.IssueNumber, "err", err)
			continue
		}

		prompt := agent.GetDevPrompt(agent.DevPromptConfig{
			AgentID:      selectedAgent,
			Repo:         issue.Repo,
			TaskFile:     taskFile,
			IssueNumber:  issue.IssueNumber,
			Workspace:    workspace,
			SubmitPRTool: "submit_pr",
			GitCommitTool: "git_commit",
		})

		label := fmt.Sprintf("dev:%s#%d", issue.Repo, issue.IssueNumber)
		_, err = agent.SpawnAgent(label, prompt, selectedAgent, 1800)
		if err != nil {
			slog.Error("spawning dev agent", "issue", issue.IssueNumber, "err", err)
			continue
		}

		d.Store.MarkDispatched(issue.ItemID, "review", "")
		count++
		slog.Info("dispatched dev agent", "issue", issue.IssueNumber, "agent", selectedAgent)
	}

	return count, nil
}

// ReviewOpenPRs finds PRs needing review and dispatches reviewer agents.
func (d *Dispatcher) ReviewOpenPRs(ctx context.Context) (int, error) {
	client := &tools.PRQueueClient{Store: d.Store}
	resp, err := client.Query("needs_review", 20, nil)
	if err != nil {
		return 0, fmt.Errorf("querying PRs: %w", err)
	}

	count := 0
	for _, pr := range resp.PRs {
		reviewersCfg, err := config.LoadReviewersForRepo(d.ConfigDir, pr.Repo)
		if err != nil {
			slog.Error("loading reviewers config", "repo", pr.Repo, "err", err)
			continue
		}

		for _, reviewer := range reviewersCfg.EnabledReviewers() {
			// Skip if already reviewed this SHA
			if sha, ok := pr.ReviewerSHAs[reviewer.Name]; ok && sha == pr.HeadSHA {
				continue
			}
			// Skip if already dispatched for this SHA
			if sha, ok := pr.ReviewerDispatchSHAs[reviewer.Name]; ok && sha == pr.HeadSHA {
				continue
			}

			taskFile, workspace, err := agent.SetupReviewerWorkspace(ctx, reviewer.Name, pr.Repo, pr.PRNumber, pr.HeadRefName)
			if err != nil {
				slog.Error("setting up reviewer workspace", "pr", pr.PRNumber, "reviewer", reviewer.Name, "err", err)
				continue
			}

			prompt := agent.GetReviewerPrompt(reviewer.Name, pr.Repo, pr.PRNumber, workspace, taskFile, "submit_review")

			label := fmt.Sprintf("review:%s#%d:%s", pr.Repo, pr.PRNumber, reviewer.Name)
			_, err = agent.SpawnAgent(label, prompt, reviewer.Name, reviewer.Timeout)
			if err != nil {
				slog.Error("spawning reviewer", "pr", pr.PRNumber, "reviewer", reviewer.Name, "err", err)
				continue
			}

			d.Store.MarkReviewerDispatched(pr.ItemID, reviewer.Name, pr.HeadSHA)
			count++
			slog.Info("dispatched reviewer", "pr", pr.PRNumber, "reviewer", reviewer.Name)
		}
	}

	return count, nil
}

// FixOpenPRs finds PRs with changes requested and dispatches fix agents.
func (d *Dispatcher) FixOpenPRs(ctx context.Context) (int, error) {
	client := &tools.PRQueueClient{Store: d.Store}
	resp, err := client.Query("needs_fix", 20, nil)
	if err != nil {
		return 0, fmt.Errorf("querying fix PRs: %w", err)
	}

	count := 0
	for _, pr := range resp.PRs {
		item, err := d.Store.GetWorkflowItem(pr.ItemID)
		if err != nil {
			continue
		}

		devAgent := item.AssignedAgent
		if devAgent == "" {
			devAgent = pr.SuggestedDevAgent
		}
		if devAgent == "" {
			devAgent = "backend-dev"
		}

		taskFile, workspace, err := agent.SetupFixWorkspace(ctx, devAgent, pr.Repo, pr.PRNumber, pr.HeadRefName)
		if err != nil {
			slog.Error("setting up fix workspace", "pr", pr.PRNumber, "err", err)
			continue
		}

		prompt := agent.GetPRFixPrompt(agent.DevPromptConfig{
			AgentID:      devAgent,
			Repo:         pr.Repo,
			TaskFile:     taskFile,
			Workspace:    workspace,
			GitCommitTool: "git_commit",
		}, pr.PRNumber, pr.HeadRefName)

		label := fmt.Sprintf("fix:%s#%d", pr.Repo, pr.PRNumber)
		_, err = agent.SpawnAgent(label, prompt, devAgent, 1800)
		if err != nil {
			slog.Error("spawning fix agent", "pr", pr.PRNumber, "err", err)
			continue
		}

		d.Store.MarkDispatched(pr.ItemID, "fix", pr.HeadSHA)
		count++
		slog.Info("dispatched fix agent", "pr", pr.PRNumber, "agent", devAgent)
	}

	return count, nil
}

// FixPRMergeConflicts finds PRs with conflicts and dispatches conflict-resolution agents.
func (d *Dispatcher) FixPRMergeConflicts(ctx context.Context) (int, error) {
	client := &tools.PRQueueClient{Store: d.Store}
	resp, err := client.Query("needs_conflict_resolution", 20, nil)
	if err != nil {
		return 0, fmt.Errorf("querying conflict PRs: %w", err)
	}

	count := 0
	for _, pr := range resp.PRs {
		item, err := d.Store.GetWorkflowItem(pr.ItemID)
		if err != nil {
			continue
		}

		devAgent := item.AssignedAgent
		if devAgent == "" {
			devAgent = "backend-dev"
		}

		workspace, err := agent.SetupConflictWorkspace(ctx, devAgent, pr.Repo, pr.HeadRefName)
		if err != nil {
			slog.Error("setting up conflict workspace", "pr", pr.PRNumber, "err", err)
			continue
		}

		prompt := agent.GetPRConflictsPrompt(devAgent, pr.Repo, pr.HeadRefName, workspace, "git_commit")

		label := fmt.Sprintf("conflict:%s#%d", pr.Repo, pr.PRNumber)
		_, err = agent.SpawnAgent(label, prompt, devAgent, 1800)
		if err != nil {
			slog.Error("spawning conflict agent", "pr", pr.PRNumber, "err", err)
			continue
		}

		d.Store.MarkDispatched(pr.ItemID, "conflict", pr.HeadSHA)
		count++
		slog.Info("dispatched conflict agent", "pr", pr.PRNumber)
	}

	return count, nil
}

// FixStatusChecks finds PRs with failing CI and dispatches fix agents.
func (d *Dispatcher) FixStatusChecks(ctx context.Context) (int, error) {
	client := &tools.PRQueueClient{Store: d.Store}
	resp, err := client.Query("needs_status_fix", 20, nil)
	if err != nil {
		return 0, fmt.Errorf("querying status-fix PRs: %w", err)
	}

	count := 0
	for _, pr := range resp.PRs {
		item, err := d.Store.GetWorkflowItem(pr.ItemID)
		if err != nil {
			continue
		}

		devAgent := item.AssignedAgent
		if devAgent == "" {
			devAgent = "backend-dev"
		}

		taskFile, workspace, err := agent.SetupStatusFixWorkspace(ctx, devAgent, pr.Repo, pr.PRNumber, pr.HeadRefName)
		if err != nil {
			slog.Error("setting up status-fix workspace", "pr", pr.PRNumber, "err", err)
			continue
		}

		prompt := agent.GetPRFixStatusChecksPrompt(agent.DevPromptConfig{
			AgentID:      devAgent,
			Repo:         pr.Repo,
			TaskFile:     taskFile,
			Workspace:    workspace,
			GitCommitTool: "git_commit",
		}, pr.PRNumber, pr.HeadRefName)

		label := fmt.Sprintf("status-fix:%s#%d", pr.Repo, pr.PRNumber)
		_, err = agent.SpawnAgent(label, prompt, devAgent, 1800)
		if err != nil {
			slog.Error("spawning status-fix agent", "pr", pr.PRNumber, "err", err)
			continue
		}

		d.Store.MarkDispatched(pr.ItemID, "status_fix", pr.HeadSHA)
		count++
		slog.Info("dispatched status-fix agent", "pr", pr.PRNumber)
	}

	return count, nil
}

// MergePRs finds approved PRs and merges them.
func (d *Dispatcher) MergePRs(ctx context.Context) (int, error) {
	client := &tools.PRQueueClient{Store: d.Store}
	resp, err := client.Query("ready_to_merge", 20, nil)
	if err != nil {
		return 0, fmt.Errorf("querying merge PRs: %w", err)
	}

	// Load merge strategy from workflow config
	strategy := "merge"
	wfCfg, err := config.LoadWorkflow(d.ConfigDir)
	if err == nil && wfCfg.MergeAgent.Enabled {
		// Could add strategy to config; default to merge for now
		_ = wfCfg
	}

	count := 0
	for _, pr := range resp.PRs {
		result := gh.MergePR(ctx, pr.Repo, pr.PRNumber, strategy)
		if !result.Success {
			slog.Error("merge failed", "pr", pr.PRNumber, "error", result.Error)
			continue
		}

		d.Store.MarkDispatched(pr.ItemID, "merge", pr.HeadSHA)

		// Record dispatch event
		d.Store.InsertDispatchEvent(db.DispatchEvent{
			ItemID:       pr.ItemID,
			StepID:       "merge",
			HeadSHA:      pr.HeadSHA,
			Agent:        "merge-bot",
			Status:       "completed",
			DispatchedAt: db.Now(),
		})

		count++
		slog.Info("merged PR", "repo", pr.Repo, "pr", pr.PRNumber)
	}

	return count, nil
}

// RunAll executes all workflow dispatch steps in sequence.
func (d *Dispatcher) RunAll(ctx context.Context) error {
	steps := []struct {
		name string
		fn   func(context.Context) (int, error)
	}{
		{"dev_open_issues", d.DevOpenIssues},
		{"review_open_prs", d.ReviewOpenPRs},
		{"fix_open_prs", d.FixOpenPRs},
		{"fix_pr_merge_conflicts", d.FixPRMergeConflicts},
		{"fix_status_checks", d.FixStatusChecks},
		{"merge_prs", d.MergePRs},
	}

	for _, step := range steps {
		if ctx.Err() != nil {
			return ctx.Err()
		}

		count, err := step.fn(ctx)
		if err != nil {
			slog.Error("workflow step failed", "step", step.name, "err", err)
			continue
		}
		if count > 0 {
			slog.Info("workflow step complete", "step", step.name, "dispatched", count)
		}
	}

	return nil
}

// reviewerSHAsFromJSON parses reviewer dispatch SHAs from JSON.
func reviewerSHAsFromJSON(raw string) map[string]string {
	m := make(map[string]string)
	json.Unmarshal([]byte(raw), &m)
	return m
}
