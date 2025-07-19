import logging
import os
from typing import Optional


def setup_logging(log_level: Optional[str] = None):
    """
    Set up logging configuration for the application.
    """
    if log_level is None:
        log_level = os.getenv("LOG_LEVEL", "INFO")
    log_level = log_level.upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(name)s:%(lineno)d - %(message)s",
        handlers=[
            logging.StreamHandler(),  # Log to console
            logging.FileHandler("app.log", encoding="utf-8"),  # Log to a file
        ],
    )
    logging.info("Logging configured successfully.")