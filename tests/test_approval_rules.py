"""Tests for approval_rules support in evaluate_reviews / determine_pr_action.

The reviewer config has an 'approval_rules' field that specifies how many
approvals are needed (min_approvals) instead of requiring ALL reviewers.
PR #65 has 1 approval from 2 reviewers with min_approvals=1 → should be
READY_TO_MERGE, not NEEDS_REVIEW.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "github"))

from github_sync import (
    Action,
    Status,
    evaluate_reviews,
    determine_pr_action,
    WorkflowItem,
    ItemType,
    MAX_ITERATIONS,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _make_review(author, state, sha, submitted_at=None):
    return {
        "author": {"login": author},
        "state": state,
        "commit": {"oid": sha},
        "body": "",
        "submittedAt": submitted_at or datetime.now(timezone.utc).isoformat(),
    }


def _make_existing(
    item_id="miller46/jm-api#pr#65",
    iteration=0,
    last_reviewed_sha=None,
    **kwargs,
):
    now = datetime.now(timezone.utc).isoformat()
    defaults = dict(
        id=item_id,
        type=ItemType.PR,
        repo="miller46/jm-api",
        number=65,
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
        last_review_dispatch_sha=None,
        last_fix_dispatch_sha=None,
        last_merge_dispatch_sha=None,
        last_conflict_dispatch_sha=None,
        last_head_sha_seen="abc123",
        iteration=iteration,
        max_iterations=MAX_ITERATIONS,
        assigned_agent=None,
        lock_expires=None,
        created_at=now,
        updated_at=now,
        last_sync=now,
    )
    defaults.update(kwargs)
    return WorkflowItem(**defaults)


# ── evaluate_reviews with approval_rules ──────────────────────────────────


class TestEvaluateReviewsApprovalRules:
    """evaluate_reviews should respect approval_rules.min_approvals."""

    def test_one_approval_meets_min_approvals_1(self):
        """1 approval out of 2 reviewers, min_approvals=1 → all_required_approved."""
        reviews = [
            _make_review("miller46architect", "APPROVED", "sha1"),
        ]
        approval_rules = {
            "mode": "majority",
            "min_approvals": 1,
            "required_reviewers": [],
            "veto_powers": [],
        }
        ev = evaluate_reviews(
            reviews,
            required_reviewers=["miller46codesnob", "miller46architect"],
            approval_rules=approval_rules,
        )
        assert ev.all_required_approved is True
        assert ev.any_changes_requested is False

    def test_zero_approvals_does_not_meet_min_approvals_1(self):
        """0 approvals, min_approvals=1 → not approved."""
        reviews = []
        approval_rules = {
            "mode": "majority",
            "min_approvals": 1,
            "required_reviewers": [],
            "veto_powers": [],
        }
        ev = evaluate_reviews(
            reviews,
            required_reviewers=["miller46codesnob", "miller46architect"],
            approval_rules=approval_rules,
        )
        assert ev.all_required_approved is False

    def test_required_reviewer_must_approve_even_if_min_met(self):
        """If approval_rules.required_reviewers names a specific reviewer,
        that reviewer MUST approve even if min_approvals is met by others."""
        reviews = [
            _make_review("miller46codesnob", "APPROVED", "sha1"),
        ]
        approval_rules = {
            "mode": "majority",
            "min_approvals": 1,
            "required_reviewers": ["miller46architect"],
            "veto_powers": [],
        }
        ev = evaluate_reviews(
            reviews,
            required_reviewers=["miller46codesnob", "miller46architect"],
            approval_rules=approval_rules,
        )
        # min_approvals met (1 approval) but required reviewer not approved
        assert ev.all_required_approved is False

    def test_required_reviewer_approved_and_min_met(self):
        """required_reviewers approved + min_approvals met → approved."""
        reviews = [
            _make_review("miller46architect", "APPROVED", "sha1"),
        ]
        approval_rules = {
            "mode": "majority",
            "min_approvals": 1,
            "required_reviewers": ["miller46architect"],
            "veto_powers": [],
        }
        ev = evaluate_reviews(
            reviews,
            required_reviewers=["miller46codesnob", "miller46architect"],
            approval_rules=approval_rules,
        )
        assert ev.all_required_approved is True

    def test_veto_blocks_even_when_min_met(self):
        """A reviewer with veto_powers requesting changes blocks approval."""
        reviews = [
            _make_review("miller46architect", "APPROVED", "sha1"),
            _make_review("miller46codesnob", "CHANGES_REQUESTED", "sha1"),
        ]
        approval_rules = {
            "mode": "majority",
            "min_approvals": 1,
            "required_reviewers": [],
            "veto_powers": ["miller46codesnob"],
        }
        ev = evaluate_reviews(
            reviews,
            required_reviewers=["miller46codesnob", "miller46architect"],
            approval_rules=approval_rules,
        )
        assert ev.all_required_approved is False
        assert ev.any_changes_requested is True

    def test_no_approval_rules_falls_back_to_all_required(self):
        """Without approval_rules, all reviewers must approve (backward compat)."""
        reviews = [
            _make_review("miller46architect", "APPROVED", "sha1"),
        ]
        ev = evaluate_reviews(
            reviews,
            required_reviewers=["miller46codesnob", "miller46architect"],
        )
        assert ev.all_required_approved is False

    def test_min_approvals_2_needs_two(self):
        """min_approvals=2 with only 1 approval → not approved."""
        reviews = [
            _make_review("miller46architect", "APPROVED", "sha1"),
        ]
        approval_rules = {
            "mode": "majority",
            "min_approvals": 2,
            "required_reviewers": [],
            "veto_powers": [],
        }
        ev = evaluate_reviews(
            reviews,
            required_reviewers=["miller46codesnob", "miller46architect"],
            approval_rules=approval_rules,
        )
        assert ev.all_required_approved is False


# ── determine_pr_action with approval_rules ───────────────────────────────


class TestDeterminePrActionApprovalRules:
    """determine_pr_action should pass approval_rules through to evaluate_reviews."""

    def test_pr65_one_approval_ready_to_merge(self):
        """PR #65 scenario: 1 approval, 2 reviewers, min_approvals=1 → READY_TO_MERGE."""
        pr_detail = json.loads((FIXTURES / "github_pr_detail_65.json").read_text())
        head_sha = pr_detail["headRefOid"]
        existing = _make_existing(last_reviewed_sha=head_sha, head_sha=head_sha)

        approval_rules = {
            "mode": "majority",
            "min_approvals": 1,
            "required_reviewers": [],
            "veto_powers": [],
        }
        status, action, all_approved, *_ = determine_pr_action(
            pr_detail,
            existing,
            required_reviewers=["miller46codesnob", "miller46architect"],
            approval_rules=approval_rules,
        )
        assert status == Status.APPROVED
        assert action == Action.READY_TO_MERGE
        assert all_approved is True

    def test_pr_partial_approval_without_rules_needs_review(self):
        """Same PR without approval_rules → NEEDS_REVIEW (backward compat)."""
        pr_detail = json.loads((FIXTURES / "github_pr_detail_65.json").read_text())
        head_sha = pr_detail["headRefOid"]
        existing = _make_existing(last_reviewed_sha=head_sha, head_sha=head_sha)

        status, action, all_approved, *_ = determine_pr_action(
            pr_detail,
            existing,
            required_reviewers=["miller46codesnob", "miller46architect"],
        )
        # Without approval_rules, all reviewers must approve → pending
        assert status == Status.PENDING_REVIEW
        assert action == Action.NEEDS_REVIEW
        assert all_approved is False
