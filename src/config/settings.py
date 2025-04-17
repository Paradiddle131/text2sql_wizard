import os
import logging
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, computed_field, PostgresDsn, validator
from pathlib import Path
from typing import Optional, Union

# Adjust BASE_DIR assuming settings.py is in 'src'
BASE_DIR = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    Manages application configuration using environment variables and a .env file.
    Determines database connection string and other core settings.

    Attributes:
        # --- Core LLM Settings ---
        LLM_MODEL: The primary LiteLLM model string (e.g., 'ollama/codellama:13b', 'gemini/gemini-1.5-flash-latest', 'gpt-4o').
        LLM_API_KEY: Optional API key for the LLM provider (reads from env var LLM_API_KEY).
        LLM_API_BASE_URL: Optional API base URL (e.g., for local Ollama or self-hosted models).
        LLM_TIMEOUT: Timeout in seconds for LLM API calls.

        # --- RAG ---
        EMBEDDING_MODEL_NAME: The Sentence Transformer model for embeddings.
        CHUNK_SIZE: Text splitter chunk size.
        CHUNK_OVERLAP: Text splitter chunk overlap.
        RAG_RETRIEVAL_K: Number of chunks to retrieve for context.
        DOCUMENT_UPLOAD_DIR_STR: Raw path string for storing uploaded docs temporarily (if needed).
        VECTOR_STORE_PATH_STR: Raw path string for vector store persistence.
        VECTOR_STORE_COLLECTION: The name of the collection within ChromaDB.

        # --- Database ---
        DB_HOST: PostgreSQL host (used if full DATABASE_URL is not provided).
        DB_PORT: PostgreSQL port (used if full DATABASE_URL is not provided).
        DB_USER: PostgreSQL username (used if full DATABASE_URL is not provided).
        DB_PASSWORD: PostgreSQL password (used if full DATABASE_URL is not provided).
        DB_NAME: PostgreSQL database name (used if full DATABASE_URL is not provided).
        DB_SCHEMA: Default PostgreSQL schema to introspect/query.
        DB_DDL_FILE_PATH_STR: Optional raw path string to a DDL file.

        # --- Logging ---
        LOG_LEVEL: Logging level for the application.
        LOG_FILE: Path to the log file, relative to project root.

        # --- Server ---
        APP_HOST: Host for the FastAPI application.
        APP_PORT: Port for the FastAPI application.
        UVICORN_LOG_LEVEL: Log level for Uvicorn server.

        # --- Computed Fields ---
        DATABASE_URL: Computed SQLAlchemy connection string (PostgreSQL).
        PROJECT_ROOT_PATH: Calculated absolute root path of the project.
        VECTOR_STORE_PATH: Resolved absolute path for vector store.
        DB_DDL_FILE_PATH: Resolved absolute path to the optional DDL file.
        LOGS_DIR: Resolved absolute path to the logs directory.
        RESOLVED_LOG_FILE: Resolved absolute path to the log file.
    """

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Core LLM Settings ---
    LLM_MODEL: str = "ollama/codellama:13b" # Example: Can be changed via .env
    LLM_API_KEY: Optional[str] = Field(None, repr=False) # Set via environment variable LLM_API_KEY
    LLM_API_BASE_URL: Optional[str] = None # Example: "http://localhost:11434" for local Ollama
    LLM_TIMEOUT: int = 60

    # --- RAG ---
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-small-en-v1.5"
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 150
    RAG_RETRIEVAL_K: int = 5
    DOCUMENT_UPLOAD_DIR_STR: str = "./data/uploaded_docs" # Example placeholder, not actively used by RAG service currently

    VECTOR_STORE_PATH_STR: str = "./data/chroma_db"
    VECTOR_STORE_COLLECTION: str = "text2sql_rag"

    # --- Database ---
    DB_HOST: Optional[str] = None
    DB_PORT: Optional[int] = 5432
    DB_USER: Optional[str] = None
    DB_PASSWORD: Optional[str] = Field(None, repr=False)
    DB_NAME: Optional[str] = None
    DB_SCHEMA: str = "public"
    DB_DDL_FILE_PATH_STR: Optional[str] = Field(None, alias="DB_DDL_FILE_PATH")

    # --- Logging ---
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "./logs/app.log"

    # --- Server ---
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    UVICORN_LOG_LEVEL: str = "info"

    @computed_field(repr=False)
    def DATABASE_URL(self) -> PostgresDsn:
        """
        Provides the primary SQLAlchemy database connection string (PostgreSQL).
        Reads 'DATABASE_URL' from the environment first. If not found,
        constructs it from DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME.
        """
        env_db_url = os.environ.get("DATABASE_URL")
        if env_db_url:
            logger.debug("Using DATABASE_URL from environment variable.")
            return PostgresDsn(env_db_url)
        else:
            logger.debug("Building DATABASE_URL from components.")
            if not all([self.DB_HOST, self.DB_USER, self.DB_NAME]):
                raise ValueError(
                    "If DATABASE_URL environment variable is not set, "
                    "DB_HOST, DB_USER, and DB_NAME must be provided."
                )
            return PostgresDsn.build(
                scheme="postgresql+psycopg2",
                username=self.DB_USER,
                password=self.DB_PASSWORD,
                host=self.DB_HOST,
                port=self.DB_PORT or 5432,
                path=f"{self.DB_NAME}",
            )

    @computed_field()
    def PROJECT_ROOT_PATH(self) -> Path:
        return BASE_DIR

    @computed_field()
    def VECTOR_STORE_PATH(self) -> Path:
        path = Path(self.VECTOR_STORE_PATH_STR)
        if not path.is_absolute():
            return (self.PROJECT_ROOT_PATH / path).resolve()
        return path

    @computed_field()
    def DB_DDL_FILE_PATH(self) -> Optional[Path]:
        """Resolves the absolute path to the DDL file, if configured."""
        if not self.DB_DDL_FILE_PATH_STR:
            return None
        path = Path(self.DB_DDL_FILE_PATH_STR)
        if not path.is_absolute():
            return (self.PROJECT_ROOT_PATH / path).resolve()
        return path

    @computed_field()
    def LOGS_DIR(self) -> Path:
        """Resolves the absolute log directory path."""
        log_file_path = Path(self.LOG_FILE)
        if not log_file_path.is_absolute():
            log_file_path = (self.PROJECT_ROOT_PATH / log_file_path).resolve()
        return log_file_path.parent

    @computed_field()
    def RESOLVED_LOG_FILE(self) -> Path:
        """Resolves the absolute log file path."""
        log_file_path = Path(self.LOG_FILE)
        if not log_file_path.is_absolute():
            return (self.PROJECT_ROOT_PATH / log_file_path).resolve()
        return log_file_path

    def init_dirs(self) -> None:
        """Explicitly initializes directories required by the settings."""
        logger.debug("Initializing required directories...")
        self.VECTOR_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        logger.debug("Directories initialized.")


try:
    settings = Settings()
    # Set API key from environment AFTER loading other settings
    settings.LLM_API_KEY = os.environ.get("LLM_API_KEY", settings.LLM_API_KEY)
    settings.init_dirs()

except Exception as e:
    print(f"[ERROR] Failed to load or validate configuration: {e}")
    print(
        "Ensure database settings (either DATABASE_URL env var or DB_HOST/PORT/USER/PASSWORD/NAME) "
        "are correctly set in '.env' and other required settings are valid (e.g., LLM_MODEL)."
    )
    raise