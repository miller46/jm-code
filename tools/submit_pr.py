#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

WORKSPACE_MANAGER_ROOT = Path(
    os.environ.get("WORKSPACE_MANAGER_ROOT", "/Users/jack/.openclaw/workspace-manager")
)
DEFAULT_AGENTS_PATH = WORKSPACE_MANAGER_ROOT / "agents.json"

ALLOWED_EVENTS = {"create", "create_draft"}


def error(code: str, message: str, retryable: bool = False) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "retryable": retryable}}


def load_json(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not path.exists():
        return None, error("CONFIG_NOT_FOUND", f"Config not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        return None, error("INVALID_CONFIG", f"Invalid JSON in {path}: {exc}")
    except OSError as exc:
        return None, error("CONFIG_READ_FAILED", f"Unable to read {path}: {exc}", retryable=True)

    if not isinstance(data, dict):
        return None, error("INVALID_CONFIG", f"Top-level JSON must be an object: {path}")
    return data, None


def parse_repo(repo: str) -> tuple[str, str] | None:
    parts = [p for p in repo.strip().split("/") if p]
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def resolve_agent_config(repo: str) -> tuple[dict[str, Any] | None, str, dict[str, Any] | None]:
    parsed = parse_repo(repo)
    if not parsed:
        return None, "", error("INVALID_INPUT", "repo must be in owner/repo format")

    owner, name = parsed
    repo_cfg = WORKSPACE_MANAGER_ROOT / "repos" / owner / name / "config" / "agents.json"
    default_cfg = DEFAULT_AGENTS_PATH

    if repo_cfg.exists():
        payload, err = load_json(repo_cfg)
        if err:
            return None, "", err
        return payload, str(repo_cfg), None

    payload, err = load_json(default_cfg)
    if err:
        return None, "", err
    return payload, str(default_cfg), None


def find_agent(payload: dict[str, Any], agent_id: str) -> dict[str, Any] | None:
    # Repo-specific format
    for entry in payload.get("required_reviewers", []):
        if not isinstance(entry, dict):
            continue
        rid = entry.get("id") or entry.get("agent") or entry.get("name")
        if isinstance(rid, str) and rid.strip() == agent_id:
            return entry

    # Global format
    for entry in payload.get("agents", []):
        if not isinstance(entry, dict):
            continue
        rid = entry.get("id") or entry.get("name") or entry.get("agent")
        if isinstance(rid, str) and rid.strip() == agent_id:
            return entry

    return None


def agent_gh_config_dir(agent: dict[str, Any], agent_id: str) -> str | None:
    candidate = os.path.expanduser(f"~/.openclaw/agents/{agent_id}/agent")
    if os.path.isdir(candidate):
        return candidate
    return None


def validate_inputs(repo: str, head: str, base: str, title: str) -> dict[str, Any] | None:
    if not repo or not parse_repo(repo):
        return error("INVALID_INPUT", "repo must be in owner/repo format")
    if not head or not head.strip():
        return error("INVALID_INPUT", "head branch is required")
    if not base or not base.strip():
        return error("INVALID_INPUT", "base branch is required")
    if not title or not title.strip():
        return error("INVALID_INPUT", "title is required")
    return None


def get_gh_auth_info(gh_config_dir: str | None, env: dict[str, str]) -> dict[str, Any]:
    """Get current gh auth status for debugging."""
    cmd = ["gh", "auth", "status"]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def log_debug(info: dict[str, Any]) -> None:
    """Write debug info to log file for troubleshooting."""
    log_path = Path("/Users/jack/.openclaw/workspace-manager/logs/submit_pr.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    import datetime
    with log_path.open("a") as f:
        f.write(f"\n--- {datetime.datetime.now().isoformat()} ---\n")
        f.write(json.dumps(info, indent=2))
        f.write("\n")


def submit_pr(
    repo: str,
    head: str,
    base: str,
    title: str,
    body: str,
    gh_config_dir: str | None,
    draft: bool = False,
    labels: list[str] | None = None,
    debug: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    cmd = [
        "gh",
        "pr",
        "create",
        "--repo",
        repo,
        "--head",
        head,
        "--base",
        base,
        "--title",
        title,
        "--body",
        body,
    ]

    if draft:
        cmd.append("--draft")

    for label in labels or []:
        cmd.extend(["--label", label])

    env = os.environ.copy()
    if gh_config_dir:
        env["GH_CONFIG_DIR"] = gh_config_dir
    else:
        env.pop("GH_CONFIG_DIR", None)

    # Clear other gh env vars that might interfere
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)

    debug_info = {
        "gh_config_dir": gh_config_dir,
        "gh_config_dir_exists": os.path.isdir(gh_config_dir) if gh_config_dir else None,
        "hosts_yml_exists": os.path.isfile(os.path.join(gh_config_dir, "hosts.yml")) if gh_config_dir else None,
        "auth_status": get_gh_auth_info(gh_config_dir, env) if debug else None,
    }

    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "gh pr create failed").strip(), debug_info
    return True, (proc.stdout or "submitted").strip(), debug_info


def parse_input(stdin_text: str | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    payload: dict[str, Any] = {}
    if stdin_text and stdin_text.strip():
        try:
            payload = json.loads(stdin_text)
        except json.JSONDecodeError:
            return None, error("INVALID_INPUT", "stdin must contain valid JSON")
    return payload, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Submit a pull request via gh CLI with agent token enforcement")
    parser.add_argument("--repo", help="owner/repo")
    parser.add_argument("--head", help="Source branch name")
    parser.add_argument("--base", default="main", help="Target branch (default: main)")
    parser.add_argument("--title", help="PR title")
    parser.add_argument("--body", default="", help="PR body/description")
    parser.add_argument("--agent-id", help="Agent identity for token resolution")
    parser.add_argument("--draft", action="store_true", help="Create as draft PR")
    parser.add_argument("--label", action="append", dest="labels", help="Labels to add (repeatable)")
    parser.add_argument("--input-json", default=None, help="Alternative JSON payload")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print command plan without calling gh")
    parser.add_argument("--debug", action="store_true", help="Include debug info about auth")
    args = parser.parse_args(argv or sys.argv[1:])

    payload = {
        "repo": args.repo,
        "head": args.head,
        "base": args.base,
        "title": args.title,
        "body": args.body,
        "agentId": args.agent_id,
        "draft": args.draft,
        "labels": args.labels or [],
    }

    if args.input_json is not None:
        try:
            payload = json.loads(args.input_json)
        except json.JSONDecodeError:
            print(json.dumps(error("INVALID_INPUT", "--input-json must be valid JSON")))
            return 1
    elif not args.repo and not args.head and not args.title and not args.agent_id:
        parsed, err = parse_input(sys.stdin.read())
        if err:
            print(json.dumps(err))
            return 1
        payload = parsed or {}

    repo = payload.get("repo")
    head = payload.get("head")
    base = payload.get("base", "main")
    title = payload.get("title")
    body = payload.get("body", "")
    agent_id = payload.get("agentId")
    draft = payload.get("draft", False)
    labels = payload.get("labels", [])

    input_err = validate_inputs(repo or "", head or "", base or "", title or "")
    if input_err:
        print(json.dumps(input_err))
        return 1

    if not isinstance(agent_id, str) or not agent_id.strip():
        print(json.dumps(error("INVALID_INPUT", "agentId is required")))
        return 1

    cfg, cfg_source, cfg_err = resolve_agent_config(repo)
    if cfg_err:
        print(json.dumps(cfg_err))
        return 1
    assert cfg is not None

    agent = find_agent(cfg, agent_id)
    if agent is None:
        print(json.dumps(error("CONFIG_ERROR", f"agent '{agent_id}' not found in {cfg_source}")))
        return 1

    gh_config_dir = agent_gh_config_dir(agent, agent_id)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "ok": True,
                    "dryRun": True,
                    "repo": repo,
                    "head": head,
                    "base": base,
                    "title": title,
                    "agentId": agent_id,
                    "draft": draft,
                    "labels": labels,
                    "configSource": cfg_source,
                    "ghConfigDir": gh_config_dir,
                    "authSource": "agent_gh_config_dir" if gh_config_dir else "default_env_token",
                }
            )
        )
        return 0

    ok, details, debug_info = submit_pr(
        repo=repo,
        head=head,
        base=base,
        title=title,
        body=body,
        gh_config_dir=gh_config_dir,
        draft=draft,
        labels=labels,
        debug=args.debug,
    )
    if not ok:
        result = error("GH_PR_CREATE_FAILED", details, retryable=True)
        if args.debug:
            result["debug"] = debug_info
        log_debug({"error": result, "debug": debug_info, "args": vars(args)})
        print(json.dumps(result))
        return 1

    result = {
        "ok": True,
        "repo": repo,
        "head": head,
        "base": base,
        "title": title,
        "agentId": agent_id,
        "draft": draft,
        "configSource": cfg_source,
        "ghConfigDir": gh_config_dir,
        "authSource": "agent_gh_config_dir" if gh_config_dir else "default_env_token",
        "result": details,
    }
    if args.debug:
        result["debug"] = debug_info
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
