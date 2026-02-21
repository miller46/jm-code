"""Tests for github_sync state machine pure functions."""

import sqlite3
import os
import sys
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

# Add parent scripts dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from github_sync import (
    make_item_id,
    ItemType,
    Action,
    Status,
    evaluate_reviews,
    determine_pr_action,
    apply_dispatch_dedupe,
    update_iteration,
    acquire_lock,
    release_lock,
    cleanup_expired_locks,
    mark_dispatched,
    WorkflowItem,
    find_linked_prs,
    save_item,
    SCHEMA,
    MAX_ITERATIONS,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

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
    last_reviewed_sha=None,
    last_review_dispatch_sha=None,
    last_fix_dispatch_sha=None,
    last_merge_dispatch_sha=None,
    last_conflict_dispatch_sha=None,
    last_status_fix_dispatch_sha=None,
) -> WorkflowItem:
    """Helper to build a minimal WorkflowItem for testing."""
    now = datetime.now(timezone.utc).isoformat()
    return WorkflowItem(
        id=item_id,
        type=ItemType.PR,
        repo="miller46/jm-api",
        number=10,
        title="test PR",
        github_state="open",
        repo_scoped_id=item_id,
        status=Status.PENDING_REVIEW,
        action=Action.NEEDS_REVIEW,
        head_sha="abc123",
        head_ref_name=None,
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
        last_status_fix_dispatch_sha=last_status_fix_dispatch_sha,
        last_head_sha_seen="abc123",
        status_check_rollup=None,
        iteration=iteration,
        max_iterations=MAX_ITERATIONS,
        assigned_agent=None,
        lock_expires=None,
        created_at=now,
        updated_at=now,
        last_sync=now,
    )


def _make_review(author: str, state: str, sha: str = "abc123", body: str = "", submitted_at: str = None) -> dict:
    return {
        "author": {"login": author},
        "state": state,
        "commit": {"oid": sha},
        "body": body,
        "submittedAt": submitted_at or datetime.now(timezone.utc).isoformat(),
    }


# ── 1. test_repo_scoped_id_uniqueness ─────────────────────────────────────────

class TestRepoScopedId:
    def test_different_repos_same_number(self):
        id1 = make_item_id("alice/foo", ItemType.PR, 10)
        id2 = make_item_id("bob/bar", ItemType.PR, 10)
        assert id1 != id2

    def test_same_repo_different_types(self):
        id_issue = make_item_id("alice/foo", ItemType.ISSUE, 10)
        id_pr = make_item_id("alice/foo", ItemType.PR, 10)
        assert id_issue != id_pr

    def test_format(self):
        assert make_item_id("miller46/jm-api", ItemType.PR, 56) == "miller46/jm-api#pr#56"
        assert make_item_id("miller46/jm-api", ItemType.ISSUE, 48) == "miller46/jm-api#issue#48"


# ── 2. test_latest_review_per_reviewer_wins ────────────────────────────────────

class TestEvaluateReviews:
    def test_latest_review_wins(self):
        reviews = [
            _make_review("code-snob", "CHANGES_REQUESTED", "sha1"),
            _make_review("code-snob", "APPROVED", "sha2"),
            _make_review("architect", "APPROVED", "sha2"),
        ]
        ev = evaluate_reviews(
            reviews,
            required_reviewers=["code-snob", "architect"],
        )
        assert ev.latest_decision_by_reviewer["code-snob"] == "APPROVED"
        assert ev.latest_decision_by_reviewer["architect"] == "APPROVED"
        assert ev.all_required_approved is True
        assert ev.any_changes_requested is False

    def test_changes_requested_blocks_approval(self):
        reviews = [
            _make_review("code-snob", "APPROVED", "sha1"),
            _make_review("architect", "CHANGES_REQUESTED", "sha1"),
        ]
        ev = evaluate_reviews(
            reviews,
            required_reviewers=["code-snob", "architect"],
        )
        assert ev.all_required_approved is False
        assert ev.any_changes_requested is True

    def test_missing_reviewer_not_approved(self):
        reviews = [
            _make_review("code-snob", "APPROVED", "sha1"),
        ]
        ev = evaluate_reviews(
            reviews,
            required_reviewers=["code-snob", "architect"],
        )
        assert ev.all_required_approved is False

    def test_latest_review_sha_tracked(self):
        reviews = [
            _make_review("code-snob", "APPROVED", "sha_old"),
            _make_review("architect", "APPROVED", "sha_new"),
        ]
        ev = evaluate_reviews(reviews, required_reviewers=["code-snob", "architect"])
        assert ev.latest_review_sha == "sha_new"


