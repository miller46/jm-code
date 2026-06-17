package bot

import (
	"context"
	"encoding/json"
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

type Bot struct {
	Store     *db.Store
	ConfigDir string
	Interval  time.Duration

	dispatcher *workflow.Dispatcher
}

func (b *Bot) Run(ctx context.Context) error {
	slog.Info("bot starting", "interval", b.Interval, "configDir", b.ConfigDir)

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
			return &cfg.ApprovalRules
		},
		MaxIterations: 3,
		DevTimeout:    45 * time.Minute,
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
		if data, err := json.Marshal(syncErrors); err == nil {
			errJSON = string(data)
		}
	}
	b.Store.InsertSyncLog(startedAt, finishedAt, totalSynced, errJSON)

	slog.Info("sync complete", "items", totalSynced, "errors", len(syncErrors))

	if b.dispatcher == nil {
		b.dispatcher = &workflow.Dispatcher{
			Store:     b.Store,
			ConfigDir: b.ConfigDir,
		}
	}

	if err := b.dispatcher.RunAll(ctx); err != nil {
		return fmt.Errorf("dispatch: %w", err)
	}

	slog.Info("cycle complete")
	return nil
}

func DefaultDBPath() string {
	home, _ := os.UserHomeDir()
	dir := filepath.Join(home, ".openclaw", "workspace-manager")
	os.MkdirAll(dir, 0755)
	return filepath.Join(dir, "workflow.db")
}
