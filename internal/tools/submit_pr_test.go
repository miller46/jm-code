package tools_test

import (
	"testing"

	"github.com/jack/go-cli/internal/tools"
)

func TestEnsureIssueLink(t *testing.T) {
	tests := []struct {
		name        string
		body        string
		issueNumber int
		want        string
	}{
		{
			"appends when missing",
			"Some description",
			42,
			"Some description\n\nCloses #42",
		},
		{
			"no-op when Closes already present",
			"Some description\n\nCloses #42",
			42,
			"Some description\n\nCloses #42",
		},
		{
			"no-op when Fixes #N present",
			"Some description\n\nFixes #42",
			42,
			"Some description\n\nFixes #42",
		},
		{
			"no-op when Resolves #N present",
			"Resolves #42\n\nSome description",
			42,
			"Resolves #42\n\nSome description",
		},
		{
			"zero issue number does nothing",
			"Some description",
			0,
			"Some description",
		},
		{
			"appends even when body mentions issue without keyword",
			"Related to #42",
			42,
			"Related to #42\n\nCloses #42",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := tools.EnsureIssueLink(tt.body, tt.issueNumber)
			if got != tt.want {
				t.Errorf("EnsureIssueLink() = %q, want %q", got, tt.want)
			}
		})
	}
}

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
