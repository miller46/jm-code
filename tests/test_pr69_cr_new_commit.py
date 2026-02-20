"""Tests for PR #69 scenario: CHANGES_REQUESTED review on old commit, new commit pushed.

PR #69 on miller46/jm-api has:
- 1 review: CHANGES_REQUESTED by miller46architect on commit 3ef44bf
- New commit pushed: 85c55d3 (head)
- Only miller46architect is an enabled reviewer (miller46codesnob disabled)
- approval_rules: min_approvals=1, no veto_powers, no required_reviewers

Expected: status=PENDING_REVIEW, action=NEEDS_REVIEW (review is stale due to new commit)
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "github"))

from github_sync import (
    Action,
    ItemType,
    Status,
    WorkflowItem,
    evaluate_reviews,
    determine_pr_action,
    make_item_id,
    save_item,
    sync_repo,
    SCHEMA,
    MAX_ITERATIONS,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPO = "miller46/jm-api"

# Actual reviewer config for miller46/jm-api: only miller46architect is enabled
REQUIRED_REVIEWERS = ["miller46architect"]
APPROVAL_RULES = {
    "mode": "majority",
    "min_approvals": 1,
    "required_reviewers": [],
    "veto_powers": [],
}

OLD_SHA = "3ef44bf05340c12e787ae4e3ace8a83a6db326a4"
NEW_SHA = "85c55d3de2dd7f3e16d423742ddaa0233c53a848"


def load_fixture(name: str):
    with open(FIXTURES / name) as f:
        return json.load(f)


@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    return db_path


def _make_existing(item_id, **kwargs):
    now = datetime.now(timezone.utc).isoformat()
    defaults = dict(
        id=item_id,
        type=ItemType.PR,
        repo=REPO,
        number=69,
        title="Harden auth flow for internet exposure",
        github_state="open",
        repo_scoped_id=item_id,
        status=Status.CHANGES_REQUESTED,
        action=Action.NEEDS_FIX,
        head_sha=OLD_SHA,
        last_reviewed_sha=OLD_SHA,
        reviews={"miller46architect": "CHANGES_REQUESTED"},
        all_reviewers_approved=False,
        any_changes_requested=True,
        sha_matches_review=True,
        has_conflicts=False,
        last_review_dispatch_sha=None,
        last_fix_dispatch_sha=None,
        last_merge_dispatch_sha=None,
        last_conflict_dispatch_sha=None,
        last_head_sha_seen=OLD_SHA,
        iteration=0,
        max_iterations=MAX_ITERATIONS,
        assigned_agent=None,
        lock_expires=None,
        created_at=now,
        updated_at=now,
        last_sync=now,
    )
    defaults.update(kwargs)
    return WorkflowItem(**defaults)


def _read_items(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM workflow_items ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Unit tests: evaluate_reviews ─────────────────────────────────────────────


class TestEvaluateReviewsPR69:
    """evaluate_reviews with single reviewer + approval_rules for PR #69."""

    def test_single_reviewer_changes_requested(self):
        """Single enabled reviewer with CHANGES_REQUESTED on old commit."""
        reviews = [
            {
                "author": {"login": "miller46architect"},
                "state": "CHANGES_REQUESTED",
                "commit": {"oid": OLD_SHA},
                "body": "Needs fixes.",
                "submittedAt": "2026-02-20T18:45:51Z",
            }
        ]
        ev = evaluate_reviews(
            reviews,
            required_reviewers=REQUIRED_REVIEWERS,
            approval_rules=APPROVAL_RULES,
        )
        assert ev.all_required_approved is False
        assert ev.any_changes_requested is True
        assert ev.latest_review_sha == OLD_SHA
        assert ev.latest_decision_by_reviewer["miller46architect"] == "CHANGES_REQUESTED"


# ── Unit tests: determine_pr_action ──────────────────────────────────────────


