"""Tests for PR #64: reviews from non-required reviewer accounts.

PR #64 has 5 reviews from miller46bot, which is not a required reviewer.
In the simplified reviewer model, author login = reviewer identity.
Reviews from non-required accounts should not affect the PR state.
"""

import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from github_sync import (
    Action,
    Status,
    WorkflowItem,
    ItemType,
    evaluate_reviews,
    determine_pr_action,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
PR64_SHA = "e2bed5badec6c29ab09e2ee99d75ee6dec4fdc36"
REQUIRED_REVIEWERS = ["code-snob", "architect"]


@pytest.fixture
def pr64_detail():
    with open(os.path.join(FIXTURES, "github_pr_detail_64.json")) as f:
        return json.load(f)


@pytest.fixture
def pr64_existing():
    """Simulate an existing DB row from a prior sync (first-seen PR)."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    return WorkflowItem(
        id="miller46/jm-api#pr#64",
        type=ItemType.PR,
        repo="miller46/jm-api",
        number=64,
        title="[backend] Security hardening",
        github_state="open",
        repo_scoped_id="miller46/jm-api#pr#64",
        status=Status.PENDING_REVIEW,
        action=Action.NEEDS_REVIEW,
        head_sha=PR64_SHA,
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
        last_head_sha_seen=PR64_SHA,
        iteration=0,
        max_iterations=5,
        assigned_agent=None,
        lock_expires=None,
        created_at=now,
        updated_at=now,
        last_sync=now,
    )


# ── evaluate_reviews: non-required reviewer reviews ──────────────────────────


class TestPR64EvaluateReviews:
    """evaluate_reviews should ignore reviews from non-required accounts."""

    def test_no_changes_requested_from_required_reviewers(self, pr64_detail):
        """All reviews are from miller46bot (not required) — no changes requested from required reviewers."""
        ev = evaluate_reviews(
            pr64_detail["reviews"],
            REQUIRED_REVIEWERS,
        )
        assert ev.any_changes_requested is False

    def test_all_approved_is_false(self, pr64_detail):
        """Not all required reviewers approved — must be False."""
        ev = evaluate_reviews(
            pr64_detail["reviews"],
            REQUIRED_REVIEWERS,
        )
        assert ev.all_required_approved is False

    def test_no_decisions_for_required_reviewers(self, pr64_detail):
        """No required reviewers have decisions since all reviews are from miller46bot."""
        ev = evaluate_reviews(
            pr64_detail["reviews"],
            REQUIRED_REVIEWERS,
        )
        assert "code-snob" not in ev.latest_decision_by_reviewer
        assert "architect" not in ev.latest_decision_by_reviewer


# ── determine_pr_action: full state machine ─────────────────────────────────


class TestPR64DeterminePrAction:
    """determine_pr_action should produce NEEDS_REVIEW for PR #64 (no required reviewer decisions)."""

    def test_action_is_needs_review(self, pr64_detail, pr64_existing):
        """No required reviewer decisions → NEEDS_REVIEW."""
        status, action, *_ = determine_pr_action(
            pr64_detail,
            pr64_existing,
            required_reviewers=REQUIRED_REVIEWERS,
        )
        assert action == Action.NEEDS_REVIEW

    def test_status_is_pending_review(self, pr64_detail, pr64_existing):
        """Status should be pending review (no required reviewer input yet)."""
        status, action, *_ = determine_pr_action(
            pr64_detail,
            pr64_existing,
            required_reviewers=REQUIRED_REVIEWERS,
        )
        assert status == Status.PENDING_REVIEW

    def test_first_sync_also_needs_review(self, pr64_detail):
        """On first sync (no existing row), should be NEEDS_REVIEW."""
        status, action, *_ = determine_pr_action(
            pr64_detail,
            None,  # first sync
            required_reviewers=REQUIRED_REVIEWERS,
        )
        assert action == Action.NEEDS_REVIEW
        assert status == Status.PENDING_REVIEW


# ── Reviews from required reviewer accounts work correctly ───────────────────


class TestRequiredReviewerIdentity:
    """When reviews come from required reviewer accounts, they are correctly attributed."""

    def test_direct_reviewer_changes_requested(self):
        """CHANGES_REQUESTED from a required reviewer account is detected."""
        reviews = [
            {
                "author": {"login": "code-snob"},
                "state": "CHANGES_REQUESTED",
                "commit": {"oid": "sha_abc"},
                "body": "Fix the error handling.",
                "submittedAt": "2026-02-19T17:00:00Z",
            },
        ]
        ev = evaluate_reviews(reviews, REQUIRED_REVIEWERS)
        assert ev.any_changes_requested is True

    def test_direct_reviewer_approval(self):
        """APPROVED from required reviewer accounts is detected."""
        reviews = [
            {
                "author": {"login": "code-snob"},
                "state": "APPROVED",
                "commit": {"oid": "sha_abc"},
                "body": "Looks good.",
                "submittedAt": "2026-02-19T17:00:00Z",
            },
            {
                "author": {"login": "architect"},
                "state": "APPROVED",
                "commit": {"oid": "sha_abc"},
                "body": "Architecture is solid.",
                "submittedAt": "2026-02-19T17:05:00Z",
            },
        ]
        ev = evaluate_reviews(reviews, REQUIRED_REVIEWERS)
        assert ev.all_required_approved is True

    def test_mixed_required_and_non_required_reviewers(self):
        """Non-required reviewer reviews don't affect decisions for required reviewers."""
        reviews = [
            {
                "author": {"login": "code-snob"},
                "state": "APPROVED",
                "commit": {"oid": "sha_abc"},
                "body": "Looks good.",
                "submittedAt": "2026-02-19T17:00:00Z",
            },
            {
                "author": {"login": "random-bot"},
                "state": "CHANGES_REQUESTED",
                "commit": {"oid": "sha_abc"},
                "body": "Needs refactor.",
                "submittedAt": "2026-02-19T17:05:00Z",
            },
        ]
        ev = evaluate_reviews(reviews, REQUIRED_REVIEWERS)
        # Only code-snob approved, architect hasn't reviewed
        assert ev.all_required_approved is False
        # random-bot's CHANGES_REQUESTED doesn't count (not a required reviewer)
        assert ev.any_changes_requested is False
