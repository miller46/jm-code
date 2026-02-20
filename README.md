# jm-code

Bots to enable agents to write code, review pull requests, fix issues, and merge while enforcing high standards for quality. 

## Workflow

This system automates the full coding lifecycle:

```
Spec → GitHub Issue → Triage to Dev Agent → Pull Request → CI Testing →
Code Review → Fix & Re-review (repeat as needed) → Merge → CD
```

A sync loop continuously evaluates GitHub issues and PRs, then dispatches Claude agents to handle each stage:

1. **Triage** — Open issues are routed to a dev agent (frontend or backend) based on keywords
2. **Implement** — Dev agent writes code, opens a PR
3. **Review** — Reviewer agents (architect, code-snob, etc.) review the PR
4. **Fix** — If changes are requested, a dev agent addresses the feedback
5. **Re-review** — Reviewer agents re-review. Steps 4-5 repeat until approved.
6. **Merge** — Auto-merges approved PRs with no conflicts

## How it works

- `bot.py` — Entry point. Runs the sync + dispatch loop.
- `github/github_sync.py` — State machine. Maps GitHub state to worfklow state into SQLite and determines the next action per PR.
- `workflow/tasks.py` — Dispatches agents based on computed actions.
- `agent/review_agent.py` — Spawns OpenClaw agents for reviews, fixes, and conflict resolution.

## Config

### `config/repos.json` — Which repos to manage

```json
{
  "repos": {
    "owner/repo": { "enabled": true, "priority": 0, "max_per_run": 50 }
  }
}
```

### `config/default_reviewers.json` — Reviewer agents and approval rules

Defines which agents review PRs, their focus areas, and approval thresholds. Per-repo overrides go in `repos/{owner}/{repo}/config/reviewers.json`.

### `config/workflow.json` — Action dispatch settings

Configures agent routing (frontend vs backend keywords), lock durations, timeouts, and merge strategy. Per-repo overrides go in `repos/{owner}/{repo}/config/workflow.json`.

## Stack

Python, SQLite, GitHub CLI (`gh`)
