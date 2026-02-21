from config.tools import SUBMIT_PR_TOOL_FILE_LOCATION

def get_dev_prompt(agent_id: str, repo: str, issue_number: str) -> str:
    return (
f"""Implement issue #{issue_number} in {repo}.

1. Read the issue: gh issue view {issue_number} --repo {repo}
2. Create branch: git checkout -b feature/issue-{issue_number} origin/main
3. Implement the fix/feature
4. Run tests to verify
5. Commit and push to origin
6. Make a concise title and a clear description in markdown format that includes "Fixes {issue_number}" at the bottom
7. Double check the description includes "Fixes {issue_number} at the bottom
8. Open PR using: python3 {SUBMIT_PR_TOOL_FILE_LOCATION} --agentId {agent_id} --repo {repo} --head <branch> --base main --title <title> --body <description>

Return the PR URL when done.
"""
    )

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

def get_pr_fix_status_checks_prompt(repo:str, pr_number:str, branch:str) -> str:
    return (
f"""Fix failing automated status checks for PR #{pr_number} in {repo} on branch {branch}.

Before changing code, you MUST:
1) Read PR discussion + review feedback:
- gh pr view {pr_number} --comments --repo {repo}
- gh api repos/{repo}/pulls/{pr_number}/comments
2) Identify the latest review that requested changes.
3) Make only the changes needed to satisfy that feedback and get checks green.

Rules:
- Focus on fixing CI/status checks (e.g., GitHub Actions failures).
- No unrelated refactors, features, or extra tests unless required to fix checks/review comments.
- Commit directly to branch {branch}.
- Do NOT open a new PR.
"""
    )