# ── 3. test_changes_requested_requires_fix_when_no_new_commit ──────────────────

class TestDeterminePrAction:
    def test_changes_requested_same_sha_needs_fix(self):
        """When changes requested and no new commit, action = NEEDS_FIX."""
        reviews = [
            _make_review("code-snob", "CHANGES_REQUESTED", "abc123"),
            _make_review("architect", "APPROVED", "abc123"),
        ]
        pr_detail = {
            "state": "OPEN",
            "headRefOid": "abc123",
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "reviews": reviews,
        }
        existing = _make_existing(last_reviewed_sha="abc123")
        status, action, *_ = determine_pr_action(
            pr_detail, existing, required_reviewers=["code-snob", "architect"]
        )
        assert status == Status.CHANGES_REQUESTED
        assert action == Action.NEEDS_FIX

    # ── 4. test_new_commit_after_changes_requested_requires_review ─────────

    def test_new_commit_after_changes_requested_needs_review(self):
        """After changes requested + new commit pushed, action = NEEDS_REVIEW."""
        reviews = [
            _make_review("code-snob", "CHANGES_REQUESTED", "old_sha"),
            _make_review("architect", "APPROVED", "old_sha"),
        ]
        pr_detail = {
            "state": "OPEN",
            "headRefOid": "new_sha",
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "reviews": reviews,
        }
        existing = _make_existing(last_reviewed_sha="old_sha")
        status, action, *_ = determine_pr_action(
            pr_detail, existing, required_reviewers=["code-snob", "architect"]
        )
        assert status == Status.PENDING_REVIEW
        assert action == Action.NEEDS_REVIEW

    # ── 5. test_approval_on_current_sha_ready_to_merge ─────────────────────

    def test_all_approved_current_sha_ready_to_merge(self):
        """All required approved on current SHA → READY_TO_MERGE."""
        reviews = [
            _make_review("code-snob", "APPROVED", "abc123"),
            _make_review("architect", "APPROVED", "abc123"),
        ]
        pr_detail = {
            "state": "OPEN",
            "headRefOid": "abc123",
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "reviews": reviews,
        }
        existing = _make_existing(last_reviewed_sha="abc123")
        status, action, *_ = determine_pr_action(
            pr_detail, existing, required_reviewers=["code-snob", "architect"]
        )
        assert status == Status.APPROVED
        assert action == Action.READY_TO_MERGE

    def test_merged_pr(self):
        pr_detail = {
            "state": "MERGED",
            "headRefOid": "abc123",
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "reviews": [],
        }
        status, action, *_ = determine_pr_action(
            pr_detail, None, required_reviewers=["code-snob", "architect"]
        )
        assert status == Status.MERGED
        assert action == Action.NONE

    def test_conflicts_with_approval_needs_resolution(self):
        reviews = [
            _make_review("code-snob", "APPROVED", "abc123"),
            _make_review("architect", "APPROVED", "abc123"),
        ]
        pr_detail = {
            "state": "OPEN",
            "headRefOid": "abc123",
            "mergeable": "CONFLICTING",
            "mergeStateStatus": "DIRTY",
            "reviews": reviews,
        }
        existing = _make_existing(last_reviewed_sha="abc123")
        status, action, *_ = determine_pr_action(
            pr_detail, existing, required_reviewers=["code-snob", "architect"]
        )
        assert status == Status.CONFLICTING
        assert action == Action.NEEDS_CONFLICT_RESOLUTION

    def test_conflicts_without_approval_needs_resolution(self):
        """PR #77 regression: conflicts with no reviews should still need resolution."""
        pr_detail = {
            "state": "OPEN",
            "headRefOid": "6f6f5f7aa565855ee475813248861fb03639a4c6",
            "mergeable": "CONFLICTING",
            "mergeStateStatus": "DIRTY",
            "reviews": [],
        }
        status, action, *_ = determine_pr_action(
            pr_detail, None, required_reviewers=["code-snob", "architect"]
        )
        assert status == Status.CONFLICTING
        assert action == Action.NEEDS_CONFLICT_RESOLUTION


