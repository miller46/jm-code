package cmd

import (
	"context"
	"fmt"
	"path/filepath"

	"github.com/spf13/cobra"

	"github.com/jack/go-cli/internal/agent"
	"github.com/jack/go-cli/internal/tools"
)

var submitReviewCmd = &cobra.Command{
	Use:   "submit-review",
	Short: "Submit a PR review for an agent",
	RunE: func(cmd *cobra.Command, args []string) error {
		reviewerID, _ := cmd.Flags().GetString("reviewer-id")
		repo, _ := cmd.Flags().GetString("repo")
		prNumber, _ := cmd.Flags().GetInt("pr-number")
		verdict, _ := cmd.Flags().GetString("verdict")
		body, _ := cmd.Flags().GetString("body")

		ghConfigDir := filepath.Join(agent.AgentHomeDir(reviewerID), "agent")

		ok, err := tools.SubmitReview(context.Background(), repo, prNumber, verdict, body, reviewerID, ghConfigDir)
		if err != nil {
			return fmt.Errorf("submit review failed: %w", err)
		}
		if !ok {
			return fmt.Errorf("review submission returned false")
		}

		fmt.Printf("Review submitted: %s on %s#%d\n", verdict, repo, prNumber)
		return nil
	},
}

func init() {
	submitReviewCmd.Flags().String("reviewer-id", "", "reviewer agent identifier (required)")
	submitReviewCmd.Flags().String("repo", "", "repository owner/name (required)")
	submitReviewCmd.Flags().Int("pr-number", 0, "pull request number (required)")
	submitReviewCmd.Flags().String("verdict", "", "approve, request_changes, or comment (required)")
	submitReviewCmd.Flags().String("body", "", "review body text (required)")

	submitReviewCmd.MarkFlagRequired("reviewer-id")
	submitReviewCmd.MarkFlagRequired("repo")
	submitReviewCmd.MarkFlagRequired("pr-number")
	submitReviewCmd.MarkFlagRequired("verdict")
	submitReviewCmd.MarkFlagRequired("body")

	rootCmd.AddCommand(submitReviewCmd)
}
