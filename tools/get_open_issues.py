#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

DEFAULT_DB_PATH = os.environ.get("GITHUB_SYNC_DB_PATH", "/Users/jack/.openclaw/workspace-manager/workflow.db")
DEFAULT_CONFIG_PATH = os.environ.get("WORKFLOW_REPOS_CONFIG", "config/repos.json")
MAX_LIMIT = 500

NEEDS_DEV_ACTIONS = {"needs_dev", "requires_implementation", "needs_implementation"}


@dataclass(slots=True)
class InputSpec:
    repos: list[str] | None
    repo_allowlist: list[str] | None
    limit: int
    cursor: int
    include_suggested_agent: bool
    exclude_already_dispatched: bool
    exclude_claimed: bool
    priority_min: int


@dataclass(slots=True)
class RepoRule:
    enabled: bool
    priority: int
    max_per_run: int | None


@dataclass(slots=True)
class ToolConfig:
    default_agent: str
    global_limit: int
    repos: dict[str, RepoRule]


def error(code: str, message: str, retryable: bool) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "retryable": retryable}}


def _parse_str_list(payload: dict[str, Any], key: str) -> tuple[list[str] | None, dict[str, Any] | None]:
    raw = payload.get(key)
    if raw is None:
        return None, None
    if not isinstance(raw, list) or not all(isinstance(x, str) and x.strip() for x in raw):
        return None, error("INVALID_INPUT", f"{key} must be an array of non-empty strings", False)
    return [x.strip() for x in raw], None


def parse_input(stdin_text: str | None) -> tuple[InputSpec | None, dict[str, Any] | None]:
    payload: dict[str, Any] = {}
    if stdin_text and stdin_text.strip():
        try:
            payload = json.loads(stdin_text)
        except json.JSONDecodeError:
            return None, error("INVALID_INPUT", "stdin must contain valid JSON", False)

    repos, err = _parse_str_list(payload, "repos")
    if err is not None:
        return None, err
    repo_allowlist, err = _parse_str_list(payload, "repoAllowlist")
    if err is not None:
        return None, err

    limit = payload.get("limit", 50)
    if not isinstance(limit, int) or limit <= 0:
        return None, error("INVALID_INPUT", "limit must be a positive integer", False)
    limit = min(limit, MAX_LIMIT)

    cursor = payload.get("cursor", 0)
    if not isinstance(cursor, int) or cursor < 0:
        return None, error("INVALID_INPUT", "cursor must be a non-negative integer", False)

    include_suggested_agent = payload.get("includeSuggestedAgent", True)
    exclude_already_dispatched = payload.get("excludeAlreadyDispatched", True)
    exclude_claimed = payload.get("excludeClaimed", True)
    priority_min = payload.get("priorityMin", 0)

    for name, val in [
        ("includeSuggestedAgent", include_suggested_agent),
        ("excludeAlreadyDispatched", exclude_already_dispatched),
        ("excludeClaimed", exclude_claimed),
    ]:
        if not isinstance(val, bool):
            return None, error("INVALID_INPUT", f"{name} must be boolean", False)

    if not isinstance(priority_min, int):
        return None, error("INVALID_INPUT", "priorityMin must be an integer", False)

    # Interpretation contract: repos null/missing/[] means all enabled repos from config.
    if repos == []:
        repos = None

    return (
        InputSpec(
            repos=repos,
            repo_allowlist=repo_allowlist,
            limit=limit,
            cursor=cursor,
            include_suggested_agent=include_suggested_agent,
            exclude_already_dispatched=exclude_already_dispatched,
            exclude_claimed=exclude_claimed,
            priority_min=priority_min,
        ),
        None,
    )


