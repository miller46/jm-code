"""Tests for github.merge module."""

from __future__ import annotations

import subprocess
from unittest.mock import patch, MagicMock

import pytest

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from merge import merge_pr


class TestMergePr:
    def test_merge_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Merged PR #42\n"
        mock_result.stderr = ""

        with patch("merge.subprocess.run", return_value=mock_result) as mock_run:
            result = merge_pr("acme/app", 42)

        mock_run.assert_called_once_with(
            ["gh", "pr", "merge", "42", "--repo", "acme/app", "--merge"],
            capture_output=True,
            text=True,
        )
        assert result["success"] is True
        assert result["pr_number"] == 42
        assert result["repo"] == "acme/app"

    def test_merge_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "PR is not mergeable"

        with patch("merge.subprocess.run", return_value=mock_result):
            result = merge_pr("acme/app", 42)

        assert result["success"] is False
        assert "PR is not mergeable" in result["error"]

    def test_merge_with_squash(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("merge.subprocess.run", return_value=mock_result) as mock_run:
            result = merge_pr("acme/app", 10, strategy="squash")

        mock_run.assert_called_once_with(
            ["gh", "pr", "merge", "10", "--repo", "acme/app", "--squash"],
            capture_output=True,
            text=True,
        )
        assert result["success"] is True

    def test_merge_with_rebase(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("merge.subprocess.run", return_value=mock_result) as mock_run:
            merge_pr("acme/app", 5, strategy="rebase")

        mock_run.assert_called_once_with(
            ["gh", "pr", "merge", "5", "--repo", "acme/app", "--rebase"],
            capture_output=True,
            text=True,
        )

    def test_merge_invalid_strategy_raises(self):
        with pytest.raises(ValueError, match="strategy must be one of"):
            merge_pr("acme/app", 1, strategy="invalid")
