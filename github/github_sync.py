#!/usr/bin/env python3
"""
GitHub Sync Script for Multi-Agent Workflow

This is the "brain" of the system. It:
1. Fetches all issues and PRs from GitHub
2. Computes derived state (approved? needs review? etc.)
3. Stores in SQLite DB
4. Determines next actions for worker agents

Worker agents only READ this DB and execute actions.
They never write state - only .lock files to claim work.
"""

import sqlite3
import json
import os
import subprocess
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import List, Optional, Dict
from enum import Enum

# ============================================================================
# CONFIGURATION
# ============================================================================

import logging

from github.workflow_config import get_config, load_reviewers_for_repo, load_approval_rules_for_repo
from github.workflow_config import MAX_ITERATIONS  # backward-compat re-export  # noqa: F401

logger = logging.getLogger(__name__)


def _casefold_eq(a, b):
    """Case-insensitive string comparison (handles None)."""
    if a is None or b is None:
        return False
    return a.casefold() == b.casefold()


# Keep module-level names so existing tests using `patch("github_sync.DB_PATH", ...)` still work.
# These are only used as defaults; functions below read from get_config() at call time.
DB_PATH = get_config()["db_path"]
REPOS = get_config()["repos"]


# ============================================================================
# DATA MODELS
# ============================================================================

class ItemType(Enum):
    ISSUE = "issue"
    PR = "pr"


class Action(Enum):
    NONE = "none"  # Nothing to do
    NEEDS_DEV = "needs_dev"  # Issue needs implementation
    NEEDS_REVIEW = "needs_review"  # PR needs reviewers spawned
    IN_REVIEW = "in_review"  # Reviews in progress, waiting for reviewers
    NEEDS_FIX = "needs_fix"  # PR has changes_requested, needs dev fix
    NEEDS_CONFLICT_RESOLUTION = "needs_conflict_resolution"  # Merge conflicts
    READY_TO_MERGE = "ready_to_merge"  # Approved, no conflicts, SHA matches
    MAX_ITERATIONS_REACHED = "max_iterations_reached"  # Manual intervention needed
    DISPATCHED = "dispatched"  # Agent spawned, awaiting result


class Status(Enum):
    # Issues
    OPEN = "open"
    IN_PROGRESS = "in_progress"  # Dev assigned
    PR_CREATED = "pr_created"  # PR exists for this issue
    CLOSED = "closed"

    # PRs
    PENDING_REVIEW = "pending_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    MERGED = "merged"
    CONFLICTING = "conflicting"


def make_item_id(repo: str, item_type: ItemType, number: int) -> str:
    """Return stable repo-scoped ID, e.g. 'miller46/jm-api#pr#56'."""
    return f"{repo}#{item_type.value}#{number}"


@dataclass
class WorkflowItem:
    id: str  # "owner/repo#issue#48" or "owner/repo#pr#56"
    type: ItemType
    repo: str
    number: int
    title: str
    github_state: str  # Raw GitHub state (open/closed/merged)

    # Same as id (kept for index/query convenience)
    repo_scoped_id: str

    # Computed fields
    status: Status
    action: Action

    # Review state (for PRs)
    head_sha: Optional[str]
    head_ref_name: Optional[str]
    last_reviewed_sha: Optional[str]
    reviews: Dict[str, str]  # {"code-snob": "APPROVED", ...}
    all_reviewers_approved: bool
    any_changes_requested: bool
    sha_matches_review: bool
    has_conflicts: bool

    # Dispatch dedup SHAs - track which SHA each action was last dispatched for
    last_review_dispatch_sha: Optional[str]
    last_fix_dispatch_sha: Optional[str]
    last_merge_dispatch_sha: Optional[str]
    last_conflict_dispatch_sha: Optional[str]
    last_head_sha_seen: Optional[str]

    # Iteration tracking (for changes_requested cycles)
    iteration: int
    max_iterations: int

    # Work assignment
    assigned_agent: Optional[str]  # Who's working on it
    lock_expires: Optional[str]  # ISO timestamp when lock expires

    # Metadata
    created_at: str
    updated_at: str
    last_sync: str


# ============================================================================
# DATABASE SCHEMA
# ============================================================================

