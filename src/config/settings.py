from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """
    Manages application configuration using environment variables and a .env file.

    Attributes:
        LLM_PROVIDER: The primary LLM provider.
        OLLAMA_MODEL_NAME: The specific Ollama model to use.
        OLLAMA_API_BASE_URL: The base URL for the Ollama API service.
        EMBEDDING_MODEL_NAME: The Sentence Transformer model for embeddings.
        VECTOR_STORE_PATH_STR: Raw path string for vector store persistence.
        VECTOR_STORE_COLLECTION: The name of the collection within ChromaDB.
        DATABASE_URL_STR: Raw database URL string (MUST be set in .env).
        LOG_LEVEL: Logging level for the application.
        LOG_FILE: Path to the log file, relative to project root.

        PROJECT_ROOT_PATH: Calculated absolute root path of the project.
        VECTOR_STORE_PATH: Resolved absolute path for vector store.
        DATABASE_URL: Resolved SQLAlchemy connection string.
        LOGS_DIR: Resolved absolute path to the logs directory.
    """

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- LLM Configuration ---
    LLM_PROVIDER: str = "ollama"
    OLLAMA_MODEL_NAME: str = "codellama:13b"
    OLLAMA_API_BASE_URL: str = "http://localhost:11434"

    # --- Embedding Model Configuration ---
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-small-en-v1.5"

    # --- Vector Store Configuration ---
    VECTOR_STORE_PATH_STR: str = "./data/chroma_db"
    VECTOR_STORE_COLLECTION: str = "text2sql_rag"

    # --- Database Configuration ---
    DATABASE_URL_STR: str = Field(..., validation_alias="DATABASE_URL")

    # --- Logging Configuration ---
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "./logs/app.log"  # Relative path for log file

    # --- Calculated Paths ---
    @property
    def PROJECT_ROOT_PATH(self) -> Path:
        return BASE_DIR

    @property
    def VECTOR_STORE_PATH(self) -> Path:
        path = Path(self.VECTOR_STORE_PATH_STR)
        if not path.is_absolute():
            return (self.PROJECT_ROOT_PATH / path).resolve()
        return path

    @property
    def DATABASE_URL(self) -> str:
        """Resolves the database URL, handling relative SQLite paths."""
        db_url = self.DATABASE_URL_STR  # Get value loaded by Pydantic
        if db_url.startswith("sqlite:///./"):
            relative_path = db_url[len("sqlite:///./") :]
            abs_path = (self.PROJECT_ROOT_PATH / relative_path).resolve()
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{abs_path}"
        elif db_url.startswith("sqlite:///"):
            abs_path = Path(db_url[len("sqlite:///") :])
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            return db_url
        return db_url

    @property
    def LOGS_DIR(self) -> Path:
        """Resolves the absolute path to the log directory."""
        log_file_path = Path(self.LOG_FILE)
        if not log_file_path.is_absolute():
            log_file_path = (self.PROJECT_ROOT_PATH / log_file_path).resolve()
        log_dir = log_file_path.parent
        log_dir.mkdir(parents=True, exist_ok=True)  # Ensure logs directory exists
        return log_dir

    @property
    def RESOLVED_LOG_FILE(self) -> Path:
        """Resolves the absolute path to the log file."""
        log_file_path = Path(self.LOG_FILE)
        if not log_file_path.is_absolute():
            return (self.PROJECT_ROOT_PATH / log_file_path).resolve()
        return log_file_path


# --- Instantiate Settings ---
try:
    settings = Settings()
    # Ensure directories exist upon successful settings load
    settings.VECTOR_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ = settings.DATABASE_URL
    _ = settings.LOGS_DIR
except Exception as e:
    print(f"[ERROR] Failed to load configuration: {e}")
    print(
        "Ensure required environment variables (like DATABASE_URL) are set in '.env'."
    )
    raise