# ── 6. test_dedupe_prevents_double_review_fix_merge ────────────────────────────

class TestDispatchDedupe:
    def test_review_already_dispatched(self):
        result = apply_dispatch_dedupe(
            action=Action.NEEDS_REVIEW,
            head_sha="abc123",
            last_review_dispatch_sha="abc123",
            last_fix_dispatch_sha=None,
            last_merge_dispatch_sha=None,
        )
        assert result == Action.NONE

    def test_fix_already_dispatched(self):
        result = apply_dispatch_dedupe(
            action=Action.NEEDS_FIX,
            head_sha="abc123",
            last_review_dispatch_sha=None,
            last_fix_dispatch_sha="abc123",
            last_merge_dispatch_sha=None,
        )
        assert result == Action.NONE

    def test_merge_already_dispatched(self):
        result = apply_dispatch_dedupe(
            action=Action.READY_TO_MERGE,
            head_sha="abc123",
            last_review_dispatch_sha=None,
            last_fix_dispatch_sha=None,
            last_merge_dispatch_sha="abc123",
        )
        assert result == Action.NONE

    def test_new_sha_allows_dispatch(self):
        result = apply_dispatch_dedupe(
            action=Action.NEEDS_REVIEW,
            head_sha="new_sha",
            last_review_dispatch_sha="old_sha",
            last_fix_dispatch_sha=None,
            last_merge_dispatch_sha=None,
        )
        assert result == Action.NEEDS_REVIEW

    def test_unrelated_action_passes_through(self):
        result = apply_dispatch_dedupe(
            action=Action.NONE,
            head_sha="abc123",
            last_review_dispatch_sha="abc123",
            last_fix_dispatch_sha=None,
            last_merge_dispatch_sha=None,
        )
        assert result == Action.NONE


# ── 7. test_iteration_increments_only_on_new_fix_dispatch ──────────────────────

class TestIteration:
    """update_iteration no longer increments; it only enforces the cap.
    Actual increment happens in mark_dispatched(dispatch_type='fix')."""

    def test_no_increment_in_sync_path(self):
        existing = _make_existing(iteration=1, last_fix_dispatch_sha="old_sha")
        iteration, action = update_iteration(
            existing, Action.NEEDS_FIX, max_iterations=MAX_ITERATIONS,
        )
        assert iteration == 1  # unchanged — increment is in mark_dispatched
        assert action == Action.NEEDS_FIX

    # ── 8. test_max_iterations_reached_blocks_further_fix ──────────────────

    def test_max_iterations_blocks(self):
        existing = _make_existing(iteration=MAX_ITERATIONS, last_fix_dispatch_sha="old_sha")
        iteration, action = update_iteration(
            existing, Action.NEEDS_FIX, max_iterations=MAX_ITERATIONS,
        )
        assert iteration == MAX_ITERATIONS
        assert action == Action.MAX_ITERATIONS_REACHED

    def test_non_fix_action_unchanged(self):
        existing = _make_existing(iteration=2)
        iteration, action = update_iteration(
            existing, Action.NEEDS_REVIEW, max_iterations=MAX_ITERATIONS,
        )
        assert iteration == 2
        assert action == Action.NEEDS_REVIEW


