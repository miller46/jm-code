

def get_reviewer_prompt(reviewer_id:str, repo:str, pr_number:str) -> str:
    return (
        f"You are reviewer agent \"{reviewer_id}\" for PR #{pr_number} in {repo}.\n\n"
        "Your job is ONLY:\n"
        "1) Determine review outcome.\n"
        "2) Submit it via submit_pr_review.\n\n"
        "Process:\n"
        "- Review the PR and decide verdict: \"approve\" or \"request_changes\".\n"
        "- Write concise, actionable review text in \"body\".\n"
        "- Call submit_pr_review with:\n"
        f" - repo: \"{repo}\"\n"
        f" - prNumber: {pr_number}\n"
        f" - reviewerId: \"{reviewer_id}\"\n"
        " - verdict: <approve|request_changes>\n"
        " - body: <review comments>\n\n"
        "Output rules:\n"
        "- If submit_pr_review succeeds, reply exactly valid JSON:\n"
        " {{\"status\":\"submitted\",\"verdict\":\"approve|request_changes\"}}\n"
        "- If submit_pr_review fails, reply exactly valid JSON:\n"
        " {{\"status\":\"failed\",\"error\":\"<tool error>\"}}\n\n"
        "Constraints:\n"
        "- Do NOT fetch queue items.\n"
        "- Do NOT spawn other agents.\n"
        "- Do NOT mark dispatched.\n"
        "- Do NOT send summary messages.\n"
        "- Do NOT use gh pr review directly."
    )

# TODO custom tool for submitting PR fixes (add dispatch)
def get_pr_fix_prompt(reviewer_id:str, repo:str, pr_number:str) -> str:
    return (
        f"You are reviewer agent \"{reviewer_id}\" tasked with fixing PR #{pr_number} in {repo}.\n\n"
        f"You must commit code changes to the same branch as the pull request.\n" 
        f"Do NOT open a new pull request."
    )

# TODO custom tool for submitting merge conflict fixes (this could maybe be the same as "fix" with like one line added about conflicts)
def get_pr_conflicts_prompt(reviewer_id:str, repo:str, pr_number:str) -> str:
    return (
        f"You are reviewer agent \"{reviewer_id}\" tasked with fixing the merge conflicts in PR #{pr_number} in {repo}.\n\n"
        f"You must commit code changes to the same branch as the pull request.\n" 
        f"Do NOT open a new pull request."
    )
