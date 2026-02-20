"""Load reviewer config for a given repo, with per-repo overrides."""

import json
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def get_reviewers(repo: str) -> list[dict]:
    return get_reviewer_data(repo)["reviewers"]

def get_review_policy(repo: str) -> list[dict]:
    return get_reviewer_data(repo)["approval_rules"]

def get_reviewer_data(repo: str) -> list[dict]:
    """Return the reviewer list for *repo* (owner/repo format).

    Looks for config/{owner}/{repo}/reviewers.json first.
    Falls back to config/default_reviewers.json.
    """
    if "/" not in repo or not repo.strip():
        raise ValueError(f"repo must be in owner/repo format, got: {repo!r}")

    owner, name = repo.split("/", 1)
    if not owner or not name:
        raise ValueError(f"repo must be in owner/repo format, got: {repo!r}")

    override = CONFIG_DIR / owner / name / "reviewers.json"
    if override.is_file():
        data = json.loads(override.read_text())
        return data["reviewers"]

    default = CONFIG_DIR / "default_reviewers.json"
    data = json.loads(default.read_text())
    return data
