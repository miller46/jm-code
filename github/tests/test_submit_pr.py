"""Tests for github.submit_pr module."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from submit_pr import (
    ALLOWED_EVENTS,
    error,
    find_agent,
    agent_gh_config_dir,
    resolve_agent_config,
    submit_pr,
    validate_inputs,
    main,
)


# ---------------------------------------------------------------------------
# error helper
# ---------------------------------------------------------------------------
class TestError:
    def test_basic(self):
        result = error("CODE", "msg")
        assert result == {"error": {"code": "CODE", "message": "msg", "retryable": False}}

    def test_retryable(self):
        result = error("CODE", "msg", retryable=True)
        assert result["error"]["retryable"] is True


# ---------------------------------------------------------------------------
# resolve_agent_config
# ---------------------------------------------------------------------------
class TestResolveAgentConfig:
    def test_invalid_repo_format(self):
        _, _, err = resolve_agent_config("bad-repo")
        assert err is not None
        assert err["error"]["code"] == "INVALID_INPUT"

    @patch("submit_pr.load_json")
    def test_repo_specific_config_preferred(self, mock_load, tmp_path):
        repo_cfg = tmp_path / "repos" / "acme" / "app" / "config" / "agents.json"
        repo_cfg.parent.mkdir(parents=True)
        repo_cfg.write_text('{"agents": []}')

        mock_load.return_value = ({"agents": []}, None)

        with patch("submit_pr.WORKSPACE_MANAGER_ROOT", tmp_path):
            payload, source, err = resolve_agent_config("acme/app")

        assert err is None
        assert payload == {"agents": []}

    @patch("submit_pr.load_json")
    def test_falls_back_to_default(self, mock_load, tmp_path):
        default_cfg = tmp_path / "agents.json"
        default_cfg.write_text('{"agents": []}')

        mock_load.return_value = ({"agents": []}, None)

        with patch("submit_pr.WORKSPACE_MANAGER_ROOT", tmp_path):
            payload, source, err = resolve_agent_config("acme/app")

        assert err is None


# ---------------------------------------------------------------------------
# find_agent
# ---------------------------------------------------------------------------
class TestFindAgent:
    def test_finds_by_id(self):
        payload = {"agents": [{"id": "dev-bot", "name": "Dev Bot"}]}
        assert find_agent(payload, "dev-bot") == {"id": "dev-bot", "name": "Dev Bot"}

    def test_finds_by_name(self):
        payload = {"agents": [{"name": "dev-bot"}]}
        assert find_agent(payload, "dev-bot") == {"name": "dev-bot"}

    def test_finds_by_agent_key(self):
        payload = {"agents": [{"agent": "dev-bot"}]}
        assert find_agent(payload, "dev-bot") == {"agent": "dev-bot"}

    def test_not_found(self):
        payload = {"agents": [{"id": "other"}]}
        assert find_agent(payload, "dev-bot") is None

    def test_empty_agents(self):
        assert find_agent({}, "dev-bot") is None

    def test_required_reviewers_format(self):
        payload = {"required_reviewers": [{"id": "dev-bot"}]}
        assert find_agent(payload, "dev-bot") == {"id": "dev-bot"}


# ---------------------------------------------------------------------------
# agent_gh_config_dir
# ---------------------------------------------------------------------------
class TestAgentGhConfigDir:
    @patch("os.path.isdir", return_value=True)
    def test_returns_dir_when_exists(self, _mock):
        result = agent_gh_config_dir({}, "dev-bot")
        assert result == os.path.expanduser("~/.openclaw/agents/dev-bot/agent")

    @patch("os.path.isdir", return_value=False)
    def test_returns_none_when_missing(self, _mock):
        assert agent_gh_config_dir({}, "dev-bot") is None


# ---------------------------------------------------------------------------
# validate_inputs
# ---------------------------------------------------------------------------
class TestValidateInputs:
    def test_valid(self):
        assert validate_inputs("acme/app", "feature-x", "main", "Add feature") is None

    def test_bad_repo(self):
        err = validate_inputs("bad", "feature-x", "main", "title")
        assert err["error"]["code"] == "INVALID_INPUT"

    def test_empty_head(self):
        err = validate_inputs("acme/app", "", "main", "title")
        assert err["error"]["code"] == "INVALID_INPUT"

    def test_empty_title(self):
        err = validate_inputs("acme/app", "feature-x", "main", "")
        assert err["error"]["code"] == "INVALID_INPUT"

    def test_empty_base(self):
        err = validate_inputs("acme/app", "feature-x", "", "title")
        assert err["error"]["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# submit_pr
# ---------------------------------------------------------------------------
class TestSubmitPr:
    def test_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/acme/app/pull/99\n"
        mock_result.stderr = ""

        with patch("submit_pr.subprocess.run", return_value=mock_result) as mock_run:
            ok, details, _ = submit_pr(
                repo="acme/app",
                head="feature-x",
                base="main",
                title="Add feature",
                body="Description here",
                gh_config_dir=None,
            )

        assert ok is True
        assert "99" in details
        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["gh", "pr", "create"]
        assert "--repo" in cmd
        assert "acme/app" in cmd
        assert "--head" in cmd
        assert "feature-x" in cmd

    def test_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "branch does not exist"

        with patch("submit_pr.subprocess.run", return_value=mock_result):
            ok, details, _ = submit_pr(
                repo="acme/app",
                head="feature-x",
                base="main",
                title="Add feature",
                body="Desc",
                gh_config_dir=None,
            )

        assert ok is False
        assert "branch does not exist" in details

    def test_gh_config_dir_injected(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/acme/app/pull/1"
        mock_result.stderr = ""

        with patch("submit_pr.subprocess.run", return_value=mock_result) as mock_run:
            submit_pr(
                repo="acme/app",
                head="feature-x",
                base="main",
                title="title",
                body="body",
                gh_config_dir="/fake/config",
            )

        env = mock_run.call_args[1]["env"]
        assert env["GH_CONFIG_DIR"] == "/fake/config"
        assert "GH_TOKEN" not in env
        assert "GITHUB_TOKEN" not in env

    def test_tokens_cleared_without_config_dir(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/acme/app/pull/1"
        mock_result.stderr = ""

        fake_env = {"GH_TOKEN": "leaked", "GITHUB_TOKEN": "leaked", "PATH": "/usr/bin"}

        with patch("submit_pr.subprocess.run", return_value=mock_result) as mock_run, \
             patch.dict("os.environ", fake_env, clear=True):
            submit_pr(
                repo="acme/app",
                head="feature-x",
                base="main",
                title="title",
                body="body",
                gh_config_dir=None,
            )

        env = mock_run.call_args[1]["env"]
        assert "GH_TOKEN" not in env
        assert "GITHUB_TOKEN" not in env

    def test_draft_flag(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/acme/app/pull/1"
        mock_result.stderr = ""

        with patch("submit_pr.subprocess.run", return_value=mock_result) as mock_run:
            submit_pr(
                repo="acme/app",
                head="feature-x",
                base="main",
                title="title",
                body="body",
                gh_config_dir=None,
                draft=True,
            )

        cmd = mock_run.call_args[0][0]
        assert "--draft" in cmd

    def test_labels(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/acme/app/pull/1"
        mock_result.stderr = ""

        with patch("submit_pr.subprocess.run", return_value=mock_result) as mock_run:
            submit_pr(
                repo="acme/app",
                head="feature-x",
                base="main",
                title="title",
                body="body",
                gh_config_dir=None,
                labels=["bug", "urgent"],
            )

        cmd = mock_run.call_args[0][0]
        assert "--label" in cmd
        assert "bug" in cmd
        assert "urgent" in cmd


# ---------------------------------------------------------------------------
# main (CLI)
# ---------------------------------------------------------------------------
class TestMain:
    @patch("submit_pr.submit_pr")
    @patch("submit_pr.resolve_agent_config")
    @patch("submit_pr.find_agent")
    @patch("submit_pr.agent_gh_config_dir")
    def test_happy_path_cli_args(self, mock_gh_dir, mock_find, mock_cfg, mock_submit):
        mock_cfg.return_value = ({"agents": []}, "/path/agents.json", None)
        mock_find.return_value = {"id": "dev-bot"}
        mock_gh_dir.return_value = "/fake/dir"
        mock_submit.return_value = (True, "https://github.com/acme/app/pull/5", {})

        rc = main([
            "--repo", "acme/app",
            "--head", "feature-x",
            "--base", "main",
            "--title", "Add feature",
            "--body", "Description",
            "--agent-id", "dev-bot",
        ])

        assert rc == 0
        mock_submit.assert_called_once()

    @patch("submit_pr.submit_pr")
    @patch("submit_pr.resolve_agent_config")
    @patch("submit_pr.find_agent")
    @patch("submit_pr.agent_gh_config_dir")
    def test_input_json(self, mock_gh_dir, mock_find, mock_cfg, mock_submit, capsys):
        mock_cfg.return_value = ({"agents": []}, "/path/agents.json", None)
        mock_find.return_value = {"id": "dev-bot"}
        mock_gh_dir.return_value = None
        mock_submit.return_value = (True, "https://github.com/acme/app/pull/10", {})

        payload = json.dumps({
            "repo": "acme/app",
            "head": "feature-x",
            "base": "main",
            "title": "Title",
            "body": "Body",
            "agentId": "dev-bot",
        })

        rc = main(["--input-json", payload])
        assert rc == 0

    def test_missing_repo(self, capsys):
        rc = main(["--head", "feature-x", "--title", "T", "--body", "B", "--agent-id", "dev-bot"])
        assert rc == 1
        out = json.loads(capsys.readouterr().out)
        assert out["error"]["code"] == "INVALID_INPUT"

    @patch("submit_pr.resolve_agent_config")
    @patch("submit_pr.find_agent")
    @patch("submit_pr.agent_gh_config_dir")
    def test_dry_run(self, mock_gh_dir, mock_find, mock_cfg, capsys):
        mock_cfg.return_value = ({"agents": []}, "/path/agents.json", None)
        mock_find.return_value = {"id": "dev-bot"}
        mock_gh_dir.return_value = "/fake/dir"

        rc = main([
            "--repo", "acme/app",
            "--head", "feature-x",
            "--base", "main",
            "--title", "Add feature",
            "--body", "Description",
            "--agent-id", "dev-bot",
            "--dry-run",
        ])

        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["dryRun"] is True
        assert out["ghConfigDir"] == "/fake/dir"

    @patch("submit_pr.resolve_agent_config")
    @patch("submit_pr.find_agent")
    def test_agent_not_found(self, mock_find, mock_cfg, capsys):
        mock_cfg.return_value = ({"agents": []}, "/path/agents.json", None)
        mock_find.return_value = None

        rc = main([
            "--repo", "acme/app",
            "--head", "feature-x",
            "--title", "T",
            "--body", "B",
            "--agent-id", "unknown",
        ])

        assert rc == 1
        out = json.loads(capsys.readouterr().out)
        assert out["error"]["code"] == "CONFIG_ERROR"
