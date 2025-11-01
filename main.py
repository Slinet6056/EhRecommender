"""Main program entry point"""

import signal
import sys
import os
from pathlib import Path

from telegram.ext import Application
from telegram.request import HTTPXRequest

from utils.config import Config
from utils.logger import setup_logger
from models.database import Database
from models.ehdb import EhdbDatabase
from recommender.engine import RecommendationEngine
from bot.handlers import BotHandlers
from bot.safe_job_queue import SafeJobQueue
from scheduler.tasks import TaskScheduler


class EhRecommender:
    """E-Hentai recommendation system main class"""

    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize recommendation system

        Args:
            config_path: Configuration file path
        """
        # Load configuration
        self.config = Config(config_path)

        # Setup logging
        log_file = Path("logs") / "recommender.log"
        self.logger = setup_logger(
            "EhRecommender", level=self.config.log_level, log_file=str(log_file)
        )

        self.logger.info("=" * 30)
        self.logger.info("E-Hentai Recommendation System Starting")
        self.logger.info("=" * 30)

        # Initialize database
        self.logger.info("Initializing local database...")
        self.database = Database(self.config.local_database)

        self.logger.info("Connecting to EHDB database...")
        self.ehdb_database = EhdbDatabase(self.config.ehdb_database)
        self.ehdb_database.connect()

        # Initialize recommendation engine
        self.logger.info("Initializing recommendation engine...")
        self.recommender = RecommendationEngine(
            self.database, self.ehdb_database, self.config.recommender
        )
        self.recommender.initialize()

        # Create Telegram Application with proxy configuration
        self.logger.info("Creating Telegram Application...")
        telegram_config = self.config.telegram

        # Build Application builder
        builder = Application.builder().token(telegram_config["token"])

        # Configure proxy if specified in config
        proxy_url = telegram_config.get("proxy")
        if proxy_url and proxy_url.strip():  # Ensure it's not an empty string
            self.logger.info(f"Using proxy for Telegram: {proxy_url}")
            # Clear environment variables that might interfere
            for env_var in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
                if env_var in os.environ:
                    del os.environ[env_var]
            # Use proxy() instead of deprecated proxy_url()
            builder = builder.proxy(proxy_url)
        else:
            # If no proxy configured, clear environment variables to avoid using system proxy
            self.logger.info(
                "No proxy configured for Telegram, clearing proxy environment variables"
            )
            for env_var in [
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "http_proxy",
                "https_proxy",
                "ALL_PROXY",
                "all_proxy",
            ]:
                if env_var in os.environ:
                    del os.environ[env_var]
            # Configure connection and read timeouts only when no proxy is set
            # (proxy and custom request cannot be used together)
            request = HTTPXRequest(
                connection_pool_size=8,
                read_timeout=30,
                write_timeout=30,
                connect_timeout=30,
                pool_timeout=30,
            )
            builder = builder.request(request)

        # Set job queue
        builder = builder.job_queue(SafeJobQueue())

        # Build Application
        self.application = builder.build()

        # Initialize Telegram bot
        self.logger.info("Initializing Telegram bot...")
        self.bot_handlers = BotHandlers(
            self.database,
            self.ehdb_database,
            self.recommender,
            self.application.bot,
            self.config.crawler,
            self.config.telegram,
        )

        # Setup handlers
        self.bot_handlers.setup_application(self.application)

        # Initialize task scheduler
        self.logger.info("Initializing task scheduler...")
        self.task_scheduler = TaskScheduler(
            self.database,
            self.ehdb_database,
            self.recommender,
            self.application.bot,
            self.config.crawler,
            self.config.telegram,
            self.config.scheduler,
        )

        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger.info("Initialization completed")

    def _signal_handler(self, signum, frame):
        """Handle termination signals"""
        self.logger.info(f"Received signal {signum}, preparing to exit...")
        self.shutdown()
        sys.exit(0)

    def shutdown(self):
        """Shutdown system"""
        self.logger.info("Shutting down system...")

        # Shutdown scheduler
        self.task_scheduler.shutdown()

        # Close database connections
        self.ehdb_database.close()

        self.logger.info("System shutdown completed")

    async def _post_init(self, application: Application) -> None:
        """Post-initialization after bot starts"""
        await self.bot_handlers.setup_commands(application)

    def run(self):
        """Run system"""
        try:
            self.task_scheduler.start()
            self.logger.info("Starting Telegram bot...")

            # Setup post_init callback
            self.application.post_init = self._post_init

            self.application.run_polling(
                stop_signals=None,
                allowed_updates=["message", "callback_query"],
            )
        finally:
            self.shutdown()


def main():
    """Main function"""
    # Check configuration file
    if not Path("config.yaml").exists():
        print("❌ Configuration file not found!")
        print(
            "Please copy config.example.yaml to config.yaml and fill in the configuration"
        )
        sys.exit(1)

    # Create and run recommendation system
    try:
        recommender = EhRecommender()
        recommender.run()
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Startup failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
