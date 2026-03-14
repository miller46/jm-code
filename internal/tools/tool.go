package tools

import "context"

type Tool interface {
	Name() string
	Run(ctx context.Context, input string) (string, error)
}