SCHEMA = """
CREATE TABLE IF NOT EXISTS workflow_items (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,              -- 'issue' or 'pr'
    repo TEXT NOT NULL,
    number INTEGER NOT NULL,
    title TEXT,
    github_state TEXT,               -- 'open', 'closed', 'merged'
    repo_scoped_id TEXT,             -- same as id; kept for index/query convenience

    status TEXT NOT NULL,            -- Computed status
    action TEXT NOT NULL,            -- What worker should do

    -- PR-specific fields
    head_sha TEXT,
    head_ref_name TEXT,
    last_reviewed_sha TEXT,
    reviews_json TEXT,               -- JSON dict of reviewer->decision
    all_reviewers_approved BOOLEAN DEFAULT 0,
    any_changes_requested BOOLEAN DEFAULT 0,
    sha_matches_review BOOLEAN DEFAULT 0,
    has_conflicts BOOLEAN DEFAULT 0,

    -- Dispatch dedup SHAs
    last_review_dispatch_sha TEXT,
    last_fix_dispatch_sha TEXT,
    last_merge_dispatch_sha TEXT,
    last_conflict_dispatch_sha TEXT,
    last_head_sha_seen TEXT,

    -- Iteration tracking
    iteration INTEGER DEFAULT 0,
    max_iterations INTEGER DEFAULT 3,

    -- Work assignment
    assigned_agent TEXT,
    lock_expires TEXT,               -- ISO timestamp

    -- Metadata
    created_at TEXT,
    updated_at TEXT,
    last_sync TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_action ON workflow_items(action);
CREATE INDEX IF NOT EXISTS idx_status ON workflow_items(status);
CREATE INDEX IF NOT EXISTS idx_type ON workflow_items(type);
CREATE INDEX IF NOT EXISTS idx_repo_scoped ON workflow_items(repo_scoped_id);

CREATE TABLE IF NOT EXISTS locks (
    name TEXT PRIMARY KEY,           -- e.g. 'review_pr_56', 'fix_pr_56'
    owner TEXT NOT NULL,             -- agent/process that holds the lock
    expires_at TEXT NOT NULL         -- ISO timestamp
);

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    items_synced INTEGER DEFAULT 0,
    errors TEXT
);

CREATE TABLE IF NOT EXISTS dispatch_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    step_id TEXT,
    head_sha TEXT,
    agent TEXT,
    status TEXT NOT NULL,
    dispatched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dispatch_item ON dispatch_events(item_id);
"""


@dataclass
class ReviewEvaluation:
    all_required_approved: bool
    any_changes_requested: bool
    latest_review_sha: Optional[str]
    latest_decision_by_reviewer: Dict[str, str]  # reviewer -> APPROVED/CHANGES_REQUESTED/...


def evaluate_reviews(
        reviews: List[dict],
        required_reviewers: List[str],
        approval_rules: Optional[Dict] = None,
) -> ReviewEvaluation:
    """
    Build latest decision per required reviewer.
    Each review's author.login is treated as the reviewer identity.
    Reviews are sorted by submittedAt ascending so "latest review wins" is deterministic.

    When approval_rules is provided, uses min_approvals threshold instead of
    requiring ALL reviewers to approve.
    """
    latest_decision: Dict[str, str] = {}
    latest_review_sha: Optional[str] = None

    # Sort by submittedAt ascending so last-in-time overwrites earlier decisions
    sorted_reviews = sorted(
        reviews,
        key=lambda r: r.get("submittedAt", ""),
    )

    for review in sorted_reviews:
        author = review.get("author", {}).get("login", "")
        state = review.get("state", "COMMENTED")
        review_sha = review.get("commit", {}).get("oid", "")

        if _casefold_eq(state, "COMMENTED"):
            continue

        if author in required_reviewers:
            latest_decision[author] = state
            if review_sha:
                latest_review_sha = review_sha

    if approval_rules and approval_rules.get("min_approvals") is not None:
        # Count approvals from the reviewer pool
        approval_count = sum(
            1 for r in required_reviewers
            if _casefold_eq(latest_decision.get(r), "APPROVED")
        )
        min_approvals = approval_rules["min_approvals"]

        # Check specifically-required reviewers (subset that MUST approve)
        rules_required = approval_rules.get("required_reviewers", [])
        specific_ok = all(
            _casefold_eq(latest_decision.get(r), "APPROVED") for r in rules_required
        )

        # Check veto powers
        veto_reviewers = approval_rules.get("veto_powers", [])
        veto_blocked = any(
            _casefold_eq(latest_decision.get(r), "CHANGES_REQUESTED") for r in veto_reviewers
        )

        all_required_approved = (
            approval_count >= min_approvals
            and specific_ok
            and not veto_blocked
        )
    else:
        # Legacy: all reviewers must approve
        all_required_approved = all(
            _casefold_eq(latest_decision.get(r), "APPROVED") for r in required_reviewers
        )

    any_changes_requested = any(
        _casefold_eq(latest_decision.get(r), "CHANGES_REQUESTED") for r in required_reviewers
    )

    for reviewer in required_reviewers:
        decision = latest_decision.get(reviewer, "(no review)")
        logger.debug("review: %s = %s", reviewer, decision)
    logger.debug(
        "all_approved=%s  any_changes_requested=%s  review_sha=%s",
        all_required_approved, any_changes_requested, latest_review_sha)

    return ReviewEvaluation(
        all_required_approved=all_required_approved,
        any_changes_requested=any_changes_requested,
        latest_review_sha=latest_review_sha,
        latest_decision_by_reviewer=latest_decision,
    )


