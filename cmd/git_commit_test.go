package cmd

import (
	"testing"
)

func TestGitCommitCmd_RequiredFlags(t *testing.T) {
	tests := []struct {
		name    string
		args    []string
		wantErr bool
	}{
		{
			name:    "missing all flags",
			args:    []string{"git-commit"},
			wantErr: true,
		},
		{
			name:    "missing branch",
			args:    []string{"git-commit", "--agent-id", "dev", "--workspace", "/tmp", "--message", "fix"},
			wantErr: true,
		},
		{
			name:    "missing workspace",
			args:    []string{"git-commit", "--agent-id", "dev", "--branch", "main", "--message", "fix"},
			wantErr: true,
		},
		{
			name:    "missing message",
			args:    []string{"git-commit", "--agent-id", "dev", "--branch", "main", "--workspace", "/tmp"},
			wantErr: true,
		},
		{
			name:    "missing agent-id",
			args:    []string{"git-commit", "--branch", "main", "--workspace", "/tmp", "--message", "fix"},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cmd := rootCmd
			cmd.SetArgs(tt.args)
			err := cmd.Execute()
			if (err != nil) != tt.wantErr {
				t.Errorf("Execute() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func TestSubmitPRCmd_RequiredFlags(t *testing.T) {
	tests := []struct {
		name    string
		args    []string
		wantErr bool
	}{
		{
			name:    "missing all flags",
			args:    []string{"submit-pr"},
			wantErr: true,
		},
		{
			name:    "missing repo",
			args:    []string{"submit-pr", "--agent-id", "dev", "--head", "feat", "--title", "t", "--body", "b"},
			wantErr: true,
		},
		{
			name:    "missing head",
			args:    []string{"submit-pr", "--agent-id", "dev", "--repo", "o/r", "--title", "t", "--body", "b"},
			wantErr: true,
		},
		{
			name:    "missing title",
			args:    []string{"submit-pr", "--agent-id", "dev", "--repo", "o/r", "--head", "feat", "--body", "b"},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cmd := rootCmd
			cmd.SetArgs(tt.args)
			err := cmd.Execute()
			if (err != nil) != tt.wantErr {
				t.Errorf("Execute() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func TestSubmitReviewCmd_RequiredFlags(t *testing.T) {
	tests := []struct {
		name    string
		args    []string
		wantErr bool
	}{
		{
			name:    "missing all flags",
			args:    []string{"submit-review"},
			wantErr: true,
		},
		{
			name:    "missing repo",
			args:    []string{"submit-review", "--pr-number", "1", "--reviewer-id", "r", "--verdict", "approve", "--body", "lgtm"},
			wantErr: true,
		},
		{
			name:    "missing verdict",
			args:    []string{"submit-review", "--repo", "o/r", "--pr-number", "1", "--reviewer-id", "r", "--body", "lgtm"},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cmd := rootCmd
			cmd.SetArgs(tt.args)
			err := cmd.Execute()
			if (err != nil) != tt.wantErr {
				t.Errorf("Execute() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}
