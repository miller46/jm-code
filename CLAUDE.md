## Context

This is an app to automate coding workflows using GitHub actions.

The orchestrator syncs GitHub issues/PRs, dispatches Claude Code agents via the OpenClaw gateway, and manages the full dev lifecycle: issue -> code -> PR -> review -> fix loop -> merge.

## Agent Tools

Agents are spawned via `sessions_spawn` on the OpenClaw gateway. They are Claude Code sessions that run in `~/.openclaw/agents/{agent-name}/` directories.

Custom tools (`git-commit`, `submit-pr`, `submit-review`) are cobra subcommands on the orchestrator binary. Agents invoke them via the binary's absolute path, resolved at runtime by `agent.ToolCommand()`. Example prompt output:

```
/path/to/orchestrator git-commit --agent-id backend-dev --branch feature/issue-42 --workspace /path/to/ws --message "fix bug"
```

Tool implementations live in `internal/tools/`. CLI wrappers live in `cmd/`. The `ghConfigDir` for each agent is derived from `AgentHomeDir(agentID) + "/agent"`.