# ============================================================================
# GITHUB API HELPERS
# ============================================================================

ISSUE_FIELDS = ["number", "title", "state", "createdAt", "updatedAt", "body", "labels", "author", "closed", "closedAt"]
PR_LIST_FIELDS = ["number", "title", "state", "createdAt", "updatedAt", "author", "headRefName", "body"]
PR_DETAIL_FIELDS = ["number", "title", "state", "headRefOid", "mergeable", "mergeStateStatus", "reviews", "createdAt",
                    "updatedAt", "body", "author"]


def gh_api(args: List[str], fields: List[str] = None) -> dict:
    """Call GitHub CLI and return JSON response."""
    cmd = ["gh"] + args
    if fields:
        cmd.extend(["--json", ",".join(fields)])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"GitHub API error: {result.stderr}")
    return json.loads(result.stdout)


def fetch_issues(repo: str) -> List[dict]:
    """Fetch all open issues from repo."""
    return gh_api(["issue", "list", "--repo", repo, "--state", "open", "--limit", "100"], ISSUE_FIELDS)


def fetch_prs(repo: str) -> List[dict]:
    """Fetch all open PRs from repo."""
    return gh_api(["pr", "list", "--repo", repo, "--state", "open", "--limit", "100"], PR_LIST_FIELDS)


def fetch_pr_reviews(repo: str, pr_number: int) -> List[dict]:
    """Fetch reviews for a specific PR."""
    return gh_api(["pr", "view", str(pr_number), "--repo", repo], ["reviews"])


def fetch_pr_detail(repo: str, pr_number: int) -> dict:
    """Fetch full PR details including mergeable state."""
    return gh_api([
        "pr", "view", str(pr_number), "--repo", repo
    ], PR_DETAIL_FIELDS)


# ============================================================================
# STATE COMPUTATION
# ============================================================================

def apply_dispatch_dedupe(
        action: Action,
        head_sha: Optional[str],
        last_review_dispatch_sha: Optional[str],
        last_fix_dispatch_sha: Optional[str],
        last_merge_dispatch_sha: Optional[str],
        last_conflict_dispatch_sha: Optional[str] = None,
) -> Action:
    """Return Action.NONE when action for this SHA was already dispatched."""
    sha_short = head_sha[:8] if head_sha else "None"
    if action == Action.NEEDS_REVIEW and head_sha and head_sha == last_review_dispatch_sha:
        logger.debug("dedupe: NEEDS_REVIEW already dispatched for %s -> suppressed", sha_short)
        return Action.NONE
    if action == Action.NEEDS_FIX and head_sha and head_sha == last_fix_dispatch_sha:
        logger.debug("dedupe: NEEDS_FIX already dispatched for %s -> suppressed", sha_short)
        return Action.NONE
    if action == Action.READY_TO_MERGE and head_sha and head_sha == last_merge_dispatch_sha:
        logger.debug("dedupe: READY_TO_MERGE already dispatched for %s -> suppressed", sha_short)
        return Action.NONE
    if action == Action.NEEDS_CONFLICT_RESOLUTION and head_sha and head_sha == last_conflict_dispatch_sha:
        logger.debug("dedupe: NEEDS_CONFLICT_RESOLUTION already dispatched for %s -> suppressed", sha_short)
        return Action.NONE
    return action