# ── 9. test_lock_acquire_prevents_overlap ──────────────────────────────────────

class TestLocks:
    def test_acquire_and_block(self, tmp_db):
        with patch("github_sync.DB_PATH", tmp_db):
            assert acquire_lock("sync", "proc-1", 600) is True
            assert acquire_lock("sync", "proc-2", 600) is False

    # ── 10. test_lock_cleanup_removes_expired ──────────────────────────────

    def test_expired_lock_can_be_reacquired(self, tmp_db):
        with patch("github_sync.DB_PATH", tmp_db):
            # Insert an already-expired lock
            conn = sqlite3.connect(tmp_db)
            expired = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
            conn.execute(
                "INSERT INTO locks (name, owner, expires_at) VALUES (?, ?, ?)",
                ("sync", "old-proc", expired),
            )
            conn.commit()
            conn.close()

            # Should be able to acquire because old one is expired
            assert acquire_lock("sync", "new-proc", 600) is True

    def test_release_lock(self, tmp_db):
        with patch("github_sync.DB_PATH", tmp_db):
            acquire_lock("sync", "proc-1", 600)
            assert release_lock("sync", "proc-1") is True
            # Now another process can acquire
            assert acquire_lock("sync", "proc-2", 600) is True


# ── 11. test_find_linked_prs (tightened) ───────────────────────────────────────

class TestFindLinkedPrs:
    def test_closes_keyword_matches(self):
        prs = [{"number": 5, "body": "This closes #10", "title": "fix stuff"}]
        assert find_linked_prs(prs, 10) == 5

    def test_fixes_keyword_matches(self):
        prs = [{"number": 5, "body": "fixes #10", "title": "fix stuff"}]
        assert find_linked_prs(prs, 10) == 5

    def test_resolves_keyword_matches(self):
        prs = [{"number": 5, "body": "resolves #10", "title": "fix stuff"}]
        assert find_linked_prs(prs, 10) == 5

    def test_plain_hash_does_not_match(self):
        """Plain #N without keyword should NOT link (per fix_plan item 9)."""
        prs = [{"number": 5, "body": "see #10 for context", "title": "unrelated"}]
        assert find_linked_prs(prs, 10) is None

    def test_addresses_does_not_match(self):
        """'addresses' removed per fix_plan item 9."""
        prs = [{"number": 5, "body": "addresses #10", "title": "stuff"}]
        assert find_linked_prs(prs, 10) is None


# ── v2: Deterministic review ordering ─────────────────────────────────────────

class TestDeterministicReviewOrdering:
    def test_latest_by_time_wins_not_list_order(self):
        """Reviews must be sorted by submittedAt; last in time wins."""
        # Intentionally put the later review FIRST in the list
        reviews = [
            _make_review("code-snob", "APPROVED", "sha1",
                         submitted_at="2025-06-02T00:00:00+00:00"),
            _make_review("code-snob", "CHANGES_REQUESTED", "sha1",
                         submitted_at="2025-06-01T00:00:00+00:00"),
            _make_review("architect", "APPROVED", "sha1",
                         submitted_at="2025-06-01T00:00:00+00:00"),
        ]
        ev = evaluate_reviews(reviews, ["code-snob", "architect"])
        # code-snob's latest (by time) is APPROVED (June 2)
        assert ev.latest_decision_by_reviewer["code-snob"] == "APPROVED"
        assert ev.all_required_approved is True


# ── v2: Non-required reviewer reviews are ignored ─────────────────────────────

