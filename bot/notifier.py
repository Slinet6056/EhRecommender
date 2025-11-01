"""Telegram notification module"""

import json
import logging
from typing import Dict, Any, List, Optional
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import TelegramError

from utils.i18n import I18n


class TelegramNotifier:
    """Telegram notifier"""

    def __init__(self, bot: Bot, chat_id: int, host: str = "e-hentai.org"):
        """
        Initialize notifier

        Args:
            bot: Bot instance
            chat_id: Target Chat ID
            host: E-Hentai site domain
        """
        self.bot: Any = bot
        self.chat_id = chat_id
        self.host = host
        self.logger = logging.getLogger(__name__)
        self.i18n: Optional[I18n] = None  # Will be set by handlers per request

    def format_gallery_message(
        self, gallery: Dict[str, Any], score: float, details: Dict[str, Any]
    ) -> str:
        """
        Format gallery recommendation message

        Args:
            gallery: Gallery information
            score: Recommendation score
            details: Detailed scores

        Returns:
            Formatted message text
        """
        # Use i18n if available, fallback to English
        if self.i18n is None:
            self.i18n = I18n("en")

        gid = gallery["gid"]
        token = gallery.get("token", "")
        title = gallery.get("title", "N/A")
        title_jpn = gallery.get("title_jpn", "")
        category = gallery.get("category", "N/A")
        rating = gallery.get("rating", 0)
        filecount = gallery.get("filecount", 0)
        uploader = gallery.get("uploader", "N/A")

        # Build message
        lines = []
        lines.append(f"📚 <b>{title}</b>")
        if title_jpn and title_jpn != title:
            lines.append(f"   {title_jpn}")
        lines.append("")

        lines.append(self.i18n.t("gallery.category", category=category))
        lines.append(self.i18n.t("gallery.rating", rating=rating))
        lines.append(self.i18n.t("gallery.pages", count=filecount))
        lines.append(self.i18n.t("gallery.uploader", uploader=uploader))
        lines.append("")

        # Recommendation reason
        lines.append(self.i18n.t("gallery.recommendation_score", score=score))

        # Parse all tags from gallery
        all_tags = gallery.get("tags", [])
        if isinstance(all_tags, str):
            try:
                all_tags = json.loads(all_tags)
            except:
                all_tags = []

        # Display all tags
        if all_tags:
            tags_str = ", ".join(all_tags)
            lines.append(self.i18n.t("gallery.all_tags", tags=tags_str))

        # Also show matched tags if available
        matched_tags = details.get("matched_tags", [])
        if matched_tags:
            matched_tags_str = ", ".join(matched_tags[:5])
            lines.append(self.i18n.t("gallery.matched_tags", tags=matched_tags_str))

        lines.append("")
        lines.append(f"🔗 https://{self.host}/g/{gid}/{token}/")

        return "\n".join(lines)

    def create_feedback_keyboard(
        self, gid: int, source: str = "new"
    ) -> InlineKeyboardMarkup:
        """
        Create feedback button keyboard

        Args:
            gid: Gallery ID
            source: Source tag

        Returns:
            InlineKeyboardMarkup
        """
        # Use i18n if available, fallback to English
        if self.i18n is None:
            self.i18n = I18n("en")

        keyboard = [
            [
                InlineKeyboardButton(
                    self.i18n.t("buttons.like"), callback_data=f"like_{gid}_{source}"
                ),
                InlineKeyboardButton(
                    self.i18n.t("buttons.dislike"),
                    callback_data=f"dislike_{gid}_{source}",
                ),
            ],
            [
                InlineKeyboardButton(
                    self.i18n.t("buttons.view_related"), callback_data=f"similar_{gid}"
                )
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    async def send_recommendation(
        self,
        gallery: Dict[str, Any],
        score: float,
        details: Dict[str, Any],
        source: str = "new",
    ) -> bool:
        """
        Send recommendation notification

        Args:
            gallery: Gallery information
            score: Recommendation score
            details: Detailed scores
            source: Source tag

        Returns:
            Whether sending was successful
        """
        try:
            gid = gallery["gid"]
            thumb = gallery.get("thumb", "")

            # Format message
            message = self.format_gallery_message(gallery, score, details)
            keyboard = self.create_feedback_keyboard(gid, source)

            # Send message (with image)
            if thumb:
                try:
                    await self.bot.send_photo(
                        chat_id=self.chat_id,
                        photo=thumb,
                        caption=message,
                        parse_mode="HTML",
                        reply_markup=keyboard,
                    )
                    self.logger.info(f"Recommendation sent successfully: gid={gid}")
                    return True
                except TelegramError as e:
                    # Fallback to plain text if image sending fails
                    self.logger.warning(f"Image sending failed: {e}, using plain text")

            # Plain text message
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=False,
            )

            self.logger.info(f"Recommendation sent successfully: gid={gid}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to send recommendation: {e}")
            return False

    async def send_batch_recommendations(
        self, recommendations: List[Dict[str, Any]]
    ) -> int:
        """
        Send recommendations in batch

        Args:
            recommendations: Recommendation list

        Returns:
            Number of successfully sent
        """
        success_count = 0

        for rec in recommendations:
            gallery = rec["gallery"]
            score = rec["score"]
            details = rec["details"]
            source = rec.get("source", "batch")

            if await self.send_recommendation(gallery, score, details, source):
                success_count += 1

        return success_count

    async def send_message(self, text: str) -> bool:
        """
        Send plain message

        Args:
            text: Message text

        Returns:
            Whether successful
        """
        try:
            await self.bot.send_message(
                chat_id=self.chat_id, text=text, parse_mode="HTML"
            )
            return True
        except Exception as e:
            self.logger.error(f"Failed to send message: {e}")
            return False
