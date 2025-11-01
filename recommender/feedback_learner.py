"""Feedback learner - dynamic weight adjustment"""

import json
from typing import List, Dict, Any
import logging


class FeedbackLearner:
    """Feedback learner"""

    def __init__(self, database):
        """
        Initialize feedback learner

        Args:
            database: Database instance
        """
        self.database = database
        self.logger = logging.getLogger(__name__)

        # Decay parameters
        self.learning_rate_decay = 0.95  # Decay with feedback count
        self.base_positive_delta = 0.10
        self.base_negative_delta = 0.15

    def learn_from_feedback(
        self, gid: int, rating: int, gallery_info: Dict[str, Any]
    ) -> None:
        """
        Learn from user feedback, update tag weights

        Args:
            gid: Gallery ID
            rating: Rating (1=like, -1=dislike)
            gallery_info: Gallery information
        """
        tags = gallery_info.get("tags", [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except:
                tags = []

        uploader = gallery_info.get("uploader")

        is_positive = rating > 0

        # Update tag weights
        for tag in tags:
            self._update_tag_weight(tag, is_positive)

        # Update uploader preference (recorded in database for uploader analyzer)
        if uploader:
            self._update_uploader_preference(uploader, is_positive)

        self.logger.info(
            f"Feedback learning completed: gid={gid}, rating={rating}, "
            f"tags={len(tags)}, uploader={uploader}"
        )

    def _update_tag_weight(self, tag: str, is_positive: bool) -> None:
        """
        Update feedback count for a single tag (weights will be recalculated on next startup based on feedback stats)

        Args:
            tag: Tag name
            is_positive: Whether positive feedback
        """
        # Get current preference
        pref = self.database.get_tag_preference(tag)

        if pref:
            # Preserve existing base weight (do not modify)
            base_weight = pref["weight"]
            pos_count = pref["positive_count"]
            neg_count = pref["negative_count"]
        else:
            # If new tag, need to get base weight first (may need from tag_analyzer)
            # Set to 1.0 for now, will be updated by sync_tag_preferences on next startup
            base_weight = 1.0
            pos_count = 0
            neg_count = 0

        # Update feedback count
        if is_positive:
            pos_count += 1
        else:
            neg_count += 1

        # Update database (preserve base weight, only update feedback count)
        # Note: weight field temporarily keeps original value, actual weight will be recalculated on next startup
        self.database.update_tag_preference(tag, base_weight, pos_count, neg_count)

        self.logger.debug(
            f"Tag feedback updated: {tag} pos={pos_count}, neg={neg_count}"
        )

    def _update_uploader_preference(self, uploader: str, is_positive: bool) -> None:
        """
        Record uploader feedback (actual weight updates handled by UploaderAnalyzer)

        Args:
            uploader: Uploader name
            is_positive: Whether positive feedback
        """
        # Can record uploader feedback statistics in database here
        # Since current database schema doesn't have separate uploader table, log for now
        self.logger.debug(
            f"Uploader feedback: {uploader} {'positive' if is_positive else 'negative'}"
        )

    def batch_learn_from_history(self, ehdb_database) -> None:
        """
        Batch learn from historical feedback

        Args:
            ehdb_database: EHDB database instance
        """
        # Get all feedback
        all_feedback = self.database.get_all_feedback()

        if not all_feedback:
            self.logger.info("No historical feedback, skipping batch learning")
            return

        self.logger.info(f"Starting batch learning, {len(all_feedback)} feedback items")

        # Batch get gallery information
        gids = [gid for gid, _ in all_feedback]
        galleries = ehdb_database.get_galleries_by_ids(gids)
        gallery_dict = {g["gid"]: g for g in galleries}

        # Learn one by one
        for gid, rating in all_feedback:
            if gid in gallery_dict:
                self.learn_from_feedback(gid, rating, gallery_dict[gid])

        self.logger.info("Batch learning completed")

    def get_tag_feedback_summary(self, top_n: int = 20) -> Dict[str, Any]:
        """
        Get tag feedback statistics summary

        Args:
            top_n: Return top N tags

        Returns:
            Statistics summary
        """
        all_prefs = self.database.get_all_tag_preferences()

        # Sort by weight
        sorted_tags = sorted(all_prefs.items(), key=lambda x: x[1], reverse=True)[
            :top_n
        ]

        return {
            "top_tags": [{"tag": tag, "weight": weight} for tag, weight in sorted_tags],
            "total_tags": len(all_prefs),
        }
