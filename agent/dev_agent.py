from config.openclaw import SUBMIT_PR_TOOL_FILE_LOCATION

def get_dev_prompt(repo: str, issue_number: str) -> str:
    return f"""You are tasked with implementing issue #{issue_number} in {repo}.

STEP 1 - READ AND UNDERSTAND THE ISSUE:
Run: gh issue view {issue_number} --repo {repo}
Read the title, body, and all comments. Understand exactly what needs to be implemented.

STEP 2 - CHECKOUT AND BRANCH:
git checkout main
git pull origin main
git checkout -b feature/issue-{issue_number}-$(echo "{{issue_title}}" | tr ' ' '-' | tr '[:upper:]' '[:lower:]' | cut -c1-30)

STEP 3 - IMPLEMENT:
1. Make code changes to address the issue
2. Add/update tests as needed
3. Run tests locally: uv run pytest -q (or equivalent)
4. Run linting: uv run ruff check . (or equivalent)

STEP 4 - COMMIT AND PUSH:
git add .
git commit -m "fix: implement #{issue_number} - {{brief_description}}

- Detailed change 1
- Detailed change 2

Fixes #{issue_number}"
git push origin $(git branch --show-current)

STEP 5 - OPEN PULL REQUEST:
Run this exact command:
python3 {SUBMIT_PR_TOOL_FILE_LOCATION} \
  --repo "{repo}" \
  --head "$(git branch --show-current)" \
  --base "main" \
  --title "fix: {{descriptive_title}} (#{issue_number})" \
  --body "## Summary
Implements #{issue_number}

### Changes
- Change 1
- Change 2

### Testing
- [x] Tests added/updated
- [x] Local test run passed

Fixes #{issue_number}"

STEP 6 - REPORT BACK:
Return this exact JSON format:
{{
  "issue": "{issue_number}",
  "repo": "{repo}",
  "branch": "$(git branch --show-current)",
  "commit": "$(git rev-parse HEAD)",
  "pr_url": "{{PR_URL_FROM_STEP_5}}",
  "status": "completed"
}}

If any step fails, return:
{{
  "issue": "{issue_number}",
  "status": "failed",
  "failed_step": "{{step_number}}",
  "error": "{{exact_error_message}}",
  "last_successful_step": "{{step_number}}"
}}
"""

# TODO custom tool for submitting PR fixes (add dispatch)
def get_pr_fix_prompt(repo:str, pr_number:str, branch:str) -> str:
    return (
f"""You are tasked with fixing PR #{pr_number} in {repo}.
The PR is on branch: {branch}

CRITICAL: Before making any changes, you MUST:
1. Read the PR comments and review feedback using `gh pr view {pr_number} --comments` or `gh api repos/{repo}/pulls/{pr_number}/comments`
2. Read the latest review that requested changes
3. Understand exactly what fixes are being requested
4. Make THOSE specific fixes — not other changes

The reviewer is requesting changes. Address their specific concerns. Do NOT add unrelated tests or features

You must commit code changes to THIS EXACT BRANCH: {branch}
Do NOT open a new pull request.
"""
    )

# TODO custom tool for submitting merge conflict fixes
#  (this could maybe be combined with "fix" with one line added about conflicts)
def get_pr_conflicts_prompt(repo:str, pr_number:str, branch:str) -> str:
    return (
f"""Fix merge conflicts in PR #{pr_number} in {repo}.

The PR is on branch: {branch}

STEP 1 - ASSESS THE CONFLICTS:
Run: git status
Identify all files with merge conflicts.

STEP 2 - UNDERSTAND THE CHANGES:
For each conflicted file:
- View the conflict markers to see what changed
- Understand what both sides were trying to do
- git log --oneline origin/main..HEAD (to see your branch's commits)
- git log --oneline HEAD..origin/main (to see what main added)

STEP 3 - RESOLVE CONFLICTS:
- Edit each conflicted file to resolve conflicts logically
- Do NOT just pick "ours" or "theirs" blindly
- Ensure the code still makes sense after resolution
- Remove all conflict markers (<<<<<<, =======, >>>>>>>)

STEP 4 - VALIDATE:
- Stage resolved files: git add <files>
- Commit the merge: git commit (accept default message)
- Push to branch: git push origin {branch}
- Run tests if available to ensure resolution didn't break anything

You must commit to THIS EXACT BRANCH: {branch}
Do NOT open a new pull request.
"""
    )
