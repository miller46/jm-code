"""Tests for sync_repo covering basic workflow scenarios.

Each scenario uses minimal fixture files from tests/fixtures/scenario_*.json.
Tests verify that sync_repo produces correct DB state for the fundamental
workflow paths: empty repos, issues, PRs at various review stages,
reconciliation of closed/merged PRs.
"""

import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from github_sync import (
    Action,
    ItemType,
    Status,
    WorkflowItem,
    make_item_id,
    save_item,
    sync_repo,
    SCHEMA,
    MAX_ITERATIONS,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPO = "test-org/test-repo"
REQUIRED_REVIEWERS = ["code-snob", "architect"]
HEAD_SHA = "aaa111bbb222ccc333ddd444eee555fff66677788"


# ── Helpers ──────────────────────────────────────────────────────────────────

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


def _read_items(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM workflow_items ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _make_existing(item_id, **kwargs):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    defaults = dict(
        id=item_id,
        type=ItemType.PR,
        repo=REPO,
        number=200,
        title="Implement auth feature",
        github_state="open",
        repo_scoped_id=item_id,
        status=Status.PENDING_REVIEW,
        action=Action.NEEDS_REVIEW,
        head_sha=HEAD_SHA,
        head_ref_name=None,
        last_reviewed_sha=None,
        reviews={},
        all_reviewers_approved=False,
        any_changes_requested=False,
        sha_matches_review=False,
        has_conflicts=False,
        last_review_dispatch_sha=None,
        last_fix_dispatch_sha=None,
        last_merge_dispatch_sha=None,
        last_conflict_dispatch_sha=None,
        last_head_sha_seen=HEAD_SHA,
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


def _sync(tmp_db, issues, prs, pr_detail=None):
    """Run sync_repo with standard mocks. Returns item count."""
    patches = {
        "github_sync.DB_PATH": tmp_db,
        "github_sync.fetch_issues": lambda _: issues,
        "github_sync.fetch_prs": lambda _: prs,
        "github_sync.load_reviewers_for_repo": lambda _: REQUIRED_REVIEWERS,
        "github_sync.load_approval_rules_for_repo": lambda _: None,
    }
    if pr_detail is not None:
        patches["github_sync.fetch_pr_detail"] = lambda *a, **kw: pr_detail

    with patch.multiple("github_sync", **{
        k.split(".")[-1]: v for k, v in patches.items()
    }):
        with patch("github_sync.DB_PATH", tmp_db):
            return sync_repo(REPO)


# ── Scenario 1: Empty repo ─────────────────────────────────────────────────


class TestEmptyRepo:
    """No issues, no PRs → nothing in DB."""

    def test_sync_empty_repo(self, tmp_db):
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=[]),
            patch("github_sync.fetch_prs", return_value=[]),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=None),
        ):
            count = sync_repo(REPO)

        assert count == 0
        assert _read_items(tmp_db) == []


# ── Scenario 2: One open issue, no PRs ──────────────────────────────────────


class TestSingleOpenIssue:
    """Open issue with no linked PR → OPEN / NEEDS_DEV."""

    def test_sync_open_issue(self, tmp_db):
        issues = load_fixture("scenario_open_issue.json")
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=issues),
            patch("github_sync.fetch_prs", return_value=[]),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=None),
        ):
            count = sync_repo(REPO)

        assert count == 1
        items = _read_items(tmp_db)
        assert len(items) == 1
        item = items[0]
        assert item["type"] == "issue"
        assert item["number"] == 100
        assert item["status"] == "open"
        assert item["action"] == "needs_dev"


# ── Scenario 3: One closed issue ────────────────────────────────────────────


class TestSingleClosedIssue:
    """Closed issue → CLOSED / NONE."""

    def test_sync_closed_issue(self, tmp_db):
        issues = load_fixture("scenario_closed_issue.json")
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=issues),
            patch("github_sync.fetch_prs", return_value=[]),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=None),
        ):
            count = sync_repo(REPO)

        assert count == 1
        items = _read_items(tmp_db)
        assert len(items) == 1
        assert items[0]["status"] == "closed"
        assert items[0]["action"] == "none"


