import logging
import sys
import os
import time

logging.basicConfig(format='%(asctime)-15s %(levelname)-8s %(name)s %(message)s', level=logging.INFO)

# Add jm_bot submodule to sys.path so its internal absolute imports resolve correctly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "jm_bot"))

from jm_bot.base_bot.remote_config_bots.redis_remote_bot import BotWithRedisRemoteConfig
from tools.get_open_prs import PRQueueClient
from tools.get_open_issues import IssueQueueClient
from workflow import tasks
from github import github_sync


class Bot(BotWithRedisRemoteConfig):

    def on_startup(self):
        self.logging.info("Startup")
        pass

    def on_run_loop(self):
        self.logging.info("Start Loop")

        self.logging.info("Start GitHub sync")
        github_sync.sync()

        self.logging.info("Start Issues dev")
        with IssueQueueClient() as issue_client:
            issues = tasks.dev_open_issues(issue_client)

        self.logging.info("Start PR reviews")
        with PRQueueClient() as pr_client:
            merged = tasks.merge_prs(pr_client)
            open_prs = tasks.fix_open_prs(pr_client)
            merge_conflicts = tasks.fix_pr_merge_conflicts(pr_client)
            status_checks = tasks.fix_status_checks(pr_client)
            reviewed = tasks.review_open_prs(pr_client)
        self.logging.info("End Loop")

    def on_shutdown(self):
        self.logging.info("Shutdown")
        pass


if __name__ == '__main__':
    Bot(sys.argv[1:]).main()