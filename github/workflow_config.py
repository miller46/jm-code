"""Centralized configuration loader for the workflow system."""

import json
import os
from typing import List

_DEFAULTS = {
    "db_path": "~/.openclaw/workspace-manager/workflow.db",
    "lock_dir": "~/.openclaw/workspace-manager/locks",
    "repos": ["miller46/jm-api"],
    "max_iterations": 5,
}

_DEFAULT_REVIEWERS = ["miller46codesnob", "miller46architect"]

_cached_config = None


def _workspace_root() -> str:
    """Return workspace-manager root (parent of scripts/)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_reviewers_for_repo(repo: str) -> List[str]:
    """Load enabled reviewer names for a repo from its reviewers.json.

    Lookup order:
      1. repos/{owner}/{repo}/reviewers.json
      2. reviewers.json (global)
      3. _DEFAULT_REVIEWERS hardcoded fallback
    """
    root = _workspace_root()
    candidates = [
        os.path.join(root, "config", *repo.split("/"), "reviewers.json"),
        os.path.join(root, "config", "default_reviewers.json"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            with open(path) as f:
                cfg = json.load(f)
            reviewers = cfg.get("reviewers", [])
            if reviewers:
                return [r["name"] for r in reviewers if r.get("enabled", True)]
    return list(_DEFAULT_REVIEWERS)


def _find_config_path():
    """Walk up from this file to find workflow_config.json."""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        candidate = os.path.join(d, "workflow_config.json")
        if os.path.isfile(candidate):
            return candidate
        d = os.path.dirname(d)
    return None


def load_config(path=None):
    """Read JSON config, merge with defaults, expand tildes."""
    raw = {}
    resolved = path or _find_config_path()
    if resolved and os.path.isfile(resolved):
        with open(resolved) as f:
            raw = json.load(f)

    cfg = {**_DEFAULTS, **raw}

    # Expand tildes in path values
    for key in ("db_path", "lock_dir"):
        if key in cfg and isinstance(cfg[key], str):
            cfg[key] = os.path.expanduser(cfg[key])

    return cfg


def get_config():
    """Return cached singleton config."""
    global _cached_config
    if _cached_config is None:
        _cached_config = load_config()
    return _cached_config


def reset_config():
    """Clear cached config (for tests)."""
    global _cached_config
    _cached_config = None


# Backward-compat re-export
MAX_ITERATIONS = _DEFAULTS["max_iterations"]
