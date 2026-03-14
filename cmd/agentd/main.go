package main

import (
	"context"
	"fmt"

	"github.com/jack/go-cli/internal/agent"
	"github.com/jack/go-cli/internal/tools"
)

func main() {
	a := agent.Agent{
		Name:  "agentdeeznuts",
		Tools: []tools.Tool{tools.ShellTool{}},
	}

	fmt.Printf("agent %q loaded with %d tool(s)\n", a.Name, len(a.Tools))
	for _, t := range a.Tools {
		fmt.Printf("%q\n", t.Name())
	}

	out, err := a.Tools[0].Run(context.Background(), "echo hello from agentd")
	if err != nil {
		fmt.Printf("error: %v\n", err)
		return
	}
	fmt.Print(out)
}
