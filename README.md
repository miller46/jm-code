# jm-code

Bots to enable agents to write code, review pull requests, fix issues, and merge while enforcing high standards for quality. 

`bot.py` is the entry point and contains the primary workflow logic. 

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENCLAW_GATEWAY_TOKEN` | **Yes** | — | OpenClaw Gateway auth token |
| `OPENCLAW_GATEWAY_URL` | No | `http://127.0.0.1:18789` | OpenClaw Gateway URL |
| `GITHUB_SYNC_DB_PATH` | No | `~/.openclaw/workspace-manager/workflow.db` | SQLite DB path |
| `WORKFLOW_REPOS_CONFIG` | No | `config/repos.json` | Repos config path |
| `WORKSPACE_MANAGER_ROOT` | No | `~/.openclaw/workspace-manager` | Root for reviewer configs and logs |

## Workflow

This system automates the full coding lifecycle:

```
Spec → GitHub Issue → Triage to Dev Agent → Pull Request → CI Testing →
Code Review → Fix & Re-review (repeat as needed) → Merge → CD
```

A sync loop continuously evaluates GitHub issues and PRs, then dispatches Claude agents to handle each stage:

1. **Triage**  Open issues are routed to a dev agent (frontend or backend) based on keywords
2. **Implement**  Dev agent writes code, opens a PR
3. **Review**  Reviewer agents (architect, code-snob, etc.) review the PR
4. **Fix**  If changes are requested, a dev agent addresses the feedback
5. **Re-review**  Reviewer agents re-review. Steps 4-5 repeat until approved.
6. **Merge**  Auto-merges approved PRs with no conflicts

## How it works

- `bot.py`  Entry point. Runs the sync and dispatch loop. Main logic is here.
- `sync_bot.py`  Separate process to run GitHub sync if you want to decouple them.
- `github/github_sync.py`  State machine. Maps GitHub state to worfklow state into SQLite and determines the next action per PR.
- `workflow/tasks.py`  Dispatches agents based on computed actions.
- `agent/review_agent.py`  Spawns OpenClaw agents for reviews, fixes, and conflict resolution.

## Custom Tools

Agents don't call `gh` directly. Instead, they use custom tool scripts (e.g. `submit_pr_review`, `get_open_issues`, `get_open_prs`) that act as middleware:

- **Per-agent GitHub tokens** — Each agent has its own `GH_CONFIG_DIR` (e.g. `~/.openclaw/agents/architect/agent`). The tools resolve the caller's identity from the reviewer config, set the correct `GH_CONFIG_DIR`, and strip ambient `GH_TOKEN`/`GITHUB_TOKEN` so every GitHub action is attributed to the right agent account.
- **Dispatch logging** — Tool invocations are logged for the manager agent. Failures write debug info (auth status, config source) to `~/.openclaw/workspace-manager/logs/`.
- **Input validation** — Tools enforce structured output (e.g. review body must start with `VERDICT: APPROVE` or `VERDICT: REQUEST_CHANGES`) so downstream parsing is reliable.

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

Defines which agents review PRs, their focus areas, and approval thresholds. 

Per-repo overrides go in `repos/{owner}/{repo}/config/reviewers.json`.

### `config/workflow.json` — Action dispatch settings

Configures agent routing and merge approval criteria. 

Per-repo overrides go in `repos/{owner}/{repo}/config/workflow.json`.
