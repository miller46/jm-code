import sys
import os

# Add jm_bot submodule to sys.path so its internal absolute imports resolve correctly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "jm_bot"))

from jm_bot.base_bot.remote_config_bots.redis_remote_bot import BotWithRedisRemoteConfig
from github.get_open_prs import PRQueueClient
from workflow import tasks
from github import github_sync


class Bot(BotWithRedisRemoteConfig):

    def on_startup(self):
        self.logging.info("Startup")
        pass

    def on_run_loop(self):
        self.logging.info("Loop Start")

        self.logging.info("Start GitHub sync")
        github_sync.sync()

        self.logging.info("Start PR reviews")
        with PRQueueClient() as client:
            tasks.review_open_prs(client)
            tasks.fix_open_prs(client)
            tasks.fix_pr_merge_conflicts(client)
            tasks.merge_prs(client)
        self.logging.info("End Start")

    def on_shutdown(self):
        self.logging.info("Shutdown")
        pass


if __name__ == '__main__':
    Bot(sys.argv[1:]).main()