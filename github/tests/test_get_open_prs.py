"""Tests for PRQueueClient class in get_open_prs."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest

# Ensure the github package is importable
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from get_open_prs import PRQueueClient, VALID_ACTIONS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_CONFIG = {
    "defaultAgent": "backend-dev",
    "defaultMaxIterations": 5,
    "repos": {
        "acme/app": {"enabled": True, "priority": 10},
        "acme/lib": {"enabled": True, "priority": 0},
    },
}

_SCHEMA = """\
CREATE TABLE workflow_items (
    item_type TEXT,
    github_state TEXT,
    action TEXT,
    number INTEGER,
    title TEXT,
    url TEXT,
    repo TEXT,
    author TEXT,
    head_sha TEXT,
    head_ref_name TEXT,
    iteration INTEGER DEFAULT 0,
    labels_json TEXT,
    updated_at TEXT,
    priority INTEGER DEFAULT 0,
    has_conflicts INTEGER DEFAULT 0,
    all_reviewers_approved INTEGER DEFAULT 0,
    any_changes_requested INTEGER DEFAULT 0,
    last_reviewed_sha TEXT,
    last_review_dispatch_sha TEXT,
    last_fix_dispatch_sha TEXT,
    last_merge_dispatch_sha TEXT,
    last_conflict_dispatch_sha TEXT,
    claimed INTEGER DEFAULT 0,
    claimed_by TEXT,
    in_progress INTEGER DEFAULT 0,
    claim_expires_at TEXT
);
"""


def _insert_pr(
    cur: sqlite3.Cursor,
    *,
    repo: str = "acme/app",
    number: int = 1,
    title: str = "Fix bug",
    action: str = "needs_review",
    state: str = "open",
    head_sha: str = "abc123",
    head_ref_name: str | None = None,
    iteration: int = 0,
    priority: int = 0,
    updated_at: str = "2025-01-01T00:00:00Z",
    claimed: int = 0,
    last_review_dispatch_sha: str | None = None,
    last_fix_dispatch_sha: str | None = None,
) -> None:
    cur.execute(
        """INSERT INTO workflow_items
        (item_type, github_state, action, number, title, repo, author,
         head_sha, head_ref_name, iteration, priority, updated_at, claimed,
         last_review_dispatch_sha, last_fix_dispatch_sha)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "pr",
            state,
            action,
            number,
            title,
            repo,
            "dev1",
            head_sha,
            head_ref_name,
            iteration,
            priority,
            updated_at,
            claimed,
            last_review_dispatch_sha,
            last_fix_dispatch_sha,
        ),
    )


@pytest.fixture()
def config_path(tmp_path):
    p = tmp_path / "repos_config.json"
    p.write_text(json.dumps(MINIMAL_CONFIG))
    return str(p)


@pytest.fixture()
def db_path(tmp_path):
    p = tmp_path / "workflow.db"
    conn = sqlite3.connect(str(p))
    conn.executescript(_SCHEMA)
    cur = conn.cursor()
    _insert_pr(cur, repo="acme/app", number=1, action="needs_review", head_sha="sha1", head_ref_name="feature/auth", updated_at="2025-01-01T00:00:00Z")
    _insert_pr(cur, repo="acme/app", number=2, action="needs_review", head_sha="sha2", head_ref_name="fix/login-bug", updated_at="2025-01-02T00:00:00Z")
    _insert_pr(cur, repo="acme/app", number=3, action="needs_fix", head_sha="sha3", head_ref_name="feature/api-update", updated_at="2025-01-03T00:00:00Z")
    _insert_pr(cur, repo="acme/lib", number=10, action="needs_review", head_sha="sha10", updated_at="2025-01-04T00:00:00Z")
    _insert_pr(cur, repo="acme/app", number=4, action="needs_review", head_sha="sha4", updated_at="2025-01-05T00:00:00Z", claimed=1)
    conn.commit()
    conn.close()
    return str(p)


# ---------------------------------------------------------------------------
# Init tests
# ---------------------------------------------------------------------------


