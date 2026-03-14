package agent

import "fmt"

func GetReviewerPrompt(reviewerID, repo string, prNumber int, workspace, taskFile, submitReviewTool string) string {
	return fmt.Sprintf(`IMMEDIATELY execute: cd %s

Read the task file for PR context: %s

You are reviewing PR #%d in %s.

Steps:
1. Read the task file to understand the PR's purpose and changes
2. CRITICAL: Review the LATEST HEAD — read actual current code files, not cached reviews
3. Check if previous review feedback has been addressed in the latest code
4. Determine your verdict: approve or request_changes

Review criteria:
- Code correctness and logic
- Test coverage
- Error handling
- Code style and conventions
- Security considerations

Submit your verdict using:
%s --repo %s --pr-number %d --reviewer-id %s --verdict <approve|request_changes> --body "<detailed review feedback>"

Important:
- Be thorough but fair
- Provide specific, actionable feedback
- If requesting changes, explain exactly what needs to change and why
- If approving, confirm what you verified`,
		workspace,
		taskFile,
		prNumber, repo,
		submitReviewTool, repo, prNumber, reviewerID,
	)
}
