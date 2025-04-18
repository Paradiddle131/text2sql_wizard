import logging
from typing import AsyncGenerator, List, Dict, Optional
from sqlalchemy import (
    create_engine,
    inspect as sqla_inspect,
    exc as sqlalchemy_exc,
    MetaData,
)
from sqlalchemy.engine import Engine

from app.core.llm_handler import stream_llm_response, LLMNotAvailableError
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
                echo=False,
            )
            with _DB_ENGINE.connect() as connection:
                logger.info(f"Successfully created DB engine and tested connection.")
        except sqlalchemy_exc.SQLAlchemyError as e:
            logger.exception(f"Failed to create database engine or connect: {e}")
            raise ConnectionError("Could not connect to the database.") from e
        except Exception as e:
            logger.exception(f"Unexpected error initializing database engine: {e}")
            raise ConnectionError(
                "Unexpected error initializing database engine."
            ) from e
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
            if target_schema == "public":
                logger.info(
                    "Retrying introspection without explicit schema parameter for default schema."
                )
                tables = inspector.get_table_names(schema=None)
                if not tables:
                    logger.warning(
                        "Introspection found no tables in default schema either."
                    )
                    return None
                else:
                    logger.info(
                        f"Found tables in default schema (no explicit param): {tables}"
                    )
                    target_schema = ""
            else:
                return None

        logger.debug(
            f"Found tables for schema '{target_schema or 'default'}': {tables}"
        )
        metadata = MetaData()
        metadata.reflect(bind=engine, schema=target_schema or None, only=tables)

        for table_name in sorted(tables):
            table_key = f"{target_schema}.{table_name}" if target_schema else table_name
            table = metadata.tables.get(table_key)
            if table is None:
                # Fallback check if reflection didn't use schema prefix
                if not target_schema and table_name in metadata.tables:
                     table = metadata.tables[table_name]
                     table_key = table_name # Adjust key for logging/error msg
                elif table_key not in metadata.tables:
                     # If still not found, log warning and skip
                     logger.warning(
                         f"Could not find table '{table_key}' in reflected metadata. Keys available: {list(metadata.tables.keys())}"
                     )
                     continue

            from sqlalchemy.schema import CreateTable

            try:
                create_table_ddl = str(CreateTable(table).compile(engine)).strip()
                cleaned_ddl = ' '.join(create_table_ddl.replace('"', '').split())
                schema_parts.append(f"{cleaned_ddl};")
            except Exception as ddl_exc:
                logger.error(
                    f"Failed to generate DDL for table '{table_key}': {ddl_exc}",
                    exc_info=True,
                )

        if not schema_parts:
            logger.warning(
                f"No table definitions successfully generated for schema '{target_schema or 'default'}'."
            )
            return None

        full_schema = " ".join(schema_parts)
        logger.debug(
            f"Successfully generated schema via introspection for '{target_schema or 'default'}'."
        )
        return full_schema
    except sqlalchemy_exc.OperationalError as e:
        logger.error(
            f"DB Operational Error during introspection for '{target_schema or 'default'}': {e}. Check permissions/connection."
        )
        return None
    except sqlalchemy_exc.SQLAlchemyError as e:
        logger.exception(
            f"DB error during introspection for '{target_schema or 'default'}': {e}"
        )
        return None
    except Exception as e:
        logger.exception(
            f"Unexpected error during introspection for '{target_schema or 'default'}': {e}"
        )
        return None


def _get_schema_from_ddl_file() -> str | None:
    """Reads schema definition from the DDL file specified in settings."""
    ddl_path = settings.DB_DDL_FILE_PATH
    if not ddl_path:
        logger.debug("DDL file path not configured in settings.")
        return None
    if not ddl_path.exists():
        logger.debug(f"DDL file not found at configured path: {ddl_path}")
        return None

    try:
        schema_content = ddl_path.read_text(encoding="utf-8")
        if not schema_content.strip():
            logger.debug(f"DDL file is empty: {ddl_path}")
            return None
        logger.debug(f"Successfully loaded schema from DDL file: {ddl_path}")
        return " ".join(schema_content.strip().split())
    except Exception as e:
        logger.exception(f"Error reading DDL file {ddl_path}: {e}")
        return None


