import logging
from typing import AsyncGenerator, List, Dict, Optional
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
        metadata.reflect(bind=engine, schema=target_schema, only=tables)

        for table_name in sorted(tables):
            table_key = f"{target_schema}.{table_name}" if target_schema else table_name
            table = metadata.tables.get(table_key)
            if table is None:
                logger.warning(
                    f"Could not find table '{table_key}' in reflected metadata."
                )
                continue

            from sqlalchemy.schema import CreateTable

            try:
                create_table_ddl = str(CreateTable(table).compile(engine)).strip()
                schema_parts.append(
                    f"{create_table_ddl};".replace("\n", "").replace("\t", "")
                )
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
        logger.info(
            f"Successfully generated schema via introspection for '{target_schema or 'default'}'."
        )
        return full_schema
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
        logger.warning(f"DDL file not found at configured path: {ddl_path}")
        return None

    try:
        schema_content = ddl_path.read_text(encoding="utf-8")
        if not schema_content.strip():
            logger.warning(f"DDL file is empty: {ddl_path}")
            return None
        logger.info(f"Successfully loaded schema from DDL file: {ddl_path}")
        return schema_content.strip()
    except Exception as e:
        logger.exception(f"Error reading DDL file {ddl_path}: {e}")
        return None


def get_database_schema(force_refresh: bool = False) -> str:
    """
    Retrieves database schema via introspection or DDL file, caches result.

    Args:
        force_refresh: If True, bypasses cache and reloads the schema.

    Returns:
        The database schema as a string, or an error message string.

    Raises:
        ValueError: If schema loading fails definitively after trying all methods.
    """
    global _SCHEMA_CACHE, _SCHEMA_SOURCE
    if _SCHEMA_CACHE and not force_refresh and not _SCHEMA_CACHE.startswith("ERROR:"):
        logger.debug(f"Using cached schema (source: {_SCHEMA_SOURCE})")
        return _SCHEMA_CACHE

    logger.info(
        f"Attempting to load database schema (force_refresh={force_refresh})..."
    )
    schema: str | None = None
    source: str = "Unknown"

    try:
        engine = _get_db_engine()
        schema = _get_schema_from_introspection(engine, settings.DB_SCHEMA)
        if schema:
            source = "Introspection"
        else:
            logger.warning("Introspection failed or yielded no schema content.")
    except ConnectionError as conn_err:
        logger.error(f"Introspection skipped: DB connection failed. {conn_err}")
    except Exception as intro_err:
        logger.exception(
            f"Unexpected error during introspection setup/execution: {intro_err}"
        )

    if not schema:
        logger.info(
            "Introspection failed or yielded no schema. Attempting DDL file fallback."
        )
        schema = _get_schema_from_ddl_file()
        if schema:
            source = "DDL File"
        else:
            logger.warning("DDL file loading failed or yielded no schema content.")

    if not schema:
        logger.error("Failed to load schema from both introspection and DDL file.")
        error_msg = "ERROR:NO_SCHEMA_AVAILABLE"
        _SCHEMA_CACHE = error_msg
        _SCHEMA_SOURCE = "None"
        raise ValueError("Database schema could not be loaded from any source.")
    else:
        logger.info(
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
    except ValueError as e:
        logger.error(
            f"Cannot generate SQL: Essential schema loading failed. Error: {e}"
        )
        raise ValueError(f"Database schema could not be loaded: {e}") from e

    system_prompt = f"""You are an expert PostgreSQL query generator.
    Given the following PostgreSQL database schema (primarily for the '{settings.DB_SCHEMA}' schema) and potentially relevant context from business documents, generate a *single*, valid PostgreSQL query that accurately answers the user's question.

    **Instructions:**
    - Output ONLY the raw SQL query, enclosed in a markdown code block (```sql ... ```).
    - Ensure the query is syntactically correct for PostgreSQL.
    - Use table and column names exactly as defined in the schema. If table names require schema qualification (e.g., because they are not in the default search_path implicitly covered by the schema definition), qualify them (e.g., "{settings.DB_SCHEMA}.table_name"). Assume '{settings.DB_SCHEMA}' is the primary schema unless context strongly implies otherwise.
    - If relevant context from documents is provided, use it to understand business terms, relationships, or specific constraints mentioned in the user question that might not be obvious from the schema alone.
    - Do NOT include any explanations, comments, or introductory text outside the markdown code block.
    - Pay close attention to PostgreSQL specific functions and syntax if needed."""

    context_section = ""
    if retrieved_context:
        context_section = f"""**Relevant Context from Documents:**
    ```text
    {retrieved_context}
    ```
    """

    user_prompt_content = f"""**Database Schema ({settings.DB_SCHEMA}):**
    ```
    {db_schema}
    ```
    {context_section}
    **User Question:**
    {user_query}

    SQL Query (PostgreSQL):
    """
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt_content},
    ]

    logger.debug(
        f"Sending prompt to LLM for query: '{user_query}' (context included: {bool(retrieved_context)})"
    )

    try:
        async for chunk in stream_llm_response(messages):
            yield chunk
        logger.info(f"Finished streaming SQL for query: '{user_query}'")
    except LLMNotAvailableError as e:
        logger.error(f"LLM error during SQL generation stream: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.exception(f"Unexpected error generating SQL query stream: {e}")
        raise LLMNotAvailableError(
            f"Unexpected error during SQL generation stream: {e}"
        ) from e
