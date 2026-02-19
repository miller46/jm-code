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
from urllib.parse import urlparse

import workflow_config

DEFAULT_DB_PATH = os.environ.get("GITHUB_SYNC_DB_PATH", "/Users/jack/.openclaw/workspace-manager/workflow.db")
DEFAULT_CONFIG_PATH = os.environ.get("WORKFLOW_REPOS_CONFIG", "config/repos.json")
MAX_LIMIT = 200
DEFAULT_MAX_ITERATIONS = 5

VALID_ACTIONS: set[str] = {
    "needs_review",
    "needs_fix",
    "needs_conflict_resolution",
    "ready_to_merge",
    "max_iterations_reached",
}

DISPATCH_TYPE_MAP: dict[str, str] = {
    "needs_review": "review",
    "needs_fix": "fix",
    "needs_conflict_resolution": "conflict",
    "ready_to_merge": "merge",
    "max_iterations_reached": "alert",
}

DISPATCH_SHA_COL_MAP: dict[str, tuple[str, ...]] = {
    "needs_review": ("last_review_dispatch_sha", "lastReviewDispatchSha"),
    "needs_fix": ("last_fix_dispatch_sha", "lastFixDispatchSha"),
    "ready_to_merge": ("last_merge_dispatch_sha", "lastMergeDispatchSha"),
    "needs_conflict_resolution": ("last_conflict_dispatch_sha", "lastConflictDispatchSha"),
}

_DEV_AGENT_DEFAULT_ACTIONS: set[str] = {"needs_fix", "needs_conflict_resolution"}


@dataclass(slots=True)
class InputSpec:
    action: str
    repos: list[str] | None
    limit: int
    exclude_already_dispatched: bool
    exclude_claimed: bool
    include_suggested_dev_agent: bool
    include_meta: bool


@dataclass(slots=True)
class RepoRule:
    enabled: bool
    priority: int


@dataclass(slots=True)
class ToolConfig:
    default_agent: str
    default_max_iterations: int
    repos: dict[str, RepoRule]


def error(code: str, message: str, retryable: bool) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "retryable": retryable}}


def _parse_str_list(payload: dict[str, Any], key: str) -> tuple[list[str] | None, dict[str, Any] | None]:
    raw = payload.get(key)
    if raw is None:
        return None, None
    if not isinstance(raw, list):
        return None, error("INVALID_INPUT", f"{key} must be an array of strings", False)
    vals = [str(x).strip() for x in raw if str(x).strip()]
    return (vals if vals else None), None


