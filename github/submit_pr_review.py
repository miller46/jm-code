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
DEFAULT_REVIEWERS_PATH = WORKSPACE_MANAGER_ROOT / "reviewers.json"

ALLOWED_VERDICTS = {"approve", "request_changes"}


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


def resolve_reviewers_config(repo: str) -> tuple[dict[str, Any] | None, str, dict[str, Any] | None]:
    parsed = parse_repo(repo)
    if not parsed:
        return None, "", error("INVALID_INPUT", "repo must be in owner/repo format")

    owner, name = parsed
    repo_cfg = WORKSPACE_MANAGER_ROOT / "repos" / owner / name / "config" / "reviewers.json"
    default_cfg = DEFAULT_REVIEWERS_PATH

    if repo_cfg.exists():
        payload, err = load_json(repo_cfg)
        if err:
            return None, "", err
        return payload, str(repo_cfg), None

    payload, err = load_json(default_cfg)
    if err:
        return None, "", err
    return payload, str(default_cfg), None


def find_reviewer(payload: dict[str, Any], reviewer_id: str) -> dict[str, Any] | None:
    # Repo-specific format
    for entry in payload.get("required_reviewers", []):
        if not isinstance(entry, dict):
            continue
        rid = entry.get("id") or entry.get("agent") or entry.get("name")
        if isinstance(rid, str) and rid.strip() == reviewer_id:
            return entry

    # Global format
    for entry in payload.get("reviewers", []):
        if not isinstance(entry, dict):
            continue
        rid = entry.get("name") or entry.get("agent")
        if isinstance(rid, str) and rid.strip() == reviewer_id:
            return entry

    return None


def reviewer_gh_config_dir(reviewer: dict[str, Any], reviewer_id: str) -> str | None:
    # Deterministic lookup from reviewer_id path only (no prompt/runtime override).
    candidate = os.path.expanduser(f"~/.openclaw/agents/{reviewer_id}/agent")
    if os.path.isdir(candidate):
        return candidate

    # Fallback: return None so caller uses ambient env/default token behavior.
    return None


def validate_body(verdict: str, body: str) -> dict[str, Any] | None:
    if not body.strip():
        return error("INVALID_INPUT", "body is required")

    # machine-checkable requirement
    first_line = body.strip().splitlines()[0].strip().upper()
    expected = "VERDICT: APPROVE" if verdict == "approve" else "VERDICT: REQUEST_CHANGES"
    if first_line != expected:
        return error(
            "INVALID_INPUT",
            f"body must start with '{expected}' for machine-checkable output",
        )
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
    log_path = Path("/Users/jack/.openclaw/workspace-manager/logs/submit_pr_review.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    import datetime
    with log_path.open("a") as f:
        f.write(f"\n--- {datetime.datetime.now().isoformat()} ---\n")
        f.write(json.dumps(info, indent=2))
        f.write("\n")


def submit_review(
    repo: str, pr_number: int, verdict: str, body: str, gh_config_dir: str | None, debug: bool = False
) -> tuple[bool, str, dict[str, Any]]:
    if verdict == "approve":
        flag = "--approve"
    elif verdict == "request_changes":
        flag = "--request-changes"
    else:
        return False, "invalid verdict", {}

    cmd = [
        "gh",
        "pr",
        "review",
        str(pr_number),
        "--repo",
        repo,
        flag,
        "--body",
        body,
    ]

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
        return False, (proc.stderr or proc.stdout or "gh pr review failed").strip(), debug_info
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
    parser = argparse.ArgumentParser(description="Submit PR review with strict verdict enforcement")
    parser.add_argument("--repo", help="owner/repo")
    parser.add_argument("--pr-number", type=int, help="Pull request number")
    parser.add_argument("--reviewer-id", help="code-snob, architect, etc")
    parser.add_argument("--verdict", help="approve | request_changes")
    parser.add_argument("--body", help="Review body (must start with VERDICT line)")
    parser.add_argument("--input-json", default=None, help="Alternative JSON payload")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print command plan without calling gh")
    parser.add_argument("--debug", action="store_true", help="Include debug info about auth")
    args = parser.parse_args(argv or sys.argv[1:])

    payload = {
        "repo": args.repo,
        "prNumber": args.pr_number,
        "reviewerId": args.reviewer_id,
        "verdict": args.verdict,
        "body": args.body,
    }

    if args.input_json is not None:
        try:
            payload = json.loads(args.input_json)
        except json.JSONDecodeError:
            print(json.dumps(error("INVALID_INPUT", "--input-json must be valid JSON")))
            return 1
    elif not any(payload.values()):
        parsed, err = parse_input(sys.stdin.read())
        if err:
            print(json.dumps(err))
            return 1
        payload = parsed or {}

    repo = payload.get("repo")
    pr_number = payload.get("prNumber")
    reviewer_id = payload.get("reviewerId")
    verdict = payload.get("verdict")
    body = payload.get("body")

    if not isinstance(repo, str) or not parse_repo(repo):
        print(json.dumps(error("INVALID_INPUT", "repo must be in owner/repo format")))
        return 1
    if not isinstance(pr_number, int) or pr_number <= 0:
        print(json.dumps(error("INVALID_INPUT", "prNumber must be a positive integer")))
        return 1
    if not isinstance(verdict, str) or verdict not in ALLOWED_VERDICTS:
        print(json.dumps(error("INVALID_INPUT", "verdict must be one of: approve, request_changes")))
        return 1
    if not isinstance(body, str):
        print(json.dumps(error("INVALID_INPUT", "body must be a string")))
        return 1

    body_err = validate_body(verdict=verdict, body=body)
    if body_err:
        print(json.dumps(body_err))
        return 1

    cfg, cfg_source, cfg_err = resolve_reviewers_config(repo)
    if cfg_err:
        print(json.dumps(cfg_err))
        return 1
    assert cfg is not None

    reviewer = find_reviewer(cfg, reviewer_id)
    if reviewer is None:
        print(json.dumps(error("CONFIG_ERROR", f"reviewer '{reviewer_id}' not found in {cfg_source}")))
        return 1

    gh_config_dir = reviewer_gh_config_dir(reviewer, reviewer_id)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "ok": True,
                    "dryRun": True,
                    "repo": repo,
                    "prNumber": pr_number,
                    "reviewerId": reviewer_id,
                    "verdict": verdict,
                    "configSource": cfg_source,
                    "ghConfigDir": gh_config_dir,
                    "authSource": "reviewer_gh_config_dir" if gh_config_dir else "default_env_token",
                }
            )
        )
        return 0

    ok, details, debug_info = submit_review(
        repo=repo,
        pr_number=pr_number,
        verdict=verdict,
        body=body,
        gh_config_dir=gh_config_dir,
        debug=args.debug,
    )
    if not ok:
        result = error("GH_REVIEW_FAILED", details, retryable=True)
        if args.debug:
            result["debug"] = debug_info
        # Always log debug info on failure
        log_debug({"error": result, "debug": debug_info, "args": vars(args)})
        print(json.dumps(result))
        return 1

    result = {
        "ok": True,
        "repo": repo,
        "prNumber": pr_number,
        "reviewerId": reviewer_id,
        "verdict": verdict,
        "configSource": cfg_source,
        "ghConfigDir": gh_config_dir,
        "authSource": "reviewer_gh_config_dir" if gh_config_dir else "default_env_token",
        "result": details,
    }
    if args.debug:
        result["debug"] = debug_info
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