# ── Scenario 4: PR with no reviews ──────────────────────────────────────────


class TestPrNoReviews:
    """Open PR with no reviews → PENDING_REVIEW / NEEDS_REVIEW."""

    def test_sync_pr_no_reviews(self, tmp_db):
        pr_list = load_fixture("scenario_pr_list.json")
        pr_detail = load_fixture("scenario_pr_detail_no_reviews.json")
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=[]),
            patch("github_sync.fetch_prs", return_value=pr_list),
            patch("github_sync.fetch_pr_detail", return_value=pr_detail),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=None),
        ):
            count = sync_repo(REPO)

        assert count == 1
        items = _read_items(tmp_db)
        pr = items[0]
        assert pr["type"] == "pr"
        assert pr["number"] == 200
        assert pr["status"] == "pending_review"
        assert pr["action"] == "needs_review"
        assert pr["head_sha"] == HEAD_SHA
        assert pr["all_reviewers_approved"] == 0
        assert pr["any_changes_requested"] == 0


# ── Scenario 5: Issue with linked PR ────────────────────────────────────────


class TestIssueWithLinkedPr:
    """Open issue + PR that 'Closes #100' →
    issue: PR_CREATED/NONE, PR: PENDING_REVIEW/NEEDS_REVIEW."""

    def test_sync_issue_linked_to_pr(self, tmp_db):
        issues = load_fixture("scenario_open_issue.json")
        pr_list = load_fixture("scenario_pr_list_linked.json")
        pr_detail = load_fixture("scenario_pr_detail_no_reviews.json")
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=issues),
            patch("github_sync.fetch_prs", return_value=pr_list),
            patch("github_sync.fetch_pr_detail", return_value=pr_detail),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=None),
        ):
            count = sync_repo(REPO)

        assert count == 2
        items = _read_items(tmp_db)
        issue = next(i for i in items if i["type"] == "issue")
        pr = next(i for i in items if i["type"] == "pr")

        assert issue["status"] == "pr_created"
        assert issue["action"] == "none"
        assert pr["status"] == "pending_review"
        assert pr["action"] == "needs_review"


# ── Scenario 6: PR all approved → ready to merge ────────────────────────────


class TestPrAllApproved:
    """All required reviewers approved on current SHA → APPROVED / READY_TO_MERGE."""

    def test_sync_pr_all_approved(self, tmp_db):
        pr_list = load_fixture("scenario_pr_list.json")
        pr_detail = load_fixture("scenario_pr_detail_all_approved.json")
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=[]),
            patch("github_sync.fetch_prs", return_value=pr_list),
            patch("github_sync.fetch_pr_detail", return_value=pr_detail),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=None),
        ):
            count = sync_repo(REPO)

        items = _read_items(tmp_db)
        pr = items[0]
        assert pr["status"] == "approved"
        assert pr["action"] == "ready_to_merge"
        assert pr["all_reviewers_approved"] == 1
        assert pr["sha_matches_review"] == 1


# ── Scenario 7: PR changes requested → needs fix ────────────────────────────


class TestPrChangesRequested:
    """One reviewer requested changes on current SHA → CHANGES_REQUESTED / NEEDS_FIX."""

    def test_sync_pr_changes_requested(self, tmp_db):
        pr_list = load_fixture("scenario_pr_list.json")
        pr_detail = load_fixture("scenario_pr_detail_changes_requested.json")
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=[]),
            patch("github_sync.fetch_prs", return_value=pr_list),
            patch("github_sync.fetch_pr_detail", return_value=pr_detail),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=None),
        ):
            count = sync_repo(REPO)

        items = _read_items(tmp_db)
        pr = items[0]
        assert pr["status"] == "changes_requested"
        assert pr["action"] == "needs_fix"
        assert pr["any_changes_requested"] == 1


