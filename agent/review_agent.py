from config.openclaw import SUBMIT_PR_TOOL_FILE_LOCATION

def get_reviewer_prompt(reviewer_id:str, repo:str, pr_number:str, branch:str) -> str:
    return (
f"""You are tasked with code reviewing PR #{pr_number} in {repo}.

Your job is ONLY:
1) Determine review verdict: "approve" or "request_changes".
2) Write concise, actionable review text in "body".
3) Submit verdict and body via submit_pr_review.

CRITICAL - REVIEW LATEST HEAD:
You MUST look at the LATEST HEAD of the PR branch, not cached or old reviews:

1. Fetch latest: git fetch origin
2. Check out PR branch: git checkout {branch}
3. Read the ACTUAL current code files (cat/view them)
4. Check: gh pr view {pr_number} --comments (for context)
5. If you or another reviewer previously requested changes:
   - VERIFY if those fixes are NOW in the latest HEAD code
   - If YES → approve (don't repeat stale feedback)
   - If NO → request_changes with specific remaining issues

DO NOT submit "request_changes" based on old review memory. 
Only reject if the CURRENT CODE at HEAD is actually wrong.

To submit the review, run this exact command:
python3 {SUBMIT_PR_TOOL_FILE_LOCATION} \
  --repo "{repo}" \
  --pr-number {pr_number} \
  --reviewer-id {reviewer_id} \
  --verdict <approve|request_changes> \
  --body "<review text>"
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
