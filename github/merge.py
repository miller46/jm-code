"""Merge a GitHub pull request via the gh CLI."""

from __future__ import annotations

import subprocess
from typing import Any

VALID_STRATEGIES = {"merge", "squash", "rebase"}


def merge_pr(
    repo: str,
    pr_number: int,
    strategy: str = "merge",
) -> dict[str, Any]:
    """Merge a pull request using ``gh pr merge``.

    Args:
        repo: Repository in ``owner/repo`` format.
        pr_number: The PR number to merge.
        strategy: One of ``merge``, ``squash``, or ``rebase``.

    Returns:
        A dict with ``success`` (bool), ``repo``, ``pr_number``, and
        ``error`` (str) on failure.
    """
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"strategy must be one of {sorted(VALID_STRATEGIES)}, got: {strategy!r}")

    cmd = ["gh", "pr", "merge", str(pr_number), "--repo", repo, f"--{strategy}"]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        return {
            "success": False,
            "repo": repo,
            "pr_number": pr_number,
            "error": result.stderr.strip(),
        }

    return {
        "success": True,
        "repo": repo,
        "pr_number": pr_number,
    }
