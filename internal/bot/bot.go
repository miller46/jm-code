// Package bot implements the main orchestrator loop: sync → dispatch on a timer.
package bot

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"time"

	"github.com/jack/go-cli/internal/config"
	"github.com/jack/go-cli/internal/db"
	gh "github.com/jack/go-cli/internal/github"
	"github.com/jack/go-cli/internal/workflow"
)

// Bot is the main orchestrator that syncs GitHub state and dispatches agents.
type Bot struct {
	Store     *db.Store
	ConfigDir string
	Interval  time.Duration
}

// Run starts the bot loop, syncing and dispatching on each tick.
// It shuts down gracefully when ctx is cancelled.
func (b *Bot) Run(ctx context.Context) error {
	slog.Info("bot starting", "interval", b.Interval, "configDir", b.ConfigDir)

	// Run immediately on start
	if err := b.tick(ctx); err != nil {
		slog.Error("initial tick failed", "err", err)
	}

	ticker := time.NewTicker(b.Interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			slog.Info("bot shutting down")
			return nil
		case <-ticker.C:
			if err := b.tick(ctx); err != nil {
				slog.Error("tick failed", "err", err)
			}
		}
	}
}

func (b *Bot) tick(ctx context.Context) error {
	slog.Info("starting sync cycle")
	startedAt := db.Now()

	// 1. Sync all enabled repos
	reposCfg, err := config.LoadRepos(b.ConfigDir)
	if err != nil {
		return fmt.Errorf("loading repos config: %w", err)
	}

	syncer := &gh.Syncer{
		Store:  b.Store,
		Client: &gh.CLIClient{},
		RequiredReviewers: func(repo string) []string {
			cfg, err := config.LoadReviewersForRepo(b.ConfigDir, repo)
			if err != nil {
				return nil
			}
			return cfg.ReviewerNames()
		},
		ApprovalRules: func(repo string) *gh.ApprovalRules {
			cfg, err := config.LoadReviewersForRepo(b.ConfigDir, repo)
			if err != nil {
				return nil
			}
			return &gh.ApprovalRules{
				Mode:              cfg.ApprovalRules.Mode,
				MinApprovals:      cfg.ApprovalRules.MinApprovals,
				RequiredReviewers: cfg.ApprovalRules.RequiredReviewers,
				VetoPowers:        cfg.ApprovalRules.VetoPowers,
			}
		},
		MaxIterations: 3,
	}

	totalSynced := 0
	var syncErrors []string

	for _, repo := range reposCfg.EnabledRepos() {
		if ctx.Err() != nil {
			return ctx.Err()
		}

		count, err := syncer.SyncRepo(ctx, repo)
		if err != nil {
			slog.Error("sync failed", "repo", repo, "err", err)
			syncErrors = append(syncErrors, fmt.Sprintf("%s: %v", repo, err))
			continue
		}
		totalSynced += count
	}

	finishedAt := db.Now()
	errJSON := "null"
	if len(syncErrors) > 0 {
		errJSON = fmt.Sprintf("%q", syncErrors)
	}
	b.Store.InsertSyncLog(startedAt, finishedAt, totalSynced, errJSON)

	slog.Info("sync complete", "items", totalSynced, "errors", len(syncErrors))

	// 2. Dispatch workflow tasks
	dispatcher := &workflow.Dispatcher{
		Store:     b.Store,
		ConfigDir: b.ConfigDir,
	}

	if err := dispatcher.RunAll(ctx); err != nil {
		return fmt.Errorf("dispatch: %w", err)
	}

	slog.Info("cycle complete")
	return nil
}

// DefaultDBPath returns the default database path.
func DefaultDBPath() string {
	home, _ := os.UserHomeDir()
	dir := filepath.Join(home, ".openclaw", "workspace-manager")
	os.MkdirAll(dir, 0755)
	return filepath.Join(dir, "workflow.db")
}