def load_config(config_path: str) -> tuple[ToolConfig | None, dict[str, Any] | None]:
    if not os.path.exists(config_path):
        return None, error("CONFIG_ERROR", f"Config not found: {config_path}", False)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return None, error("CONFIG_ERROR", f"Invalid config: {exc}", False)

    default_agent = str(payload.get("defaultAgent") or "backend-dev")
    global_limit = payload.get("globalLimit", MAX_LIMIT)
    if not isinstance(global_limit, int) or global_limit <= 0:
        return None, error("CONFIG_ERROR", "globalLimit must be a positive integer", False)

    repos_raw = payload.get("repos")
    if not isinstance(repos_raw, dict):
        return None, error("CONFIG_ERROR", "repos must be an object keyed by repo name", False)

    repos: dict[str, RepoRule] = {}
    for repo, cfg in repos_raw.items():
        if not isinstance(repo, str) or not repo.strip() or not isinstance(cfg, dict):
            return None, error("CONFIG_ERROR", "invalid repo entry in config", False)
        enabled = bool(cfg.get("enabled", True))
        prio = cfg.get("priority", 0)
        max_per_run = cfg.get("max_per_run")
        if not isinstance(prio, int):
            return None, error("CONFIG_ERROR", f"repo priority must be int: {repo}", False)
        if max_per_run is not None and (not isinstance(max_per_run, int) or max_per_run <= 0):
            return None, error("CONFIG_ERROR", f"repo max_per_run must be positive int: {repo}", False)

        repos[repo] = RepoRule(enabled=enabled, priority=prio, max_per_run=max_per_run)

    return ToolConfig(default_agent=default_agent, global_limit=min(global_limit, MAX_LIMIT), repos=repos), None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _col(cols: set[str], *candidates: str) -> str | None:
    for c in candidates:
        if c in cols:
            return c
    return None


