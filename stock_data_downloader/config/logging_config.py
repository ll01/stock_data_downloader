import logging
import os
from typing import Optional


def setup_logging(log_level: Optional[str] = None):
    """
    Set up logging configuration for the application.
    """
    print(log_level)
    if log_level is None:
        log_level = os.getenv("LOG_LEVEL", "INFO")
        print("log level is none setting to info")
    log_level = log_level.upper()
    
    numeric_level = getattr(logging, log_level, None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {log_level}")
    
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(levelname)s - %(name)s:%(lineno)d - %(message)s",
        handlers=[
            logging.StreamHandler(),  # Log to console
            logging.FileHandler("app.log", encoding="utf-8"),  # Log to a file
        ],
    )
    logger = logger = logging.getLogger(__name__)
    print(f"log set {logger.level}")
    print(f"log reqiested {numeric_level}")
    logging.debug("Logging configured successfully.")