def update_iteration(
        existing: Optional[WorkflowItem],
        action: Action,
        max_iterations: int,
) -> tuple[int, Action]:
    """
    Check iteration cap only.  Actual increment happens atomically
    in mark_dispatched(dispatch_type="fix") on successful dispatch.
    """
    iteration = existing.iteration if existing else 0

    if action != Action.NEEDS_FIX:
        return iteration, action

    if iteration >= max_iterations:
        logger.debug("iteration: %s/%s -> MAX_ITERATIONS_REACHED (capped)", iteration, max_iterations)
        return iteration, Action.MAX_ITERATIONS_REACHED

    logger.debug("iteration: %s/%s -> NEEDS_FIX allowed", iteration, max_iterations)
    return iteration, action


def determine_pr_action(
        pr_detail: dict,
        existing: Optional[WorkflowItem],
        required_reviewers: List[str] = None,
        approval_rules: Optional[Dict] = None,
) -> tuple[Status, Action, bool, bool, dict, str]:
    """
    SHA-gated state machine for PR action determination.

    Returns: (status, action, all_approved, any_changes_requested,
              latest_decisions, last_reviewed_sha)
    """
    if required_reviewers is None:
        required_reviewers = load_reviewers_for_repo("")

    reviews_raw = pr_detail.get("reviews", [])
    head_sha = pr_detail.get("headRefOid")
    mergeable = pr_detail.get("mergeable")
    merge_state = pr_detail.get("mergeStateStatus")

    pr_num = pr_detail.get("number", "?")
    logger.debug(
        "PR #%s: gh_state=%s  head=%s  mergeable=%s  mergeState=%s",
        pr_num, pr_detail.get('state'), head_sha[:8] if head_sha else 'None', mergeable, merge_state)

    # Evaluate reviews using pure function
    ev = evaluate_reviews(reviews_raw, required_reviewers, approval_rules=approval_rules)

    has_conflicts = _casefold_eq(mergeable, "CONFLICTING") or _casefold_eq(merge_state, "DIRTY")

    # Determine last_reviewed_sha – always update from latest review so
    # sha_matches reflects the *current* review, not a stale DB value.
    last_reviewed_sha = existing.last_reviewed_sha if existing else None
    if ev.all_required_approved and ev.latest_review_sha == head_sha:
        last_reviewed_sha = head_sha
    elif ev.any_changes_requested or ev.all_required_approved:
        last_reviewed_sha = ev.latest_review_sha or last_reviewed_sha or head_sha

    sha_matches = head_sha == last_reviewed_sha if last_reviewed_sha else False
    logger.debug(
        "sha_matches=%s  head=%s  reviewed=%s  conflicts=%s",
        sha_matches, head_sha[:8] if head_sha else 'None', last_reviewed_sha[:8] if last_reviewed_sha else 'None', has_conflicts)

    # Rule 1: merged
    if _casefold_eq(pr_detail.get("state"), "MERGED"):
        logger.debug("-> RULE 1: MERGED  status=merged  action=none")
        return Status.MERGED, Action.NONE, ev.all_required_approved, ev.any_changes_requested, ev.latest_decision_by_reviewer, last_reviewed_sha

    # Rule 2: conflicts + approved
    if has_conflicts:
        if ev.all_required_approved:
            logger.debug("-> RULE 2a: CONFLICTS + APPROVED  status=conflicting  action=needs_conflict_resolution")
            return Status.CONFLICTING, Action.NEEDS_CONFLICT_RESOLUTION, ev.all_required_approved, ev.any_changes_requested, ev.latest_decision_by_reviewer, last_reviewed_sha
        logger.debug("-> RULE 2b: CONFLICTS (not approved)  status=conflicting  action=none")
        return Status.CONFLICTING, Action.NONE, ev.all_required_approved, ev.any_changes_requested, ev.latest_decision_by_reviewer, last_reviewed_sha

    # Rule 3 & 4: all required approved
    if ev.all_required_approved:
        if sha_matches:
            logger.debug("-> RULE 3: ALL APPROVED + SHA MATCH  status=approved  action=ready_to_merge")
            return Status.APPROVED, Action.READY_TO_MERGE, True, ev.any_changes_requested, ev.latest_decision_by_reviewer, last_reviewed_sha
        else:
            logger.debug("-> RULE 4: ALL APPROVED + SHA MISMATCH  status=pending_review  action=needs_review")
            return Status.PENDING_REVIEW, Action.NEEDS_REVIEW, True, ev.any_changes_requested, ev.latest_decision_by_reviewer, last_reviewed_sha

    # Rule 5 & 6: any changes requested
    if ev.any_changes_requested:
        if sha_matches:
            logger.debug("-> RULE 5: CHANGES REQUESTED + SHA MATCH  status=changes_requested  action=needs_fix")
            return Status.CHANGES_REQUESTED, Action.NEEDS_FIX, False, True, ev.latest_decision_by_reviewer, last_reviewed_sha
        else:
            logger.debug("-> RULE 6: CHANGES REQUESTED + SHA MISMATCH  status=pending_review  action=needs_review")
            return Status.PENDING_REVIEW, Action.NEEDS_REVIEW, False, True, ev.latest_decision_by_reviewer, last_reviewed_sha

    # Rule 7: default
    logger.debug("-> RULE 7: NO DECISIONS YET  status=pending_review  action=needs_review")
    return Status.PENDING_REVIEW, Action.NEEDS_REVIEW, False, False, ev.latest_decision_by_reviewer, last_reviewed_sha


