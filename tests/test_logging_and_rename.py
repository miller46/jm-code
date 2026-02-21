"""Tests for unified logging and task->prompt rename."""

import logging
from unittest.mock import patch, Mock

from workflow import tasks
from agent import spawn_agent
from agent import dev_agent, review_agent


class TestTasksUsesLogger:
    """workflow/tasks.py should use logging, not print()."""

    def test_dev_open_issues_logs_prompt_at_debug(self):
        """The prompt text should only be logged at DEBUG level."""
        mock_client = Mock()
        mock_client.query.return_value = {
            "issues": [{
                "title": "Fix bug",
                "issueNumber": 1,
                "repo": "owner/repo",
            }]
        }
        with (
            patch.object(tasks, "spawn_agent") as mock_spawn,
            patch.object(tasks, "_suggest_agent", return_value="backend-dev"),
            patch("workflow.tasks.logger") as mock_logger,
        ):
            mock_spawn.return_value = {}
            tasks.dev_open_issues(mock_client)
            # The prompt should be logged at debug level
            mock_logger.debug.assert_called()
            # Check that at least one debug call contains the prompt content
            debug_calls = [str(c) for c in mock_logger.debug.call_args_list]
            assert any("prompt" in c.lower() or "implement" in c.lower() for c in debug_calls)

    def test_review_open_prs_logs_prompt_at_debug(self):
        """The prompt text should only be logged at DEBUG level."""
        mock_client = Mock()
        mock_client.query.return_value = {
            "counts": {"returned": 1},
            "prs": [{
                "prNumber": 42,
                "repo": "owner/repo",
                "headRefName": "feature/test",
            }],
        }
        with (
            patch.object(tasks, "spawn_agent") as mock_spawn,
            patch.object(tasks, "get_reviewers", return_value=[{"agent": "code-snob", "enabled": True}]),
            patch("workflow.tasks.logger") as mock_logger,
        ):
            mock_spawn.return_value = {}
            tasks.review_open_prs(mock_client)
            mock_logger.debug.assert_called()

    def test_fix_open_prs_logs_prompt_at_debug(self):
        """The prompt text should only be logged at DEBUG level."""
        mock_client = Mock()
        mock_client.query.return_value = {
            "counts": {"returned": 1},
            "prs": [{
                "prNumber": 42,
                "repo": "owner/repo",
                "title": "Fix stuff",
                "headRefName": "feature/fix",
            }],
        }
        with (
            patch.object(tasks, "spawn_agent") as mock_spawn,
            patch.object(tasks, "_suggest_agent", return_value="backend-dev"),
            patch("workflow.tasks.logger") as mock_logger,
        ):
            mock_spawn.return_value = {}
            tasks.fix_open_prs(mock_client)
            mock_logger.debug.assert_called()


class TestPromptRename:
    """Variables holding prompts should be named 'prompt', not 'task'."""

    def test_spawn_agent_accepts_prompt_param(self):
        """spawn_agent should accept 'prompt' as parameter name."""
        with patch("agent.openclaw_tool") as mock_tool:
            mock_tool.return_value = {"ok": True}
            spawn_agent("label", prompt="do something", agent_id="dev")
            call_args = mock_tool.call_args[0][1]
            assert "task" in call_args  # API key stays as 'task' (external contract)
            assert call_args["task"] == "do something"

    def test_dev_agent_get_dev_prompt_returns_string(self):
        prompt = dev_agent.get_dev_prompt(repo="owner/repo", issue_number="1")
        assert isinstance(prompt, str)
        assert "owner/repo" in prompt

    def test_review_agent_get_reviewer_prompt_returns_string(self):
        prompt = review_agent.get_reviewer_prompt(
            reviewer_id="snob", repo="owner/repo", pr_number="1", branch="main"
        )
        assert isinstance(prompt, str)
        assert "owner/repo" in prompt


class TestGithubSyncUsesLogger:
    """github/github_sync.py should use logging, not print()."""

    def test_no_print_calls_in_github_sync(self):
        """github_sync should not use print() anywhere."""
        import inspect
        from github import github_sync
        source = inspect.getsource(github_sync)
        # Allow 'print' in string literals but not as function calls
        lines = source.split('\n')
        for i, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if stripped.startswith('#'):
                continue
            if stripped.startswith('print(') or stripped.startswith('print ('):
                raise AssertionError(f"github_sync.py line {i} uses print(): {stripped}")