class TestNonRequiredReviewerIgnored:
    def test_unknown_reviewer_does_not_count(self):
        """Reviews from accounts not in required_reviewers are ignored."""
        reviews = [
            _make_review("random-user", "APPROVED", "sha1"),
            _make_review("architect", "APPROVED", "sha1"),
        ]
        ev = evaluate_reviews(reviews, ["code-snob", "architect"])
        assert "code-snob" not in ev.latest_decision_by_reviewer
        assert ev.all_required_approved is False

    def test_all_reviews_from_non_required_accounts(self):
        """Reviews only from non-required accounts → no approvals."""
        reviews = [
            _make_review("random-bot", "APPROVED", "sha1"),
            _make_review("another-user", "APPROVED", "sha1"),
        ]
        ev = evaluate_reviews(reviews, ["code-snob", "architect"])
        assert ev.all_required_approved is False


# ── v2: Dispatch dedupe marker persistence ─────────────────────────────────────

class TestDispatchPersistence:
    def test_mark_dispatched_review(self, tmp_db):
        """mark_dispatched writes last_review_dispatch_sha to DB."""
        with patch("github_sync.DB_PATH", tmp_db):
            item = _make_existing()
            save_item(item)
            mark_dispatched(item.id, "review", "sha_abc")

            conn = sqlite3.connect(tmp_db)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT last_review_dispatch_sha FROM workflow_items WHERE id = ?",
                (item.id,)
            ).fetchone()
            conn.close()
            assert row["last_review_dispatch_sha"] == "sha_abc"

    def test_mark_dispatched_fix(self, tmp_db):
        """mark_dispatched("fix") writes sha and atomically increments iteration."""
        with patch("github_sync.DB_PATH", tmp_db):
            item = _make_existing()
            item.iteration = 1
            save_item(item)
            mark_dispatched(item.id, "fix", "sha_def")

            conn = sqlite3.connect(tmp_db)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT last_fix_dispatch_sha, iteration FROM workflow_items WHERE id = ?",
                (item.id,)
            ).fetchone()
            conn.close()
            assert row["last_fix_dispatch_sha"] == "sha_def"
            assert row["iteration"] == 2  # was 1, incremented by mark_dispatched

    def test_mark_dispatched_merge(self, tmp_db):
        """mark_dispatched writes last_merge_dispatch_sha."""
        with patch("github_sync.DB_PATH", tmp_db):
            item = _make_existing()
            save_item(item)
            mark_dispatched(item.id, "merge", "sha_ghi")

            conn = sqlite3.connect(tmp_db)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT last_merge_dispatch_sha FROM workflow_items WHERE id = ?",
                (item.id,)
            ).fetchone()
            conn.close()
            assert row["last_merge_dispatch_sha"] == "sha_ghi"

    def test_double_dispatch_blocked_after_mark(self, tmp_db):
        """After marking review dispatched, dedupe blocks same SHA."""
        with patch("github_sync.DB_PATH", tmp_db):
            item = _make_existing()
            save_item(item)
            mark_dispatched(item.id, "review", "sha_abc")

            result = apply_dispatch_dedupe(
                Action.NEEDS_REVIEW, "sha_abc",
                last_review_dispatch_sha="sha_abc",
                last_fix_dispatch_sha=None,
                last_merge_dispatch_sha=None,
            )
            assert result == Action.NONE


# ── v2: Conflict persistence consistency ───────────────────────────────────────

class TestConflictConsistency:
    def test_has_conflicts_includes_dirty_merge_state(self):
        """has_conflicts should be True when mergeStateStatus is DIRTY."""
        reviews = [
            _make_review("code-snob", "APPROVED", "abc123"),
            _make_review("architect", "APPROVED", "abc123"),
        ]
        pr_detail = {
            "state": "OPEN",
            "headRefOid": "abc123",
            "mergeable": "MERGEABLE",      # not CONFLICTING
            "mergeStateStatus": "DIRTY",    # but DIRTY
            "reviews": reviews,
        }
        existing = _make_existing(last_reviewed_sha="abc123")
        status, action, *_ = determine_pr_action(
            pr_detail, existing, ["code-snob", "architect"]
        )
        assert status == Status.CONFLICTING
        assert action == Action.NEEDS_CONFLICT_RESOLUTION