# ── Scenario 8: PR partial approval (one reviewer, other missing) ───────────


class TestPrPartialApproval:
    """Only one reviewer approved, other hasn't reviewed → PENDING_REVIEW / NEEDS_REVIEW."""

    def test_sync_pr_partial_approval(self, tmp_db):
        pr_list = load_fixture("scenario_pr_list.json")
        pr_detail = load_fixture("scenario_pr_detail_partial_approval.json")
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=[]),
            patch("github_sync.fetch_prs", return_value=pr_list),
            patch("github_sync.fetch_pr_detail", return_value=pr_detail),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=None),
        ):
            count = sync_repo(REPO)

        items = _read_items(tmp_db)
        pr = items[0]
        assert pr["status"] == "pending_review"
        assert pr["action"] == "needs_review"
        assert pr["all_reviewers_approved"] == 0


# ── Scenario 9: PR approved but has merge conflicts ─────────────────────────


class TestPrApprovedWithConflicts:
    """All approved but merge conflicts → CONFLICTING / NEEDS_CONFLICT_RESOLUTION."""

    def test_sync_pr_approved_conflicts(self, tmp_db):
        pr_list = load_fixture("scenario_pr_list.json")
        pr_detail = load_fixture("scenario_pr_detail_approved_conflicts.json")
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=[]),
            patch("github_sync.fetch_prs", return_value=pr_list),
            patch("github_sync.fetch_pr_detail", return_value=pr_detail),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=None),
        ):
            count = sync_repo(REPO)

        items = _read_items(tmp_db)
        pr = items[0]
        assert pr["status"] == "conflicting"
        assert pr["action"] == "needs_conflict_resolution"
        assert pr["has_conflicts"] == 1


# ── Scenario 10: PR conflicts but not approved ──────────────────────────────


class TestPrConflictsNotApproved:
    """Conflicts but no approvals → CONFLICTING / NEEDS_CONFLICT_RESOLUTION."""

    def test_sync_pr_conflicts_no_approval(self, tmp_db):
        pr_list = load_fixture("scenario_pr_list.json")
        pr_detail = load_fixture("scenario_pr_detail_conflicts_no_approval.json")
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=[]),
            patch("github_sync.fetch_prs", return_value=pr_list),
            patch("github_sync.fetch_pr_detail", return_value=pr_detail),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=None),
        ):
            count = sync_repo(REPO)

        items = _read_items(tmp_db)
        pr = items[0]
        assert pr["status"] == "conflicting"
        assert pr["action"] == "needs_conflict_resolution"
        assert pr["has_conflicts"] == 1
        assert pr["all_reviewers_approved"] == 0


# ── Scenario 11: Merged PR ──────────────────────────────────────────────────


class TestPrMerged:
    """Merged PR → MERGED / NONE."""

    def test_sync_pr_merged(self, tmp_db):
        pr_list = load_fixture("scenario_pr_list.json")
        pr_detail = load_fixture("scenario_pr_detail_merged.json")
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=[]),
            patch("github_sync.fetch_prs", return_value=pr_list),
            patch("github_sync.fetch_pr_detail", return_value=pr_detail),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=None),
        ):
            count = sync_repo(REPO)

        items = _read_items(tmp_db)
        pr = items[0]
        assert pr["status"] == "merged"
        assert pr["action"] == "none"


# ── Scenario 12: New commit after review (stale reviews) ────────────────────


