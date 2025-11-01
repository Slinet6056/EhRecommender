"""Content scorer - quality metrics, content features, recency"""

import json
from typing import List, Dict, Any
from collections import Counter
from datetime import datetime
import numpy as np
import logging


class ContentScorer:
    """Content scorer"""

    def __init__(self):
        """Initialize content scorer"""
        self.logger = logging.getLogger(__name__)

        # User preference statistics
        self.avg_rating = 0.0
        self.rating_std = 0.0
        self.avg_filecount = 0
        self.filecount_range = (0, 10000)
        self.preferred_languages = {}
        self.preferred_categories = {}

    def build_quality_profile(self, favorite_galleries: List[Dict[str, Any]]) -> None:
        """
        Build user quality preference profile

        Args:
            favorite_galleries: User favorite galleries list
        """
        if not favorite_galleries:
            return

        # Rating preferences
        ratings = [g.get("rating", 0) for g in favorite_galleries]
        self.avg_rating = np.mean(ratings) if ratings else 0.0
        self.rating_std = np.std(ratings) if len(ratings) > 1 else 0.5

        # Page count preferences
        filecounts = [g.get("filecount", 0) for g in favorite_galleries]
        self.avg_filecount = int(np.mean(filecounts)) if filecounts else 0
        self.filecount_range = (
            int(np.percentile(filecounts, 10)) if filecounts else 0,
            int(np.percentile(filecounts, 90)) if filecounts else 10000,
        )

        # Language preferences
        language_counter = Counter()
        for gallery in favorite_galleries:
            tags = gallery.get("tags", [])
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except:
                    tags = []

            for tag in tags:
                if tag.startswith("language:") or tag.startswith("lang:"):
                    language_counter[tag] += 1

        total = sum(language_counter.values())
        if total > 0:
            self.preferred_languages = {
                lang: count / total for lang, count in language_counter.items()
            }

        # Category preferences
        category_counter = Counter(g.get("category", "") for g in favorite_galleries)
        total = len(favorite_galleries)
        self.preferred_categories = {
            cat: count / total for cat, count in category_counter.items() if cat
        }

        self.logger.info(
            f"Quality preference profile construction completed: avg_rating={self.avg_rating:.2f}, "
            f"avg_filecount={self.avg_filecount}, "
            f"language_preferences={len(self.preferred_languages)}"
        )

    def compute_quality_score(self, gallery: Dict[str, Any]) -> float:
        """
        Compute gallery quality score

        Args:
            gallery: Candidate gallery information

        Returns:
            Quality score (0-1)
        """
        scores = []

        # 1. Rating matching
        rating = gallery.get("rating", 0)
        if self.avg_rating > 0:
            # Use Gaussian distribution, prefer ratings within range
            rating_diff = abs(rating - self.avg_rating)
            rating_score = np.exp(-(rating_diff**2) / (2 * self.rating_std**2))
            scores.append(rating_score)
        else:
            # Simple linear mapping
            scores.append(rating / 5.0)

        # 2. Page count matching
        filecount = gallery.get("filecount", 0)
        if self.filecount_range[0] <= filecount <= self.filecount_range[1]:
            filecount_score = 1.0
        elif filecount < self.filecount_range[0]:
            filecount_score = 0.7
        else:
            filecount_score = 0.8
        scores.append(filecount_score)

        return float(np.mean(scores)) if scores else 0.5

    def compute_content_score(self, gallery: Dict[str, Any]) -> float:
        """
        Compute content feature score

        Args:
            gallery: Candidate gallery information

        Returns:
            Content score (0-1)
        """
        scores = []

        # 1. Language matching
        tags = gallery.get("tags", [])
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except:
                tags = []

        language_score = 0.0
        for tag in tags:
            if tag in self.preferred_languages:
                language_score = max(language_score, self.preferred_languages[tag])

        # If no language tag, give neutral score
        scores.append(language_score if language_score > 0 else 0.5)

        # 2. Category matching
        category = gallery.get("category", "")
        category_score = self.preferred_categories.get(category, 0.3)
        scores.append(category_score)

        return float(np.mean(scores)) if scores else 0.5

    def compute_recency_score(self, gallery: Dict[str, Any]) -> float:
        """
        Compute recency score

        Args:
            gallery: Candidate gallery information

        Returns:
            Recency score (0-1)
        """
        posted = gallery.get("posted")
        if not posted:
            return 0.5

        # Convert to datetime
        if isinstance(posted, str):
            try:
                posted = datetime.fromisoformat(posted.replace("Z", "+00:00"))
            except:
                return 0.5

        # Calculate day difference
        now = datetime.now(posted.tzinfo) if posted.tzinfo else datetime.now()
        days_diff = (now - posted).days

        # Use exponential decay
        # Within 30 days: 1.0, 90 days: 0.8, 180 days: 0.6, 365 days: 0.4
        if days_diff < 0:
            return 1.0

        decay_factor = 0.002  # Adjust decay speed
        score = np.exp(-decay_factor * days_diff)

        return max(0.2, min(1.0, score))  # Limit range
