"""
Logging module for the Llama.cpp Build Assistant.
Handles build logs, installation logs, and error logs.
"""
import os
import logging
from datetime import datetime
from config import BUILD_LOG_FILE, INSTALL_LOG_FILE, ERROR_LOG_FILE


def get_logger(log_file, name=None):
    """Create a logger that writes to a specific file and to console."""
    logger = logging.getLogger(name or os.path.basename(log_file))
    logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    # File handler
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


def get_build_logger():
    return get_logger(BUILD_LOG_FILE, "build")


def get_install_logger():
    return get_logger(INSTALL_LOG_FILE, "install")


def get_error_logger():
    return get_logger(ERROR_LOG_FILE, "error")


def log_build(message, logger=None):
    """Convenience function for build logging."""
    if logger is None:
        logger = get_build_logger()
    logger.info(message)


def log_install(message, logger=None):
    """Convenience function for installation logging."""
    if logger is None:
        logger = get_install_logger()
    logger.info(message)


def log_error(message, logger=None):
    """Convenience function for error logging."""
    if logger is None:
        logger = get_error_logger()
    logger.error(message)


def log_warning(message, logger=None):
    """Convenience function for warning logging."""
    if logger is None:
        logger = get_build_logger()
    logger.warning(message)
