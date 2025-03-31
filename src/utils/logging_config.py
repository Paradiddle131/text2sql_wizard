import logging
import logging.handlers
import sys

from config.settings import settings


def setup_logging():
    """Configures logging for the application."""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    log_file = settings.RESOLVED_LOG_FILE

    # Define log format
    log_format = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Get root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # --- Console Handler ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_format)
    # Avoid adding handler if already present (e.g., in testing scenarios)
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        logger.addHandler(console_handler)

    # --- File Handler (Rotating) ---
    # Rotate logs: 5 files, max 5MB each
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(log_format)
    if not any(
        isinstance(h, logging.handlers.RotatingFileHandler)
        and h.baseFilename == str(log_file)
        for h in logger.handlers
    ):
        logger.addHandler(file_handler)

    # Optional: Set higher levels for noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)

    # Log that logging is configured (using the root logger directly)
    logging.info(f"Logging configured: Level={settings.LOG_LEVEL}, File='{log_file}'")