def _bool(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _json_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        try:
            loaded = json.loads(value)
            if isinstance(loaded, list):
                return [str(x) for x in loaded]
            if isinstance(loaded, str):
                return [loaded]
        except json.JSONDecodeError:
            return [x.strip() for x in value.split(",") if x.strip()]
    return [str(value)]


def _suggest_agent(title: str, labels: list[str], default_agent: str) -> str:
    text = f"{title} {' '.join(labels)}".lower()
    frontend_terms = ("frontend", "ui", "ux", "react", "css", "tailwind", "nextjs", "next.js")
    backend_terms = ("backend", "api", "db", "database", "sql", "postgres", "migration", "fastapi", "django")

    if any(t in text for t in frontend_terms):
        return "frontend-dev"
    if any(t in text for t in backend_terms):
        return "backend-dev"
    return default_agent


def _effective_repos(spec: InputSpec, cfg: ToolConfig) -> list[str]:
    if spec.repos:
        repos = list(spec.repos)
    else:
        repos = [repo for repo, rule in cfg.repos.items() if rule.enabled]

    if spec.repo_allowlist:
        allow = set(spec.repo_allowlist)
        repos = [r for r in repos if r in allow]

    return sorted(set(repos))


def _is_dispatched(row: sqlite3.Row, cols: set[str]) -> bool:
    if "already_dispatched" in cols:
        return _bool(row["already_dispatched"])
    if "dispatched_at" in cols and row["dispatched_at"] is not None:
        return True
    if "last_dispatched_state" in cols and row["last_dispatched_state"] is not None:
        return True
    return False


def _is_claimed(row: sqlite3.Row, cols: set[str]) -> bool:
    now = datetime.now(tz=UTC)
    if "claimed" in cols and _bool(row["claimed"]):
        return True
    if "claimed_by" in cols and row["claimed_by"]:
        return True
    if "in_progress" in cols and _bool(row["in_progress"]):
        return True
    if "claim_expires_at" in cols and row["claim_expires_at"]:
        try:
            expires = datetime.fromisoformat(str(row["claim_expires_at"]).replace("Z", "+00:00"))
            if expires > now:
                return True
        except ValueError:
            return True
    return False


def _has_linked_pr(row: sqlite3.Row, cols: set[str]) -> bool:
    if "has_linked_pr" in cols:
        return _bool(row["has_linked_pr"])
    if "linked_pr_number" in cols:
        return row["linked_pr_number"] is not None
    return False


def _build_issue_item(
    row: sqlite3.Row,
    cols: set[str],
    repo: str,
    cfg: ToolConfig,
    spec: InputSpec,
    *,
    number_col: str,
    title_col: str,
    action_col: str,
    labels_col: str | None,
    priority_col: str | None,
    rule: RepoRule,
) -> dict[str, Any] | None:
    if not rule.enabled:
        return None
    if _has_linked_pr(row, cols):
        return None
    if spec.exclude_already_dispatched and _is_dispatched(row, cols):
        return None
    if spec.exclude_claimed and _is_claimed(row, cols):
        return None

    base_priority = int(row[priority_col]) if priority_col and row[priority_col] is not None else 0
    priority = base_priority + int(rule.priority)
    if priority < spec.priority_min:
        return None

    labels = _json_list(row[labels_col]) if labels_col else []
    title = str(row[title_col])
    issue_number = int(row[number_col])
    action = str(row[action_col])

    item: dict[str, Any] = {
        "itemId": f"{repo}#issue#{issue_number}",
        "repo": repo,
        "issueNumber": issue_number,
        "title": title,
        "labels": labels,
        "status": "open",
        "action": action,
        "hasLinkedPr": False,
        "priority": priority,
        "reason": "needs_dev + no linked PR + not dispatched",
    }
    if spec.include_suggested_agent:
        item["suggestedAgent"] = _suggest_agent(title=title, labels=labels, default_agent=cfg.default_agent)

    return item


def run(spec: InputSpec, db_path: str, config_path: str) -> dict[str, Any]:
    cfg, cfg_err = load_config(config_path)
    if cfg_err is not None:
        return cfg_err
    assert cfg is not None

    if not os.path.exists(db_path):
        return error("DB_UNAVAILABLE", f"{db_path} not found", True)

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return error("DB_UNAVAILABLE", f"Unable to open {db_path}", True)

    try:
        return _execute(spec, conn, cfg, db_path)
    finally:
        conn.close()


def _execute(
    spec: InputSpec,
    conn: sqlite3.Connection,
    cfg: ToolConfig,
    db_path: str,
) -> dict[str, Any]:
    requested_repos = spec.repos
    effective_repos = _effective_repos(spec, cfg)

    if not effective_repos:
        return {
            "generatedAt": datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "source": db_path,
            "filters": {
                "requestedRepos": requested_repos,
                "effectiveRepos": [],
                "repoAllowlist": spec.repo_allowlist,
                "limit": min(spec.limit, cfg.global_limit),
                "cursor": spec.cursor,
                "includeSuggestedAgent": spec.include_suggested_agent,
                "excludeAlreadyDispatched": spec.exclude_already_dispatched,
                "excludeClaimed": spec.exclude_claimed,
                "priorityMin": spec.priority_min,
            },
            "counts": {"scanned": 0, "eligible": 0, "returned": 0},
            "issues": [],
            "nextCursor": None,
        }

    try:
        cols = _columns(conn, "workflow_items")
        if not cols:
            return error("CONFIG_ERROR", "workflow_items table missing", False)

        type_col = _col(cols, "item_type", "type")
        repo_col = _col(cols, "repo", "repository", "repo_full_name")
        number_col = _col(cols, "number", "issue_number")
        title_col = _col(cols, "title")
        state_col = _col(cols, "github_state", "state", "status")
        action_col = _col(cols, "action")
        labels_col = _col(cols, "labels_json", "labels")
        priority_col = _col(cols, "priority")

        if not all([type_col, repo_col, number_col, title_col, state_col, action_col]):
            return error("CONFIG_ERROR", "workflow_items schema missing required columns", False)

        effective_limit = min(spec.limit, cfg.global_limit)

        sql = [
            f"SELECT * FROM workflow_items WHERE {type_col} = ?",
            f"AND lower({state_col}) = 'open'",
            "AND lower(action) IN ({})".format(",".join("?" for _ in NEEDS_DEV_ACTIONS)),
            "AND {} IN ({})".format(repo_col, ",".join("?" for _ in effective_repos)),
        ]
        params: list[Any] = ["issue", *sorted(NEEDS_DEV_ACTIONS), *effective_repos]

        rows = conn.execute(" ".join(sql), params).fetchall()
        scanned = len(rows)

        selected: list[dict[str, Any]] = []
        per_repo_counts: dict[str, int] = {repo: 0 for repo in effective_repos}

        for row in rows:
            repo = str(row[repo_col])
            rule = cfg.repos.get(repo, RepoRule(enabled=True, priority=0, max_per_run=None))

            if rule.max_per_run is not None and per_repo_counts.get(repo, 0) >= rule.max_per_run:
                continue

            item = _build_issue_item(
                row, cols, repo, cfg, spec,
                number_col=number_col,
                title_col=title_col,
                action_col=action_col,
                labels_col=labels_col,
                priority_col=priority_col,
                rule=rule,
            )
            if item is None:
                continue

            selected.append(item)
            per_repo_counts[repo] = per_repo_counts.get(repo, 0) + 1

        selected.sort(key=lambda x: (-int(x.get("priority", 0)), str(x.get("itemId"))))
        start = spec.cursor
        end = start + effective_limit
        returned = selected[start:end]
        next_cursor = end if end < len(selected) else None

        return {
            "generatedAt": datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "source": db_path,
            "filters": {
                "requestedRepos": requested_repos,
                "effectiveRepos": effective_repos,
                "repoAllowlist": spec.repo_allowlist,
                "limit": effective_limit,
                "cursor": spec.cursor,
                "includeSuggestedAgent": spec.include_suggested_agent,
                "excludeAlreadyDispatched": spec.exclude_already_dispatched,
                "excludeClaimed": spec.exclude_claimed,
                "priorityMin": spec.priority_min,
            },
            "counts": {
                "scanned": scanned,
                "eligible": len(selected),
                "returned": len(returned),
            },
            "issues": returned,
            "nextCursor": next_cursor,
        }

    except sqlite3.Error as exc:
        return error("DB_QUERY_FAILED", str(exc), True)


class IssueQueueClient:
    """Reusable client for querying the issue workflow queue.

    Usage::

        with IssueQueueClient(db_path="workflow.db") as client:
            result = client.query(limit=10)
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        config_path: str = DEFAULT_CONFIG_PATH,
    ) -> None:
        cfg, cfg_err = load_config(config_path)
        if cfg_err is not None:
            raise ValueError(cfg_err["error"]["message"])
        assert cfg is not None
        self._config: ToolConfig = cfg

        if not os.path.exists(db_path):
            raise FileNotFoundError(f"{db_path} not found")
        try:
            self._conn: sqlite3.Connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            self._conn.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            raise FileNotFoundError(f"Unable to open {db_path}: {exc}") from exc

        self._db_path = db_path
        self._cols: set[str] | None = None

    # -- context manager -----------------------------------------------------

    def __enter__(self) -> IssueQueueClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- public API ----------------------------------------------------------

    def query(
        self,
        repos: list[str] | None = None,
        repo_allowlist: list[str] | None = None,
        limit: int = 50,
        cursor: int = 0,
        include_suggested_agent: bool = True,
        exclude_already_dispatched: bool = True,
        exclude_claimed: bool = True,
        priority_min: int = 0,
    ) -> dict[str, Any]:
        if limit <= 0:
            raise ValueError("limit must be a positive integer")
        limit = min(limit, MAX_LIMIT)

        spec = InputSpec(
            repos=repos if repos else None,
            repo_allowlist=repo_allowlist,
            limit=limit,
            cursor=cursor,
            include_suggested_agent=include_suggested_agent,
            exclude_already_dispatched=exclude_already_dispatched,
            exclude_claimed=exclude_claimed,
            priority_min=priority_min,
        )
        return _execute(spec, self._conn, self._config, self._db_path)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministically select dispatch-ready open issues")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to workflow sqlite db")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Repos config JSON path")
    parser.add_argument(
        "--input-json",
        default=None,
        help="JSON payload string. If omitted, reads JSON from stdin. Empty input uses defaults.",
    )
    args = parser.parse_args(argv or sys.argv[1:])

    stdin_text = args.input_json if args.input_json is not None else sys.stdin.read()

    spec, err = parse_input(stdin_text)
    if err is not None:
        print(json.dumps(err))
        return 1

    assert spec is not None
    result = run(spec=spec, db_path=args.db, config_path=args.config)
    if "error" in result:
        print(json.dumps(result))
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
