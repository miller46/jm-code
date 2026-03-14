package db

import (
	"database/sql"
	"encoding/json"
	"fmt"

	_ "modernc.org/sqlite"
)

type Store struct {
	db *sql.DB
}

func (s *Store) DB() *sql.DB { return s.db }

func (s *Store) Close() error { return s.db.Close() }

func Open(dsn string) (*Store, error) {
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, fmt.Errorf("opening database: %w", err)
	}

	// WAL mode for better concurrent reads
	if _, err := db.Exec("PRAGMA journal_mode=WAL"); err != nil {
		db.Close()
		return nil, fmt.Errorf("setting WAL mode: %w", err)
	}

	s := &Store{db: db}
	if err := s.migrate(); err != nil {
		db.Close()
		return nil, fmt.Errorf("running migrations: %w", err)
	}
	return s, nil
}

func (s *Store) migrate() error {
	_, err := s.db.Exec(`
		CREATE TABLE IF NOT EXISTS workflow_items (
			id TEXT PRIMARY KEY,
			type TEXT,
			repo TEXT,
			number INTEGER,
			title TEXT,
			github_state TEXT,
			repo_scoped_id TEXT,

			status TEXT,
			action TEXT,

			head_sha TEXT,
			head_ref_name TEXT,
			last_reviewed_sha TEXT,
			reviews_json TEXT DEFAULT '{}',
			all_reviewers_approved BOOLEAN DEFAULT 0,
			any_changes_requested BOOLEAN DEFAULT 0,
			sha_matches_review BOOLEAN DEFAULT 0,
			has_conflicts BOOLEAN DEFAULT 0,

			reviewer_shas_json TEXT DEFAULT '{}',
			reviewer_dispatch_shas_json TEXT DEFAULT '{}',

			last_review_dispatch_sha TEXT DEFAULT '',
			last_fix_dispatch_sha TEXT DEFAULT '',
			last_merge_dispatch_sha TEXT DEFAULT '',
			last_conflict_dispatch_sha TEXT DEFAULT '',
			last_status_fix_dispatch_sha TEXT DEFAULT '',
			last_head_sha_seen TEXT DEFAULT '',

			status_check_rollup TEXT DEFAULT '[]',
			linked_issue_number INTEGER DEFAULT 0,

			iteration INTEGER DEFAULT 0,
			max_iterations INTEGER DEFAULT 3,

			assigned_agent TEXT DEFAULT '',
			lock_expires TEXT DEFAULT '',

			created_at TEXT DEFAULT '',
			updated_at TEXT DEFAULT '',
			last_sync TEXT DEFAULT ''
		);

		CREATE TABLE IF NOT EXISTS locks (
			name TEXT PRIMARY KEY,
			owner TEXT,
			expires_at TEXT
		);

		CREATE TABLE IF NOT EXISTS sync_log (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			started_at TEXT,
			finished_at TEXT,
			items_synced INTEGER,
			errors TEXT
		);

		CREATE TABLE IF NOT EXISTS dispatch_events (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			item_id TEXT,
			step_id TEXT,
			head_sha TEXT,
			agent TEXT,
			status TEXT,
			dispatched_at TEXT
		);

		CREATE TABLE IF NOT EXISTS agent_selections (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			repo TEXT,
			number INTEGER,
			agent_id TEXT,
			created_at TEXT,
			UNIQUE(repo, number)
		);
	`)
	return err
}

func (s *Store) UpsertWorkflowItem(item WorkflowItem) error {
	_, err := s.db.Exec(`
		INSERT OR REPLACE INTO workflow_items (
			id, type, repo, number, title, github_state, repo_scoped_id,
			status, action,
			head_sha, head_ref_name, last_reviewed_sha, reviews_json,
			all_reviewers_approved, any_changes_requested, sha_matches_review, has_conflicts,
			reviewer_shas_json, reviewer_dispatch_shas_json,
			last_review_dispatch_sha, last_fix_dispatch_sha, last_merge_dispatch_sha,
			last_conflict_dispatch_sha, last_status_fix_dispatch_sha, last_head_sha_seen,
			status_check_rollup, linked_issue_number,
			iteration, max_iterations,
			assigned_agent, lock_expires,
			created_at, updated_at, last_sync
		) VALUES (
			?, ?, ?, ?, ?, ?, ?,
			?, ?,
			?, ?, ?, ?,
			?, ?, ?, ?,
			?, ?,
			?, ?, ?,
			?, ?, ?,
			?, ?,
			?, ?,
			?, ?,
			?, ?, ?
		)`,
		item.ID, item.Type, item.Repo, item.Number, item.Title, item.GitHubState, item.RepoScopedID,
		item.Status, item.Action,
		item.HeadSHA, item.HeadRefName, item.LastReviewedSHA, item.ReviewsJSON,
		item.AllReviewersApproved, item.AnyChangesRequested, item.SHAMatchesReview, item.HasConflicts,
		item.ReviewerSHAsJSON, item.ReviewerDispatchSHAsJSON,
		item.LastReviewDispatchSHA, item.LastFixDispatchSHA, item.LastMergeDispatchSHA,
		item.LastConflictDispatchSHA, item.LastStatusFixDispatchSHA, item.LastHeadSHASeen,
		item.StatusCheckRollup, item.LinkedIssueNumber,
		item.Iteration, item.MaxIterations,
		item.AssignedAgent, item.LockExpires,
		item.CreatedAt, item.UpdatedAt, item.LastSync,
	)
	return err
}

