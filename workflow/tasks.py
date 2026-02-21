from github.get_open_prs import PRQueueClient, _suggest_agent
from github.get_open_issues import IssueQueueClient
from github.merge import merge_pr
from agent import spawn_agent, review_agent, dev_agent
from workflow import get_reviewers, get_review_policy
from config import DEFAULT_DEV_AGENT

def dev_open_issues(client:IssueQueueClient):
    issue_response = client.query()
    for issue in issue_response["issues"]:
        # todo have manager pick the dev
        description = issue["title"]
        issue_number = issue["number"]
        repo = issue["repo"]
        agent_id = _suggest_agent(title=description, labels=[], default_agent=DEFAULT_DEV_AGENT)
        task = dev_agent.get_dev_prompt(repo=repo, issue_number=issue_number)
        print(task)
        spawn_agent(f"{repo}#{issue_number}", task=task, agent_id=agent_id)
        print(f"Spawned DEV for Issue #{issue_number} by agent {agent_id}")

def review_open_prs(client:PRQueueClient):
    review_response = client.query(action="needs_review", limit=10)
    print(f"Found {review_response['counts']['returned']} PRs needing review")
    for pr in review_response["prs"]:
        pr_number = pr["prNumber"]
        print(f"Init review for PR #{pr_number}")
        repo = pr["repo"]
        reviewers = get_reviewers(repo)
        for reviewer in reviewers:
            agent_id = reviewer["agent"]
            if 'enabled' in reviewer and not reviewer['enabled']:
                print(f"Skipping. Agent {agent_id} disabled")
                continue
            branch = pr['headRefName']
            task = review_agent.get_reviewer_prompt(reviewer_id=agent_id, repo=repo, pr_number=pr_number, branch=branch)
            print(task)
            spawn_agent(f"{repo}#{pr_number}", task=task, agent_id=agent_id)
            print(f"Spawned REVIEW for PR #{pr_number} by agent {agent_id}")

def fix_open_prs(client:PRQueueClient):
    fixes_response = client.query(action="needs_fix", limit=10)
    print(f"Found {fixes_response['counts']['returned']} PRs needing fixes")
    for pr in fixes_response["prs"]:
        pr_number = pr["prNumber"]
        print(f"Init fix for PR #{pr['prNumber']}")
        repo = pr["repo"]
        description = pr["title"]
        # todo have manager pick the dev
        agent_id = _suggest_agent(title=description, labels=[], default_agent=DEFAULT_DEV_AGENT)
        branch = pr['headRefName']
        task = review_agent.get_pr_fix_prompt(repo=repo, pr_number=pr_number, branch=branch)
        print(task)
        spawn_agent(f"{repo}#{pr_number}", agent_id=agent_id, task=task)

def fix_pr_merge_conflicts(client:PRQueueClient):
    conflicts_response = client.query(action="needs_conflict_resolution", limit=10)
    print(f"Found {conflicts_response['counts']['returned']} PRs needing conflict resolution")
    for pr in conflicts_response["prs"]:
        print(f"Init merge conflict fix for PR #{pr['prNumber']}")
        pr_number = pr["prNumber"]
        repo = pr["repo"]
        description = pr["title"]
        agent_id = _suggest_agent(title=description, labels=[], default_agent=DEFAULT_DEV_AGENT)
        branch = pr['headRefName']
        task = review_agent.get_pr_conflicts_prompt(repo=repo, pr_number=pr_number, branch=branch)
        print(task)
        spawn_agent(f"{repo}#{pr_number}", agent_id=agent_id, task=task)
        print(f"Spawned MERGE CONFLICT FIX for PR #{pr['prNumber']} by {agent_id}")

def merge_prs(client:PRQueueClient):
    merges_response = client.query(action="ready_to_merge", limit=10)
    print(f"Found {merges_response['counts']['returned']} PRs ready to merge")
    for pr in merges_response["prs"]:
        repo = pr["repo"]
        pr_number = pr["prNumber"]
        print(f"Init merge for PR #{pr_number}")
        result = merge_pr(repo, pr_number)
        if result["success"]:
            print(f"Merged PR #{pr_number} in {repo}")
        else:
            print(f"Failed to merge PR #{pr_number} in {repo}: {result['error']}")
