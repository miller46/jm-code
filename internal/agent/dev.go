package agent

import "fmt"

type DevPromptConfig struct {
	AgentID      string
	Repo         string
	TaskFile     string
	IssueNumber  int
	Workspace    string
	PRTargetBase string // default: "main"
	SubmitPRTool string
	GitCommitTool string
}

func GetDevPrompt(cfg DevPromptConfig) string {
	if cfg.PRTargetBase == "" {
		cfg.PRTargetBase = "main"
	}
	branch := fmt.Sprintf("feature/issue-%d", cfg.IssueNumber)

	return fmt.Sprintf(`IMMEDIATELY execute: cd %s

Task: Read %s, implement the feature/fix described in the issue, write tests, and verify they pass.

Only do work on branch %s.

Steps:
1. Read the task file to understand the issue
2. Implement the required changes
3. Write tests for your changes
4. Run the tests and ensure they pass
5. Commit your changes using: %s --agent-id %s --branch %s --workspace %s --message "<commit message>"
6. Open a PR using: %s --agent-id %s --repo %s --issue-number %d --head %s --base %s --title "<title>" --body "<description>"

Important:
- Follow existing code patterns and conventions
- Write meaningful commit messages
- Include "Closes #%d" in the PR body`,
		cfg.Workspace,
		cfg.TaskFile,
		branch,
		cfg.GitCommitTool, cfg.AgentID, branch, cfg.Workspace,
		cfg.SubmitPRTool, cfg.AgentID, cfg.Repo, cfg.IssueNumber, branch, cfg.PRTargetBase,
		cfg.IssueNumber,
	)
}

func GetPRFixPrompt(cfg DevPromptConfig, prNumber int, branch string) string {
	return fmt.Sprintf(`You are tasked with fixing PR #%d in %s.

IMMEDIATELY execute: cd %s

Task: Read %s for review feedback. Make only the specific changes requested and any required tests.

Steps:
1. Read the task file for review context
2. Make the requested changes
3. Run tests to verify nothing is broken
4. Commit using: %s --agent-id %s --branch %s --workspace %s --message "<commit message>"

Do NOT open a new pull request. The existing PR will be updated by your push.`,
		prNumber, cfg.Repo,
		cfg.Workspace,
		cfg.TaskFile,
		cfg.GitCommitTool, cfg.AgentID, branch, cfg.Workspace,
	)
}

func GetPRConflictsPrompt(agentID, repo, branch, workspace, gitCommitTool string) string {
	return fmt.Sprintf(`You are tasked with resolving merge conflicts on branch %s in %s.

IMMEDIATELY execute: cd %s

Steps:
1. Run git status to identify conflicted files
2. Run git log to understand changes on both sides
3. Edit each conflicted file to resolve logically — preserve intent from both sides
4. Stage resolved files with git add
5. Run tests to verify the resolution
6. Commit using: %s --agent-id %s --branch %s --workspace %s --message "resolve merge conflicts"

Important: Do NOT just pick one side. Understand and merge both sets of changes.`,
		branch, repo,
		workspace,
		gitCommitTool, agentID, branch, workspace,
	)
}

func GetPRFixStatusChecksPrompt(cfg DevPromptConfig, prNumber int, branch string) string {
	return fmt.Sprintf(`You are tasked with fixing failing CI checks on PR #%d in %s.

IMMEDIATELY execute: cd %s

Task: Read %s for context on the failing checks and any review comments.

Steps:
1. Read the task file to understand what's failing
2. Identify the root cause of the CI failures
3. Make targeted fixes — only change what's needed
4. Run tests locally to verify
5. Commit using: %s --agent-id %s --branch %s --workspace %s --message "fix CI checks"

Do NOT open a new pull request.`,
		prNumber, cfg.Repo,
		cfg.Workspace,
		cfg.TaskFile,
		cfg.GitCommitTool, cfg.AgentID, branch, cfg.Workspace,
	)
}
