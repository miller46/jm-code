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

var gitCommitCmd = &cobra.Command{
	Use:   "git-commit",
	Short: "Commit and push changes for an agent",
	RunE: func(cmd *cobra.Command, args []string) error {
		agentID, _ := cmd.Flags().GetString("agent-id")
		branch, _ := cmd.Flags().GetString("branch")
		workspace, _ := cmd.Flags().GetString("workspace")
		message, _ := cmd.Flags().GetString("message")

		ghConfigDir := filepath.Join(agent.AgentHomeDir(agentID), "agent")

		result := tools.GitCommitAndPush(context.Background(), branch, message, workspace, ghConfigDir)

		out, _ := json.Marshal(result)
		fmt.Println(string(out))

		if !result.Success {
			return fmt.Errorf("git commit failed: %s", result.Details)
		}
		return nil
	},
}

func init() {
	gitCommitCmd.Flags().String("agent-id", "", "agent identifier (required)")
	gitCommitCmd.Flags().String("branch", "", "branch to commit and push to (required)")
	gitCommitCmd.Flags().String("workspace", "", "workspace directory (required)")
	gitCommitCmd.Flags().String("message", "", "commit message (required)")

	gitCommitCmd.MarkFlagRequired("agent-id")
	gitCommitCmd.MarkFlagRequired("branch")
	gitCommitCmd.MarkFlagRequired("workspace")
	gitCommitCmd.MarkFlagRequired("message")

	rootCmd.AddCommand(gitCommitCmd)
}
