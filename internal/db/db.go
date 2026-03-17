package db

import (
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	_ "modernc.org/sqlite"
)

func IsNotFound(err error) bool {
	return errors.Is(err, sql.ErrNoRows)
}

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
			last_dev_dispatch_at TEXT DEFAULT '',
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
	if err != nil {
		return err
	}

	// Add columns that may not exist on older databases.
	migrations := []string{
		"ALTER TABLE workflow_items ADD COLUMN last_dev_dispatch_at TEXT DEFAULT ''",
	}
	for _, m := range migrations {
		s.db.Exec(m) // ignore "duplicate column" errors
	}

	return nil
}

func (s *Store) UpsertWorkflowItem(item WorkflowItem) error {
	query := fmt.Sprintf(
		"INSERT OR REPLACE INTO workflow_items (%s) VALUES (%s)",
		workflowItemColumns, workflowItemPlaceholders,
	)
	_, err := s.db.Exec(query, item.values()...)
	return err
}

func (s *Store) GetWorkflowItem(id string) (*WorkflowItem, error) {
	query := fmt.Sprintf("SELECT %s FROM workflow_items WHERE id = ?", workflowItemColumns)
	row := s.db.QueryRow(query, id)

	var item WorkflowItem
	if err := row.Scan(item.scanDest()...); err != nil {
		return nil, fmt.Errorf("getting workflow item %q: %w", id, err)
	}
	return &item, nil
}

func (s *Store) QueryWorkflowItems(itemType, action, repo string, limit int) ([]WorkflowItem, error) {
	query := fmt.Sprintf("SELECT %s FROM workflow_items WHERE type = ? AND action = ?", workflowItemColumns)
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
		if err := rows.Scan(item.scanDest()...); err != nil {
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

// dispatchQueries maps dispatch type to the corresponding UPDATE query.
// Using pre-built queries instead of fmt.Sprintf with column names.
var dispatchQueries = map[string]string{
	"review":     "UPDATE workflow_items SET last_review_dispatch_sha = ?, updated_at = ? WHERE id = ?",
	"fix":        "UPDATE workflow_items SET last_fix_dispatch_sha = ?, updated_at = ?, iteration = iteration + 1 WHERE id = ?",
	"merge":      "UPDATE workflow_items SET last_merge_dispatch_sha = ?, updated_at = ? WHERE id = ?",
	"conflict":   "UPDATE workflow_items SET last_conflict_dispatch_sha = ?, updated_at = ? WHERE id = ?",
	"status_fix": "UPDATE workflow_items SET last_status_fix_dispatch_sha = ?, updated_at = ? WHERE id = ?",
}

func (s *Store) SetLastDevDispatchAt(itemID string) error {
	_, err := s.db.Exec(
		"UPDATE workflow_items SET last_dev_dispatch_at = ?, updated_at = ? WHERE id = ?",
		Now(), Now(), itemID,
	)
	return err
}

func (s *Store) MarkDispatched(itemID, dispatchType, headSHA string) error {
	query, ok := dispatchQueries[dispatchType]
	if !ok {
		return fmt.Errorf("unknown dispatch type: %q", dispatchType)
	}
	_, err := s.db.Exec(query, headSHA, Now(), itemID)
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
		if err := json.Unmarshal([]byte(current), &shas); err != nil {
			return fmt.Errorf("parsing reviewer dispatch SHAs JSON: %w", err)
		}
	}
	shas[reviewer] = headSHA

	data, err := json.Marshal(shas)
	if err != nil {
		return fmt.Errorf("marshaling reviewer dispatch SHAs: %w", err)
	}
	_, err = s.db.Exec(
		"UPDATE workflow_items SET reviewer_dispatch_shas_json = ?, updated_at = ? WHERE id = ?",
		string(data), Now(), itemID,
	)
	return err
}

func (s *Store) AcquireLock(name, owner string, duration time.Duration) (bool, error) {
	expiresAt := time.Now().UTC().Add(duration).Format(time.RFC3339)

	result, err := s.db.Exec(
		`INSERT INTO locks (name, owner, expires_at) VALUES (?, ?, ?)
		 ON CONFLICT(name) DO UPDATE SET owner = excluded.owner, expires_at = excluded.expires_at
		 WHERE expires_at < ?`,
		name, owner, expiresAt, Now(),
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

// PruneStaleItems marks items for a repo that were not seen in the current
// sync cycle (i.e. not in seenIDs) and still have an active action as
// action="none". Returns the number of items pruned.
func (s *Store) PruneStaleItems(repo string, seenIDs []string) (int, error) {
	if len(seenIDs) == 0 {
		res, err := s.db.Exec(
			"UPDATE workflow_items SET action = 'none', updated_at = ? WHERE repo = ? AND action != 'none'",
			Now(), repo,
		)
		if err != nil {
			return 0, err
		}
		n, _ := res.RowsAffected()
		return int(n), nil
	}

	placeholders := make([]string, len(seenIDs))
	args := []any{Now(), repo}
	for i, id := range seenIDs {
		placeholders[i] = "?"
		args = append(args, id)
	}

	query := fmt.Sprintf(
		"UPDATE workflow_items SET action = 'none', updated_at = ? WHERE repo = ? AND action != 'none' AND id NOT IN (%s)",
		strings.Join(placeholders, ", "),
	)
	res, err := s.db.Exec(query, args...)
	if err != nil {
		return 0, err
	}
	n, _ := res.RowsAffected()
	return int(n), nil
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
