"""Tests for sync_repo using real GitHub API fixture data.

Fixtures in tests/fixtures/ were captured from live miller46/jm-api API calls.
Tests mock fetch_issues/fetch_prs/fetch_pr_detail and verify that
determine_issue_action, determine_pr_action, and sync_repo produce
correct state in the SQLite DB.
"""

import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add parent scripts dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from github_sync import (
    Action,
    ItemType,
    Status,
    WorkflowItem,
    determine_issue_action,
    determine_pr_action,
    find_linked_prs,
    make_item_id,
    sync_repo,
    SCHEMA,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPO = "miller46/jm-api"
REQUIRED_REVIEWERS = ["code-snob", "architect"]


# ── Fixture helpers ──────────────────────────────────────────────────────────

def load_fixture(name: str):
    with open(FIXTURES / name) as f:
        return json.load(f)


@pytest.fixture
def issues():
    return load_fixture("github_issues.json")


@pytest.fixture
def prs_list():
    return load_fixture("github_prs_list.json")


@pytest.fixture
def pr_detail_54():
    return load_fixture("github_pr_detail_54.json")


@pytest.fixture
def pr_detail_60():
    return load_fixture("github_pr_detail_60.json")


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary SQLite DB with schema applied."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    return db_path


def _make_existing(
    item_id="miller46/jm-api#pr#10",
    iteration=0,
    status=Status.PENDING_REVIEW,
    last_reviewed_sha=None,
    last_review_dispatch_sha=None,
    last_fix_dispatch_sha=None,
    last_merge_dispatch_sha=None,
    last_conflict_dispatch_sha=None,
) -> WorkflowItem:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    return WorkflowItem(
        id=item_id,
        type=ItemType.PR,
        repo=REPO,
        number=10,
        title="test PR",
        github_state="open",
        repo_scoped_id=item_id,
        status=status,
        action=Action.NEEDS_REVIEW,
        head_sha="abc123",
        last_reviewed_sha=last_reviewed_sha,
        reviews={},
        all_reviewers_approved=False,
        any_changes_requested=False,
        sha_matches_review=False,
        has_conflicts=False,
        last_review_dispatch_sha=last_review_dispatch_sha,
        last_fix_dispatch_sha=last_fix_dispatch_sha,
        last_merge_dispatch_sha=last_merge_dispatch_sha,
        last_conflict_dispatch_sha=last_conflict_dispatch_sha,
        last_head_sha_seen="abc123",
        iteration=iteration,
        max_iterations=5,
        assigned_agent=None,
        lock_expires=None,
        created_at=now,
        updated_at=now,
        last_sync=now,
    )


# ── determine_issue_action with real fixture data ────────────────────────────

class TestDetermineIssueActionFixture:
    """Test determine_issue_action using live issue #61 data."""

    def test_open_issue_no_linked_pr_needs_dev(self, issues):
        """Open issue #61 with no linked PR → OPEN / NEEDS_DEV."""
        issue = issues[0]
        assert issue["number"] == 61
        assert issue["state"] == "OPEN"

        status, action = determine_issue_action(issue, existing=None, linked_pr_number=None)
        assert status == Status.OPEN
        assert action == Action.NEEDS_DEV

    def test_open_issue_with_linked_pr_no_action(self, issues):
        """Open issue #61 with a linked PR → PR_CREATED / NONE."""
        issue = issues[0]
        status, action = determine_issue_action(issue, existing=None, linked_pr_number=62)
        assert status == Status.PR_CREATED
        assert action == Action.NONE

    def test_closed_issue(self, issues):
        """Simulating closed state on issue #61."""
        issue = {**issues[0], "state": "closed"}
        status, action = determine_issue_action(issue, existing=None)
        assert status == Status.CLOSED
        assert action == Action.NONE

    def test_in_progress_issue_stays_in_progress(self, issues):
        """Existing in-progress issue stays in-progress."""
        issue = issues[0]
        existing = _make_existing(
            item_id=make_item_id(REPO, ItemType.ISSUE, 61),
        )
        existing.type = ItemType.ISSUE
        existing.status = Status.IN_PROGRESS
        status, action = determine_issue_action(issue, existing=existing)
        assert status == Status.IN_PROGRESS
        assert action == Action.NONE


# ── determine_pr_action with real fixture data ───────────────────────────────

class TestDeterminePrActionFixture:
    """Test determine_pr_action using live PR #54 and #60 data."""

    def test_merged_pr_54(self, pr_detail_54):
        """PR #54 is MERGED → Status.MERGED, Action.NONE."""
        assert pr_detail_54["state"] == "MERGED"
        status, action, all_approved, any_cr, decisions, reviewed_sha = (
            determine_pr_action(pr_detail_54, existing=None, required_reviewers=REQUIRED_REVIEWERS)
        )
        assert status == Status.MERGED
        assert action == Action.NONE

    def test_closed_pr_60_with_non_required_reviewer(self, pr_detail_60):
        """PR #60 is CLOSED with reviews from miller46bot (not a required reviewer)."""
        assert pr_detail_60["state"] == "CLOSED"
        # Treat it as open for testing the review logic
        open_pr = {**pr_detail_60, "state": "OPEN", "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN"}

        status, action, all_approved, any_cr, decisions, reviewed_sha = (
            determine_pr_action(open_pr, existing=None, required_reviewers=REQUIRED_REVIEWERS)
        )
        # miller46bot is not in REQUIRED_REVIEWERS, so reviews are ignored
        assert status == Status.PENDING_REVIEW
        assert action == Action.NEEDS_REVIEW

    def test_pr_54_reviews_from_non_required_reviewer(self, pr_detail_54):
        """PR #54 has reviews from miller46bot (not a required reviewer) → no decisions for required reviewers."""
        head_sha = pr_detail_54["headRefOid"]
        open_pr = {**pr_detail_54, "state": "OPEN", "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN"}

        status, action, all_approved, any_cr, decisions, reviewed_sha = (
            determine_pr_action(open_pr, existing=None, required_reviewers=REQUIRED_REVIEWERS)
        )
        # All reviews are from miller46bot which is not in REQUIRED_REVIEWERS,
        # so no required reviewers have decisions → PENDING_REVIEW / NEEDS_REVIEW
        assert status == Status.PENDING_REVIEW
        assert action == Action.NEEDS_REVIEW
        assert all_approved is False

    def test_pr_with_conflicts_and_approval(self, pr_detail_54):
        """Simulated: approved PR with merge conflicts → NEEDS_CONFLICT_RESOLUTION."""
        open_pr = {
            **pr_detail_54,
            "state": "OPEN",
            "mergeable": "CONFLICTING",
            "mergeStateStatus": "DIRTY",
        }
        # Add explicit reviewer approvals
        open_pr["reviews"] = [
            {
                "author": {"login": "code-snob"},
                "state": "APPROVED",
                "commit": {"oid": open_pr["headRefOid"]},
                "body": "LGTM",
                "submittedAt": "2026-02-18T03:00:00Z",
            },
            {
                "author": {"login": "architect"},
                "state": "APPROVED",
                "commit": {"oid": open_pr["headRefOid"]},
                "body": "LGTM",
                "submittedAt": "2026-02-18T03:01:00Z",
            },
        ]
        existing = _make_existing(last_reviewed_sha=open_pr["headRefOid"])

        status, action, *_ = determine_pr_action(
            open_pr, existing=existing, required_reviewers=REQUIRED_REVIEWERS
        )
        assert status == Status.CONFLICTING
        assert action == Action.NEEDS_CONFLICT_RESOLUTION


# ── find_linked_prs with real fixture data ───────────────────────────────────

class TestFindLinkedPrsFixture:
    """Test find_linked_prs using real PR list data."""

    def test_pr_60_closes_issue_58(self, prs_list):
        """PR #60 body contains 'Closes #58' → should link to issue 58."""
        result = find_linked_prs(prs_list, 58)
        assert result == 60

    def test_no_pr_links_issue_61(self, prs_list):
        """No PR body references issue #61 → None."""
        result = find_linked_prs(prs_list, 61)
        assert result is None

    def test_pr_57_closes_issue_53(self, prs_list):
        """PR #57 body contains 'Closes #53' → should link to issue 53."""
        result = find_linked_prs(prs_list, 53)
        assert result == 57


# ── sync_repo end-to-end with mocked API ─────────────────────────────────────

class TestSyncRepoEndToEnd:
    """Test sync_repo with mocked GitHub API, verifying DB state."""

    def _read_items(self, db_path):
        """Read all workflow_items from the DB."""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM workflow_items ORDER BY id").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def test_sync_issues_only_no_prs(self, tmp_db, issues):
        """Sync with 1 open issue, 0 open PRs → 1 issue in DB with NEEDS_DEV."""
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=issues),
            patch("github_sync.fetch_prs", return_value=[]),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
        ):
            count = sync_repo(REPO)

        assert count == 1
        items = self._read_items(tmp_db)
        assert len(items) == 1

        issue_item = items[0]
        assert issue_item["number"] == 61
        assert issue_item["type"] == "issue"
        assert issue_item["repo"] == REPO
        assert issue_item["status"] == "open"
        assert issue_item["action"] == "needs_dev"
        assert issue_item["title"] == "[backend] Replace in-memory refresh-token revocation with persistent session store"

    def test_sync_issue_linked_to_pr(self, tmp_db, issues):
        """When an open PR body contains 'closes #61', issue → PR_CREATED / NONE."""
        pr_in_list = {
            "number": 62,
            "title": "Implement persistent session store",
            "state": "OPEN",
            "createdAt": "2026-02-18T17:00:00Z",
            "updatedAt": "2026-02-18T17:00:00Z",
            "author": {"login": "miller46bot"},
            "headRefName": "feature/session-store",
            "body": "Implements persistent session store.\n\nCloses #61",
        }
        pr_detail = {
            "number": 62,
            "title": "Implement persistent session store",
            "state": "OPEN",
            "headRefOid": "aaa111bbb222ccc333",
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "reviews": [],
            "createdAt": "2026-02-18T17:00:00Z",
            "updatedAt": "2026-02-18T17:00:00Z",
        }

        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=issues),
            patch("github_sync.fetch_prs", return_value=[pr_in_list]),
            patch("github_sync.fetch_pr_detail", return_value=pr_detail),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
        ):
            count = sync_repo(REPO)

        # 1 issue + 1 PR = 2
        assert count == 2
        items = self._read_items(tmp_db)
        assert len(items) == 2

        issue_item = next(i for i in items if i["type"] == "issue")
        pr_item = next(i for i in items if i["type"] == "pr")

        # Issue is linked to PR → PR_CREATED
        assert issue_item["status"] == "pr_created"
        assert issue_item["action"] == "none"

        # PR has no reviews → NEEDS_REVIEW
        assert pr_item["status"] == "pending_review"
        assert pr_item["action"] == "needs_review"
        assert pr_item["head_sha"] == "aaa111bbb222ccc333"

    def test_sync_pr_with_reviews_changes_requested(self, tmp_db, issues, pr_detail_60):
        """Sync a PR that has CHANGES_REQUESTED → correct status in DB."""
        # PR #60 has a CHANGES_REQUESTED review (no marker → ambiguous, so ignored)
        # Simulate it as open with explicit reviewer markers
        pr_in_list = {
            "number": 60,
            "title": pr_detail_60["title"],
            "state": "OPEN",
            "createdAt": pr_detail_60["createdAt"],
            "updatedAt": pr_detail_60["updatedAt"],
            "author": pr_detail_60["author"],
            "headRefName": "feature/rbac",
            "body": pr_detail_60["body"],
        }
        head_sha = pr_detail_60["headRefOid"]
        modified_detail = {
            **pr_detail_60,
            "state": "OPEN",
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "reviews": [
                {
                    "author": {"login": "architect"},
                    "state": "CHANGES_REQUESTED",
                    "commit": {"oid": head_sha},
                    "body": "needs work",
                    "submittedAt": "2026-02-18T01:30:00Z",
                },
                {
                    "author": {"login": "code-snob"},
                    "state": "APPROVED",
                    "commit": {"oid": head_sha},
                    "body": "looks good",
                    "submittedAt": "2026-02-18T01:31:00Z",
                },
            ],
        }

        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=[]),
            patch("github_sync.fetch_prs", return_value=[pr_in_list]),
            patch("github_sync.fetch_pr_detail", return_value=modified_detail),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
        ):
            count = sync_repo(REPO)

        items = self._read_items(tmp_db)
        pr_item = next(i for i in items if i["type"] == "pr")

        # architect: CHANGES_REQUESTED, code-snob: APPROVED
        # On first sync with no existing → last_reviewed_sha = review SHA
        # head_sha == review SHA → sha_matches → CHANGES_REQUESTED / NEEDS_FIX
        assert pr_item["status"] == "changes_requested"
        assert pr_item["action"] == "needs_fix"
        assert pr_item["any_changes_requested"] == 1

    def test_sync_pr_approved_ready_to_merge(self, tmp_db):
        """All reviewers approved on current SHA → READY_TO_MERGE in DB."""
        head_sha = "fff999eee888ddd777"
        pr_in_list = {
            "number": 99,
            "title": "Feature: all approved",
            "state": "OPEN",
            "createdAt": "2026-02-18T10:00:00Z",
            "updatedAt": "2026-02-18T10:00:00Z",
            "author": {"login": "miller46"},
            "headRefName": "feature/approved",
            "body": "Ready to go",
        }
        pr_detail = {
            "number": 99,
            "title": "Feature: all approved",
            "state": "OPEN",
            "headRefOid": head_sha,
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "reviews": [
                {
                    "author": {"login": "code-snob"},
                    "state": "APPROVED",
                    "commit": {"oid": head_sha},
                    "body": "Ship it",
                    "submittedAt": "2026-02-18T11:00:00Z",
                },
                {
                    "author": {"login": "architect"},
                    "state": "APPROVED",
                    "commit": {"oid": head_sha},
                    "body": "LGTM",
                    "submittedAt": "2026-02-18T11:01:00Z",
                },
            ],
            "createdAt": "2026-02-18T10:00:00Z",
            "updatedAt": "2026-02-18T11:01:00Z",
        }
        # Pre-seed existing item with last_reviewed_sha matching head
        existing_id = make_item_id(REPO, ItemType.PR, 99)
        existing = _make_existing(item_id=existing_id, last_reviewed_sha=head_sha)
        existing.head_sha = head_sha

        from github_sync import save_item
        with patch("github_sync.DB_PATH", tmp_db):
            save_item(existing)

        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=[]),
            patch("github_sync.fetch_prs", return_value=[pr_in_list]),
            patch("github_sync.fetch_pr_detail", return_value=pr_detail),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
        ):
            count = sync_repo(REPO)

        items = self._read_items(tmp_db)
        pr_item = next(i for i in items if i["type"] == "pr")

        assert pr_item["status"] == "approved"
        assert pr_item["action"] == "ready_to_merge"
        assert pr_item["all_reviewers_approved"] == 1
        assert pr_item["head_sha"] == head_sha
        assert pr_item["sha_matches_review"] == 1

    def test_sync_reconciles_closed_prs(self, tmp_db):
        """PRs in DB as open but not in open list get marked closed/merged."""
        # Pre-seed a PR that was previously open
        old_pr_id = make_item_id(REPO, ItemType.PR, 50)
        existing = _make_existing(item_id=old_pr_id)
        existing.number = 50
        existing.github_state = "open"

        from github_sync import save_item
        with patch("github_sync.DB_PATH", tmp_db):
            save_item(existing)

        closed_detail = {
            "number": 50,
            "state": "MERGED",
            "headRefOid": "abc123",
            "mergeable": "UNKNOWN",
            "mergeStateStatus": "UNKNOWN",
            "reviews": [],
        }

        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=[]),
            patch("github_sync.fetch_prs", return_value=[]),  # PR #50 not in open list
            patch("github_sync.fetch_pr_detail", return_value=closed_detail),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
        ):
            count = sync_repo(REPO)

        items = self._read_items(tmp_db)
        pr_item = next(i for i in items if i["number"] == 50)

        # Should be reconciled as merged
        assert pr_item["github_state"] == "merged"
        assert pr_item["status"] == "merged"
        assert pr_item["action"] == "none"

    def test_sync_dispatch_dedupe_suppresses_repeat(self, tmp_db):
        """If review was already dispatched for this SHA, action → NONE."""
        head_sha = "dedup_sha_111"
        pr_in_list = {
            "number": 70,
            "title": "Deduped PR",
            "state": "OPEN",
            "createdAt": "2026-02-18T10:00:00Z",
            "updatedAt": "2026-02-18T10:00:00Z",
            "author": {"login": "miller46"},
            "headRefName": "feature/dedup",
            "body": "Test dedupe",
        }
        pr_detail = {
            "number": 70,
            "title": "Deduped PR",
            "state": "OPEN",
            "headRefOid": head_sha,
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "reviews": [],  # No reviews → NEEDS_REVIEW
            "createdAt": "2026-02-18T10:00:00Z",
            "updatedAt": "2026-02-18T10:00:00Z",
        }

        # Pre-seed existing with last_review_dispatch_sha = head_sha (already dispatched)
        existing_id = make_item_id(REPO, ItemType.PR, 70)
        existing = _make_existing(item_id=existing_id, last_review_dispatch_sha=head_sha)
        existing.number = 70
        existing.head_sha = head_sha

        from github_sync import save_item
        with patch("github_sync.DB_PATH", tmp_db):
            save_item(existing)

        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=[]),
            patch("github_sync.fetch_prs", return_value=[pr_in_list]),
            patch("github_sync.fetch_pr_detail", return_value=pr_detail),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
        ):
            count = sync_repo(REPO)

        items = self._read_items(tmp_db)
        pr_item = next(i for i in items if i["number"] == 70)

        # NEEDS_REVIEW would be the natural action, but dedupe suppresses it
        assert pr_item["action"] == "none"

    def test_sync_max_iterations_blocks_fix(self, tmp_db):
        """PR at max iterations with CHANGES_REQUESTED → MAX_ITERATIONS_REACHED."""
        head_sha = "maxiter_sha_999"
        pr_in_list = {
            "number": 80,
            "title": "Max iterations PR",
            "state": "OPEN",
            "createdAt": "2026-02-18T10:00:00Z",
            "updatedAt": "2026-02-18T10:00:00Z",
            "author": {"login": "miller46"},
            "headRefName": "feature/maxiter",
            "body": "Test max iterations",
        }
        pr_detail = {
            "number": 80,
            "title": "Max iterations PR",
            "state": "OPEN",
            "headRefOid": head_sha,
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "reviews": [
                {
                    "author": {"login": "architect"},
                    "state": "CHANGES_REQUESTED",
                    "commit": {"oid": head_sha},
                    "body": "still broken",
                    "submittedAt": "2026-02-18T12:00:00Z",
                },
                {
                    "author": {"login": "code-snob"},
                    "state": "APPROVED",
                    "commit": {"oid": head_sha},
                    "body": "ok",
                    "submittedAt": "2026-02-18T12:01:00Z",
                },
            ],
            "createdAt": "2026-02-18T10:00:00Z",
            "updatedAt": "2026-02-18T12:01:00Z",
        }

        # Pre-seed existing at max iterations
        from github_sync import MAX_ITERATIONS
        existing_id = make_item_id(REPO, ItemType.PR, 80)
        existing = _make_existing(
            item_id=existing_id,
            iteration=MAX_ITERATIONS,
            last_reviewed_sha=head_sha,
        )
        existing.number = 80
        existing.head_sha = head_sha

        from github_sync import save_item
        with patch("github_sync.DB_PATH", tmp_db):
            save_item(existing)

        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=[]),
            patch("github_sync.fetch_prs", return_value=[pr_in_list]),
            patch("github_sync.fetch_pr_detail", return_value=pr_detail),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
        ):
            count = sync_repo(REPO)

        items = self._read_items(tmp_db)
        pr_item = next(i for i in items if i["number"] == 80)

        assert pr_item["action"] == "max_iterations_reached"
        assert pr_item["iteration"] == MAX_ITERATIONS
