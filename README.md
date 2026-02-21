# jm-code

Bot that syncs with GitHub and spawns agents to write code, review pull request, and fix issues in a loop.


```
Issue → Dev Agent → PR → Review Agents → Fix/Re-review loop → Merge
```

## Projects Built By Agents Using `jm-code`

* https://github.com/miller46/agent-command-center
* https://github.com/miller46/jm-api


## Sync States

### Issues

| Status | Action | What happens                                      |
|---|---|---------------------------------------------------|
| `open` | `needs_dev` | Spawn dev agents (backend-dev, frontend-dev, etc) |
| `in_progress` | `none` | Dev agent already assigned, wait                  |
| `pr_created` | `none` | PR exists for this issue, tracking moves to PR    |
| `closed` | `none` | Done                                              |

### Pull Requests

| Status | Action | What happens |
|---|---|---|
| `pending_review` | `needs_review` | Spawn reviewer agents (architect, code-snob, etc.) |
| `changes_requested` | `needs_fix` | Dev agent addresses review feedback |
| `checks_failing` | `needs_status_fix` | Dev agent fixes CI failures |
| `approved` | `ready_to_merge` | All required reviewers approved, auto-merge |
| `merged` | `none` | Done |


## Key Files

| File                    | Purpose                                                |
|-------------------------|--------------------------------------------------------|
| `bot.py`                | Entry point. Main app logic                            |
| `github/github_sync.py` | State machine (GitHub state → workflow state → action) |
| `workflow/tasks.py`     | Dispatches agents based on actions                     |
| `agent/dev_agent.py`    | Spawns agents for dev, fixes, conflict resolution      |
| `agent/review_agent.py` | Spawns agents for reviews                              |
| `tools/`                | Custom tools for agents                                |

## Config

| File                    | Purpose                            |
|-------------------------|------------------------------------|
| `config/repos.json`     | Which repos to manage and sync     |
| `config/reviewers.json` | Reviewer agents and approval rules |
| `config/workflow.json`  | Agent routing and merge criteria   |
| `config/agents.json`    | Dev agents                         |

Per-repo overrides go in `repos/{owner}/{repo}/config/`.
