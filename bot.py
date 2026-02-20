import sys
import os

# Add jm_bot submodule to sys.path so its internal absolute imports resolve correctly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "jm_bot"))

from jm_bot.base_bot.remote_config_bots.redis_remote_bot import BotWithRedisRemoteConfig
from github.get_open_prs import PRQueueClient, _suggest_agent
from agent import spawn_fix_agent, review_agent
from workflow import get_reviewers, get_review_policy


class Bot(BotWithRedisRemoteConfig):

    def on_startup(self):
        self.logging.info("Startup")
        pass

    def on_run_loop(self):
        self.logging.info("Loop Start")

        self.logging.info("Start PR reviews")
        with PRQueueClient() as client:
            review = client.query(action="needs_review", limit=10)
            print(f"Found {review['counts']['returned']} PRs needing review")
            for pr in review["prs"]:
                pr_number = pr["prNumber"]
                self.logging.info(f"Init review for PR #{pr_number}")
                repo = pr["repo"]
                reviewers = get_reviewers(repo)
                for reviewer in reviewers:
                    agent_id = reviewer["agent"]
                    task = review_agent.get_reviewer_prompt(reviewer_id=agent_id, repo=repo, pr_number=pr_number)
                    print(task)
                    spawn_fix_agent(pr, task=task, agent_id=agent_id)
                    self.logging.info(f"Spawned review for PR #{pr_number} by agent {agent_id}")

            fixes = client.query(action="needs_fix", limit=10)
            print(f"Found {review['counts']['returned']} PRs needing fixes")
            for pr in fixes["prs"]:
                self.logging.info(f"Init fix for PR #{pr['prNumber']}")
                repo = pr["repo"]
                description = pr["description"]
                # todo have manager pick the dev
                agent_id = _suggest_agent(title=description, labels=[], default_agent="backend-dev")
                task = review_agent.get_pr_fix_prompt(reviewer_id=agent_id, repo=repo, pr_number=pr_number)
                print(task)
                spawn_fix_agent(pr, task=task)

            conflicts = client.query(action="needs_conflict_resolution", limit=10)
            print(f"Found {review['counts']['returned']} PRs needing conflict resolution")
            for pr in conflicts["prs"]:
                self.logging.info(f"Init merge conflict fix for PR #{pr['prNumber']}")
                agent_id = _suggest_agent(title=description, labels=[], default_agent="backend-dev")
                task = review_agent.get_pr_conflicts_prompt(reviewer_id=agent_id, repo=repo, pr_number=pr_number)
                print(task)
                spawn_fix_agent(pr, task=task)

            merges = client.query(action="ready_to_merge", limit=10)
            print(f"Found {review['counts']['returned']} PRs ready to merge")
            for pr in merges["prs"]:
                repo = pr["repo"]
                review_policy = get_review_policy(repo)
                self.logging.info(f"Init merge for PR #{pr['prNumber']}")


    def on_shutdown(self):
        self.logging.info("Shutdown")
        pass


if __name__ == '__main__':
    Bot(sys.argv[1:]).main()