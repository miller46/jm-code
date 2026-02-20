from config.openclaw import SUBMIT_PR_TOOL_FILE_LOCATION

def get_reviewer_prompt(reviewer_id:str, repo:str, pr_number:str) -> str:
    return (
f"""You are tasked with code reviewing PR #{pr_number} in {repo}...

Your job is ONLY:
1) Determine review verdict: "approve" or "request_changes".
2) Write concise, actionable review text in "body".
3) Submit verdict and body via submit_pr_review.

To submit the review, run this exact command:
python3 {SUBMIT_PR_TOOL_FILE_LOCATION} \
  --repo "{repo}" \
  --pr-number {pr_number} \
  --reviewer-id {reviewer_id} \
  --verdict <approve|request_changes> \
  --body "<review text>"

Wait for the command to complete and parse its JSON output.
"""
    )

# TODO custom tool for submitting PR fixes (add dispatch)
def get_pr_fix_prompt(repo:str, pr_number:str) -> str:
    return (
        f"You are tasked with fixing PR #{pr_number} in {repo}.\n\n"
        f"You must commit code changes to the same branch as the pull request.\n" 
        f"Do NOT open a new pull request."
    )

# TODO custom tool for submitting merge conflict fixes
#  (this could maybe be combined with "fix" with one line added about conflicts)
def get_pr_conflicts_prompt(repo:str, pr_number:str) -> str:
    return (
        f"You are tasked with fixing the merge conflicts in PR #{pr_number} in {repo}.\n\n"
        f"You must commit code changes to the same branch as the pull request.\n" 
        f"Do NOT open a new pull request."
    )
