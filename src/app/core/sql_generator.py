import logging
from typing import AsyncGenerator, List, Dict
from sqlalchemy import (
    create_engine,
    inspect as sqla_inspect,
    exc as sqlalchemy_exc,
    MetaData,
)
from sqlalchemy.engine import Engine

from app.core.llm_handler import LLMNotAvailableError, stream_llm_response
from config.settings import settings

logger = logging.getLogger(__name__)

_SCHEMA_CACHE: str | None = None
_SCHEMA_SOURCE: str | None = None
_DB_ENGINE: Engine | None = None


def _get_db_engine() -> Engine:
    """Initializes and returns the SQLAlchemy engine."""
    global _DB_ENGINE
    if _DB_ENGINE is None:
        try:
            db_url_str = str(settings.DATABASE_URL)
            _DB_ENGINE = create_engine(
                db_url_str,
                pool_pre_ping=True,
                connect_args={"options": f"-csearch_path={settings.DB_SCHEMA}"}
                if settings.DATABASE_URL.scheme.startswith("postgresql")
                else {},
            )
            with _DB_ENGINE.connect() as connection:
                logger.info(f"Successfully connected to database.")
        except sqlalchemy_exc.SQLAlchemyError as e:
            logger.exception(f"Failed to create database engine: {e}")
            raise ConnectionError(f"Could not connect to the database: {e}") from e
    return _DB_ENGINE


def _get_schema_from_introspection(engine: Engine, target_schema: str) -> str | None:
    """Uses SQLAlchemy inspect to get table definitions for a target schema."""
    schema_parts = []
    logger.info(f"Attempting introspection for schema: '{target_schema}'")
    try:
        inspector = sqla_inspect(engine)
        tables = inspector.get_table_names(schema=target_schema)
        if not tables:
            logger.warning(
                f"Introspection found no tables in schema '{target_schema}'."
            )
            return None
        logger.debug(f"Found tables in schema '{target_schema}': {tables}")
        metadata = MetaData()
        metadata.reflect(bind=engine, schema=target_schema, only=tables)
        for table_name in sorted(tables):
            table_key = f"{target_schema}.{table_name}" if target_schema else table_name
            table = metadata.tables.get(table_key)
            if table is None:
                continue
            from sqlalchemy.schema import CreateTable

            create_table_ddl = str(CreateTable(table).compile(engine)).strip()
            schema_parts.append(f"{create_table_ddl};")
        if not schema_parts:
            logger.warning(
                f"No table definitions generated for schema '{target_schema}'."
            )
            return None
        full_schema = "\n\n".join(schema_parts)
        logger.info(
            f"Successfully generated schema via introspection for '{target_schema}'."
        )
        return full_schema
    except sqlalchemy_exc.SQLAlchemyError as e:
        logger.exception(f"DB error during introspection for '{target_schema}': {e}")
        return None
    except Exception as e:
        logger.exception(
            f"Unexpected error during introspection for '{target_schema}': {e}"
        )
        return None


def _get_schema_from_ddl_file() -> str | None:
    """Reads schema definition from the DDL file specified in settings."""
    ddl_path = settings.DB_DDL_FILE_PATH
    if not ddl_path or not ddl_path.exists():
        logger.debug(f"DDL file not configured or not found: {ddl_path}")
        return None
    try:
        schema_content = ddl_path.read_text()
        logger.info(f"Successfully loaded schema from DDL file: {ddl_path}")
        return schema_content.strip()
    except Exception as e:
        logger.exception(f"Error reading DDL file {ddl_path}: {e}")
        return None


def get_database_schema(force_refresh: bool = False) -> str:
    """Retrieves database schema via introspection or DDL file, caches result."""
    global _SCHEMA_CACHE, _SCHEMA_SOURCE
    if _SCHEMA_CACHE and not force_refresh:
        logger.debug(f"Using cached schema (source: {_SCHEMA_SOURCE})")
        return _SCHEMA_CACHE
    logger.info("Attempting to load database schema...")
    schema: str | None = None
    source: str = "Unknown"
    try:
        engine = _get_db_engine()
        schema = _get_schema_from_introspection(engine, settings.DB_SCHEMA)
        if schema:
            source = "Introspection"
        else:
            logger.warning("Introspection failed/yielded no schema.")
    except ConnectionError:
        logger.error("Introspection skipped: DB connection failed.")
    except Exception as e:
        logger.exception(f"Error during introspection setup: {e}")
    if not schema:
        logger.info("Attempting DDL file fallback.")
        schema = _get_schema_from_ddl_file()
        if schema:
            source = "DDL File"
    if not schema:
        logger.error("Failed to load schema from introspection & DDL file.")
        _SCHEMA_CACHE = "ERROR:NO_SCHEMA_AVAILABLE"
        _SCHEMA_SOURCE = "None"
    else:
        logger.info(f"Database schema loaded (source: {source}).")
        _SCHEMA_CACHE = schema
        _SCHEMA_SOURCE = source
    return _SCHEMA_CACHE


async def generate_sql_query(
    user_query: str, force_schema_refresh: bool = False
) -> AsyncGenerator[str, None]:
    """
    Generates SQL query from NL query using LLM, streaming the raw response chunks.

    Args:
        user_query: The natural language query.
        force_schema_refresh: Whether to force reloading the DB schema.

    Yields:
        Raw chunks of the generated SQL query text as received from the LLM.

    Raises:
        ValueError: If the database schema cannot be loaded.
        LLMNotAvailableError: If the LLM call fails.
    """
    db_schema = get_database_schema(force_refresh=force_schema_refresh)
    if db_schema.startswith("ERROR:"):
        logger.error(f"Cannot generate SQL: Schema loading failed ({db_schema})")
        raise ValueError(f"Database schema could not be loaded ({db_schema}).")

    system_prompt = f"""You are an expert PostgreSQL query generator.
    Given the following PostgreSQL database schema (specifically for the '{settings.DB_SCHEMA}' schema) and a user question, generate a *single*, valid PostgreSQL query that accurately answers the question.

    **Instructions:**
    - Output ONLY the raw SQL query, enclosed in a markdown code block (```sql ... ```).
    - Ensure the query is syntactically correct for PostgreSQL.
    - Use table and column names exactly as defined in the schema. Qualify table names with the schema name (e.g., "{settings.DB_SCHEMA}.table_name").
    - Do NOT include any explanations, comments, or introductory text outside the markdown block.
    - Pay close attention to PostgreSQL specific functions and syntax if needed."""

    user_prompt_content = f"""**Database Schema:**
    ```sql
    {db_schema}
    ```
    User Question:
    {user_query}

    SQL Query (PostgreSQL):
    """
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt_content},
    ]

    logger.debug(f"Sending prompt to LLM for query: '{user_query}'")

    try:
        async for chunk in stream_llm_response(messages):
            yield chunk
        logger.info(f"Finished streaming SQL for query: '{user_query}'")
    except LLMNotAvailableError as e:
        logger.error(f"LLM error during SQL generation stream: {e}")
        raise
    except ValueError as e:
        logger.error(f"Schema error during SQL generation: {e}")
        raise
    except Exception as e:
        logger.exception(f"Unexpected error generating SQL query stream: {e}")
        raise LLMNotAvailableError(
            f"Unexpected error during SQL generation stream: {e}"
        ) from e
