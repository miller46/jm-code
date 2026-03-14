package cmd

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/spf13/cobra"

	"github.com/jack/go-cli/internal/bot"
	"github.com/jack/go-cli/internal/db"
)

var (
	interval  int
	configDir string
	dbPath    string
)

// rootCmd is the main "run" command that starts the bot loop.
var rootCmd = &cobra.Command{
	Use:   "orchestrator",
	Short: "GitHub dev lifecycle orchestrator — sync, dispatch, review, fix, merge",
	RunE: func(cmd *cobra.Command, args []string) error {
		// Set up structured logging
		slog.SetDefault(slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{
			Level: slog.LevelInfo,
		})))

		// Resolve defaults
		if dbPath == "" {
			dbPath = bot.DefaultDBPath()
		}

		// Open database
		store, err := db.Open(dbPath)
		if err != nil {
			return fmt.Errorf("opening database: %w", err)
		}
		defer store.Close()

		// Create bot
		b := &bot.Bot{
			Store:     store,
			ConfigDir: configDir,
			Interval:  time.Duration(interval) * time.Second,
		}

		// Graceful shutdown via OS signals
		ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
		defer cancel()

		slog.Info("starting orchestrator",
			"interval", interval,
			"configDir", configDir,
			"dbPath", dbPath,
		)

		return b.Run(ctx)
	},
}

func init() {
	rootCmd.Flags().IntVar(&interval, "interval", 600, "sync interval in seconds")
	rootCmd.Flags().StringVar(&configDir, "config", "config", "path to config directory")
	rootCmd.Flags().StringVar(&dbPath, "db", "", "path to SQLite database (default: ~/.openclaw/workspace-manager/workflow.db)")
}

// Execute runs the root command.
func Execute() {
	if err := rootCmd.Execute(); err != nil {
		os.Exit(1)
	}
}
