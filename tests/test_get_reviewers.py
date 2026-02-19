"""Tests for workflow.get_reviewers."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from workflow.get_reviewers import get_reviewers

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def test_returns_default_reviewers_for_unknown_repo():
    """Repo with no override gets default_reviewers.json list."""
    reviewers = get_reviewers("some-org/some-repo")
    default = json.loads((CONFIG_DIR / "default_reviewers.json").read_text())
    assert reviewers == default["required_reviewers"]


def test_returns_override_for_repo_with_config():
    """Repo with config/{owner}/{repo}/reviewers.json uses that file."""
    reviewers = get_reviewers("miller46/jm-api")
    override = json.loads(
        (CONFIG_DIR / "miller46" / "jm-api" / "reviewers.json").read_text()
    )
    assert reviewers == override["reviewers"]


def test_override_does_not_merge_with_default():
    """Override completely replaces the default list (no merge)."""
    default = get_reviewers("some-org/some-repo")
    override = get_reviewers("miller46/jm-api")
    # They should be independent lists, not a superset
    assert default != override


def test_invalid_repo_format_raises():
    """Repo string must be owner/repo."""
    with pytest.raises(ValueError):
        get_reviewers("no-slash-here")


def test_empty_repo_string_raises():
    with pytest.raises(ValueError):
        get_reviewers("")
