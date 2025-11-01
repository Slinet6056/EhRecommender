"""User favorites crawling module"""

import re
import time
import requests
from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional, Union
import logging


class FavoritesCrawler:
    """E-Hentai favorites crawler"""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize crawler

        Args:
            config: Crawler configuration
        """
        self.host = config.get("host", "exhentai.org")
        self.cookies = config.get("cookies", "")
        self.proxy = config.get("proxy", "")
        self.retry_times = config.get("retry_times", 3)
        self.timeout = config.get("timeout", 30)
        self.logger = logging.getLogger(__name__)

        # Setup session
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/75.0.3770.142 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*",
                "Accept-Language": "en-US;q=0.9,en;q=0.8",
                "DNT": "1",
                "Upgrade-Insecure-Requests": "1",
                "Referer": f"https://{self.host}/favorites.php",
            }
        )

        if self.cookies:
            # Set both Cookie header and cookiejar for compatibility with different site behaviors
            self.session.headers.update({"Cookie": self.cookies})
            cookie_jar = {}
            for item in self.cookies.split(";"):
                if "=" in item:
                    key, value = item.strip().split("=", 1)
                    cookie_jar[key] = value
            if cookie_jar:
                self.session.cookies.update(cookie_jar)

        if self.proxy:
            self.session.proxies = {"http": self.proxy, "https": self.proxy}

    def _make_request(self, url: str) -> Optional[str]:
        """
        Make HTTP request (with retry and 302 following)

        Args:
            url: Request URL

        Returns:
            Response text
        """
        for attempt in range(self.retry_times):
            try:
                response = self.session.get(
                    url, timeout=self.timeout, allow_redirects=True
                )
                response.raise_for_status()
                return response.text
            except Exception as e:
                self.logger.warning(
                    f"Request failed (attempt {attempt + 1}/{self.retry_times}): {e}"
                )
                if attempt < self.retry_times - 1:
                    time.sleep(1)
                else:
                    self.logger.error(f"Request finally failed: {url}")
                    return None
        return None

    def fetch_favorites_page(
        self, favcat: Union[int, str] = "all", next_token: str = ""
    ) -> Dict[str, Any]:
        """
        Get single page of favorites

        Args:
            favcat: Favorites category (0-9 or 'all')
            next_token: Pagination token (format: GID-TIMESTAMP)

        Returns:
            {
                'items': [(gid, token, favtime), ...],
                'next_token': str or None
            }
        """
        # Build URL
        url = f"https://{self.host}/favorites.php?favcat={favcat}&inline_set=fs_f"
        if next_token:
            url += f"&next={next_token}"

        self.logger.info(
            f"Fetching favorites page: favcat={favcat}, next={next_token or 'first'}"
        )

        html = self._make_request(url)
        if not html:
            return {"items": [], "next_token": None}

        # Extract all gallery links
        link_pattern = r"/g/(\d+)/([0-9a-f]{10})/"
        matches = re.findall(link_pattern, html)

        if not matches:
            self.logger.warning(
                "No gallery links found, favcat=%s, next=%s",
                favcat,
                next_token or "first",
            )
            return {"items": [], "next_token": None}

        # Deduplicate
        seen = set()
        items = []
        for gid_str, token in matches:
            gid = int(gid_str)
            key = f"{gid}_{token}"
            if key not in seen:
                seen.add(key)
                items.append({"gid": gid, "token": token, "favtime": None})

        # Extract favorite time
        # Format: <div...><p>Favorited:</p><p>2025-10-11 12:54</p></div>
        favtime_pattern = r"<div[^>]*>[\s\S]*?<p>Favorited:</p>[\s\S]*?<p>([\d\-\s:]+)</p>[\s\S]*?</div>"
        favtimes = re.findall(favtime_pattern, html, re.IGNORECASE)

        # Match favorite time to galleries
        for i, item in enumerate(items):
            if i < len(favtimes):
                favtime_str = favtimes[i].strip()
                try:
                    # Parse "2025-10-11 12:54" format
                    dt = datetime.strptime(favtime_str, "%Y-%m-%d %H:%M")
                    item["favtime"] = dt
                except Exception as e:
                    self.logger.warning(
                        f"Failed to parse favorite time: {favtime_str}, {e}"
                    )
                    item["favtime"] = datetime.now()
            else:
                item["favtime"] = datetime.now()

        # Extract next token
        # Format: favorites.php?...next=GID-TIMESTAMP
        next_match = re.search(r'favorites\.php\?[^"\']*next=(\d+-\d+)', html)
        next_token_value = next_match.group(1) if next_match else None

        self.logger.info(
            f"Parsed {len(items)} galleries, next={next_token_value or 'none'}"
        )

        # Convert to return format
        result_items = [(item["gid"], item["token"], item["favtime"]) for item in items]

        return {"items": result_items, "next_token": next_token_value}

    def fetch_all_favorites(
        self, favcat: Union[int, str] = "all", max_pages: int = 50
    ) -> List[Tuple[int, str, datetime]]:
        """
        Get all favorites (full sync)

        Args:
            favcat: Favorites category (0-9 or 'all')
            max_pages: Maximum pages

        Returns:
            All favorites list
        """
        self.logger.info(f"Starting full sync of favorites (favcat={favcat})")

        all_galleries = []
        next_token = ""
        page_num = 0

        while page_num < max_pages:
            time.sleep(1)  # Rate limiting

            result = self.fetch_favorites_page(favcat, next_token)

            if not result["items"]:
                self.logger.info(f"Page {page_num} has no data, stopping sync")
                break

            all_galleries.extend(result["items"])

            if not result["next_token"]:
                self.logger.info("Reached last page")
                break

            next_token = result["next_token"]
            page_num += 1

        self.logger.info(f"Full sync completed, total {len(all_galleries)} favorites")
        return all_galleries

    def fetch_new_favorites(
        self, known_gids: set, favcat: Union[int, str] = "all", max_pages: int = 10
    ) -> List[Tuple[int, str, datetime]]:
        """
        Incrementally get new favorites

        Args:
            known_gids: Known gid set
            favcat: Favorites category (0-9 or 'all')
            max_pages: Maximum pages to check

        Returns:
            New favorites list
        """
        self.logger.info(
            f"Starting incremental sync of favorites (known {len(known_gids)} items)"
        )

        new_galleries = []
        next_token = ""
        page_num = 0

        while page_num < max_pages:
            time.sleep(1)  # Rate limiting

            result = self.fetch_favorites_page(favcat, next_token)

            if not result["items"]:
                self.logger.info(f"Page {page_num} has no data, stopping")
                break

            # Check if there are new favorites
            page_new = [g for g in result["items"] if g[0] not in known_gids]

            if not page_new:
                self.logger.info(f"Page {page_num} has no new favorites, stopping sync")
                break

            new_galleries.extend(page_new)

            if not result["next_token"]:
                self.logger.info("Reached last page")
                break

            next_token = result["next_token"]
            page_num += 1

        self.logger.info(
            f"Incremental sync completed, {len(new_galleries)} new favorites"
        )
        return new_galleries

    def fetch_all_categories(
        self, max_pages_per_category: int = 50
    ) -> List[Tuple[int, str, datetime]]:
        """
        Get favorites from all 10 favorite categories

        Args:
            max_pages_per_category: Maximum pages per category

        Returns:
            All favorites list
        """
        self.logger.info("Starting sync of all favorite categories")

        all_galleries = []

        for favcat in range(10):
            self.logger.info(f"\nSyncing favorite category {favcat}...")
            galleries = self.fetch_all_favorites(favcat, max_pages_per_category)
            all_galleries.extend(galleries)
            self.logger.info(f"Category {favcat} completed, got {len(galleries)} items")

        self.logger.info(f"\nTotal sync: {len(all_galleries)} favorites")
        return all_galleries
