"""Tests for PR #64 bug: CHANGES_REQUESTED reviews from bot account ignored.

PR #64 has 5 reviews from miller46bot (a COLLABORATOR):
  - 4x CHANGES_REQUESTED
  - 1x APPROVED

The GitHub PR clearly shows REQUEST_CHANGES status, but the local sync
marks it NEEDS_REVIEW because evaluate_reviews only checks reviews from
accounts matching required_reviewers names (["code-snob", "architect"]).

miller46bot is the shared GitHub account used by the reviewer agents to
post reviews. Because its login doesn't match the agent names in the
config, all reviews are silently dropped.

These tests assert the CORRECT expected behavior: the PR should reflect
the CHANGES_REQUESTED status visible on GitHub.
"""

import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "github"))

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
    with open(os.path.join(FIXTURES, "scenario_pr_detail_bot_changes_requested.json")) as f:
        return json.load(f)


@pytest.fixture
def pr64_existing():
    """Existing DB row from a prior sync (first-seen, no reviews yet)."""
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


# ── evaluate_reviews: bot account reviews should be recognized ───────────────


class TestBotAccountReviewsDetected:
    """Reviews from the bot account should register as CHANGES_REQUESTED."""

    def test_any_changes_requested_is_true(self, pr64_detail):
        """4 of 5 reviews are CHANGES_REQUESTED — must be detected."""
        ev = evaluate_reviews(
            pr64_detail["reviews"],
            REQUIRED_REVIEWERS,
        )
        assert ev.any_changes_requested is True

    def test_latest_review_sha_is_set(self, pr64_detail):
        """Review SHA should be captured from the bot account reviews."""
        ev = evaluate_reviews(
            pr64_detail["reviews"],
            REQUIRED_REVIEWERS,
        )
        assert ev.latest_review_sha == PR64_SHA

    def test_decisions_are_populated(self, pr64_detail):
        """At least one reviewer decision should be recorded."""
        ev = evaluate_reviews(
            pr64_detail["reviews"],
            REQUIRED_REVIEWERS,
        )
        assert len(ev.latest_decision_by_reviewer) > 0


# ── determine_pr_action: should produce CHANGES_REQUESTED ───────────────────


class TestBotAccountPrAction:
    """PR with CHANGES_REQUESTED reviews from bot account should be CHANGES_REQUESTED."""

    def test_status_is_changes_requested(self, pr64_detail, pr64_existing):
        """PR should be CHANGES_REQUESTED, not PENDING_REVIEW."""
        status, action, *_ = determine_pr_action(
            pr64_detail,
            pr64_existing,
            required_reviewers=REQUIRED_REVIEWERS,
        )
        assert status == Status.CHANGES_REQUESTED

    def test_action_is_needs_fix(self, pr64_detail, pr64_existing):
        """Action should be NEEDS_FIX, not NEEDS_REVIEW."""
        status, action, *_ = determine_pr_action(
            pr64_detail,
            pr64_existing,
            required_reviewers=REQUIRED_REVIEWERS,
        )
        assert action == Action.NEEDS_FIX

    def test_first_sync_changes_requested(self, pr64_detail):
        """On first sync (no existing row), should still detect CHANGES_REQUESTED."""
        status, action, *_ = determine_pr_action(
            pr64_detail,
            None,
            required_reviewers=REQUIRED_REVIEWERS,
        )
        assert status == Status.CHANGES_REQUESTED
        assert action == Action.NEEDS_FIX

    def test_any_changes_requested_flag(self, pr64_detail, pr64_existing):
        """The any_changes_requested flag in the return tuple should be True."""
        status, action, all_approved, any_changes, *_ = determine_pr_action(
            pr64_detail,
            pr64_existing,
            required_reviewers=REQUIRED_REVIEWERS,
        )
        assert any_changes is True
