"""Scheduled tasks module"""

import logging
from datetime import datetime
from typing import Dict, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from crawler.favorites import FavoritesCrawler
from bot.notifier import TelegramNotifier


class TaskScheduler:
    """Task scheduler"""

    def __init__(
        self,
        database,
        ehdb_database,
        recommender,
        bot,
        crawler_config: Dict[str, Any],
        telegram_config: Dict[str, Any],
        scheduler_config: Dict[str, Any],
    ):
        """
        Initialize scheduler

        Args:
            database: Local database
            ehdb_database: EHDB database
            recommender: Recommendation engine
            bot: Telegram Bot instance
            crawler_config: Crawler configuration
            telegram_config: Telegram configuration
            scheduler_config: Scheduler configuration
        """
        self.database = database
        self.ehdb_database = ehdb_database
        self.recommender = recommender
        self.crawler_config = crawler_config
        self.telegram_config = telegram_config
        self.scheduler_config = scheduler_config
        self.logger = logging.getLogger(__name__)

        # Initialize APScheduler
        self.scheduler = AsyncIOScheduler()

        # Notifier
        self.notifier = TelegramNotifier(
            bot, telegram_config["chat_id"], crawler_config.get("host", "e-hentai.org")
        )

        # Favorites crawler
        self.favorites_crawler = FavoritesCrawler(crawler_config)

    async def task_sync_favorites(self):
        """Scheduled favorites sync task"""
        self.logger.info("Starting scheduled favorites sync task")

        try:
            # Get known favorites
            known_gids = {gid for gid, _ in self.database.get_all_favorites()}

            # Incremental crawl
            new_favorites = self.favorites_crawler.fetch_new_favorites(known_gids)

            # Save to database
            for gid, token, added_time in new_favorites:
                self.database.add_favorite(gid, token, added_time)

            # Re-initialize recommendation engine
            if new_favorites:
                self.recommender.initialize()
                self.logger.info(
                    f"Favorites sync completed, {len(new_favorites)} new items"
                )
            else:
                self.logger.info("Favorites sync completed, no new items")

        except Exception as e:
            self.logger.error(f"Scheduled favorites sync failed: {e}")

    async def task_check_new_galleries(self):
        """Check new galleries and recommend"""
        self.logger.info("Starting new gallery check")

        try:
            # Get last checkpoint
            last_check = self.database.get_checkpoint("new_gallery_check")
            if last_check:
                since_timestamp = int(last_check)
            else:
                # Default: check last 1 hour
                since_timestamp = int(datetime.now().timestamp()) - 3600

            # Recommend new galleries
            recommendations = self.recommender.recommend_new_galleries(
                since_timestamp, limit=200
            )

            if not recommendations:
                self.logger.info("No matching new galleries")
                # Update checkpoint
                self.database.set_checkpoint(
                    "new_gallery_check", str(int(datetime.now().timestamp()))
                )
                return

            # Check notification mode
            notification_mode = self.telegram_config.get(
                "notification_mode", "immediate"
            )

            immediate_recs = []
            batch_recs = []

            for rec in recommendations:
                score = rec["score"]

                if self.recommender.should_push_immediately(score):
                    immediate_recs.append(rec)
                else:
                    batch_recs.append(rec)

            # Immediately push high-score recommendations
            if notification_mode != "manual" and immediate_recs:
                self.logger.info(
                    f"Found {len(immediate_recs)} high-score new galleries, pushing immediately"
                )

                for rec in immediate_recs:
                    gallery = rec["gallery"]
                    score = rec["score"]
                    details = rec["details"]

                    # Save recommendation record
                    self.database.add_recommendation(
                        gallery["gid"], score, details, notified=True
                    )

                    # Send
                    await self.notifier.send_recommendation(
                        gallery, score, details, source="new"
                    )

            # Save batch recommendations to database, wait for batch notification task
            if batch_recs:
                self.logger.info(
                    f"Saving {len(batch_recs)} regular new galleries, waiting for batch notification"
                )

                for rec in batch_recs:
                    gallery = rec["gallery"]
                    score = rec["score"]
                    details = rec["details"]

                    self.database.add_recommendation(
                        gallery["gid"], score, details, notified=False
                    )

            # Update checkpoint
            self.database.set_checkpoint(
                "new_gallery_check", str(int(datetime.now().timestamp()))
            )

            self.logger.info("New gallery check completed")

        except Exception as e:
            self.logger.error(f"New gallery check failed: {e}")

    async def task_batch_notification(self):
        """Batch notification task"""
        self.logger.info("Starting batch notification task")

        try:
            notification_mode = self.telegram_config.get(
                "notification_mode", "immediate"
            )

            if notification_mode == "manual":
                self.logger.info(
                    "Notification mode is manual, skipping batch notification"
                )
                return

            if notification_mode != "batch":
                self.logger.info(
                    "Notification mode is not batch, skipping batch notification"
                )
                return

            # Batch notification logic can be implemented here
            # For example: get all unnotified recommendations and send summary

            await self.notifier.send_message(
                "📬 Today's recommendation summary will be sent here"
            )

            self.logger.info("Batch notification completed")

        except Exception as e:
            self.logger.error(f"Batch notification failed: {e}")

    def start(self):
        """Start scheduler"""
        # Favorites sync task
        favorites_cron = self.scheduler_config.get("favorites_sync_cron", "0 3 * * *")
        self.scheduler.add_job(
            self.task_sync_favorites,
            CronTrigger.from_crontab(favorites_cron),
            id="sync_favorites",
            name="Sync Favorites",
            replace_existing=True,
        )

        # New gallery check task
        new_gallery_cron = self.scheduler_config.get(
            "new_gallery_check_cron", "0 * * * *"
        )
        self.scheduler.add_job(
            self.task_check_new_galleries,
            CronTrigger.from_crontab(new_gallery_cron),
            id="check_new_galleries",
            name="Check New Galleries",
            replace_existing=True,
        )

        # Batch notification task
        batch_notification_cron = self.scheduler_config.get(
            "batch_notification_cron", "0 20 * * *"
        )
        self.scheduler.add_job(
            self.task_batch_notification,
            CronTrigger.from_crontab(batch_notification_cron),
            id="batch_notification",
            name="Batch Notification",
            replace_existing=True,
        )

        self.scheduler.start()
        self.logger.info("Task scheduler started")
        self.logger.info(f"Favorites sync: {favorites_cron}")
        self.logger.info(f"New gallery check: {new_gallery_cron}")
        self.logger.info(f"Batch notification: {batch_notification_cron}")

    def shutdown(self):
        """Shutdown scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            self.logger.info("Task scheduler shutdown")
