import logging
import sys
import os

logging.basicConfig(format='%(asctime)-15s %(levelname)-8s %(name)s %(message)s', level=logging.INFO)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "jm_bot"))

from base_bot.remote_config_bots.redis_remote_bot import BotWithRedisRemoteConfig
from github import github_sync


class SyncBot(BotWithRedisRemoteConfig):

    def on_startup(self):
        self.logging.info("Startup")
        pass

    def on_run_loop(self):
        self.logging.info("Loop Start")

        self.logging.info("Start GitHub sync")
        github_sync.sync()
        self.logging.info("End GitHub sync")
        pass

    def on_shutdown(self):
        self.logging.info("Shutdown")
        pass


if __name__ == '__main__':
    SyncBot(sys.argv[1:]).main()