# ── v2: Stale lock cleanup ─────────────────────────────────────────────────────

class TestStaleLockCleanup:
    def test_cleanup_removes_expired(self, tmp_db):
        with patch("github_sync.DB_PATH", tmp_db):
            conn = sqlite3.connect(tmp_db)
            expired = (datetime.now(timezone.utc) - timedelta(seconds=100)).isoformat()
            valid = (datetime.now(timezone.utc) + timedelta(seconds=600)).isoformat()
            conn.execute("INSERT INTO locks VALUES (?, ?, ?)",
                         ("expired_lock", "owner1", expired))
            conn.execute("INSERT INTO locks VALUES (?, ?, ?)",
                         ("valid_lock", "owner2", valid))
            conn.commit()
            conn.close()

            removed = cleanup_expired_locks()
            assert removed == 1

            conn = sqlite3.connect(tmp_db)
            rows = conn.execute("SELECT name FROM locks").fetchall()
            conn.close()
            names = [r[0] for r in rows]
            assert "valid_lock" in names
            assert "expired_lock" not in names


# ── v3: First-sync baseline SHA uses review SHA, not head SHA ──────────────────

class TestFirstSyncBaselineSha:
    def test_no_existing_reviews_on_old_sha_does_not_false_match(self):
        """
        On first sync (no existing row), if reviews were on an older commit,
        baseline should use ev.latest_review_sha, not head_sha.
        This prevents sha_matches=True → needs_fix when it should be needs_review.
        """
        reviews = [
            _make_review("code-snob", "CHANGES_REQUESTED", "old_sha"),
            _make_review("architect", "APPROVED", "old_sha"),
        ]
        pr_detail = {
            "state": "OPEN",
            "headRefOid": "new_head_sha",   # head is newer than review SHA
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "reviews": reviews,
        }
        # existing=None simulates first sync
        status, action, *_ = determine_pr_action(
            pr_detail, None, required_reviewers=["code-snob", "architect"]
        )
        # Because reviews are on old_sha but head is new_head_sha,
        # sha should NOT match → needs_review, not needs_fix
        assert status == Status.PENDING_REVIEW
        assert action == Action.NEEDS_REVIEW

    def test_first_sync_all_approved_on_old_sha(self):
        """First sync: all approved on old SHA, head is newer → needs_review."""
        reviews = [
            _make_review("code-snob", "APPROVED", "old_sha"),
            _make_review("architect", "APPROVED", "old_sha"),
        ]
        pr_detail = {
            "state": "OPEN",
            "headRefOid": "new_head_sha",
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "reviews": reviews,
        }
        status, action, *_ = determine_pr_action(
            pr_detail, None, required_reviewers=["code-snob", "architect"]
        )
        assert status == Status.PENDING_REVIEW
        assert action == Action.NEEDS_REVIEW


# ── v3: Conflict resolution dedupe ─────────────────────────────────────────────

class TestConflictResolutionDedupe:
    def test_conflict_resolution_deduped(self):
        result = apply_dispatch_dedupe(
            action=Action.NEEDS_CONFLICT_RESOLUTION,
            head_sha="abc123",
            last_review_dispatch_sha=None,
            last_fix_dispatch_sha=None,
            last_merge_dispatch_sha=None,
            last_conflict_dispatch_sha="abc123",
        )
        assert result == Action.NONE

    def test_conflict_resolution_new_sha_allowed(self):
        result = apply_dispatch_dedupe(
            action=Action.NEEDS_CONFLICT_RESOLUTION,
            head_sha="new_sha",
            last_review_dispatch_sha=None,
            last_fix_dispatch_sha=None,
            last_merge_dispatch_sha=None,
            last_conflict_dispatch_sha="old_sha",
        )
        assert result == Action.NEEDS_CONFLICT_RESOLUTION


