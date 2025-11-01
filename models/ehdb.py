"""EHDB database connection (read-only)"""

import json
import logging
from decimal import Decimal
from typing import Any, List, Dict, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg import Connection


class EhdbDatabase:
    """EHDB PostgreSQL database connection class (read-only)"""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize database connection

        Args:
            config: Database configuration dictionary
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._conn: Optional[Connection[Any]] = None

    def connect(self) -> None:
        """Establish database connection"""
        try:
            conninfo = (
                f"host={self.config['host']} "
                f"port={self.config['port']} "
                f"user={self.config['user']} "
                f"password={self.config['password']} "
                f"dbname={self.config['dbname']}"
            )
            self._conn = psycopg.connect(conninfo)
            self.logger.info("EHDB database connection successful")
        except Exception as e:
            self.logger.error(f"EHDB database connection failed: {e}")
            raise

    def close(self) -> None:
        """Close database connection"""
        if self._conn:
            self._conn.close()
            self.logger.info("EHDB database connection closed")

    def execute_query(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """
        Execute query and return results

        Args:
            query: SQL query statement
            params: Query parameters

        Returns:
            Query result list
        """
        if self._conn is None:
            self.connect()

        if self._conn is None:
            raise RuntimeError("EHDB database connection not initialized")

        try:
            with self._conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, params)  # type: ignore[arg-type]
                rows = cursor.fetchall()
                return [self._normalize_row(dict(row)) for row in rows]
        except Exception as e:
            self.logger.error(f"Query execution failed: {e}")
            if self._conn is not None:
                self._conn.rollback()
            raise

    def get_gallery(self, gid: int) -> Optional[Dict[str, Any]]:
        """
        Get single gallery information

        Args:
            gid: Gallery ID

        Returns:
            Gallery information dictionary
        """
        query = """
            SELECT gid, token, archiver_key, title, title_jpn, category,
                   thumb, uploader, posted, filecount, filesize, expunged,
                   removed, replaced, rating, torrentcount, tags
            FROM gallery
            WHERE gid = %s
        """
        results = self.execute_query(query, (gid,))
        return results[0] if results else None

    def get_galleries_by_ids(self, gids: List[int]) -> List[Dict[str, Any]]:
        """
        Get gallery information in batch

        Args:
            gids: Gallery ID list

        Returns:
            Gallery information list
        """
        if not gids:
            return []

        query = """
            SELECT gid, token, archiver_key, title, title_jpn, category,
                   thumb, uploader, posted, filecount, filesize, expunged,
                   removed, replaced, rating, torrentcount, tags
            FROM gallery
            WHERE gid = ANY(%s)
        """
        return self.execute_query(query, (gids,))

    def get_new_galleries(
        self, since_timestamp: int, limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Get new galleries after specified time

        Args:
            since_timestamp: Unix timestamp
            limit: Maximum return count

        Returns:
            Gallery information list
        """
        query = """
            SELECT gid, token, archiver_key, title, title_jpn, category,
                   thumb, uploader, posted, filecount, filesize, expunged,
                   removed, replaced, rating, torrentcount, tags
            FROM gallery
            WHERE EXTRACT(EPOCH FROM posted)::bigint > %s
                AND expunged = false
                AND removed = false
            ORDER BY posted DESC
            LIMIT %s
        """
        return self.execute_query(query, (since_timestamp, limit))

    def get_random_galleries(
        self, count: int = 100, min_rating: float = 3.0
    ) -> List[Dict[str, Any]]:
        """
        Get random galleries (for old gallery recommendations)

        Args:
            count: Count
            min_rating: Minimum rating

        Returns:
            Gallery information list
        """
        query = """
            SELECT gid, token, archiver_key, title, title_jpn, category,
                   thumb, uploader, posted, filecount, filesize, expunged,
                   removed, replaced, rating, torrentcount, tags
            FROM gallery
            WHERE expunged = false
                AND removed = false
                AND rating >= %s
            ORDER BY RANDOM()
            LIMIT %s
        """
        return self.execute_query(query, (min_rating, count))

    def search_similar_galleries(
        self, tags: List[str], uploader: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Search similar galleries

        Args:
            tags: Tag list
            uploader: Uploader (optional)
            limit: Maximum return count

        Returns:
            Gallery information list
        """
        # Use JSONB containment operator
        query = """
            SELECT gid, token, archiver_key, title, title_jpn, category,
                   thumb, uploader, posted, filecount, filesize, expunged,
                   removed, replaced, rating, torrentcount, tags,
                   jsonb_array_length(
                       (SELECT jsonb_agg(elem)
                        FROM jsonb_array_elements(tags) elem
                        WHERE elem IN (SELECT jsonb_array_elements(%s::jsonb)))
                   ) as tag_match_count
            FROM gallery
            WHERE expunged = false
                AND removed = false
                AND tags ?| %s
        """

        params: List[Any] = [json.dumps(tags), tags]

        if uploader:
            query += " AND uploader = %s"
            params.append(uploader)

        query += " ORDER BY tag_match_count DESC, rating DESC LIMIT %s"
        params.append(limit)

        return self.execute_query(query, tuple(params))

    def get_galleries_by_uploader(
        self, uploader: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get galleries by specified uploader

        Args:
            uploader: Uploader name
            limit: Maximum return count

        Returns:
            Gallery information list
        """
        query = """
            SELECT gid, token, archiver_key, title, title_jpn, category,
                   thumb, uploader, posted, filecount, filesize, expunged,
                   removed, replaced, rating, torrentcount, tags
            FROM gallery
            WHERE uploader = %s
                AND expunged = false
                AND removed = false
            ORDER BY posted DESC
            LIMIT %s
        """
        return self.execute_query(query, (uploader, limit))

    # ==================== Helper Methods ====================

    def _normalize_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Convert database returned data to Python common types"""
        if not row:
            return row

        normalized = dict(row)

        for key, value in list(normalized.items()):
            if isinstance(value, Decimal):
                if key in ("rating", "avg_rating"):
                    normalized[key] = float(value)
                else:
                    normalized[key] = int(value)

        tags = normalized.get("tags")
        if isinstance(tags, str):
            try:
                normalized["tags"] = json.loads(tags)
            except Exception:
                pass

        return normalized
