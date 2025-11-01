"""SQLite database model"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
import json
import logging


class Database:
    """Local SQLite database management class"""

    def __init__(self, db_path: str):
        """
        Initialize database

        Args:
            db_path: Database file path
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)
        self._init_database()

    def get_connection(self) -> sqlite3.Connection:
        """Get database connection"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_database(self) -> None:
        """Initialize database table structure"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # User favorites table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS favorites (
                    gid INTEGER PRIMARY KEY,
                    token TEXT NOT NULL,
                    added_time TIMESTAMP NOT NULL,
                    last_sync TIMESTAMP NOT NULL
                )
            """
            )

            # User feedback table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback (
                    gid INTEGER PRIMARY KEY,
                    rating INTEGER NOT NULL,
                    feedback_time TIMESTAMP NOT NULL,
                    source TEXT NOT NULL
                )
            """
            )

            # Recommendation history table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS recommendation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gid INTEGER NOT NULL,
                    score REAL NOT NULL,
                    reason TEXT NOT NULL,
                    recommended_time TIMESTAMP NOT NULL,
                    notified INTEGER DEFAULT 0
                )
            """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rec_history_gid
                ON recommendation_history(gid)
            """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rec_history_time
                ON recommendation_history(recommended_time DESC)
            """
            )

            # User preferences table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    tag TEXT PRIMARY KEY,
                    weight REAL NOT NULL DEFAULT 1.0,
                    positive_count INTEGER DEFAULT 0,
                    negative_count INTEGER DEFAULT 0,
                    updated_time TIMESTAMP NOT NULL
                )
            """
            )

            # Sync checkpoint table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_checkpoint (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """
            )

            # User settings table (for language preference, etc.)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    locale TEXT NOT NULL DEFAULT 'en',
                    updated_time TIMESTAMP NOT NULL
                )
            """
            )

            conn.commit()
            self.logger.info("Database initialization completed")

    # ==================== Favorites Management ====================

    def add_favorite(self, gid: int, token: str, added_time: datetime) -> None:
        """Add favorite"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO favorites (gid, token, added_time, last_sync)
                VALUES (?, ?, ?, ?)
            """,
                (gid, token, added_time, datetime.now()),
            )
            conn.commit()

    def remove_favorite(self, gid: int) -> None:
        """Remove favorite"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM favorites WHERE gid = ?", (gid,))
            conn.commit()

    def get_all_favorites(self) -> List[Tuple[int, str]]:
        """Get all favorites (gid, token)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT gid, token FROM favorites")
            return [(row["gid"], row["token"]) for row in cursor.fetchall()]

    def is_favorited(self, gid: int) -> bool:
        """Check if already favorited"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM favorites WHERE gid = ? LIMIT 1", (gid,))
            return cursor.fetchone() is not None

    def clear_favorites(self) -> None:
        """Clear favorites table (for full sync)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM favorites")
            conn.commit()

    # ==================== Feedback Management ====================

    def add_feedback(self, gid: int, rating: int, source: str) -> None:
        """
        Add user feedback

        Args:
            gid: Gallery ID
            rating: Rating (1=like, -1=dislike)
            source: Source (new/old/manual)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO feedback (gid, rating, feedback_time, source)
                VALUES (?, ?, ?, ?)
            """,
                (gid, rating, datetime.now(), source),
            )
            conn.commit()

    def get_feedback(self, gid: int) -> Optional[int]:
        """Get gallery feedback rating"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT rating FROM feedback WHERE gid = ?", (gid,))
            row = cursor.fetchone()
            return row["rating"] if row else None

    def get_all_feedback(self) -> List[Tuple[int, int]]:
        """Get all feedback (gid, rating)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT gid, rating FROM feedback")
            return [(row["gid"], row["rating"]) for row in cursor.fetchall()]

    # ==================== Recommendation History ====================

    def add_recommendation(
        self, gid: int, score: float, reason: Dict[str, Any], notified: bool = False
    ) -> None:
        """Add recommendation record"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO recommendation_history
                (gid, score, reason, recommended_time, notified)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    gid,
                    score,
                    json.dumps(reason, ensure_ascii=False),
                    datetime.now(),
                    1 if notified else 0,
                ),
            )
            conn.commit()

    def is_recommended(self, gid: int, expiry_days: Optional[int] = None) -> bool:
        """
        Check if already recommended

        Args:
            gid: Gallery ID
            expiry_days: Expiry days, if specified only check recommendations within this period

        Returns:
            Whether already recommended within validity period
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            if expiry_days is not None:
                # Calculate expiry time point
                expiry_time = datetime.now() - timedelta(days=expiry_days)
                cursor.execute(
                    "SELECT 1 FROM recommendation_history WHERE gid = ? AND recommended_time > ? LIMIT 1",
                    (gid, expiry_time),
                )
            else:
                cursor.execute(
                    "SELECT 1 FROM recommendation_history WHERE gid = ? LIMIT 1", (gid,)
                )

            return cursor.fetchone() is not None

    def mark_as_notified(self, gid: int) -> None:
        """Mark as notified"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE recommendation_history
                SET notified = 1
                WHERE gid = ?
            """,
                (gid,),
            )
            conn.commit()

    def clean_expired_recommendations(self, expiry_days: int) -> int:
        """
        Clean expired recommendation records

        Args:
            expiry_days: Expiry days

        Returns:
            Number of deleted records
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            expiry_time = datetime.now() - timedelta(days=expiry_days)
            cursor.execute(
                """
                DELETE FROM recommendation_history
                WHERE recommended_time < ?
            """,
                (expiry_time,),
            )
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count

    # ==================== User Preferences ====================

    def update_tag_preference(
        self, tag: str, weight: float, positive_count: int = 0, negative_count: int = 0
    ) -> None:
        """Update tag preference"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO user_preferences
                (tag, weight, positive_count, negative_count, updated_time)
                VALUES (?, ?, ?, ?, ?)
            """,
                (tag, weight, positive_count, negative_count, datetime.now()),
            )
            conn.commit()

    def get_tag_preference(self, tag: str) -> Optional[Dict[str, Any]]:
        """Get tag preference"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT weight, positive_count, negative_count, updated_time
                FROM user_preferences WHERE tag = ?
            """,
                (tag,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "tag": tag,
                    "weight": row["weight"],
                    "positive_count": row["positive_count"],
                    "negative_count": row["negative_count"],
                    "updated_time": row["updated_time"],
                }
            return None

    def get_all_tag_preferences(self) -> Dict[str, float]:
        """Get all tag weights"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT tag, weight FROM user_preferences")
            return {row["tag"]: row["weight"] for row in cursor.fetchall()}

    def get_all_tag_feedback_stats(self) -> Dict[str, Dict[str, int]]:
        """
        Get feedback statistics for all tags

        Returns:
            {tag: {'positive_count': int, 'negative_count': int}}
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT tag, positive_count, negative_count FROM user_preferences"
            )
            return {
                row["tag"]: {
                    "positive_count": row["positive_count"],
                    "negative_count": row["negative_count"],
                }
                for row in cursor.fetchall()
            }

    def sync_tag_preferences(self, tag_weights: Dict[str, float]) -> None:
        """
        Sync tag base weights (only update tags without feedback, preserve weights of tags with feedback)

        Note: This method only syncs base weights calculated from favorites, will not overwrite tag weights adjusted by feedback
        """
        if not tag_weights:
            return

        with self.get_connection() as conn:
            cursor = conn.cursor()

            for tag, base_weight in tag_weights.items():
                # Check if tag has feedback records
                cursor.execute(
                    """
                    SELECT positive_count, negative_count
                    FROM user_preferences
                    WHERE tag = ?
                """,
                    (tag,),
                )
                row = cursor.fetchone()

                if row and (row["positive_count"] > 0 or row["negative_count"] > 0):
                    # Tags with feedback, preserve existing weights, do not overwrite
                    continue

                # Tags without feedback, update base weights
                pos = row["positive_count"] if row else 0
                neg = row["negative_count"] if row else 0
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO user_preferences
                    (tag, weight, positive_count, negative_count, updated_time)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (tag, base_weight, pos, neg, datetime.now()),
                )

            conn.commit()

    def increment_tag_feedback(self, tag: str, is_positive: bool) -> None:
        """Increment tag feedback count"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Get current values first
            cursor.execute(
                """
                SELECT weight, positive_count, negative_count
                FROM user_preferences WHERE tag = ?
            """,
                (tag,),
            )
            row = cursor.fetchone()

            if row:
                weight = row["weight"]
                pos = row["positive_count"]
                neg = row["negative_count"]
            else:
                weight = 1.0
                pos = neg = 0

            # Update count
            if is_positive:
                pos += 1
            else:
                neg += 1

            self.update_tag_preference(tag, weight, pos, neg)

    # ==================== Checkpoint Management ====================

    def set_checkpoint(self, key: str, value: str) -> None:
        """Set checkpoint"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO sync_checkpoint (key, value)
                VALUES (?, ?)
            """,
                (key, value),
            )
            conn.commit()

    def get_checkpoint(self, key: str) -> Optional[str]:
        """Get checkpoint"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM sync_checkpoint WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else None

    # ==================== Statistics ====================

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Favorites count
            cursor.execute("SELECT COUNT(*) as count FROM favorites")
            favorites_count = cursor.fetchone()["count"]

            # Feedback count
            cursor.execute("SELECT COUNT(*) as count FROM feedback")
            feedback_count = cursor.fetchone()["count"]

            # Positive/negative feedback
            cursor.execute(
                """
                SELECT
                    SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) as positive,
                    SUM(CASE WHEN rating = -1 THEN 1 ELSE 0 END) as negative
                FROM feedback
            """
            )
            feedback_stats = cursor.fetchone()

            # Recommendation count
            cursor.execute("SELECT COUNT(*) as count FROM recommendation_history")
            recommendation_count = cursor.fetchone()["count"]

            return {
                "favorites_count": favorites_count,
                "feedback_count": feedback_count,
                "positive_feedback": feedback_stats["positive"] or 0,
                "negative_feedback": feedback_stats["negative"] or 0,
                "recommendation_count": recommendation_count,
            }

    # ==================== User Settings ====================

    def set_user_locale(self, user_id: int, locale: str) -> None:
        """Set user language preference"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO user_settings (user_id, locale, updated_time)
                VALUES (?, ?, ?)
            """,
                (user_id, locale, datetime.now()),
            )
            conn.commit()

    def get_user_locale(self, user_id: int) -> Optional[str]:
        """Get user language preference"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT locale FROM user_settings WHERE user_id = ?", (user_id,)
            )
            row = cursor.fetchone()
            return row["locale"] if row else None
