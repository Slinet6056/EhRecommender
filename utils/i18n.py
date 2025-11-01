"""Internationalization (i18n) module"""

import json
import logging
from pathlib import Path
from typing import Dict, Any


class I18n:
    """Internationalization manager"""

    def __init__(self, locale: str = "en"):
        """
        Initialize i18n

        Args:
            locale: Language code (e.g., 'en', 'zh_CN')
        """
        self.locale = locale
        self.translations: Dict[str, Any] = {}
        self.logger = logging.getLogger(__name__)
        self._load_translations()

    def _load_translations(self) -> None:
        """Load translation files"""
        locale_dir = Path(__file__).parent.parent / "locales"
        locale_file = locale_dir / f"{self.locale}.json"

        if not locale_file.exists():
            self.logger.warning(
                f"Translation file not found: {locale_file}, using English"
            )
            locale_file = locale_dir / "en.json"

        if locale_file.exists():
            try:
                with open(locale_file, "r", encoding="utf-8") as f:
                    self.translations = json.load(f)
            except Exception as e:
                self.logger.error(f"Failed to load translations: {e}")
                self.translations = {}
        else:
            self.logger.warning("No translation files found, using empty translations")
            self.translations = {}

    def t(self, key: str, **kwargs) -> str:
        """
        Translate a key

        Args:
            key: Translation key (supports dot notation, e.g., 'commands.start')
            **kwargs: Variables to format in the translation

        Returns:
            Translated string
        """
        keys = key.split(".")
        value = self.translations

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                # Fallback to key if translation not found
                self.logger.warning(f"Translation key not found: {key}")
                return key

        if not isinstance(value, str):
            self.logger.warning(f"Translation value is not a string: {key}")
            return key

        # Format with kwargs if provided
        try:
            return value.format(**kwargs) if kwargs else value
        except KeyError as e:
            self.logger.warning(f"Missing format variable {e} in translation: {key}")
            return value

    def set_locale(self, locale: str) -> None:
        """
        Change locale and reload translations

        Args:
            locale: Language code
        """
        self.locale = locale
        self._load_translations()

    @staticmethod
    def get_user_locale(update) -> str:
        """
        Get user locale from Telegram update

        Args:
            update: Telegram Update object

        Returns:
            Language code
        """
        if update.message and update.message.from_user:
            lang_code = update.message.from_user.language_code
            if lang_code:
                # Map common language codes
                lang_map = {
                    "zh": "zh_CN",
                    "zh-CN": "zh_CN",
                    "zh-TW": "zh_TW",
                    "zh-HK": "zh_TW",
                }
                mapped = lang_map.get(lang_code)
                if mapped:
                    return mapped
                # Fallback to first part of language code
                parts = lang_code.split("-")
                if parts and parts[0]:
                    return parts[0]
        return "en"

    @staticmethod
    def get_available_locales() -> Dict[str, str]:
        """
        Get all available locales by scanning the locales directory

        Returns:
            Dictionary mapping locale codes to their display names
            e.g., {"en": "English", "zh_CN": "简体中文"}
        """
        locale_dir = Path(__file__).parent.parent / "locales"
        available_languages = {}

        if not locale_dir.exists():
            return {"en": "English"}  # Fallback

        # Scan for all .json files in locales directory
        for locale_file in locale_dir.glob("*.json"):
            locale_code = locale_file.stem  # Get filename without extension

            # Load the language file to get the display name
            try:
                with open(locale_file, "r", encoding="utf-8") as f:
                    translations = json.load(f)
                    # Get language name from translations
                    lang_name = translations.get("languages", {}).get(
                        locale_code, locale_code
                    )
                    available_languages[locale_code] = lang_name
            except Exception:
                # If we can't load it, just use the code as name
                available_languages[locale_code] = locale_code

        # Ensure at least English is available
        if "en" not in available_languages:
            available_languages["en"] = "English"

        return available_languages