class TestInit:
    def test_init_loads_config(self, db_path, config_path):
        client = PRQueueClient(db_path=db_path, config_path=config_path)
        assert client._config is not None
        assert client._config.default_agent == "backend-dev"
        client.close()

    def test_init_missing_db_raises(self, config_path):
        with pytest.raises(FileNotFoundError):
            PRQueueClient(db_path="/tmp/nonexistent_abc123.db", config_path=config_path)

    def test_init_bad_config_raises(self, db_path, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json!!!")
        with pytest.raises(ValueError):
            PRQueueClient(db_path=db_path, config_path=str(bad))

    def test_init_missing_config_raises(self, db_path):
        with pytest.raises(ValueError):
            PRQueueClient(db_path=db_path, config_path="/tmp/nonexistent_config_xyz.json")


# ---------------------------------------------------------------------------
# Context manager tests
# ---------------------------------------------------------------------------


class TestContextManager:
    def test_context_manager_opens_and_closes(self, db_path, config_path):
        with PRQueueClient(db_path=db_path, config_path=config_path) as client:
            assert client._conn is not None
        # After exiting, connection should be closed
        with pytest.raises(Exception):
            client._conn.execute("SELECT 1")

    def test_context_manager_closes_on_exception(self, db_path, config_path):
        with pytest.raises(RuntimeError):
            with PRQueueClient(db_path=db_path, config_path=config_path) as client:
                raise RuntimeError("boom")
        with pytest.raises(Exception):
            client._conn.execute("SELECT 1")


# ---------------------------------------------------------------------------
# Query tests
# ---------------------------------------------------------------------------


class TestQuery:
    def test_needs_review_returns_prs(self, db_path, config_path):
        with PRQueueClient(db_path=db_path, config_path=config_path) as client:
            result = client.query(action="needs_review")
        assert "prs" in result
        assert "error" not in result
        # PRs 1, 2, 10 are needs_review and not claimed; PR 4 is claimed (excluded by default)
        assert result["counts"]["returned"] == 3

    def test_needs_fix_returns_prs(self, db_path, config_path):
        with PRQueueClient(db_path=db_path, config_path=config_path) as client:
            result = client.query(action="needs_fix")
        assert result["counts"]["returned"] == 1
        assert result["prs"][0]["prNumber"] == 3

    def test_invalid_action_raises(self, db_path, config_path):
        with PRQueueClient(db_path=db_path, config_path=config_path) as client:
            with pytest.raises(ValueError, match="invalid action"):
                client.query(action="bogus")

    def test_limit_respected(self, db_path, config_path):
        with PRQueueClient(db_path=db_path, config_path=config_path) as client:
            result = client.query(action="needs_review", limit=1)
        assert result["counts"]["returned"] == 1

    def test_repo_filter(self, db_path, config_path):
        with PRQueueClient(db_path=db_path, config_path=config_path) as client:
            result = client.query(action="needs_review", repos=["acme/lib"])
        assert result["counts"]["returned"] == 1
        assert result["prs"][0]["repo"] == "acme/lib"

    def test_include_claimed(self, db_path, config_path):
        with PRQueueClient(db_path=db_path, config_path=config_path) as client:
            result = client.query(action="needs_review", exclude_claimed=False)
        # Should include PR 4 which is claimed
        assert result["counts"]["returned"] == 4

    def test_exclude_dispatched(self, db_path, config_path, tmp_path):
        """PRs whose head_sha matches the dispatch sha are skipped."""
        p = tmp_path / "dispatch.db"
        conn = sqlite3.connect(str(p))
        conn.executescript(_SCHEMA)
        cur = conn.cursor()
        _insert_pr(cur, number=1, action="needs_review", head_sha="abc", last_review_dispatch_sha="abc")
        _insert_pr(cur, number=2, action="needs_review", head_sha="def", last_review_dispatch_sha=None)
        conn.commit()
        conn.close()

        with PRQueueClient(db_path=str(p), config_path=config_path) as client:
            result = client.query(action="needs_review", exclude_already_dispatched=True)
        assert result["counts"]["returned"] == 1
        assert result["prs"][0]["prNumber"] == 2

    def test_include_meta_true(self, db_path, config_path):
        with PRQueueClient(db_path=db_path, config_path=config_path) as client:
            result = client.query(action="needs_fix", include_meta=True)
        pr = result["prs"][0]
        assert "iteration" in pr
        assert "dispatchState" in pr

    def test_include_meta_false(self, db_path, config_path):
        with PRQueueClient(db_path=db_path, config_path=config_path) as client:
            result = client.query(action="needs_fix", include_meta=False)
        pr = result["prs"][0]
        assert "iteration" not in pr
        assert "dispatchState" not in pr

    def test_suggested_dev_agent_auto(self, db_path, config_path):
        """needs_fix auto-includes suggestedDevAgent; needs_review does not."""
        with PRQueueClient(db_path=db_path, config_path=config_path) as client:
            fix = client.query(action="needs_fix")
            review = client.query(action="needs_review")
        assert "suggestedDevAgent" in fix["prs"][0]
        assert "suggestedDevAgent" not in review["prs"][0]

    def test_suggested_dev_agent_override(self, db_path, config_path):
        with PRQueueClient(db_path=db_path, config_path=config_path) as client:
            result = client.query(action="needs_review", include_suggested_dev_agent=True)
        assert "suggestedDevAgent" in result["prs"][0]

    def test_head_ref_name_included_in_output(self, db_path, config_path):
        """headRefName should appear in query output when stored in DB."""
        with PRQueueClient(db_path=db_path, config_path=config_path) as client:
            result = client.query(action="needs_fix")
        pr = result["prs"][0]
        assert pr["prNumber"] == 3
        assert pr["headRefName"] == "feature/api-update"

    def test_head_ref_name_null_when_missing(self, db_path, config_path):
        """headRefName should be None when not stored in DB."""
        with PRQueueClient(db_path=db_path, config_path=config_path) as client:
            result = client.query(action="needs_review", repos=["acme/lib"])
        pr = result["prs"][0]
        assert pr["prNumber"] == 10
        assert pr["headRefName"] is None

    def test_result_shape(self, db_path, config_path):
        with PRQueueClient(db_path=db_path, config_path=config_path) as client:
            result = client.query(action="needs_review")
        assert "generatedAt" in result
        assert "source" in result
        assert "queue" in result
        assert result["queue"] == "needs_review"
        assert "filters" in result
        assert "counts" in result
        assert "prs" in result

    def test_multiple_queries_same_client(self, db_path, config_path):
        """Client should support multiple sequential queries."""
        with PRQueueClient(db_path=db_path, config_path=config_path) as client:
            r1 = client.query(action="needs_review")
            r2 = client.query(action="needs_fix")
            r3 = client.query(action="needs_review", limit=1)
        assert r1["counts"]["returned"] == 3
        assert r2["counts"]["returned"] == 1
        assert r3["counts"]["returned"] == 1


# ---------------------------------------------------------------------------
# Close / double-close
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_is_idempotent(self, db_path, config_path):
        client = PRQueueClient(db_path=db_path, config_path=config_path)
        client.close()
        client.close()  # should not raise