func (s *Store) GetWorkflowItem(id string) (*WorkflowItem, error) {
	row := s.db.QueryRow(`SELECT
		id, type, repo, number, title, github_state, repo_scoped_id,
		status, action,
		head_sha, head_ref_name, last_reviewed_sha, reviews_json,
		all_reviewers_approved, any_changes_requested, sha_matches_review, has_conflicts,
		reviewer_shas_json, reviewer_dispatch_shas_json,
		last_review_dispatch_sha, last_fix_dispatch_sha, last_merge_dispatch_sha,
		last_conflict_dispatch_sha, last_status_fix_dispatch_sha, last_head_sha_seen,
		status_check_rollup, linked_issue_number,
		iteration, max_iterations,
		assigned_agent, lock_expires,
		created_at, updated_at, last_sync
		FROM workflow_items WHERE id = ?`, id)

	var item WorkflowItem
	err := row.Scan(
		&item.ID, &item.Type, &item.Repo, &item.Number, &item.Title, &item.GitHubState, &item.RepoScopedID,
		&item.Status, &item.Action,
		&item.HeadSHA, &item.HeadRefName, &item.LastReviewedSHA, &item.ReviewsJSON,
		&item.AllReviewersApproved, &item.AnyChangesRequested, &item.SHAMatchesReview, &item.HasConflicts,
		&item.ReviewerSHAsJSON, &item.ReviewerDispatchSHAsJSON,
		&item.LastReviewDispatchSHA, &item.LastFixDispatchSHA, &item.LastMergeDispatchSHA,
		&item.LastConflictDispatchSHA, &item.LastStatusFixDispatchSHA, &item.LastHeadSHASeen,
		&item.StatusCheckRollup, &item.LinkedIssueNumber,
		&item.Iteration, &item.MaxIterations,
		&item.AssignedAgent, &item.LockExpires,
		&item.CreatedAt, &item.UpdatedAt, &item.LastSync,
	)
	if err != nil {
		return nil, fmt.Errorf("getting workflow item %q: %w", id, err)
	}
	return &item, nil
}

