package cmd

import (
	"context"
	"encoding/json"
	"fmt"
	"path/filepath"

	"github.com/spf13/cobra"

	"github.com/jack/go-cli/internal/agent"
	"github.com/jack/go-cli/internal/tools"
)

var submitPRCmd = &cobra.Command{
	Use:   "submit-pr",
	Short: "Create a pull request for an agent",
	RunE: func(cmd *cobra.Command, args []string) error {
		agentID, _ := cmd.Flags().GetString("agent-id")
		repo, _ := cmd.Flags().GetString("repo")
		head, _ := cmd.Flags().GetString("head")
		base, _ := cmd.Flags().GetString("base")
		title, _ := cmd.Flags().GetString("title")
		body, _ := cmd.Flags().GetString("body")
		issueNumber, _ := cmd.Flags().GetInt("issue-number")
		draft, _ := cmd.Flags().GetBool("draft")
		labels, _ := cmd.Flags().GetStringSlice("label")

		ghConfigDir := filepath.Join(agent.AgentHomeDir(agentID), "agent")

		result := tools.SubmitPR(context.Background(), repo, head, base, title, body, issueNumber, ghConfigDir, draft, labels)

		out, _ := json.Marshal(result)
		fmt.Println(string(out))

		if !result.Success {
			return fmt.Errorf("submit PR failed: %s", result.Error)
		}
		return nil
	},
}

func init() {
	submitPRCmd.Flags().String("agent-id", "", "agent identifier (required)")
	submitPRCmd.Flags().String("repo", "", "repository owner/name (required)")
	submitPRCmd.Flags().String("head", "", "head branch (required)")
	submitPRCmd.Flags().String("base", "main", "base branch")
	submitPRCmd.Flags().String("title", "", "PR title (required)")
	submitPRCmd.Flags().String("body", "", "PR body")
	submitPRCmd.Flags().Int("issue-number", 0, "linked issue number")
	submitPRCmd.Flags().Bool("draft", false, "create as draft PR")
	submitPRCmd.Flags().StringSlice("label", nil, "labels to add")

	submitPRCmd.MarkFlagRequired("agent-id")
	submitPRCmd.MarkFlagRequired("repo")
	submitPRCmd.MarkFlagRequired("head")
	submitPRCmd.MarkFlagRequired("title")

	rootCmd.AddCommand(submitPRCmd)
}
