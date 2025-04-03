from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import PostgresDsn, computed_field
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
    DATABASE_URL: str | None = None  # Loaded directly if present in .env
    DB_HOST: str | None = None
    DB_PORT: int | None = None
    DB_USER: str | None = None
    DB_PASSWORD: str | None = None
    DB_NAME: str | None = None
    DB_SCHEMA: str = "public"

    # --- Logging Configuration ---
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "./logs/app.log"  # Relative path for log file

    @computed_field(repr=False)
    def SQLALCHEMY_DATABASE_URL(self) -> str:
        """Computes the SQLAlchemy database URL."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        else:
            return str(
                PostgresDsn.build(
                    scheme="postgresql+psycopg2",
                    username=self.DB_USER,
                    password=self.DB_PASSWORD,
                    host=self.DB_HOST,
                    port=self.DB_PORT,
                    path=f"{self.DB_NAME}",
                )
            )

    @computed_field()
    def PROJECT_ROOT_PATH(self) -> Path:
        return BASE_DIR

    @computed_field
    def VECTOR_STORE_PATH(self) -> Path:
        path = Path(self.VECTOR_STORE_PATH_STR)
        if not path.is_absolute():
            return (self.PROJECT_ROOT_PATH / path).resolve()
        return path

    @computed_field
    def LOGS_DIR(self) -> Path:
        """Resolves the absolute log directory without side effects."""
        log_file_path = Path(self.LOG_FILE)
        if not log_file_path.is_absolute():
            log_file_path = (self.PROJECT_ROOT_PATH / log_file_path).resolve()
        return log_file_path.parent

    @computed_field
    def RESOLVED_LOG_FILE(self) -> Path:
        """Resolves the absolute log file path."""
        log_file_path = Path(self.LOG_FILE)
        if not log_file_path.is_absolute():
            return (self.PROJECT_ROOT_PATH / log_file_path).resolve()
        return log_file_path

    def init_dirs(self) -> None:
        """
        Explicitly initialize directories for the vector store and logs.
        This separates side effects from pure computation.
        """
        self.VECTOR_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.LOGS_DIR.mkdir(parents=True, exist_ok=True)


try:
    settings = Settings()
    if not settings.DATABASE_URL and not all(
        [settings.DB_HOST, settings.DB_USER, settings.DB_NAME]
    ):
        raise ValueError(
            "If DATABASE_URL is not set, DB_HOST, DB_USER, and DB_NAME must be provided in .env"
        )
    settings.init_dirs()
except Exception as e:
    print(f"[ERROR] Failed to load configuration: {e}")
    print(
        "Ensure required environment variables (like DATABASE_URL) are set in '.env'."
    )
    raise
