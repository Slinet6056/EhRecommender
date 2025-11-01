"""Logging configuration module"""

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logger(
    name: str, level: str = "INFO", log_file: Optional[str] = None
) -> logging.Logger:
    """
    Setup logger

    Args:
        name: Logger name
        level: Log level (DEBUG/INFO/WARNING/ERROR/CRITICAL)
        log_file: Log file path (optional)

    Returns:
        Configured logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    # Formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (if specified)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