def get_database_schema(force_refresh: bool = False) -> str:
    """
    Retrieves database schema via introspection or DDL file, caches result.

    Args:
        force_refresh: If True, bypasses cache and reloads the schema.

    Returns:
        The database schema as a string.

    Raises:
        ValueError: If schema loading fails definitively after trying all methods.
    """
    global _SCHEMA_CACHE, _SCHEMA_SOURCE
    if _SCHEMA_CACHE and not force_refresh:
        logger.debug(f"Using cached schema (source: {_SCHEMA_SOURCE})")
        return _SCHEMA_CACHE

    logger.debug(
        f"Attempting to load database schema (force_refresh={force_refresh})..."
    )
    schema: str | None = None
    source: str = "Unknown"

    # Attempt 1: Introspection
    try:
        engine = _get_db_engine()
        schema = _get_schema_from_introspection(engine, settings.DB_SCHEMA)
        if schema:
            source = "Introspection"
        else:
            logger.debug(f"Introspection for schema '{settings.DB_SCHEMA}' failed or yielded no schema content.")
    except ConnectionError as conn_err:
        logger.error(f"Introspection skipped: DB connection failed. {conn_err}")
    except Exception as intro_err:
        logger.exception(
            f"Unexpected error during introspection setup/execution: {intro_err}"
        )

    # Attempt 2: DDL File (if introspection failed)
    if not schema:
        logger.debug(
            "Attempting DDL file fallback."
        )
        schema = _get_schema_from_ddl_file()
        if schema:
            source = "DDL File"
        else:
            logger.debug("DDL file loading failed or yielded no schema content.")

    # Final Check and Caching
    if not schema:
        logger.error("FATAL: Failed to load schema from both introspection and DDL file.")
        error_msg = "ERROR: Database schema could not be loaded. Check logs for introspection/DDL file errors."
        _SCHEMA_CACHE = error_msg # Cache error state to prevent repeated attempts
        _SCHEMA_SOURCE = "None"
        raise ValueError("Database schema could not be loaded from any source.")
    else:
        logger.debug(
            f"Database schema loaded successfully (source: {source}). Caching result."
        )
        _SCHEMA_CACHE = schema
        _SCHEMA_SOURCE = source
        return _SCHEMA_CACHE


async def generate_sql_query_with_context(
    user_query: str,
    retrieved_context: Optional[str] = None,
    force_schema_refresh: bool = False,
) -> AsyncGenerator[str, None]:
    """
    Generates SQL query from NL query using LLM, schema, and optional context, streaming the response.

    Args:
        user_query: The natural language query.
        retrieved_context: Optional context string retrieved from documents.
        force_schema_refresh: Whether to force reloading the DB schema.

    Yields:
        Raw chunks of the generated SQL query text as received from the LLM.

    Raises:
        ValueError: If the database schema cannot be loaded.
        LLMNotAvailableError: If the LLM call fails.
    """
    try:
        db_schema = get_database_schema(force_refresh=force_schema_refresh)
        if db_schema.startswith("ERROR:"):
             raise ValueError(db_schema) # Raise the cached error message
    except ValueError as e:
        logger.error(
            f"Cannot generate SQL: Essential schema loading failed. Error: {e}"
        )
        # Yield an error message instead of raising immediately, allows API to respond
        yield f"ERROR: Could not load database schema. Cannot generate SQL. Details: {e}"
        return # Stop generation

    db_type = "PostgreSQL"
    if settings.DATABASE_URL.scheme:
        if "mysql" in settings.DATABASE_URL.scheme:
            db_type = "MySQL"
        elif "sqlite" in settings.DATABASE_URL.scheme:
            db_type = "SQLite"

    system_prompt = f"""You are an expert {db_type} query generator.
    Given the following {db_type} database schema (primarily for the '{settings.DB_SCHEMA}' schema) and potentially relevant business context, generate a single, valid {db_type} query that directly answers the user's question.

    Instructions:
    - Output ONLY the raw SQL query, with no explanations, comments, markdown formatting (like ```sql), or introductory/trailing text.
    - The query you generate WILL be executed by the backend and the results will be returned to the user, so ensure the SQL is safe, correct, and directly answers the user's question.
    - Ensure the SQL is safe, correct, and directly answers the user's question.
    - Use table and column names exactly as defined in the schema. If schema qualification is needed, use '{settings.DB_SCHEMA}.table_name' (adjust if DB type requires different quoting).
    - Use the provided context (if any) to understand business terms or relationships.
    - The query MUST be syntactically correct for {db_type}.
    - Respond with only the SQL statement."""

    context_section = ""
    if retrieved_context:
        context_section = f"""**Relevant Context from Documents:**
    ```text
    {retrieved_context}
    ```"""

    user_prompt_content = f"""**Database Schema ({settings.DB_SCHEMA}):**
    ```sql
    {db_schema}
    ```
    {context_section}
    User Question:
    {user_query}
    {db_type} Query:"""
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt_content},
    ]

    logger.info(
        f"Generating SQL for query using LLM model: {settings.LLM_MODEL}"
    )
    logger.debug(f"Context included: {bool(retrieved_context)}")

    try:
        async for chunk in stream_llm_response(messages, model_name=settings.LLM_MODEL):
            yield chunk
        logger.info(f"Finished streaming SQL for query")
    except LLMNotAvailableError as e:
        logger.error(f"LLM error during SQL generation stream: {e}", exc_info=False) # exc_info=False as error is logged in handler
        yield f"ERROR: LLM service failed during SQL generation. Details: {e}"
    except Exception as e:
        logger.exception(f"Unexpected error generating SQL query stream: {e}")
        yield f"ERROR: An unexpected error occurred during SQL generation: {e}"