func (s *Store) QueryWorkflowItems(itemType, action, repo string, limit int) ([]WorkflowItem, error) {
	query := `SELECT
		id, type, repo, number, title, github_state, repo_scoped_id,
		status, action,
		head_sha, head_ref_name, last_reviewed_sha, reviews_json,
		all_reviewers_approved, any_changes_requested, sha_matches_review, has_conflicts,
		reviewer_shas_json, reviewer_dispatch_shas_json,
		last_review_dispatch_sha, last_fix_dispatch_sha, last_merge_dispatch_sha,
		last_conflict_dispatch_sha, last_status_fix_dispatch_sha, last_head_sha_seen,
		status_check_rollup, linked_issue_number,
		iteration, max_iterations,
		assigned_agent, lock_expires,
		created_at, updated_at, last_sync
		FROM workflow_items WHERE type = ? AND action = ?`
	args := []any{itemType, action}

	if repo != "" {
		query += " AND repo = ?"
		args = append(args, repo)
	}
	query += " LIMIT ?"
	args = append(args, limit)

	rows, err := s.db.Query(query, args...)
	if err != nil {
		return nil, fmt.Errorf("querying workflow items: %w", err)
	}
	defer rows.Close()

	var items []WorkflowItem
	for rows.Next() {
		var item WorkflowItem
		if err := rows.Scan(
			&item.ID, &item.Type, &item.Repo, &item.Number, &item.Title, &item.GitHubState, &item.RepoScopedID,
			&item.Status, &item.Action,
			&item.HeadSHA, &item.HeadRefName, &item.LastReviewedSHA, &item.ReviewsJSON,
			&item.AllReviewersApproved, &item.AnyChangesRequested, &item.SHAMatchesReview, &item.HasConflicts,
			&item.ReviewerSHAsJSON, &item.ReviewerDispatchSHAsJSON,
			&item.LastReviewDispatchSHA, &item.LastFixDispatchSHA, &item.LastMergeDispatchSHA,
			&item.LastConflictDispatchSHA, &item.LastStatusFixDispatchSHA, &item.LastHeadSHASeen,
			&item.StatusCheckRollup, &item.LinkedIssueNumber,
			&item.Iteration, &item.MaxIterations,
			&item.AssignedAgent, &item.LockExpires,
			&item.CreatedAt, &item.UpdatedAt, &item.LastSync,
		); err != nil {
			return nil, fmt.Errorf("scanning workflow item: %w", err)
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (s *Store) UpdateItemStatus(itemID, status, action string) error {
	_, err := s.db.Exec(
		"UPDATE workflow_items SET status = ?, action = ?, updated_at = ? WHERE id = ?",
		status, action, Now(), itemID,
	)
	return err
}

// For "fix" dispatch type, also increments the iteration counter.
func (s *Store) MarkDispatched(itemID, dispatchType, headSHA string) error {
	var col string
	switch dispatchType {
	case "review":
		col = "last_review_dispatch_sha"
	case "fix":
		col = "last_fix_dispatch_sha"
	case "merge":
		col = "last_merge_dispatch_sha"
	case "conflict":
		col = "last_conflict_dispatch_sha"
	case "status_fix":
		col = "last_status_fix_dispatch_sha"
	default:
		return fmt.Errorf("unknown dispatch type: %q", dispatchType)
	}

	query := fmt.Sprintf("UPDATE workflow_items SET %s = ?, updated_at = ?", col)
	args := []any{headSHA, Now()}

	if dispatchType == "fix" {
		query += ", iteration = iteration + 1"
	}
	query += " WHERE id = ?"
	args = append(args, itemID)

	_, err := s.db.Exec(query, args...)
	return err
}

func (s *Store) MarkReviewerDispatched(itemID, reviewer, headSHA string) error {
	var current string
	err := s.db.QueryRow(
		"SELECT reviewer_dispatch_shas_json FROM workflow_items WHERE id = ?", itemID,
	).Scan(&current)
	if err != nil {
		return fmt.Errorf("reading reviewer dispatch SHAs: %w", err)
	}

	shas := make(map[string]string)
	if current != "" {
		json.Unmarshal([]byte(current), &shas)
	}
	shas[reviewer] = headSHA

	data, _ := json.Marshal(shas)
	_, err = s.db.Exec(
		"UPDATE workflow_items SET reviewer_dispatch_shas_json = ?, updated_at = ? WHERE id = ?",
		string(data), Now(), itemID,
	)
	return err
}

func (s *Store) AcquireLock(name, owner string, durationSeconds int) (bool, error) {
	expiresAt := fmt.Sprintf("%d", durationSeconds)

	result, err := s.db.Exec(
		"INSERT OR IGNORE INTO locks (name, owner, expires_at) VALUES (?, ?, ?)",
		name, owner, expiresAt,
	)
	if err != nil {
		return false, fmt.Errorf("acquiring lock: %w", err)
	}

	rows, _ := result.RowsAffected()
	return rows > 0, nil
}

func (s *Store) ReleaseLock(name string) error {
	_, err := s.db.Exec("DELETE FROM locks WHERE name = ?", name)
	return err
}

func (s *Store) InsertSyncLog(startedAt, finishedAt string, itemsSynced int, errors string) (int64, error) {
	result, err := s.db.Exec(
		"INSERT INTO sync_log (started_at, finished_at, items_synced, errors) VALUES (?, ?, ?, ?)",
		startedAt, finishedAt, itemsSynced, errors,
	)
	if err != nil {
		return 0, err
	}
	return result.LastInsertId()
}

func (s *Store) InsertDispatchEvent(event DispatchEvent) error {
	_, err := s.db.Exec(
		"INSERT INTO dispatch_events (item_id, step_id, head_sha, agent, status, dispatched_at) VALUES (?, ?, ?, ?, ?, ?)",
		event.ItemID, event.StepID, event.HeadSHA, event.Agent, event.Status, event.DispatchedAt,
	)
	return err
}

func (s *Store) CacheAgentSelection(repo string, number int, agentID string) error {
	_, err := s.db.Exec(
		"INSERT OR REPLACE INTO agent_selections (repo, number, agent_id, created_at) VALUES (?, ?, ?, ?)",
		repo, number, agentID, Now(),
	)
	return err
}

func (s *Store) GetCachedAgentSelection(repo string, number int) (string, error) {
	var agentID string
	err := s.db.QueryRow(
		"SELECT agent_id FROM agent_selections WHERE repo = ? AND number = ?",
		repo, number,
	).Scan(&agentID)
	if err == sql.ErrNoRows {
		return "", nil
	}
	return agentID, err
}
