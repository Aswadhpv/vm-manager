import logging
import os
from config.settings import LOG_FILE

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger("vm-manager")


def log_event(message: str) -> None:
    """
    Write a single line event to the main vm-manager.log file.
    """
    logger.info(message)
