package tools_test

import (
	"testing"

	"github.com/jack/go-cli/internal/tools"
)

func TestCleanBody(t *testing.T) {
	tests := []struct {
		name  string
		input string
		want  string
	}{
		{
			"literal newlines",
			`line1\nline2`,
			"line1\nline2",
		},
		{
			"header spacing",
			"text\n# Header",
			"text\n\n# Header",
		},
		{
			"closes on own line",
			"Description Closes #42",
			"Description\n\nCloses #42",
		},
		{
			"excessive blank lines",
			"a\n\n\n\nb",
			"a\n\nb",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := tools.CleanBody(tt.input)
			if got != tt.want {
				t.Errorf("CleanBody() = %q, want %q", got, tt.want)
			}
		})
	}
}
