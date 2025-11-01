"""Tag analyzer - compute tag similarity using TF-IDF"""

import json
from typing import List, Dict, Any, Optional, cast
from collections import Counter
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import logging
from scipy.sparse import csr_matrix


class TagAnalyzer:
    """Tag analyzer"""

    # Namespace weights
    NAMESPACE_WEIGHTS = {
        "female": 1.2,
        "male": 1.2,
        "parody": 1.0,
        "character": 1.0,
        "artist": 0.9,
        "group": 0.9,
        "language": 1.1,
        "other": 0.8,
        "mixed": 1.0,
        "cosplayer": 0.7,
        "reclass": 0.5,
    }

    def __init__(self):
        """Initialize tag analyzer"""
        self.logger = logging.getLogger(__name__)
        self.user_tag_weights: Dict[str, float] = {}
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.user_vector: Optional[np.ndarray] = None

    def extract_tags_from_galleries(
        self, galleries: List[Dict[str, Any]]
    ) -> List[List[str]]:
        """
        Extract tags from gallery list

        Args:
            galleries: Gallery information list

        Returns:
            List of tag lists
        """
        all_tags = []
        for gallery in galleries:
            tags = gallery.get("tags", [])
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except:
                    tags = []
            all_tags.append(tags)
        return all_tags

    def compute_tag_weights_from_favorites(
        self,
        favorite_galleries: List[Dict[str, Any]],
        feedback_stats: Optional[Dict[str, Dict[str, int]]] = None,
    ) -> Dict[str, float]:
        """
        Compute tag base weights from user favorites (excluding feedback adjustments)

        Args:
            favorite_galleries: User favorite galleries list
            feedback_stats: Feedback statistics {tag: {'positive_count': int, 'negative_count': int}}

        Returns:
            Tag weight dictionary (base weight * feedback multiplier)
        """
        if not favorite_galleries:
            return {}

        if feedback_stats is None:
            feedback_stats = {}

        # Count tag frequency
        tag_counter = Counter()
        for gallery in favorite_galleries:
            tags = gallery.get("tags", [])
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except:
                    tags = []
            tag_counter.update(tags)

        # Calculate base weights (TF * namespace weight)
        base_weights = {}
        for tag, count in tag_counter.items():
            # Base frequency weight
            tf = count / len(favorite_galleries)

            # Namespace weight
            namespace = tag.split(":", 1)[0] if ":" in tag else "other"
            ns_weight = self.NAMESPACE_WEIGHTS.get(namespace, 1.0)

            # Base weight (excluding feedback)
            base_weights[tag] = tf * ns_weight

        # Normalize base weights
        max_base_weight = max(base_weights.values()) if base_weights else 1.0
        base_weights = {k: v / max_base_weight for k, v in base_weights.items()}

        # Calculate feedback multiplier from feedback statistics and apply to base weights
        tag_weights = {}
        for tag, base_weight in base_weights.items():
            stats = feedback_stats.get(tag, {})
            pos_count = stats.get("positive_count", 0)
            neg_count = stats.get("negative_count", 0)

            # Calculate feedback multiplier (using similar logic to feedback_learner)
            feedback_multiplier = self._compute_feedback_multiplier(
                pos_count, neg_count
            )

            # Final weight = base weight * feedback multiplier
            tag_weights[tag] = base_weight * feedback_multiplier

        # Normalize again (after feedback adjustment)
        max_weight = max(tag_weights.values()) if tag_weights else 1.0
        if max_weight > 0:
            tag_weights = {k: v / max_weight for k, v in tag_weights.items()}

        self.user_tag_weights = tag_weights
        self.logger.info(f"Tag weight calculation completed, {len(tag_weights)} tags")

        return tag_weights

    def _compute_feedback_multiplier(self, pos_count: int, neg_count: int) -> float:
        """
        Calculate feedback multiplier from feedback statistics

        Args:
            pos_count: Positive feedback count
            neg_count: Negative feedback count

        Returns:
            Feedback multiplier (1.0 means no adjustment)
        """
        if pos_count == 0 and neg_count == 0:
            return 1.0

        # Use similar decay mechanism as feedback_learner
        total_feedback = pos_count + neg_count
        base_positive_delta = 0.1
        base_negative_delta = 0.15
        learning_rate_decay = 0.9

        # Calculate cumulative adjustment
        multiplier = 1.0
        for i in range(pos_count):
            decay = learning_rate_decay ** (i + neg_count)
            multiplier += base_positive_delta * decay

        for i in range(neg_count):
            decay = learning_rate_decay ** (i + pos_count)
            multiplier -= base_negative_delta * decay

        # Limit range [0.0, 2.0]
        multiplier = max(0.0, min(2.0, multiplier))

        return multiplier

    def _get_base_weights_for_sync(
        self, favorite_galleries: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """
        Calculate pure base weights (for syncing to database, excluding feedback adjustments)

        Args:
            favorite_galleries: User favorite galleries list

        Returns:
            Base weight dictionary (normalized)
        """
        if not favorite_galleries:
            return {}

        # Count tag frequency
        tag_counter = Counter()
        for gallery in favorite_galleries:
            tags = gallery.get("tags", [])
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except:
                    tags = []
            tag_counter.update(tags)

        # Calculate base weights (TF * namespace weight)
        base_weights = {}
        for tag, count in tag_counter.items():
            # Base frequency weight
            tf = count / len(favorite_galleries)

            # Namespace weight
            namespace = tag.split(":", 1)[0] if ":" in tag else "other"
            ns_weight = self.NAMESPACE_WEIGHTS.get(namespace, 1.0)

            # Base weight (excluding feedback)
            base_weights[tag] = tf * ns_weight

        # Normalize base weights
        max_base_weight = max(base_weights.values()) if base_weights else 1.0
        if max_base_weight > 0:
            base_weights = {k: v / max_base_weight for k, v in base_weights.items()}

        return base_weights

    def build_user_profile(
        self,
        favorite_galleries: List[Dict[str, Any]],
        feedback_stats: Optional[Dict[str, Dict[str, int]]] = None,
    ) -> None:
        """
        Build user tag profile

        Args:
            favorite_galleries: User favorite galleries list
            feedback_stats: Feedback statistics {tag: {'positive_count': int, 'negative_count': int}}
        """
        # Calculate tag weights (including feedback adjustments)
        self.compute_tag_weights_from_favorites(favorite_galleries, feedback_stats)

        # Extract all tags
        all_tags_list = self.extract_tags_from_galleries(favorite_galleries)

        # Convert to document format (space-separated)
        tag_documents = [" ".join(tags) for tags in all_tags_list]

        if not tag_documents:
            return

        # Use TF-IDF vectorization
        self.vectorizer = TfidfVectorizer(
            token_pattern=r"(?u)\b\w+:\w+\b|\b\w+\b",  # Match tag format
            min_df=1,
            max_df=0.8,
        )

        try:
            tag_matrix = cast(csr_matrix, self.vectorizer.fit_transform(tag_documents))
            # User profile: average vector of all favorites (converted to dense array)
            self.user_vector = np.asarray(tag_matrix.mean(axis=0)).reshape(1, -1)
            self.logger.info("User tag profile construction completed")
        except Exception as e:
            self.logger.error(f"Failed to build user profile: {e}")

    def compute_tag_similarity(self, candidate_tags: List[str]) -> float:
        """
        Compute tag similarity between candidate gallery and user profile

        Args:
            candidate_tags: Candidate gallery tag list

        Returns:
            Similarity score (0-1)
        """
        if not self.user_tag_weights or not candidate_tags:
            return 0.0

        # Method 1: Weighted Jaccard similarity
        candidate_set = set(candidate_tags)
        user_tags = set(self.user_tag_weights.keys())

        intersection = candidate_set & user_tags
        if not intersection:
            return 0.0

        total_user_weight = sum(self.user_tag_weights.values())
        if total_user_weight <= 0:
            return 0.0

        weighted_intersection = sum(self.user_tag_weights[tag] for tag in intersection)

        # Use normalized weight ratio as similarity
        jaccard_score = min(1.0, weighted_intersection / total_user_weight)

        # Method 2: Use TF-IDF vector cosine similarity (if built)
        if self.vectorizer is not None and self.user_vector is not None:
            try:
                candidate_doc = " ".join(candidate_tags)
                candidate_vector_sparse = cast(
                    csr_matrix, self.vectorizer.transform([candidate_doc])
                )
                candidate_vector = candidate_vector_sparse.toarray()
                user_vector = self.user_vector
                cosine_score = cosine_similarity(user_vector, candidate_vector)[0][0]

                # Combine both methods
                return 0.6 * jaccard_score + 0.4 * cosine_score
            except:
                return jaccard_score

        return jaccard_score

    def get_top_tags(self, n: int = 20) -> List[tuple]:
        """
        Get user's top N favorite tags

        Args:
            n: Return count

        Returns:
            [(tag, weight), ...] list
        """
        sorted_tags = sorted(
            self.user_tag_weights.items(), key=lambda x: x[1], reverse=True
        )
        return sorted_tags[:n]

    def explain_similarity(
        self, candidate_tags: List[str], top_n: int = 5
    ) -> List[str]:
        """
        Explain similarity source (for recommendation reasons)

        Args:
            candidate_tags: Candidate tags
            top_n: Return top N matching tags

        Returns:
            Matched tag list
        """
        candidate_set = set(candidate_tags)
        user_tags = set(self.user_tag_weights.keys())

        matched_tags = candidate_set & user_tags

        # Sort by weight
        sorted_matches = sorted(
            [(tag, self.user_tag_weights[tag]) for tag in matched_tags],
            key=lambda x: x[1],
            reverse=True,
        )

        return [tag for tag, _ in sorted_matches[:top_n]]
