"""Minimal console logging shared by scripts and the ingestion pipeline."""

from __future__ import annotations

import logging
import sys

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_ROOT_LOGGER_NAME = "debate_engine"


def configure_logging(level: int | str = logging.INFO) -> logging.Logger:
    """Attach a single console handler to the package logger.

    Safe to call more than once; repeat calls only update the level rather
    than stacking duplicate handlers.
    """
    logger = logging.getLogger(_ROOT_LOGGER_NAME)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT))
        logger.addHandler(handler)

    # Package logs should not also surface through the root logger.
    logger.propagate = False
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a namespaced child of the package logger."""
    if not name or name == _ROOT_LOGGER_NAME:
        return logging.getLogger(_ROOT_LOGGER_NAME)
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")
