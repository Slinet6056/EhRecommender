"""Telegram bot command handlers"""

import logging
import io
from typing import Dict, Any
from datetime import datetime

from telegram import (
    Bot,
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    BotCommand,
)
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from wordcloud import WordCloud
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from crawler.favorites import FavoritesCrawler
from .notifier import TelegramNotifier
from utils.i18n import I18n


class BotHandlers:
    """Telegram bot command handlers"""

    def __init__(
        self,
        database,
        ehdb_database,
        recommender,
        bot: Bot,
        crawler_config: Dict[str, Any],
        telegram_config: Dict[str, Any],
    ):
        """
        Initialize handlers

        Args:
            database: Local database instance
            ehdb_database: EHDB database instance
            recommender: Recommendation engine
            crawler_config: Crawler configuration
            telegram_config: Telegram configuration
        """
        self.database = database
        self.ehdb_database = ehdb_database
        self.recommender = recommender
        self.crawler_config = crawler_config
        self.telegram_config = telegram_config
        self.logger = logging.getLogger(__name__)

        # Allowed user ID (from config chat_id for single-user setup)
        self.allowed_user_id = telegram_config.get("chat_id")
        if not self.allowed_user_id:
            self.logger.warning(
                "No chat_id configured, bot will accept commands from anyone!"
            )

        # Notifier (will be initialized with i18n later)
        self.notifier = TelegramNotifier(
            bot, telegram_config["chat_id"], crawler_config.get("host", "e-hentai.org")
        )
        self.notifier.i18n = None  # Will be set per request

        # Favorites crawler
        self.favorites_crawler = FavoritesCrawler(crawler_config)

    def _check_access(self, update: Update) -> bool:
        """
        Check if user is authorized to use the bot

        Args:
            update: Telegram Update object

        Returns:
            True if authorized, False otherwise
        """
        if not self.allowed_user_id:
            # If no chat_id configured, allow all (backward compatibility)
            return True

        if not update.message or not update.message.from_user:
            return False

        user_id = update.message.from_user.id
        return user_id == self.allowed_user_id

    def _get_i18n(self, update: Update) -> I18n:
        """
        Get i18n instance for user
        For single-user setup, get locale from database or use default

        Args:
            update: Telegram Update object

        Returns:
            I18n instance
        """
        # For single-user setup, use the configured chat_id's locale
        if self.allowed_user_id:
            locale = self.database.get_user_locale(self.allowed_user_id)
            if not locale:
                # Try to detect from update if available
                if update.message and update.message.from_user:
                    locale = I18n.get_user_locale(update)
                    # Save to database
                    self.database.set_user_locale(self.allowed_user_id, locale)
                else:
                    locale = "en"  # Default fallback
            return I18n(locale)

        # Fallback for multi-user (shouldn't happen in single-user setup)
        if not update.message or not update.message.from_user:
            return I18n("en")

        user_id = update.message.from_user.id
        locale = self.database.get_user_locale(user_id)
        if not locale:
            locale = I18n.get_user_locale(update)
            self.database.set_user_locale(user_id, locale)

        return I18n(locale)

    async def _require_access(self, update: Update) -> bool:
        """
        Check access and send error message if unauthorized

        Args:
            update: Telegram Update object

        Returns:
            True if authorized, False otherwise
        """
        if not self._check_access(update):
            if update.message:
                i18n = I18n("en")  # Use English for error message
                await update.message.reply_text(
                    "❌ Unauthorized access. This bot is for personal use only."
                )
            return False
        return True

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        if not update.message:
            return
        if not await self._require_access(update):
            return

        i18n = self._get_i18n(update)

        help_text = f"""
{i18n.t('commands.start.title')}

{i18n.t('commands.start.available_commands')}

{i18n.t('commands.start.favorites')}
/sync - {i18n.t('cmd_descriptions.sync')}
/fullsync - {i18n.t('cmd_descriptions.fullsync')}

{i18n.t('commands.start.recommendations')}
/recommend [count] - {i18n.t('cmd_descriptions.recommend')}
/new - {i18n.t('cmd_descriptions.new')}
/related &lt;gid&gt; - {i18n.t('cmd_descriptions.related')}

{i18n.t('commands.start.statistics')}
/stats - {i18n.t('cmd_descriptions.stats')}
/wordcloud - {i18n.t('cmd_descriptions.wordcloud')}

{i18n.t('commands.start.others')}
/settings - {i18n.t('cmd_descriptions.settings')}
/language - {i18n.t('cmd_descriptions.language')}
/help - {i18n.t('cmd_descriptions.help')}

{i18n.t('commands.start.help_footer')}
"""
        await update.message.reply_text(help_text, parse_mode="HTML")

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        await self.cmd_start(update, context)

    async def cmd_sync(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /sync command (incremental sync)"""
        if not update.message:
            return
        if not await self._require_access(update):
            return
        i18n = self._get_i18n(update)
        await update.message.reply_text(i18n.t("commands.sync.starting"))

        try:
            # Get known favorites
            known_gids = {gid for gid, _ in self.database.get_all_favorites()}

            # Incremental crawl
            new_favorites = self.favorites_crawler.fetch_new_favorites(known_gids)

            # Save to database
            for gid, token, added_time in new_favorites:
                self.database.add_favorite(gid, token, added_time)

            # Re-initialize recommendation engine
            self.recommender.initialize()

            await update.message.reply_text(
                i18n.t("commands.sync.completed", count=len(new_favorites))
            )

        except Exception as e:
            self.logger.error(f"Incremental sync failed: {e}")
            await update.message.reply_text(
                i18n.t("commands.sync.failed", error=str(e))
            )

    async def cmd_fullsync(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /fullsync command (full sync)"""
        if not update.message:
            return
        if not await self._require_access(update):
            return
        i18n = self._get_i18n(update)
        await update.message.reply_text(i18n.t("commands.fullsync.starting"))

        try:
            # Full crawl
            all_favorites = self.favorites_crawler.fetch_all_favorites()

            # Clear and refill database
            self.database.clear_favorites()
            for gid, token, added_time in all_favorites:
                self.database.add_favorite(gid, token, added_time)

            # Re-initialize recommendation engine
            self.recommender.initialize()

            await update.message.reply_text(
                i18n.t("commands.fullsync.completed", count=len(all_favorites))
            )

        except Exception as e:
            self.logger.error(f"Full sync failed: {e}")
            await update.message.reply_text(
                i18n.t("commands.fullsync.failed", error=str(e))
            )

    async def cmd_recommend(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /recommend command"""
        if not update.message:
            return
        if not await self._require_access(update):
            return
        i18n = self._get_i18n(update)
        # Parse count parameter
        try:
            count = int(context.args[0]) if context.args else 5
            count = min(count, 10)  # Max 10
        except ValueError:
            count = 5

        await update.message.reply_text(
            i18n.t("commands.recommend.generating", count=count)
        )

        try:
            # Recommend from gallery pool
            multiplier = self.recommender.config.get("pool_sampling_multiplier", 20)
            recommendations = self.recommender.recommend_from_pool(count * multiplier)

            if not recommendations:
                await update.message.reply_text(i18n.t("commands.recommend.no_results"))
                return

            # Take top N
            recommendations = recommendations[:count]

            # Set i18n for notifier
            self.notifier.i18n = i18n

            # Send recommendations
            for rec in recommendations:
                gallery = rec["gallery"]
                score = rec["score"]
                details = rec["details"]

                # Save recommendation record
                self.database.add_recommendation(
                    gallery["gid"], score, details, notified=True
                )

                # Send
                await self.notifier.send_recommendation(
                    gallery, score, details, source="old"
                )

            await update.message.reply_text(
                i18n.t("commands.recommend.sent", count=len(recommendations))
            )

        except Exception as e:
            self.logger.error(f"Recommendation failed: {e}")
            await update.message.reply_text(
                i18n.t("commands.recommend.failed", error=str(e))
            )

    async def cmd_new(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /new command (view new gallery recommendations)"""
        if not update.message:
            return
        if not await self._require_access(update):
            return
        i18n = self._get_i18n(update)
        await update.message.reply_text(i18n.t("commands.new.checking"))

        try:
            # Get last checkpoint
            last_check = self.database.get_checkpoint("new_gallery_check")
            if last_check:
                since_timestamp = int(last_check)
            else:
                # Default: check last 24 hours
                since_timestamp = int(datetime.now().timestamp()) - 86400

            # Recommend new galleries
            recommendations = self.recommender.recommend_new_galleries(
                since_timestamp, limit=200
            )

            if not recommendations:
                await update.message.reply_text(i18n.t("commands.new.no_results"))
                return

            # Take top 10
            recommendations = recommendations[:10]

            # Set i18n for notifier
            self.notifier.i18n = i18n

            # Send recommendations
            for rec in recommendations:
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

            # Update checkpoint
            self.database.set_checkpoint(
                "new_gallery_check", str(int(datetime.now().timestamp()))
            )

            await update.message.reply_text(
                i18n.t("commands.new.sent", count=len(recommendations))
            )

        except Exception as e:
            self.logger.error(f"New gallery recommendation failed: {e}")
            await update.message.reply_text(i18n.t("commands.new.failed", error=str(e)))

    async def cmd_related(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /related command"""
        if not update.message:
            return
        if not await self._require_access(update):
            return
        i18n = self._get_i18n(update)
        if not context.args:
            await update.message.reply_text(i18n.t("commands.related.no_gid"))
            return

        try:
            gid = int(context.args[0])
        except ValueError:
            await update.message.reply_text(i18n.t("commands.related.invalid_gid"))
            return

        await update.message.reply_text(i18n.t("commands.related.finding", gid=gid))

        try:
            # Recommend similar galleries
            recommendations = self.recommender.recommend_similar(gid, limit=5)

            if not recommendations:
                await update.message.reply_text(i18n.t("commands.related.no_results"))
                return

            # Set i18n for notifier
            self.notifier.i18n = i18n

            # Send recommendations
            for rec in recommendations:
                gallery = rec["gallery"]
                score = rec["score"]
                details = rec["details"]

                await self.notifier.send_recommendation(
                    gallery, score, details, source="manual"
                )

            await update.message.reply_text(
                i18n.t("commands.related.sent", count=len(recommendations))
            )

        except Exception as e:
            self.logger.error(f"Related recommendation failed: {e}")
            await update.message.reply_text(
                i18n.t("commands.related.failed", error=str(e))
            )

    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command"""
        if not update.message:
            return
        if not await self._require_access(update):
            return
        i18n = self._get_i18n(update)
        try:
            stats = self.database.get_stats()

            # Get top tags
            top_tags = self.recommender.tag_analyzer.get_top_tags(10)

            # Get top uploaders
            top_uploaders = self.recommender.uploader_analyzer.get_top_uploaders(5)

            # Format message
            lines = [i18n.t("commands.stats.title") + "\n"]
            lines.append(
                i18n.t("commands.stats.favorites", count=stats["favorites_count"])
            )
            lines.append(
                i18n.t("commands.stats.feedback", count=stats["feedback_count"])
            )
            lines.append(
                i18n.t("commands.stats.liked", count=stats["positive_feedback"])
            )
            lines.append(
                i18n.t("commands.stats.disliked", count=stats["negative_feedback"])
            )
            lines.append(
                i18n.t(
                    "commands.stats.recommendations",
                    count=stats["recommendation_count"],
                )
            )

            if top_tags:
                lines.append("\n" + i18n.t("commands.stats.top_tags"))
                for tag, weight in top_tags[:5]:
                    lines.append(
                        i18n.t("commands.stats.tag_item", tag=tag, weight=weight)
                    )

            if top_uploaders:
                lines.append("\n" + i18n.t("commands.stats.top_uploaders"))
                for uploader, weight, count in top_uploaders:
                    lines.append(
                        i18n.t(
                            "commands.stats.uploader_item",
                            uploader=uploader,
                            count=count,
                        )
                    )

            await update.message.reply_text("\n".join(lines), parse_mode="HTML")

        except Exception as e:
            self.logger.error(f"Failed to get statistics: {e}")
            await update.message.reply_text(
                i18n.t("commands.stats.failed", error=str(e))
            )

    async def cmd_wordcloud(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /wordcloud command (generate tag word cloud)"""
        if not update.message:
            return
        if not await self._require_access(update):
            return
        i18n = self._get_i18n(update)
        await update.message.reply_text(i18n.t("commands.wordcloud.generating"))

        try:
            # Get all tag weights
            tag_weights = self.database.get_all_tag_preferences()
            if not tag_weights:
                # Fallback to in-memory tag profile
                tag_weights = self.recommender.tag_analyzer.user_tag_weights

            if not tag_weights:
                await update.message.reply_text(i18n.t("commands.wordcloud.no_data"))
                return

            # Generate word cloud
            wordcloud = WordCloud(
                width=800,
                height=400,
                background_color="white",
                colormap="viridis",
                relative_scaling="auto",
                min_font_size=10,
            ).generate_from_frequencies(tag_weights)

            # Plot image
            plt.figure(figsize=(10, 5))
            plt.imshow(wordcloud, interpolation="bilinear")
            plt.axis("off")
            plt.tight_layout(pad=0)

            # Save to byte stream
            buf = io.BytesIO()
            plt.savefig(buf, format="png", dpi=150)
            buf.seek(0)
            plt.close()

            # Send image
            await update.message.reply_photo(
                photo=buf, caption=i18n.t("commands.wordcloud.caption")
            )

        except Exception as e:
            self.logger.error(f"Word cloud generation failed: {e}")
            await update.message.reply_text(
                i18n.t("commands.wordcloud.failed", error=str(e))
            )

    async def cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /settings command"""
        if not update.message:
            return
        if not await self._require_access(update):
            return
        i18n = self._get_i18n(update)
        config = self.recommender.config

        lines = [i18n.t("commands.settings.title") + "\n"]
        lines.append(
            i18n.t(
                "commands.settings.min_score",
                value=config.get("min_score_threshold", 0.7),
            )
        )
        lines.append(
            i18n.t(
                "commands.settings.immediate_push",
                value=config.get("immediate_push_threshold", 0.85),
            )
        )
        lines.append(
            i18n.t(
                "commands.settings.max_recommendations",
                value=config.get("max_recommendations_per_query", 10),
            )
        )
        lines.append("\n" + i18n.t("commands.settings.weight_config"))
        lines.append(
            i18n.t("commands.settings.tag_weight", value=config.get("tag_weight", 0.4))
        )
        lines.append(
            i18n.t(
                "commands.settings.uploader_weight",
                value=config.get("uploader_weight", 0.2),
            )
        )
        lines.append(
            i18n.t(
                "commands.settings.quality_weight",
                value=config.get("quality_weight", 0.2),
            )
        )
        lines.append(
            i18n.t(
                "commands.settings.content_weight",
                value=config.get("content_weight", 0.15),
            )
        )
        lines.append(
            i18n.t(
                "commands.settings.recency_weight",
                value=config.get("recency_weight", 0.05),
            )
        )

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callback"""
        query = update.callback_query
        if not query or not query.message or not isinstance(query.message, Message):
            return

        # Check access
        if query.from_user and self.allowed_user_id:
            if query.from_user.id != self.allowed_user_id:
                await query.answer("❌ Unauthorized access", show_alert=True)
                return

        await query.answer()

        # Get i18n for callback
        if self.allowed_user_id:
            # For single-user setup, use configured user's locale
            locale = self.database.get_user_locale(self.allowed_user_id) or "en"
            i18n = I18n(locale)
        elif query.from_user:
            user_id = query.from_user.id
            locale = self.database.get_user_locale(user_id) or "en"
            i18n = I18n(locale)
        else:
            i18n = I18n("en")

        try:
            callback_data = query.data
            if not callback_data:
                return
            parts = callback_data.split("_")
            action = parts[0]
            gid = int(parts[1])
            source = parts[2] if len(parts) > 2 else "unknown"

            if action == "like":
                # Positive feedback
                self.recommender.handle_feedback(gid, 1, source)
                await query.edit_message_reply_markup(
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    i18n.t("buttons.marked_liked"), callback_data="noop"
                                )
                            ]
                        ]
                    )
                )

            elif action == "dislike":
                # Negative feedback
                self.recommender.handle_feedback(gid, -1, source)
                await query.edit_message_reply_markup(
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    i18n.t("buttons.marked_disliked"),
                                    callback_data="noop",
                                )
                            ]
                        ]
                    )
                )

            elif action == "similar":
                # View related
                recommendations = self.recommender.recommend_similar(gid, limit=3)

                if recommendations:
                    # Set i18n for notifier
                    self.notifier.i18n = i18n
                    for rec in recommendations:
                        await self.notifier.send_recommendation(
                            rec["gallery"],
                            rec["score"],
                            rec["details"],
                            source="manual",
                        )
                    await query.message.reply_text(
                        i18n.t("feedback.related_sent", count=len(recommendations))
                    )
                else:
                    await query.message.reply_text(
                        i18n.t("commands.related.no_results")
                    )

        except Exception as e:
            self.logger.error(f"Callback handling failed: {e}")
            await query.message.reply_text(
                i18n.t("feedback.operation_failed", error=str(e))
            )

    async def cmd_language(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /language command"""
        if not update.message or not update.message.from_user:
            return
        if not await self._require_access(update):
            return
        i18n = self._get_i18n(update)
        # For single-user setup, always use the configured chat_id
        user_id = (
            self.allowed_user_id
            if self.allowed_user_id
            else update.message.from_user.id
        )

        # Dynamically detect available languages from locales directory
        available_languages = I18n.get_available_locales()

        if not context.args:
            # Show current language and available options
            current_locale = self.database.get_user_locale(user_id) or "en"
            current_lang = available_languages.get(current_locale, current_locale)
            lang_list = "\n".join(
                [
                    f"  • {code}: {name}"
                    for code, name in sorted(available_languages.items())
                ]
            )
            # Use i18n for usage instructions
            usage_text = (
                i18n.t("commands.language.current", language=current_lang)
                + "\n\n"
                + i18n.t("commands.language.available", list=lang_list)
                + "\n\n"
                + "Usage: /language <code>\n"
                + "Example: /language zh_CN"
            )
            await update.message.reply_text(usage_text)
            return

        # Change language
        new_locale = context.args[0]
        if new_locale not in available_languages:
            lang_codes = ", ".join(sorted(available_languages.keys()))
            await update.message.reply_text(
                i18n.t("commands.language.invalid", languages=lang_codes)
            )
            return

        # Save to database
        self.database.set_user_locale(user_id, new_locale)

        # Create new i18n instance to get translated message
        new_i18n = I18n(new_locale)
        await update.message.reply_text(
            new_i18n.t(
                "commands.language.changed", language=available_languages[new_locale]
            )
        )

    async def setup_commands(self, app: Application) -> None:
        """
        Setup Telegram command menu for all available languages

        Args:
            app: Telegram Application instance
        """
        # Get all available languages
        available_languages = I18n.get_available_locales()

        def get_telegram_language_code(locale: str) -> str:
            """
            Convert locale code to Telegram language code

            Telegram supports language codes like:
            - "en" for English
            - "zh" or "zh-hans" for Simplified Chinese
            - "zh-hant" or "zh-tw" for Traditional Chinese

            Args:
                locale: Locale code (e.g., 'en', 'zh_CN', 'zh_TW')

            Returns:
                Telegram language code
            """
            # Direct mapping for common cases
            locale_map = {
                "en": "en",
                "zh_CN": "zh",  # Simplified Chinese
                "zh_TW": "zh-hant",  # Traditional Chinese
            }

            if locale in locale_map:
                return locale_map[locale]

            # Fallback: try to extract base language code
            # For example, "fr_CA" -> "fr", "de_AT" -> "de"
            base_lang = locale.split("_")[0] if "_" in locale else locale
            return base_lang

        def build_commands(locale: str) -> list:
            """Build command list for a specific locale"""
            i18n = I18n(locale)
            return [
                BotCommand("start", i18n.t("cmd_descriptions.start")),
                BotCommand("sync", i18n.t("cmd_descriptions.sync")),
                BotCommand("fullsync", i18n.t("cmd_descriptions.fullsync")),
                BotCommand("recommend", i18n.t("cmd_descriptions.recommend")),
                BotCommand("new", i18n.t("cmd_descriptions.new")),
                BotCommand("related", i18n.t("cmd_descriptions.related")),
                BotCommand("stats", i18n.t("cmd_descriptions.stats")),
                BotCommand("wordcloud", i18n.t("cmd_descriptions.wordcloud")),
                BotCommand("settings", i18n.t("cmd_descriptions.settings")),
                BotCommand("language", i18n.t("cmd_descriptions.language")),
                BotCommand("help", i18n.t("cmd_descriptions.help")),
            ]

        # Set default commands (for users without language preference)
        try:
            default_commands = build_commands("en")
            await app.bot.set_my_commands(default_commands)
            self.logger.info("Telegram command menu (default) set")
        except Exception as e:
            self.logger.error(f"Failed to set default command menu: {e}")

        # Set commands for each available language
        for locale_code in available_languages.keys():
            # Skip default (already set above)
            if locale_code == "en":
                continue

            try:
                # Get Telegram language code
                telegram_lang = get_telegram_language_code(locale_code)
                commands = build_commands(locale_code)
                await app.bot.set_my_commands(commands, language_code=telegram_lang)
                self.logger.info(
                    f"Telegram command menu set for language: {locale_code} (telegram: {telegram_lang})"
                )
            except Exception as e:
                self.logger.warning(
                    f"Failed to set command menu for {locale_code}: {e}"
                )

    def setup_application(self, app: Application) -> None:
        """
        Setup Application handlers

        Args:
            app: Telegram Application instance
        """
        # Command handlers
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CommandHandler("sync", self.cmd_sync))
        app.add_handler(CommandHandler("fullsync", self.cmd_fullsync))
        app.add_handler(CommandHandler("recommend", self.cmd_recommend))
        app.add_handler(CommandHandler("new", self.cmd_new))
        app.add_handler(CommandHandler("related", self.cmd_related))
        app.add_handler(CommandHandler("stats", self.cmd_stats))
        app.add_handler(CommandHandler("wordcloud", self.cmd_wordcloud))
        app.add_handler(CommandHandler("settings", self.cmd_settings))
        app.add_handler(CommandHandler("language", self.cmd_language))

        # Callback query handler
        app.add_handler(CallbackQueryHandler(self.handle_callback))

        self.logger.info("Telegram handlers set")