class TestPrNewCommitAfterReview:
    """Reviews on old SHA, new commit pushed → PENDING_REVIEW / NEEDS_REVIEW.
    This is the common case after a dev pushes a fix: the old reviews are
    stale and the PR needs re-review on the new code."""

    def test_sync_pr_stale_reviews(self, tmp_db):
        pr_list = load_fixture("scenario_pr_list.json")
        pr_detail = load_fixture("scenario_pr_detail_reviews_stale.json")
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=[]),
            patch("github_sync.fetch_prs", return_value=pr_list),
            patch("github_sync.fetch_pr_detail", return_value=pr_detail),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=None),
        ):
            count = sync_repo(REPO)

        items = _read_items(tmp_db)
        pr = items[0]
        assert pr["status"] == "pending_review"
        assert pr["action"] == "needs_review"
        # Reviews on old SHA, head is new → SHA should not match
        assert pr["sha_matches_review"] == 0


# ── Scenario 13: Reconciliation — PR was open, now closed (not merged) ──────


class TestReconcileClosedPr:
    """PR in DB as open, not in open list anymore, GitHub says CLOSED → closed/none."""

    def test_sync_reconcile_closed(self, tmp_db):
        # Pre-seed DB with an "open" PR
        existing_id = make_item_id(REPO, ItemType.PR, 200)
        existing = _make_existing(existing_id)
        with patch("github_sync.DB_PATH", tmp_db):
            save_item(existing)

        closed_detail = load_fixture("scenario_pr_detail_closed.json")
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=[]),
            patch("github_sync.fetch_prs", return_value=[]),  # PR not in open list
            patch("github_sync.fetch_pr_detail", return_value=closed_detail),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=None),
        ):
            count = sync_repo(REPO)

        items = _read_items(tmp_db)
        pr = next(i for i in items if i["number"] == 200)
        assert pr["github_state"] == "closed"
        assert pr["status"] == "closed"
        assert pr["action"] == "none"


# ── Scenario 14: Reconciliation — PR was open, now merged ───────────────────


class TestReconcileMergedPr:
    """PR in DB as open, not in open list anymore, GitHub says MERGED → merged/none."""

    def test_sync_reconcile_merged(self, tmp_db):
        existing_id = make_item_id(REPO, ItemType.PR, 200)
        existing = _make_existing(existing_id)
        with patch("github_sync.DB_PATH", tmp_db):
            save_item(existing)

        merged_detail = load_fixture("scenario_pr_detail_merged.json")
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=[]),
            patch("github_sync.fetch_prs", return_value=[]),
            patch("github_sync.fetch_pr_detail", return_value=merged_detail),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=None),
        ):
            count = sync_repo(REPO)

        items = _read_items(tmp_db)
        pr = next(i for i in items if i["number"] == 200)
        assert pr["github_state"] == "merged"
        assert pr["status"] == "merged"
        assert pr["action"] == "none"


# ── Scenario 15: Full lifecycle — issue → PR → review → fix → approve → merge


