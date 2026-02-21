import logging

from tools.get_open_prs import PRQueueClient, _suggest_agent
from tools.get_open_issues import IssueQueueClient
from github.merge import merge_pr
from agent import spawn_agent, review_agent, dev_agent
from workflow import get_reviewers
from config import DEFAULT_DEV_AGENT

logger = logging.getLogger(__name__)

def dev_open_issues(client:IssueQueueClient):
    issue_response = client.query()
    for issue in issue_response["issues"]:
        # todo have manager pick the dev
        description = issue["title"]
        issue_number = issue["issueNumber"]
        repo = issue["repo"]
        agent_id = _suggest_agent(title=description, labels=[], default_agent=DEFAULT_DEV_AGENT)
        prompt = dev_agent.get_dev_prompt(agent_id=agent_id, repo=repo, issue_number=issue_number)
        logger.debug("prompt: %s", prompt)
        spawn_agent(f"{repo}#{issue_number}", prompt=prompt, agent_id=agent_id)
        logger.info("Spawned DEV for Issue #%s by agent %s", issue_number, agent_id)
    return len(issue_response["issues"])

def review_open_prs(client:PRQueueClient):
    review_response = client.query(action="needs_review", limit=10)
    logger.info("Found %s PRs needing review", review_response['counts']['returned'])
    for pr in review_response["prs"]:
        pr_number = pr["prNumber"]
        logger.info(f"Init review for PR #{pr_number}")
        repo = pr["repo"]
        reviewers = get_reviewers(repo)
        for reviewer in reviewers:
            agent_id = reviewer["agent"]
            if 'enabled' in reviewer and not reviewer['enabled']:
                logger.info("Skipping. Agent %s disabled", agent_id)
                continue
            branch = pr['headRefName']
            prompt = review_agent.get_reviewer_prompt(reviewer_id=agent_id, repo=repo, pr_number=pr_number, branch=branch)
            logger.debug("prompt: %s", prompt)
            spawn_agent(f"{repo}#{pr_number}", prompt=prompt, agent_id=agent_id)
            logger.info(f"Spawned REVIEW for PR #{pr_number} in {repo} by agent {agent_id}")
    return len(review_response["prs"])

def fix_open_prs(client:PRQueueClient):
    fixes_response = client.query(action="needs_fix", limit=10)
    logger.info("Found %s PRs needing fixes", fixes_response['counts']['returned'])
    for pr in fixes_response["prs"]:
        pr_number = pr["prNumber"]
        repo = pr["repo"]
        description = pr["title"]
        # todo have manager pick the dev
        agent_id = _suggest_agent(title=description, labels=[], default_agent=DEFAULT_DEV_AGENT)
        logger.info(f"Init fix for PR #{pr_number} in {repo} by agent {agent_id}")
        branch = pr['headRefName']
        prompt = dev_agent.get_pr_fix_prompt(repo=repo, pr_number=pr_number, branch=branch)
        logger.debug("prompt: %s", prompt)
        spawn_agent(f"{repo}#{pr_number}", agent_id=agent_id, prompt=prompt)
    return len(fixes_response["prs"])

def fix_pr_merge_conflicts(client:PRQueueClient):
    conflicts_response = client.query(action="needs_conflict_resolution", limit=10)
    logger.info("Found %s PRs needing conflict resolution", conflicts_response['counts']['returned'])
    for pr in conflicts_response["prs"]:
        pr_number = pr["prNumber"]
        repo = pr["repo"]
        description = pr["title"]
        agent_id = _suggest_agent(title=description, labels=[], default_agent=DEFAULT_DEV_AGENT)
        logger.info(f"Init merge conflict fix for PR #{pr_number} in {repo} by agent {agent_id}")
        branch = pr['headRefName']
        prompt = dev_agent.get_pr_conflicts_prompt(repo=repo, pr_number=pr_number, branch=branch)
        logger.debug("prompt: %s", prompt)
        spawn_agent(f"{repo}#{pr_number}", agent_id=agent_id, prompt=prompt)
        logger.info("Spawned MERGE CONFLICT FIX for PR #%s by %s", pr['prNumber'], agent_id)
    return len(conflicts_response["prs"])

def fix_status_checks(client:PRQueueClient):
    status_response = client.query(action="needs_status_fix", limit=10)
    logger.info("Found %s PRs needing status fix", status_response['counts']['returned'])
    for pr in status_response["prs"]:
        pr_number = pr["prNumber"]
        repo = pr["repo"]
        description = pr["title"]
        agent_id = _suggest_agent(title=description, labels=[], default_agent=DEFAULT_DEV_AGENT)
        logger.info(f"Init status fix for PR #{pr_number} in {repo} by agent {agent_id}")
        branch = pr['headRefName']
        prompt = dev_agent.get_pr_fix_status_checks_prompt(repo=repo, pr_number=pr_number, branch=branch)
        logger.debug("prompt: %s", prompt)
        spawn_agent(f"{repo}#{pr_number}", agent_id=agent_id, prompt=prompt)
        logger.info("Spawned STATUS FIX for PR #%s by %s", pr_number, agent_id)
    return len(status_response["prs"])

def merge_prs(client:PRQueueClient):
    merges_response = client.query(action="ready_to_merge", limit=10)
    logger.info("Found %s PRs ready to merge", merges_response['counts']['returned'])
    for pr in merges_response["prs"]:
        repo = pr["repo"]
        pr_number = pr["prNumber"]
        logger.info(f"Init merge for PR #{pr_number} in {repo}")
        result = merge_pr(repo, pr_number)
        if result["success"]:
            logger.info("Merged PR #%s in %s", pr_number, repo)
        else:
            logger.error("Failed to merge PR #%s in %s: %s", pr_number, repo, result['error'])
    return len(merges_response["prs"])
