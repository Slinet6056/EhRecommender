"""Uploader analyzer"""

from typing import List, Dict, Any
from collections import Counter
import logging


class UploaderAnalyzer:
    """Uploader similarity analyzer"""

    def __init__(self):
        """Initialize uploader analyzer"""
        self.logger = logging.getLogger(__name__)
        self.uploader_weights: Dict[str, float] = {}
        self.uploader_gallery_count: Dict[str, int] = {}

    def build_uploader_profile(self, favorite_galleries: List[Dict[str, Any]]) -> None:
        """
        Build user's preferred uploader profile

        Args:
            favorite_galleries: User favorite galleries list
        """
        # Count uploader frequency
        uploader_counter = Counter()

        for gallery in favorite_galleries:
            uploader = gallery.get("uploader")
            if uploader and uploader.strip():
                uploader_counter[uploader] += 1

        total_favorites = len(favorite_galleries)
        if total_favorites == 0:
            return

        # Calculate weights (frequency + normalization)
        for uploader, count in uploader_counter.items():
            # Frequency weight
            frequency_weight = count / total_favorites

            # Enhance weights for high-frequency uploaders
            if count >= 5:
                frequency_weight *= 1.5
            elif count >= 3:
                frequency_weight *= 1.2

            self.uploader_weights[uploader] = frequency_weight
            self.uploader_gallery_count[uploader] = count

        # Normalize
        max_weight = (
            max(self.uploader_weights.values()) if self.uploader_weights else 1.0
        )
        self.uploader_weights = {
            k: v / max_weight for k, v in self.uploader_weights.items()
        }

        self.logger.info(
            f"Uploader profile construction completed, {len(self.uploader_weights)} uploaders"
        )

    def compute_uploader_score(self, candidate_uploader: str) -> float:
        """
        Compute candidate uploader matching score

        Args:
            candidate_uploader: Candidate gallery uploader

        Returns:
            Score (0-1)
        """
        if not candidate_uploader or not self.uploader_weights:
            return 0.0

        # Direct match
        if candidate_uploader in self.uploader_weights:
            return self.uploader_weights[candidate_uploader]

        # Unknown uploader, return low score (but not 0, give new uploaders a chance)
        return 0.1

    def get_top_uploaders(self, n: int = 10) -> List[tuple]:
        """
        Get user's top N favorite uploaders

        Args:
            n: Return count

        Returns:
            [(uploader, weight, count), ...] list
        """
        sorted_uploaders = sorted(
            self.uploader_weights.items(), key=lambda x: x[1], reverse=True
        )

        return [
            (uploader, weight, self.uploader_gallery_count[uploader])
            for uploader, weight in sorted_uploaders[:n]
        ]

    def update_uploader_preference(self, uploader: str, is_positive: bool) -> None:
        """
        Update uploader preference based on feedback

        Args:
            uploader: Uploader name
            is_positive: Whether positive feedback
        """
        if not uploader:
            return

        current_weight = self.uploader_weights.get(uploader, 0.1)

        if is_positive:
            # Positive feedback: increase weight
            new_weight = min(1.0, current_weight + 0.15)
        else:
            # Negative feedback: decrease weight
            new_weight = max(0.0, current_weight - 0.2)

        self.uploader_weights[uploader] = new_weight
        self.logger.debug(f"Updated uploader weight: {uploader} -> {new_weight:.2f}")