def parse_input(stdin_text: str | None) -> tuple[InputSpec | None, dict[str, Any] | None]:
    payload: dict[str, Any] = {}
    if stdin_text and stdin_text.strip():
        try:
            payload = json.loads(stdin_text)
        except json.JSONDecodeError:
            return None, error("INVALID_INPUT", "stdin must contain valid JSON", False)

    action = payload.get("action")
    if not action or not isinstance(action, str):
        return None, error("INVALID_INPUT", "action is required", False)
    if action not in VALID_ACTIONS:
        return None, error("INVALID_INPUT", f"invalid action: {action}. Must be one of {sorted(VALID_ACTIONS)}", False)

    repos, err = _parse_str_list(payload, "repos")
    if err is not None:
        return None, err

    limit = payload.get("limit", 20)
    if not isinstance(limit, int) or limit <= 0:
        return None, error("INVALID_INPUT", "limit must be a positive integer", False)
    limit = min(limit, MAX_LIMIT)

    exclude_already_dispatched = payload.get("excludeAlreadyDispatched", True)
    exclude_claimed = payload.get("excludeClaimed", True)

    include_suggested_dev_agent_default = action in _DEV_AGENT_DEFAULT_ACTIONS
    include_suggested_dev_agent = payload.get("includeSuggestedDevAgent", include_suggested_dev_agent_default)

    include_meta = payload.get("includeMeta", True)

    for k, v in [
        ("excludeAlreadyDispatched", exclude_already_dispatched),
        ("excludeClaimed", exclude_claimed),
        ("includeSuggestedDevAgent", include_suggested_dev_agent),
        ("includeMeta", include_meta),
    ]:
        if not isinstance(v, bool):
            return None, error("INVALID_INPUT", f"{k} must be boolean", False)

    return (
        InputSpec(
            action=action,
            repos=repos,
            limit=limit,
            exclude_already_dispatched=exclude_already_dispatched,
            exclude_claimed=exclude_claimed,
            include_suggested_dev_agent=include_suggested_dev_agent,
            include_meta=include_meta,
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
    default_max_iterations = payload.get("defaultMaxIterations", DEFAULT_MAX_ITERATIONS)
    if not isinstance(default_max_iterations, int) or default_max_iterations <= 0:
        return None, error("CONFIG_ERROR", "defaultMaxIterations must be positive integer", False)

    repos_raw = payload.get("repos")
    if not isinstance(repos_raw, dict):
        return None, error("CONFIG_ERROR", "repos must be an object", False)

    repos: dict[str, RepoRule] = {}
    for repo, raw in repos_raw.items():
        if not isinstance(repo, str) or not isinstance(raw, dict):
            return None, error("CONFIG_ERROR", "invalid repo entry", False)
        priority = raw.get("priority", 0)
        if not isinstance(priority, int):
            return None, error("CONFIG_ERROR", f"invalid repo priority for {repo}", False)
        repos[repo] = RepoRule(enabled=bool(raw.get("enabled", True)), priority=priority)

    return ToolConfig(default_agent=default_agent, default_max_iterations=default_max_iterations, repos=repos), None


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
        t = value.strip()
        if not t:
            return []
        try:
            loaded = json.loads(t)
            if isinstance(loaded, list):
                return [str(x) for x in loaded]
        except json.JSONDecodeError:
            return [x.strip() for x in t.split(",") if x.strip()]
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


def _repo_from_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
    except Exception:
        return None
    return None


def _effective_repos(spec: InputSpec, cfg: ToolConfig) -> list[str]:
    if spec.repos:
        return sorted(set(spec.repos))
    return sorted([repo for repo, rule in cfg.repos.items() if rule.enabled])


def _dispatch_dedup_skip(action: str, head_sha: str, row: sqlite3.Row, cols: set[str]) -> bool:
    if not head_sha:
        return False

    candidates = DISPATCH_SHA_COL_MAP.get(action)
    if not candidates:
        return False

    for col in candidates:
        if col in cols and row[col] is not None and str(row[col]) == head_sha:
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

    effective_repos = _effective_repos(spec, cfg)

    try:
        cols = _columns(conn, "workflow_items")
        if not cols:
            return error("CONFIG_ERROR", "workflow_items table missing", False)

        type_col = _col(cols, "item_type", "type")
        state_col = _col(cols, "github_state", "state", "status")
        action_col = _col(cols, "action")
        number_col = _col(cols, "number", "pr_number")
        title_col = _col(cols, "title")
        url_col = _col(cols, "url", "html_url")
        repo_col = _col(cols, "repo", "repository", "repo_full_name")
        author_col = _col(cols, "author", "author_login", "user_login")
        head_sha_col = _col(cols, "head_sha", "headSha", "latest_commit_sha")
        iteration_col = _col(cols, "iteration")
        labels_col = _col(cols, "labels_json", "labels")
        updated_col = _col(cols, "updated_at", "synced_at", "created_at")
        priority_col = _col(cols, "priority")
        has_conflicts_col = _col(cols, "has_conflicts")
        approved_col = _col(cols, "all_reviewers_approved")
        changes_col = _col(cols, "any_changes_requested")
        last_reviewed_sha_col = _col(cols, "last_reviewed_sha", "lastReviewedSha")

        if not all([type_col, state_col, action_col, number_col, title_col]):
            return error("CONFIG_ERROR", "workflow_items missing required PR columns", False)

        max_iterations = cfg.default_max_iterations

        # Build SQL based on action
        if spec.action == "max_iterations_reached":
            sql = (
                f"SELECT * FROM workflow_items WHERE {type_col} IN ('pr', 'pull_request') "
                f"AND lower({state_col}) = 'open' AND {iteration_col} >= ?"
            )
            params: tuple[Any, ...] = (max_iterations,)
        else:
            sql = (
                f"SELECT * FROM workflow_items WHERE {type_col} IN ('pr', 'pull_request') "
                f"AND lower({state_col}) = 'open' AND {action_col} = ?"
            )
            params = (spec.action,)

        rows = conn.execute(sql, params).fetchall()
        scanned = len(rows)

        # Cache reviewers per repo for needs_review queue
        reviewers_cache: dict[str, list[str]] = {}

        selected: list[dict[str, Any]] = []

        for row in rows:
            repo: str | None = None
            if repo_col:
                repo = str(row[repo_col]) if row[repo_col] is not None else None
            if not repo and url_col and row[url_col]:
                repo = _repo_from_url(str(row[url_col]))
            if not repo:
                continue
            if effective_repos and repo not in effective_repos:
                continue

            head_sha = str(row[head_sha_col]) if head_sha_col and row[head_sha_col] else ""

            if spec.exclude_already_dispatched and _dispatch_dedup_skip(spec.action, head_sha, row, cols):
                continue

            if spec.exclude_claimed and _is_claimed(row, cols):
                continue

            base_priority = int(row[priority_col]) if priority_col and row[priority_col] is not None else 0
            repo_priority = cfg.repos.get(repo, RepoRule(enabled=True, priority=0)).priority
            priority = base_priority + repo_priority

            labels = _json_list(row[labels_col]) if labels_col else []
            title = str(row[title_col])
            pr_number = int(row[number_col])
            action = str(row[action_col]) if row[action_col] is not None else ""
            iteration = int(row[iteration_col]) if iteration_col and row[iteration_col] is not None else 0

            item: dict[str, Any] = {
                "itemId": f"{repo}#pr#{pr_number}",
                "repo": repo,
                "prNumber": pr_number,
                "title": title,
                "author": str(row[author_col]) if author_col and row[author_col] is not None else None,
                "headSha": head_sha,
                "status": action,
                "dispatchType": DISPATCH_TYPE_MAP[spec.action],
                "_sortUpdated": str(row[updated_col]) if updated_col and row[updated_col] is not None else "",
                "_sortPriority": priority,
            }

            if spec.include_meta:
                item["hasConflicts"] = _bool(row[has_conflicts_col]) if has_conflicts_col else False
                item["allReviewersApproved"] = _bool(row[approved_col]) if approved_col else False
                item["anyChangesRequested"] = _bool(row[changes_col]) if changes_col else False
                item["lastReviewedSha"] = str(row[last_reviewed_sha_col]) if last_reviewed_sha_col and row[last_reviewed_sha_col] is not None else None
                item["iteration"] = iteration
                item["dispatchState"] = {
                    "lastReviewDispatchSha": str(row["last_review_dispatch_sha"]) if "last_review_dispatch_sha" in cols and row["last_review_dispatch_sha"] is not None else None,
                    "lastFixDispatchSha": str(row["last_fix_dispatch_sha"]) if "last_fix_dispatch_sha" in cols and row["last_fix_dispatch_sha"] is not None else None,
                    "lastMergeDispatchSha": str(row["last_merge_dispatch_sha"]) if "last_merge_dispatch_sha" in cols and row["last_merge_dispatch_sha"] is not None else None,
                    "lastConflictDispatchSha": str(row["last_conflict_dispatch_sha"]) if "last_conflict_dispatch_sha" in cols and row["last_conflict_dispatch_sha"] is not None else None,
                }

            if spec.action == "needs_review":
                if repo not in reviewers_cache:
                    reviewers_cache[repo] = workflow_config.load_reviewers_for_repo(repo)
                item["reviewers"] = reviewers_cache[repo]

            if spec.include_suggested_dev_agent:
                item["suggestedDevAgent"] = _suggest_agent(title=title, labels=labels, default_agent=cfg.default_agent)

            selected.append(item)

        # Sort: updated_at ASC (oldest first), then priority DESC, then itemId ASC
        selected.sort(
            key=lambda x: (
                str(x.get("_sortUpdated", "")),
                -x.get("_sortPriority", 0),
                str(x.get("itemId", "")),
            )
        )

        returned = selected[: spec.limit]
        for it in returned:
            it.pop("_sortUpdated", None)
            it.pop("_sortPriority", None)

        return {
            "generatedAt": datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "source": db_path,
            "queue": spec.action,
            "filters": {
                "requestedRepos": spec.repos,
                "effectiveRepos": effective_repos,
                "limit": spec.limit,
            },
            "counts": {
                "scanned": scanned,
                "eligible": len(selected),
                "returned": len(returned),
            },
            "prs": returned,
        }

    except sqlite3.Error as exc:
        return error("DB_QUERY_FAILED", f"unable to read workflow_items: {exc}", True)
    finally:
        conn.close()


class PRQueueClient:
    """Reusable client for querying the PR workflow queue.

    Usage::

        with PRQueueClient(db_path="workflow.db") as client:
            result = client.query(action="needs_review", limit=10)
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

    def __enter__(self) -> PRQueueClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- public API ----------------------------------------------------------

    def query(
        self,
        action: str,
        repos: list[str] | None = None,
        limit: int = 20,
        exclude_already_dispatched: bool = True,
        exclude_claimed: bool = True,
        include_suggested_dev_agent: bool | None = None,
        include_meta: bool = True,
    ) -> dict[str, Any]:
        if action not in VALID_ACTIONS:
            raise ValueError(f"invalid action: {action}. Must be one of {sorted(VALID_ACTIONS)}")
        if limit <= 0:
            raise ValueError("limit must be a positive integer")
        limit = min(limit, MAX_LIMIT)

        if include_suggested_dev_agent is None:
            include_suggested_dev_agent = action in _DEV_AGENT_DEFAULT_ACTIONS

        spec = InputSpec(
            action=action,
            repos=repos,
            limit=limit,
            exclude_already_dispatched=exclude_already_dispatched,
            exclude_claimed=exclude_claimed,
            include_suggested_dev_agent=include_suggested_dev_agent,
            include_meta=include_meta,
        )
        return self._execute(spec)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # -- internals -----------------------------------------------------------

    def _execute(self, spec: InputSpec) -> dict[str, Any]:
        cfg = self._config
        conn = self._conn

        if self._cols is None:
            self._cols = _columns(conn, "workflow_items")
        cols = self._cols

        if not cols:
            return error("CONFIG_ERROR", "workflow_items table missing", False)

        type_col = _col(cols, "item_type", "type")
        state_col = _col(cols, "github_state", "state", "status")
        action_col = _col(cols, "action")
        number_col = _col(cols, "number", "pr_number")
        title_col = _col(cols, "title")
        url_col = _col(cols, "url", "html_url")
        repo_col = _col(cols, "repo", "repository", "repo_full_name")
        author_col = _col(cols, "author", "author_login", "user_login")
        head_sha_col = _col(cols, "head_sha", "headSha", "latest_commit_sha")
        iteration_col = _col(cols, "iteration")
        labels_col = _col(cols, "labels_json", "labels")
        updated_col = _col(cols, "updated_at", "synced_at", "created_at")
        priority_col = _col(cols, "priority")
        has_conflicts_col = _col(cols, "has_conflicts")
        approved_col = _col(cols, "all_reviewers_approved")
        changes_col = _col(cols, "any_changes_requested")
        last_reviewed_sha_col = _col(cols, "last_reviewed_sha", "lastReviewedSha")

        if not all([type_col, state_col, action_col, number_col, title_col]):
            return error("CONFIG_ERROR", "workflow_items missing required PR columns", False)

        effective_repos = _effective_repos(spec, cfg)
        max_iterations = cfg.default_max_iterations

        if spec.action == "max_iterations_reached":
            sql = (
                f"SELECT * FROM workflow_items WHERE {type_col} IN ('pr', 'pull_request') "
                f"AND lower({state_col}) = 'open' AND {iteration_col} >= ?"
            )
            params: tuple[Any, ...] = (max_iterations,)
        else:
            sql = (
                f"SELECT * FROM workflow_items WHERE {type_col} IN ('pr', 'pull_request') "
                f"AND lower({state_col}) = 'open' AND {action_col} = ?"
            )
            params = (spec.action,)

        rows = conn.execute(sql, params).fetchall()
        scanned = len(rows)

        reviewers_cache: dict[str, list[str]] = {}
        selected: list[dict[str, Any]] = []

        for row in rows:
            repo: str | None = None
            if repo_col:
                repo = str(row[repo_col]) if row[repo_col] is not None else None
            if not repo and url_col and row[url_col]:
                repo = _repo_from_url(str(row[url_col]))
            if not repo:
                continue
            if effective_repos and repo not in effective_repos:
                continue

            head_sha = str(row[head_sha_col]) if head_sha_col and row[head_sha_col] else ""

            if spec.exclude_already_dispatched and _dispatch_dedup_skip(spec.action, head_sha, row, cols):
                continue

            if spec.exclude_claimed and _is_claimed(row, cols):
                continue

            base_priority = int(row[priority_col]) if priority_col and row[priority_col] is not None else 0
            repo_priority = cfg.repos.get(repo, RepoRule(enabled=True, priority=0)).priority
            priority = base_priority + repo_priority

            labels = _json_list(row[labels_col]) if labels_col else []
            title = str(row[title_col])
            pr_number = int(row[number_col])
            action = str(row[action_col]) if row[action_col] is not None else ""
            iteration = int(row[iteration_col]) if iteration_col and row[iteration_col] is not None else 0

            item: dict[str, Any] = {
                "itemId": f"{repo}#pr#{pr_number}",
                "repo": repo,
                "prNumber": pr_number,
                "title": title,
                "author": str(row[author_col]) if author_col and row[author_col] is not None else None,
                "headSha": head_sha,
                "status": action,
                "dispatchType": DISPATCH_TYPE_MAP[spec.action],
                "_sortUpdated": str(row[updated_col]) if updated_col and row[updated_col] is not None else "",
                "_sortPriority": priority,
            }

            if spec.include_meta:
                item["hasConflicts"] = _bool(row[has_conflicts_col]) if has_conflicts_col else False
                item["allReviewersApproved"] = _bool(row[approved_col]) if approved_col else False
                item["anyChangesRequested"] = _bool(row[changes_col]) if changes_col else False
                item["lastReviewedSha"] = str(row[last_reviewed_sha_col]) if last_reviewed_sha_col and row[last_reviewed_sha_col] is not None else None
                item["iteration"] = iteration
                item["dispatchState"] = {
                    "lastReviewDispatchSha": str(row["last_review_dispatch_sha"]) if "last_review_dispatch_sha" in cols and row["last_review_dispatch_sha"] is not None else None,
                    "lastFixDispatchSha": str(row["last_fix_dispatch_sha"]) if "last_fix_dispatch_sha" in cols and row["last_fix_dispatch_sha"] is not None else None,
                    "lastMergeDispatchSha": str(row["last_merge_dispatch_sha"]) if "last_merge_dispatch_sha" in cols and row["last_merge_dispatch_sha"] is not None else None,
                    "lastConflictDispatchSha": str(row["last_conflict_dispatch_sha"]) if "last_conflict_dispatch_sha" in cols and row["last_conflict_dispatch_sha"] is not None else None,
                }

            if spec.action == "needs_review":
                if repo not in reviewers_cache:
                    reviewers_cache[repo] = workflow_config.load_reviewers_for_repo(repo)
                item["reviewers"] = reviewers_cache[repo]

            if spec.include_suggested_dev_agent:
                item["suggestedDevAgent"] = _suggest_agent(title=title, labels=labels, default_agent=cfg.default_agent)

            selected.append(item)

        selected.sort(
            key=lambda x: (
                str(x.get("_sortUpdated", "")),
                -x.get("_sortPriority", 0),
                str(x.get("itemId", "")),
            )
        )

        returned = selected[: spec.limit]
        for it in returned:
            it.pop("_sortUpdated", None)
            it.pop("_sortPriority", None)

        return {
            "generatedAt": datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "source": self._db_path,
            "queue": spec.action,
            "filters": {
                "requestedRepos": spec.repos,
                "effectiveRepos": effective_repos,
                "limit": spec.limit,
            },
            "counts": {
                "scanned": scanned,
                "eligible": len(selected),
                "returned": len(returned),
            },
            "prs": returned,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Queue-based PR selector for workflow dispatch")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to workflow sqlite db")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Repos config JSON path")
    parser.add_argument(
        "--input-json",
        default=None,
        help="JSON payload string. If omitted, reads JSON from stdin.",
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
