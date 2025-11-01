"""Recommendation engine - integrates all analyzers"""

import json
from typing import List, Dict, Any, Optional, Tuple
import logging

from .tag_analyzer import TagAnalyzer
from .uploader_analyzer import UploaderAnalyzer
from .content_scorer import ContentScorer
from .feedback_learner import FeedbackLearner


class RecommendationEngine:
    """Recommendation engine"""

    def __init__(self, database, ehdb_database, config: Dict[str, Any]):
        """
        Initialize recommendation engine

        Args:
            database: Local database instance
            ehdb_database: EHDB database instance
            config: Recommender configuration
        """
        self.database = database
        self.ehdb_database = ehdb_database
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Initialize analyzers
        self.tag_analyzer = TagAnalyzer()
        self.uploader_analyzer = UploaderAnalyzer()
        self.content_scorer = ContentScorer()
        self.feedback_learner = FeedbackLearner(database)

        # Weight configuration
        self.tag_weight = config.get("tag_weight", 0.40)
        self.uploader_weight = config.get("uploader_weight", 0.20)
        self.quality_weight = config.get("quality_weight", 0.20)
        self.content_weight = config.get("content_weight", 0.15)
        self.recency_weight = config.get("recency_weight", 0.05)

        # Thresholds
        self.min_score_threshold = config.get("min_score_threshold", 0.70)
        self.immediate_push_threshold = config.get("immediate_push_threshold", 0.85)

        self._is_initialized = False

    def initialize(self) -> None:
        """Initialize recommendation engine (build user profile)"""
        self.logger.info("Starting recommendation engine initialization...")

        # Get user favorites
        favorite_gids = [gid for gid, _ in self.database.get_all_favorites()]

        if not favorite_gids:
            self.logger.warning(
                "User favorites are empty, recommendation quality may be poor"
            )
            self._is_initialized = True
            return

        # Get favorite gallery information from EHDB
        favorite_galleries = self.ehdb_database.get_galleries_by_ids(favorite_gids)

        if not favorite_galleries:
            self.logger.warning("Unable to get favorite information from EHDB")
            self._is_initialized = True
            return

        # Get feedback statistics (for calculating feedback multiplier)
        feedback_stats = self.database.get_all_tag_feedback_stats()

        # Build profiles for each analyzer
        self.tag_analyzer.build_user_profile(favorite_galleries, feedback_stats)
        self.uploader_analyzer.build_uploader_profile(favorite_galleries)
        self.content_scorer.build_quality_profile(favorite_galleries)

        # Sync base weights to database (only update tags without feedback)
        # Note: Need to calculate pure base weights (excluding feedback) for sync
        base_weights = self.tag_analyzer._get_base_weights_for_sync(favorite_galleries)
        self.database.sync_tag_preferences(base_weights)

        self._is_initialized = True
        self.logger.info("Recommendation engine initialization completed")

    def compute_recommendation_score(
        self, gallery: Dict[str, Any]
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Compute recommendation score

        Args:
            gallery: Gallery information

        Returns:
            (Total score, detailed score dictionary)
        """
        if not self._is_initialized:
            self.initialize()

        # Parse tags
        tags = gallery.get("tags", [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except:
                tags = []

        # 1. Tag similarity
        tag_score = self.tag_analyzer.compute_tag_similarity(tags)

        # 2. Uploader matching
        uploader = gallery.get("uploader") or ""
        uploader_score = self.uploader_analyzer.compute_uploader_score(uploader)

        # 3. Quality metrics
        quality_score = self.content_scorer.compute_quality_score(gallery)

        # 4. Content features
        content_score = self.content_scorer.compute_content_score(gallery)

        # 5. Recency
        recency_score = self.content_scorer.compute_recency_score(gallery)

        # Weighted total score
        total_score = (
            tag_score * self.tag_weight
            + uploader_score * self.uploader_weight
            + quality_score * self.quality_weight
            + content_score * self.content_weight
            + recency_score * self.recency_weight
        )

        # Detailed scores
        details = {
            "tag_score": round(tag_score, 3),
            "uploader_score": round(uploader_score, 3),
            "quality_score": round(quality_score, 3),
            "content_score": round(content_score, 3),
            "recency_score": round(recency_score, 3),
            "total_score": round(total_score, 3),
            "matched_tags": self.tag_analyzer.explain_similarity(tags, 5),
        }

        return total_score, details

    def recommend_new_galleries(
        self, since_timestamp: int, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Recommend new galleries

        Args:
            since_timestamp: Start timestamp
            limit: Maximum check count

        Returns:
            Recommendation list
        """
        self.logger.info(
            f"Starting new gallery recommendation (since={since_timestamp})"
        )

        # Get new galleries
        new_galleries = self.ehdb_database.get_new_galleries(since_timestamp, limit)

        return self._filter_and_score_galleries(new_galleries, "new")

    def recommend_from_pool(
        self, count: int = 100, min_rating: float = 3.0
    ) -> List[Dict[str, Any]]:
        """
        Recommend from gallery pool (old galleries)

        Args:
            count: Candidate count
            min_rating: Minimum rating

        Returns:
            Recommendation list
        """
        self.logger.info(f"Starting recommendation from gallery pool (count={count})")

        # Random sampling
        candidates = self.ehdb_database.get_random_galleries(count, min_rating)

        return self._filter_and_score_galleries(candidates, "old")

    def recommend_similar(self, gid: int, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Recommend similar galleries

        Args:
            gid: Base gallery ID
            limit: Return count

        Returns:
            Recommendation list
        """
        self.logger.info(f"Starting similar gallery recommendation (gid={gid})")

        # Get base gallery information
        base_gallery = self.ehdb_database.get_gallery(gid)
        if not base_gallery:
            self.logger.warning(f"Gallery does not exist: {gid}")
            return []

        # Extract tags and uploader
        tags = base_gallery.get("tags", [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except:
                tags = []

        uploader = base_gallery.get("uploader")

        # Search similar galleries
        similar_galleries = self.ehdb_database.search_similar_galleries(
            tags, uploader, limit * 3  # Get more candidates
        )

        # Exclude base gallery itself
        similar_galleries = [g for g in similar_galleries if g["gid"] != gid]

        return self._filter_and_score_galleries(similar_galleries, "manual")[:limit]

    def _filter_and_score_galleries(
        self, galleries: List[Dict[str, Any]], source: str
    ) -> List[Dict[str, Any]]:
        """
        Filter and score gallery list

        Args:
            galleries: Candidate gallery list
            source: Source tag (new/old/manual)

        Returns:
            Recommendation list (sorted)
        """
        recommendations = []

        for gallery in galleries:
            gid = gallery["gid"]

            # Filter: favorited, feedback given, already recommended
            if self.database.is_favorited(gid):
                continue
            if self.database.get_feedback(gid) is not None:
                continue
            # Check if already recommended within validity period
            expiry_days = self.config.get("recommendation_expiry_days")
            if source != "manual" and self.database.is_recommended(gid, expiry_days):
                continue

            # Calculate score
            score, details = self.compute_recommendation_score(gallery)

            # Filter low scores
            if score < self.min_score_threshold:
                continue

            # Add to recommendation list
            recommendations.append(
                {
                    "gallery": gallery,
                    "score": score,
                    "details": details,
                    "source": source,
                }
            )

        recommendations.sort(key=lambda x: x["score"], reverse=True)

        if recommendations:
            self.logger.info(
                "Recommendation completed: %d candidates, %d recommendations (highest %.2f, lowest %.2f)",
                len(galleries),
                len(recommendations),
                recommendations[0]["score"],
                recommendations[-1]["score"],
            )
        else:
            self.logger.info(
                "Recommendation completed: %d candidates, 0 recommendations (all below threshold %.2f)",
                len(galleries),
                self.min_score_threshold,
            )

        return recommendations

    def handle_feedback(self, gid: int, rating: int, source: str) -> None:
        """
        Handle user feedback

        Args:
            gid: Gallery ID
            rating: Rating (1 or -1)
            source: Source
        """
        # Save feedback
        self.database.add_feedback(gid, rating, source)

        # Get gallery information
        gallery = self.ehdb_database.get_gallery(gid)
        if not gallery:
            self.logger.warning(f"Unable to get gallery information: {gid}")
            return

        # Learn and update
        self.feedback_learner.learn_from_feedback(gid, rating, gallery)

        # Re-initialize (update profile)
        self.initialize()

        self.logger.info(f"Feedback handling completed: gid={gid}, rating={rating}")

    def should_push_immediately(self, score: float) -> bool:
        """Determine if should push immediately"""
        return score >= self.immediate_push_threshold