# ── Case-insensitive comparisons ────────────────────────────────────────────

class TestCaseInsensitiveStates:
    """GitHub API may return mixed-case state strings. All comparisons must be case-insensitive."""

    def test_lowercase_merged_detected(self):
        """PR state 'merged' (lowercase) should be treated as merged."""
        pr_detail = {
            "state": "merged",
            "headRefOid": "abc123",
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "reviews": [],
        }
        status, action, *_ = determine_pr_action(
            pr_detail, None, required_reviewers=["code-snob", "architect"]
        )
        assert status == Status.MERGED
        assert action == Action.NONE

    def test_mixed_case_conflicting(self):
        """mergeable='Conflicting' (mixed case) should trigger conflict detection."""
        reviews = [
            _make_review("code-snob", "APPROVED", "abc123"),
            _make_review("architect", "APPROVED", "abc123"),
        ]
        pr_detail = {
            "state": "OPEN",
            "headRefOid": "abc123",
            "mergeable": "Conflicting",
            "mergeStateStatus": "clean",
            "reviews": reviews,
        }
        existing = _make_existing(last_reviewed_sha="abc123")
        status, action, *_ = determine_pr_action(
            pr_detail, existing, required_reviewers=["code-snob", "architect"]
        )
        assert status == Status.CONFLICTING
        assert action == Action.NEEDS_CONFLICT_RESOLUTION

    def test_lowercase_dirty_merge_state(self):
        """mergeStateStatus='dirty' (lowercase) should trigger conflict detection."""
        reviews = [
            _make_review("code-snob", "APPROVED", "abc123"),
            _make_review("architect", "APPROVED", "abc123"),
        ]
        pr_detail = {
            "state": "OPEN",
            "headRefOid": "abc123",
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "dirty",
            "reviews": reviews,
        }
        existing = _make_existing(last_reviewed_sha="abc123")
        status, action, *_ = determine_pr_action(
            pr_detail, existing, required_reviewers=["code-snob", "architect"]
        )
        assert status == Status.CONFLICTING
        assert action == Action.NEEDS_CONFLICT_RESOLUTION

    def test_lowercase_review_states(self):
        """Review states 'approved'/'changes_requested' (lowercase) should work."""
        reviews = [
            _make_review("code-snob", "approved", "abc123"),
            _make_review("architect", "approved", "abc123"),
        ]
        ev = evaluate_reviews(reviews, ["code-snob", "architect"])
        assert ev.all_required_approved is True

    def test_lowercase_changes_requested(self):
        reviews = [
            _make_review("code-snob", "changes_requested", "abc123"),
            _make_review("architect", "approved", "abc123"),
        ]
        ev = evaluate_reviews(reviews, ["code-snob", "architect"])
        assert ev.any_changes_requested is True
        assert ev.all_required_approved is False

    def test_lowercase_commented_skipped(self):
        """'commented' (lowercase) should be skipped like 'COMMENTED'."""
        reviews = [
            _make_review("code-snob", "commented", "abc123"),
            _make_review("architect", "APPROVED", "abc123"),
        ]
        ev = evaluate_reviews(reviews, ["code-snob", "architect"])
        assert "code-snob" not in ev.latest_decision_by_reviewer
        assert ev.all_required_approved is False

    def test_lowercase_closed_issue(self):
        from github_sync import determine_issue_action
        issue = {"state": "Closed"}
        status, action = determine_issue_action(issue, None)
        assert status == Status.CLOSED
        assert action == Action.NONE


# ── Direct reviewer identity ────────────────────────────────────────────────

class TestDirectReviewerIdentity:
    def test_reviewer_login_is_identity(self):
        """Each reviewer's GitHub login is their identity directly."""
        reviews = [
            _make_review("code-snob", "APPROVED", "sha1"),
            _make_review("architect", "APPROVED", "sha1"),
        ]
        ev = evaluate_reviews(reviews, ["code-snob", "architect"])
        assert ev.all_required_approved is True