def determine_issue_action(issue: dict, existing: Optional[WorkflowItem], linked_pr_number: Optional[int] = None) -> \
tuple[Status, Action]:
    """Determine issue status and next action."""
    num = issue.get("number", "?")
    gh_state = issue.get("state", "?")

    if _casefold_eq(gh_state, "closed"):
        logger.debug("Issue #%s: gh_state=%s -> CLOSED / none", num, gh_state)
        return Status.CLOSED, Action.NONE

    if linked_pr_number:
        logger.debug("Issue #%s: gh_state=%s  linked_pr=#%s -> PR_CREATED / none", num, gh_state, linked_pr_number)
        return Status.PR_CREATED, Action.NONE

    if existing and existing.status == Status.IN_PROGRESS:
        logger.debug("Issue #%s: gh_state=%s  already in_progress -> IN_PROGRESS / none", num, gh_state)
        return Status.IN_PROGRESS, Action.NONE

    logger.debug("Issue #%s: gh_state=%s -> OPEN / needs_dev", num, gh_state)
    return Status.OPEN, Action.NEEDS_DEV


# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

def init_db():
    """Initialize SQLite database and run migrations."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    migrate_db()


def get_existing_item(item_id: str) -> Optional[WorkflowItem]:
    """Fetch existing item from DB."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM workflow_items WHERE id = ?", (item_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return WorkflowItem(
        id=row["id"],
        type=ItemType(row["type"]),
        repo=row["repo"],
        number=row["number"],
        title=row["title"],
        github_state=row["github_state"],
        repo_scoped_id=row["repo_scoped_id"] or "",
        status=Status(row["status"]),
        action=Action(row["action"]),
        head_sha=row["head_sha"],
        head_ref_name=row["head_ref_name"],
        last_reviewed_sha=row["last_reviewed_sha"],
        reviews=json.loads(row["reviews_json"] or "{}"),
        all_reviewers_approved=bool(row["all_reviewers_approved"]),
        any_changes_requested=bool(row["any_changes_requested"]),
        sha_matches_review=bool(row["sha_matches_review"]),
        has_conflicts=bool(row["has_conflicts"]),
        last_review_dispatch_sha=row["last_review_dispatch_sha"],
        last_fix_dispatch_sha=row["last_fix_dispatch_sha"],
        last_merge_dispatch_sha=row["last_merge_dispatch_sha"],
        last_conflict_dispatch_sha=row["last_conflict_dispatch_sha"],
        last_head_sha_seen=row["last_head_sha_seen"],
        iteration=row["iteration"],
        max_iterations=row["max_iterations"],
        assigned_agent=row["assigned_agent"],
        lock_expires=row["lock_expires"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_sync=row["last_sync"]
    )


def save_item(item: WorkflowItem):
    """Save or update item in DB."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT OR REPLACE INTO workflow_items (
            id, type, repo, number, title, github_state, repo_scoped_id,
            status, action, head_sha, head_ref_name, last_reviewed_sha, reviews_json,
            all_reviewers_approved, any_changes_requested, sha_matches_review, has_conflicts,
            last_review_dispatch_sha, last_fix_dispatch_sha, last_merge_dispatch_sha, last_conflict_dispatch_sha, last_head_sha_seen,
            iteration, max_iterations, assigned_agent, lock_expires,
            created_at, updated_at, last_sync
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        item.id, item.type.value, item.repo, item.number, item.title, item.github_state,
        item.repo_scoped_id,
        item.status.value, item.action.value, item.head_sha, item.head_ref_name, item.last_reviewed_sha,
        json.dumps(item.reviews),
        item.all_reviewers_approved, item.any_changes_requested,
        item.sha_matches_review, item.has_conflicts,
        item.last_review_dispatch_sha, item.last_fix_dispatch_sha,
        item.last_merge_dispatch_sha, item.last_conflict_dispatch_sha, item.last_head_sha_seen,
        item.iteration, item.max_iterations, item.assigned_agent, item.lock_expires,
        item.created_at, item.updated_at, item.last_sync
    ))
    conn.commit()
    conn.close()


def migrate_db():
    """Add new columns to existing DBs if missing."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("PRAGMA table_info(workflow_items)")
    existing_cols = {row[1] for row in cursor.fetchall()}

    migrations = {
        "repo_scoped_id": "ALTER TABLE workflow_items ADD COLUMN repo_scoped_id TEXT",
        "last_review_dispatch_sha": "ALTER TABLE workflow_items ADD COLUMN last_review_dispatch_sha TEXT",
        "last_fix_dispatch_sha": "ALTER TABLE workflow_items ADD COLUMN last_fix_dispatch_sha TEXT",
        "last_merge_dispatch_sha": "ALTER TABLE workflow_items ADD COLUMN last_merge_dispatch_sha TEXT",
        "last_head_sha_seen": "ALTER TABLE workflow_items ADD COLUMN last_head_sha_seen TEXT",
        "last_conflict_dispatch_sha": "ALTER TABLE workflow_items ADD COLUMN last_conflict_dispatch_sha TEXT",
        "head_ref_name": "ALTER TABLE workflow_items ADD COLUMN head_ref_name TEXT",
    }

    for col, sql in migrations.items():
        if col not in existing_cols:
            conn.execute(sql)
            logger.info("Migrated: added column %s", col)

    # Ensure lock index exists (safe to run repeatedly)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_locks_expires_at ON locks(expires_at)")

    conn.commit()
    conn.close()


def acquire_lock(name: str, owner: str, duration_seconds: int = 300) -> bool:
    """Try to acquire a named lock. Returns True if acquired."""
    conn = sqlite3.connect(DB_PATH)
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(seconds=duration_seconds)).isoformat()

    # Delete expired locks
    conn.execute("DELETE FROM locks WHERE expires_at < ?", (now.isoformat(),))

    # Try to insert
    try:
        conn.execute(
            "INSERT INTO locks (name, owner, expires_at) VALUES (?, ?, ?)",
            (name, owner, expires_at)
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def release_lock(name: str, owner: str) -> bool:
    """Release a named lock. Returns True if released."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "DELETE FROM locks WHERE name = ? AND owner = ?",
        (name, owner)
    )
    released = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return released


def cleanup_expired_locks() -> int:
    """Delete all expired lock rows. Returns count removed."""
    conn = sqlite3.connect(DB_PATH)
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute("DELETE FROM locks WHERE expires_at <= ?", (now,))
    removed = cursor.rowcount
    conn.commit()
    conn.close()
    return removed


def mark_dispatched(
        item_id: str,
        dispatch_type: str,
        head_sha: str,
) -> None:
    """
    Persist dispatch marker after successful dispatch/claim.
    dispatch_type: 'review', 'fix', 'merge', or 'conflict'.
    Called by workers after successful agent spawn.
    For 'fix', also atomically increments iteration.
    """
    conn = sqlite3.connect(DB_PATH)
    now = datetime.now(timezone.utc).isoformat()

    if dispatch_type == "review":
        conn.execute(
            "UPDATE workflow_items SET last_review_dispatch_sha = ?, last_sync = ? WHERE id = ?",
            (head_sha, now, item_id),
        )
    elif dispatch_type == "fix":
        conn.execute(
            "UPDATE workflow_items SET last_fix_dispatch_sha = ?, iteration = iteration + 1, last_sync = ? WHERE id = ?",
            (head_sha, now, item_id),
        )
    elif dispatch_type == "merge":
        conn.execute(
            "UPDATE workflow_items SET last_merge_dispatch_sha = ?, last_sync = ? WHERE id = ?",
            (head_sha, now, item_id),
        )
    elif dispatch_type == "conflict":
        conn.execute(
            "UPDATE workflow_items SET last_conflict_dispatch_sha = ?, last_sync = ? WHERE id = ?",
            (head_sha, now, item_id),
        )

    conn.commit()
    conn.close()


# ============================================================================
# MAIN SYNC LOOP
# ============================================================================

def find_linked_prs(prs: list, issue_number: int) -> Optional[int]:
    """
    Check if any PR links this issue via: closes #N, fixes #N, resolves #N.
    Returns the PR number if found, None otherwise.
    """
    import re
    issue_patterns = [
        rf'closes\s*#\s*{issue_number}\b',
        rf'fixes\s*#\s*{issue_number}\b',
        rf'resolves\s*#\s*{issue_number}\b',
    ]

    for pr in prs:
        pr_body = pr.get('body', '') or ''
        pr_title = pr.get('title', '') or ''
        combined_text = f"{pr_title}\n{pr_body}".lower()

        for pattern in issue_patterns:
            if re.search(pattern, combined_text, re.IGNORECASE):
                return pr['number']

    return None


def sync_repo(repo: str) -> int:
    """Sync all items from a repo. Returns count of items synced."""
    count = 0
    now = datetime.now(timezone.utc).isoformat()
    repo_reviewers = load_reviewers_for_repo(repo)
    repo_approval_rules = load_approval_rules_for_repo(repo)

    prs = fetch_prs(repo)
    issues = fetch_issues(repo)

    for issue in issues:
        item_id = make_item_id(repo, ItemType.ISSUE, issue['number'])
        existing = get_existing_item(item_id)

        # Check if any PR is linked to this issue
        linked_pr = find_linked_prs(prs, issue['number'])

        status, action = determine_issue_action(issue, existing, linked_pr)

        item = WorkflowItem(
            id=item_id,
            type=ItemType.ISSUE,
            repo=repo,
            number=issue["number"],
            title=issue["title"],
            github_state=issue["state"],
            repo_scoped_id=item_id,
            status=status,
            action=action,
            head_sha=None,
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
            last_head_sha_seen=None,
            iteration=existing.iteration if existing else 0,
            max_iterations=MAX_ITERATIONS,
            assigned_agent=existing.assigned_agent if existing else None,
            lock_expires=existing.lock_expires if existing else None,
            created_at=issue.get("createdAt", now),
            updated_at=issue.get("updatedAt", now),
            last_sync=now
        )

        save_item(item)
        count += 1

        if linked_pr and action == Action.NONE:
            logger.debug("Issue #%s: linked to PR #%s, skipping dev spawn", issue['number'], linked_pr)

    # Sync PRs (using already fetched list)
    for pr in prs:
        item_id = make_item_id(repo, ItemType.PR, pr['number'])
        existing = get_existing_item(item_id)

        # Get full PR details
        pr_detail = fetch_pr_detail(repo, pr["number"])

        status, action, all_approved, any_changes_requested, reviewer_decisions, last_reviewed_sha = determine_pr_action(
            pr_detail, existing, repo_reviewers, approval_rules=repo_approval_rules)

        head_sha = pr_detail.get("headRefOid")

        # Dispatch dedup SHAs from existing record
        prev_review_sha = existing.last_review_dispatch_sha if existing else None
        prev_fix_sha = existing.last_fix_dispatch_sha if existing else None
        prev_merge_sha = existing.last_merge_dispatch_sha if existing else None
        prev_conflict_sha = existing.last_conflict_dispatch_sha if existing else None

        # Apply iteration logic
        iteration, action = update_iteration(
            existing, action, MAX_ITERATIONS,
        )

        # Apply dispatch dedupe
        action = apply_dispatch_dedupe(
            action, head_sha, prev_review_sha, prev_fix_sha, prev_merge_sha,
            last_conflict_dispatch_sha=prev_conflict_sha,
        )

        item = WorkflowItem(
            id=item_id,
            type=ItemType.PR,
            repo=repo,
            number=pr["number"],
            title=pr["title"],
            github_state=pr.get("state", "open"),
            repo_scoped_id=item_id,
            status=status,
            action=action,
            head_sha=head_sha,
            head_ref_name=pr.get("headRefName"),
            last_reviewed_sha=last_reviewed_sha,
            reviews=reviewer_decisions,
            all_reviewers_approved=all_approved,
            any_changes_requested=any_changes_requested,
            sha_matches_review=head_sha == last_reviewed_sha if last_reviewed_sha else False,
            has_conflicts=_casefold_eq(pr_detail.get("mergeable"), "CONFLICTING") or _casefold_eq(
                pr_detail.get("mergeStateStatus"), "DIRTY"),
            last_review_dispatch_sha=prev_review_sha,
            last_fix_dispatch_sha=prev_fix_sha,
            last_merge_dispatch_sha=prev_merge_sha,
            last_conflict_dispatch_sha=prev_conflict_sha,
            last_head_sha_seen=head_sha,
            iteration=iteration,
            max_iterations=MAX_ITERATIONS,
            assigned_agent=existing.assigned_agent if existing else None,
            lock_expires=existing.lock_expires if existing else None,
            created_at=pr.get("createdAt", now),
            updated_at=pr.get("updatedAt", now),
            last_sync=now
        )

        logger.debug(
            "FINAL: PR #%s  status=%s  action=%s  iter=%s  sha_match=%s  conflicts=%s",
            pr['number'], status.value, action.value, iteration, item.sha_matches_review, item.has_conflicts)

        save_item(item)
        count += 1

    # Reconcile PRs that exist in DB as open but are no longer in the open list
    open_pr_numbers = {pr['number'] for pr in prs}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(
        "SELECT id, number, title FROM workflow_items WHERE type = 'pr' AND repo = ? AND LOWER(github_state) = 'open'",
        (repo,)
    )
    closed_count = 0
    for row in cursor.fetchall():
        if row['number'] not in open_pr_numbers:
            # Fetch actual PR state to distinguish merged vs closed
            try:
                pr_state_detail = fetch_pr_detail(repo, row['number'])
                actual_state = pr_state_detail.get("state", "CLOSED")
            except Exception:
                actual_state = "CLOSED"

            if _casefold_eq(actual_state, "MERGED"):
                gh_state, db_status = "merged", "merged"
                label = "MERGED"
            else:
                gh_state, db_status = "closed", "closed"
                label = "CLOSED"

            conn.execute(
                "UPDATE workflow_items SET github_state = ?, status = ?, action = 'none', last_sync = ? WHERE id = ?",
                (gh_state, db_status, now, row['id'])
            )
            logger.info("PR #%s: marked as %s (not in open PR list)", row['number'], label)
            closed_count += 1
    conn.commit()
    conn.close()
    count += closed_count

    return count


SYNC_LOCK_NAME = "github_sync_main"
SYNC_LOCK_TTL = 600  # seconds


def sync():
    """Main sync entry point."""
    import uuid
    lock_owner = f"sync-{uuid.uuid4().hex[:8]}"

    init_db()

    # Clean up stale locks at startup
    stale = cleanup_expired_locks()
    if stale:
        logger.info("Cleaned %s expired lock(s)", stale)

    # Acquire cron overlap lock
    if not acquire_lock(SYNC_LOCK_NAME, lock_owner, SYNC_LOCK_TTL):
        logger.warning("Sync already running, exiting.")
        return

    started_at = datetime.now(timezone.utc).isoformat()
    total_synced = 0
    errors = []

    try:
        for repo in REPOS:
            try:
                count = sync_repo(repo)
                total_synced += count
                logger.info("Synced %s items from %s", count, repo)
            except Exception as e:
                errors.append(f"{repo}: {str(e)}")
                logger.exception("Error syncing %s", repo)

    except Exception as e:
        errors.append(str(e))

    finally:
        release_lock(SYNC_LOCK_NAME, lock_owner)

    finished_at = datetime.now(timezone.utc).isoformat()

    # Log sync run
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO sync_log (started_at, finished_at, items_synced, errors) VALUES (?, ?, ?, ?)",
        (started_at, finished_at, total_synced, json.dumps(errors) if errors else None)
    )
    conn.commit()
    conn.close()

    logger.info("Sync complete: %s items synced", total_synced)
    if errors:
        logger.error("Errors: %s", len(errors))


if __name__ == "__main__":
    sync()
