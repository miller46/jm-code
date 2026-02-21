"""Tests for loading repos from config/repos.json."""

import json
import os
import pytest
from unittest.mock import patch

from github.workflow_config import load_repos, _workspace_root


@pytest.fixture
def repos_json(tmp_path):
    """Create a temporary repos.json and patch _workspace_root."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir / "repos.json"


def _patch_root(tmp_path):
    return patch("github.workflow_config._workspace_root", return_value=str(tmp_path))


class TestLoadRepos:
    def test_returns_enabled_repos(self, tmp_path, repos_json):
        repos_json.write_text(json.dumps({
            "repos": {
                "owner/repo-a": {"enabled": True},
                "owner/repo-b": {"enabled": True},
                "owner/repo-c": {"enabled": False},
            }
        }))
        with _patch_root(tmp_path):
            result = load_repos()
        assert sorted(result) == ["owner/repo-a", "owner/repo-b"]

    def test_skips_disabled_repos(self, tmp_path, repos_json):
        repos_json.write_text(json.dumps({
            "repos": {
                "owner/enabled": {"enabled": True},
                "owner/disabled": {"enabled": False},
            }
        }))
        with _patch_root(tmp_path):
            result = load_repos()
        assert result == ["owner/enabled"]

    def test_missing_enabled_defaults_to_true(self, tmp_path, repos_json):
        repos_json.write_text(json.dumps({
            "repos": {
                "owner/no-flag": {"priority": 0},
            }
        }))
        with _patch_root(tmp_path):
            result = load_repos()
        assert result == ["owner/no-flag"]

    def test_empty_repos_returns_empty(self, tmp_path, repos_json):
        repos_json.write_text(json.dumps({"repos": {}}))
        with _patch_root(tmp_path):
            result = load_repos()
        assert result == []

    def test_missing_file_falls_back_to_config_default(self, tmp_path):
        """When repos.json doesn't exist, fall back to get_config()['repos']."""
        (tmp_path / "config").mkdir(exist_ok=True)
        with _patch_root(tmp_path):
            with patch("github.workflow_config.get_config", return_value={"repos": ["fallback/repo"]}):
                result = load_repos()
        assert result == ["fallback/repo"]