# ── CHECKS_FAILING state machine tests ──────────────────────────────────────

class TestChecksFailing:
    def test_checks_failing_needs_status_fix(self):
        """mergeStateStatus=UNSTABLE → CHECKS_FAILING / NEEDS_STATUS_FIX."""
        reviews = [
            _make_review("code-snob", "APPROVED", "abc123"),
            _make_review("architect", "APPROVED", "abc123"),
        ]
        pr_detail = {
            "state": "OPEN",
            "headRefOid": "abc123",
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "UNSTABLE",
            "reviews": reviews,
        }
        existing = _make_existing(last_reviewed_sha="abc123")
        status, action, *_ = determine_pr_action(
            pr_detail, existing, required_reviewers=["code-snob", "architect"]
        )
        assert status == Status.CHECKS_FAILING
        assert action == Action.NEEDS_STATUS_FIX

    def test_checks_failing_with_approval_still_blocks_merge(self):
        """Approved but unstable → still CHECKS_FAILING (not READY_TO_MERGE)."""
        reviews = [
            _make_review("code-snob", "APPROVED", "abc123"),
            _make_review("architect", "APPROVED", "abc123"),
        ]
        pr_detail = {
            "state": "OPEN",
            "headRefOid": "abc123",
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "UNSTABLE",
            "reviews": reviews,
        }
        existing = _make_existing(last_reviewed_sha="abc123")
        status, action, *_ = determine_pr_action(
            pr_detail, existing, required_reviewers=["code-snob", "architect"]
        )
        assert status != Status.APPROVED
        assert action != Action.READY_TO_MERGE

    def test_checks_failing_no_reviews(self):
        """UNSTABLE with no reviews → CHECKS_FAILING / NEEDS_STATUS_FIX."""
        pr_detail = {
            "state": "OPEN",
            "headRefOid": "abc123",
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "UNSTABLE",
            "reviews": [],
        }
        status, action, *_ = determine_pr_action(
            pr_detail, None, required_reviewers=["code-snob", "architect"]
        )
        assert status == Status.CHECKS_FAILING
        assert action == Action.NEEDS_STATUS_FIX


class TestStatusFixDedupe:
    def test_status_fix_deduped(self):
        """Already dispatched for same SHA → NONE."""
        result = apply_dispatch_dedupe(
            action=Action.NEEDS_STATUS_FIX,
            head_sha="abc123",
            last_review_dispatch_sha=None,
            last_fix_dispatch_sha=None,
            last_merge_dispatch_sha=None,
            last_conflict_dispatch_sha=None,
            last_status_fix_dispatch_sha="abc123",
        )
        assert result == Action.NONE

    def test_status_fix_new_sha_allowed(self):
        """New SHA → NEEDS_STATUS_FIX passes through."""
        result = apply_dispatch_dedupe(
            action=Action.NEEDS_STATUS_FIX,
            head_sha="new_sha",
            last_review_dispatch_sha=None,
            last_fix_dispatch_sha=None,
            last_merge_dispatch_sha=None,
            last_conflict_dispatch_sha=None,
            last_status_fix_dispatch_sha="old_sha",
        )
        assert result == Action.NEEDS_STATUS_FIX


class TestStatusFixDispatchPersistence:
    def test_mark_dispatched_status_fix(self, tmp_db):
        """mark_dispatched writes last_status_fix_dispatch_sha to DB."""
        with patch("github_sync.DB_PATH", tmp_db):
            item = _make_existing()
            save_item(item)
            mark_dispatched(item.id, "status_fix", "sha_xyz")

            conn = sqlite3.connect(tmp_db)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT last_status_fix_dispatch_sha FROM workflow_items WHERE id = ?",
                (item.id,)
            ).fetchone()
            conn.close()
            assert row["last_status_fix_dispatch_sha"] == "sha_xyz"
