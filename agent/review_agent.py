from config.tools import SUBMIT_PR_REVIEW_TOOL_FILE_LOCATION

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
python3 {SUBMIT_PR_REVIEW_TOOL_FILE_LOCATION} \
  --repo "{repo}" \
  --pr-number {pr_number} \
  --reviewer-id {reviewer_id} \
  --verdict <approve|request_changes> \
  --body "<review text>"
"""
    )
