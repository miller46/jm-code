from github.get_open_prs import PRQueueClient, _suggest_agent
from github.merge import merge_pr
from agent import spawn_fix_agent, review_agent
from workflow import get_reviewers, get_review_policy


def review_open_prs(client:PRQueueClient):
    review = client.query(action="needs_review", limit=10)
    print(f"Found {review['counts']['returned']} PRs needing review")
    for pr in review["prs"]:
        pr_number = pr["prNumber"]
        print(f"Init review for PR #{pr_number}")
        repo = pr["repo"]
        reviewers = get_reviewers(repo)
        for reviewer in reviewers:
            agent_id = reviewer["agent"]
            if 'enabled' in reviewer and not reviewer['enabled']:
                print(f"Skipping. Agent {agent_id} disabled")
                continue
            task = review_agent.get_reviewer_prompt(reviewer_id=agent_id, repo=repo, pr_number=pr_number)
            print(task)
            spawn_fix_agent(pr, task=task, agent_id=agent_id)
            print(f"Spawned review for PR #{pr_number} by agent {agent_id}")

def fix_open_prs(client:PRQueueClient):
    fixes = client.query(action="needs_fix", limit=10)
    print(f"Found {fixes['counts']['returned']} PRs needing fixes")
    for pr in fixes["prs"]:
        pr_number = pr["prNumber"]
        print(f"Init fix for PR #{pr['prNumber']}")
        repo = pr["repo"]
        description = pr["title"]
        # todo have manager pick the dev
        agent_id = _suggest_agent(title=description, labels=[], default_agent="backend-dev")
        task = review_agent.get_pr_fix_prompt(repo=repo, pr_number=pr_number)
        print(task)
        spawn_fix_agent(pr, task=task)

def fix_pr_merge_conflicts(client:PRQueueClient):
    conflicts = client.query(action="needs_conflict_resolution", limit=10)
    print(f"Found {conflicts['counts']['returned']} PRs needing conflict resolution")
    for pr in conflicts["prs"]:
        print(f"Init merge conflict fix for PR #{pr['prNumber']}")
        pr_number = pr["prNumber"]
        repo = pr["repo"]
        description = pr["title"]
        agent_id = _suggest_agent(title=description, labels=[], default_agent="backend-dev")
        task = review_agent.get_pr_conflicts_prompt(repo=repo, pr_number=pr_number)
        print(task)
        spawn_fix_agent(pr, task=task)

def merge_prs(client:PRQueueClient):
    merges = client.query(action="ready_to_merge", limit=10)
    print(f"Found {merges['counts']['returned']} PRs ready to merge")
    for pr in merges["prs"]:
        repo = pr["repo"]
        pr_number = pr["prNumber"]
        print(f"Init merge for PR #{pr_number}")
        result = merge_pr(repo, pr_number)
        if result["success"]:
            print(f"Merged PR #{pr_number} in {repo}")
        else:
            print(f"Failed to merge PR #{pr_number} in {repo}: {result['error']}")