class TestDeterminePrActionPR69:
    """determine_pr_action for PR #69 scenario."""

    def test_first_sync_cr_on_old_commit_new_head(self):
        """First sync: CHANGES_REQUESTED on old SHA, head is new → NEEDS_REVIEW."""
        pr_detail = load_fixture("scenario_pr_detail_cr_new_commit.json")
        status, action, all_approved, any_cr, decisions, last_rev_sha = determine_pr_action(
            pr_detail,
            existing=None,
            required_reviewers=REQUIRED_REVIEWERS,
            approval_rules=APPROVAL_RULES,
        )
        assert status == Status.PENDING_REVIEW, f"Expected PENDING_REVIEW, got {status}"
        assert action == Action.NEEDS_REVIEW, f"Expected NEEDS_REVIEW, got {action}"
        assert all_approved is False
        assert any_cr is True

    def test_existing_record_cr_then_new_commit(self):
        """Existing record was CHANGES_REQUESTED on old SHA. New commit pushed → NEEDS_REVIEW."""
        pr_detail = load_fixture("scenario_pr_detail_cr_new_commit.json")
        item_id = make_item_id(REPO, ItemType.PR, 69)
        existing = _make_existing(item_id)

        status, action, all_approved, any_cr, decisions, last_rev_sha = determine_pr_action(
            pr_detail,
            existing=existing,
            required_reviewers=REQUIRED_REVIEWERS,
            approval_rules=APPROVAL_RULES,
        )
        assert status == Status.PENDING_REVIEW, f"Expected PENDING_REVIEW, got {status}"
        assert action == Action.NEEDS_REVIEW, f"Expected NEEDS_REVIEW, got {action}"

    def test_existing_record_cr_on_current_head_needs_fix(self):
        """Existing record has old last_reviewed_sha, new review on HEAD → NEEDS_FIX.

        Scenario: dev pushed new commit (85c55d3), reviewer then reviewed that
        exact commit and requested changes. The review is on the current HEAD,
        so sha_matches should be True and action should be NEEDS_FIX.
        """
        pr_detail = load_fixture("scenario_pr_detail_cr_on_head.json")
        item_id = make_item_id(REPO, ItemType.PR, 69)
        existing = _make_existing(item_id)  # last_reviewed_sha=OLD_SHA

        status, action, all_approved, any_cr, decisions, last_rev_sha = determine_pr_action(
            pr_detail,
            existing=existing,
            required_reviewers=REQUIRED_REVIEWERS,
            approval_rules=APPROVAL_RULES,
        )
        assert status == Status.CHANGES_REQUESTED, f"Expected CHANGES_REQUESTED, got {status}"
        assert action == Action.NEEDS_FIX, f"Expected NEEDS_FIX, got {action}"
        assert all_approved is False
        assert any_cr is True
        assert last_rev_sha == NEW_SHA

    def test_existing_with_fix_dispatched_new_commit(self):
        """After fix was dispatched on old SHA, new commit pushed → NEEDS_REVIEW (not deduped)."""
        pr_detail = load_fixture("scenario_pr_detail_cr_new_commit.json")
        item_id = make_item_id(REPO, ItemType.PR, 69)
        existing = _make_existing(item_id, last_fix_dispatch_sha=OLD_SHA)

        status, action, all_approved, any_cr, decisions, last_rev_sha = determine_pr_action(
            pr_detail,
            existing=existing,
            required_reviewers=REQUIRED_REVIEWERS,
            approval_rules=APPROVAL_RULES,
        )
        assert status == Status.PENDING_REVIEW
        assert action == Action.NEEDS_REVIEW


# ── Integration test: sync_repo ──────────────────────────────────────────────


class TestSyncRepoPR69:
    """Integration test: sync_repo should produce PENDING_REVIEW / NEEDS_REVIEW for PR #69."""

    def test_sync_pr69_first_sync(self, tmp_db):
        """First sync of PR #69 with stale CHANGES_REQUESTED review → NEEDS_REVIEW."""
        pr_list = [
            {
                "number": 69,
                "title": "Harden auth flow for internet exposure",
                "state": "OPEN",
                "createdAt": "2026-02-20T18:06:46Z",
                "updatedAt": "2026-02-20T19:55:29Z",
                "author": {"login": "miller46"},
                "headRefName": "feature/issue-68-harden-auth-internet-exposure",
                "body": "Harden auth flow for internet exposure. Fixes #68",
            }
        ]
        pr_detail = load_fixture("scenario_pr_detail_cr_new_commit.json")

        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=[]),
            patch("github_sync.fetch_prs", return_value=pr_list),
            patch("github_sync.fetch_pr_detail", return_value=pr_detail),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=APPROVAL_RULES),
        ):
            count = sync_repo(REPO)

        assert count == 1
        items = _read_items(tmp_db)
        pr = items[0]
        assert pr["status"] == "pending_review", f"Expected pending_review, got {pr['status']}"
        assert pr["action"] == "needs_review", f"Expected needs_review, got {pr['action']}"
        assert pr["head_sha"] == NEW_SHA
        assert pr["sha_matches_review"] == 0
        assert pr["any_changes_requested"] == 1

    def test_sync_pr69_after_previous_cr_sync(self, tmp_db):
        """Second sync: previous sync saw CHANGES_REQUESTED on old SHA, now new commit.
        Should transition from CHANGES_REQUESTED/NEEDS_FIX → PENDING_REVIEW/NEEDS_REVIEW."""
        # Pre-seed DB with existing state from when head was old_sha
        item_id = make_item_id(REPO, ItemType.PR, 69)
        existing = _make_existing(item_id)
        with patch("github_sync.DB_PATH", tmp_db):
            save_item(existing)

        pr_list = [
            {
                "number": 69,
                "title": "Harden auth flow for internet exposure",
                "state": "OPEN",
                "createdAt": "2026-02-20T18:06:46Z",
                "updatedAt": "2026-02-20T19:55:29Z",
                "author": {"login": "miller46"},
                "headRefName": "feature/issue-68-harden-auth-internet-exposure",
                "body": "Harden auth flow for internet exposure. Fixes #68",
            }
        ]
        pr_detail = load_fixture("scenario_pr_detail_cr_new_commit.json")

        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=[]),
            patch("github_sync.fetch_prs", return_value=pr_list),
            patch("github_sync.fetch_pr_detail", return_value=pr_detail),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=APPROVAL_RULES),
        ):
            count = sync_repo(REPO)

        items = _read_items(tmp_db)
        pr = next(i for i in items if i["number"] == 69)
        assert pr["status"] == "pending_review", f"Expected pending_review, got {pr['status']}"
        assert pr["action"] == "needs_review", f"Expected needs_review, got {pr['action']}"
        assert pr["head_sha"] == NEW_SHA
        assert pr["sha_matches_review"] == 0