class TestFullLifecycle:
    """Walk through the complete workflow in sequential syncs:
    1. Open issue → needs_dev
    2. PR opened → issue: pr_created, PR: needs_review
    3. Review with changes_requested → needs_fix
    4. New commit → needs_review again
    5. All approved → ready_to_merge
    """

    def test_lifecycle_issue_to_merge(self, tmp_db):
        issues = load_fixture("scenario_open_issue.json")
        sha_v1 = HEAD_SHA  # initial commit
        sha_v2 = "bbb222ccc333ddd444eee555fff666777aaabbb111"  # fix commit

        # Step 1: Open issue, no PRs
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=issues),
            patch("github_sync.fetch_prs", return_value=[]),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=None),
        ):
            sync_repo(REPO)

        items = _read_items(tmp_db)
        assert len(items) == 1
        assert items[0]["status"] == "open"
        assert items[0]["action"] == "needs_dev"

        # Step 2: PR opened, linked to issue (head = sha_v1, no reviews)
        pr_list = load_fixture("scenario_pr_list_linked.json")
        pr_detail_no_rev = load_fixture("scenario_pr_detail_no_reviews.json")
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=issues),
            patch("github_sync.fetch_prs", return_value=pr_list),
            patch("github_sync.fetch_pr_detail", return_value=pr_detail_no_rev),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=None),
        ):
            sync_repo(REPO)

        items = _read_items(tmp_db)
        issue = next(i for i in items if i["type"] == "issue")
        pr = next(i for i in items if i["type"] == "pr")
        assert issue["status"] == "pr_created"
        assert pr["status"] == "pending_review"
        assert pr["action"] == "needs_review"

        # Step 3: Review with changes_requested on sha_v1
        pr_detail_cr = load_fixture("scenario_pr_detail_changes_requested.json")
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=issues),
            patch("github_sync.fetch_prs", return_value=pr_list),
            patch("github_sync.fetch_pr_detail", return_value=pr_detail_cr),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=None),
        ):
            sync_repo(REPO)

        items = _read_items(tmp_db)
        pr = next(i for i in items if i["type"] == "pr")
        assert pr["status"] == "changes_requested"
        assert pr["action"] == "needs_fix"

        # Step 4: Dev pushes fix → head changes to sha_v2, reviews still on sha_v1
        pr_detail_v2_stale = {
            "number": 200,
            "title": "Implement auth feature",
            "state": "OPEN",
            "headRefOid": sha_v2,
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "reviews": [
                {
                    "author": {"login": "architect"},
                    "state": "CHANGES_REQUESTED",
                    "commit": {"oid": sha_v1},
                    "body": "Needs error handling improvements.",
                    "submittedAt": "2026-02-18T12:00:00Z",
                },
                {
                    "author": {"login": "code-snob"},
                    "state": "APPROVED",
                    "commit": {"oid": sha_v1},
                    "body": "Code quality looks good.",
                    "submittedAt": "2026-02-18T12:01:00Z",
                },
            ],
            "createdAt": "2026-02-18T11:00:00Z",
            "updatedAt": "2026-02-18T15:00:00Z",
        }
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=issues),
            patch("github_sync.fetch_prs", return_value=pr_list),
            patch("github_sync.fetch_pr_detail", return_value=pr_detail_v2_stale),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=None),
        ):
            sync_repo(REPO)

        items = _read_items(tmp_db)
        pr = next(i for i in items if i["type"] == "pr")
        assert pr["status"] == "pending_review"
        assert pr["action"] == "needs_review"
        assert pr["head_sha"] == sha_v2

        # Step 5: All reviewers approve on sha_v2 → ready to merge
        pr_detail_v2_approved = {
            "number": 200,
            "title": "Implement auth feature",
            "state": "OPEN",
            "headRefOid": sha_v2,
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "reviews": [
                {
                    "author": {"login": "code-snob"},
                    "state": "APPROVED",
                    "commit": {"oid": sha_v2},
                    "body": "LGTM after fix.",
                    "submittedAt": "2026-02-18T16:00:00Z",
                },
                {
                    "author": {"login": "architect"},
                    "state": "APPROVED",
                    "commit": {"oid": sha_v2},
                    "body": "Error handling looks good now.",
                    "submittedAt": "2026-02-18T16:01:00Z",
                },
            ],
            "createdAt": "2026-02-18T11:00:00Z",
            "updatedAt": "2026-02-18T16:01:00Z",
        }
        with (
            patch("github_sync.DB_PATH", tmp_db),
            patch("github_sync.fetch_issues", return_value=issues),
            patch("github_sync.fetch_prs", return_value=pr_list),
            patch("github_sync.fetch_pr_detail", return_value=pr_detail_v2_approved),
            patch("github_sync.load_reviewers_for_repo", return_value=REQUIRED_REVIEWERS),
            patch("github_sync.load_approval_rules_for_repo", return_value=None),
        ):
            sync_repo(REPO)

        items = _read_items(tmp_db)
        pr = next(i for i in items if i["type"] == "pr")
        assert pr["status"] == "approved"
        assert pr["action"] == "ready_to_merge"
        assert pr["all_reviewers_approved"] == 1
        assert pr["head_sha"] == sha_v2
