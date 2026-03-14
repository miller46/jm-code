package tools

import (
	"context"
	"os/exec"
)

type ShellTool struct{}

func (t ShellTool) Name() string {
	return "shell"
}

func (t ShellTool) Run(ctx context.Context, input string) (string, error) {
	cmd := exec.CommandContext(ctx, "bash", "-c", input)
	out, err := cmd.CombinedOutput()
	return string(out), err
}
