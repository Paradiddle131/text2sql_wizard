import re
import logging
from typing import AsyncGenerator
from sqlalchemy import (
    create_engine,
    inspect as sqla_inspect,
    exc as sqlalchemy_exc,
    MetaData,
    text,
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
            _DB_ENGINE = create_engine(
                str(settings.DATABASE_URL),
                pool_pre_ping=True,
                connect_args={"options": f"-csearch_path={settings.DB_SCHEMA}"}
                if settings.DATABASE_URL.drivername.startswith("postgresql")
                else {},
            )
            # Test connection
            with _DB_ENGINE.connect() as connection:
                logger.info(
                    f"Successfully connected to database: {settings.DATABASE_URL.render_as_string(hide_password=True)}"
                )
        except sqlalchemy_exc.SQLAlchemyError as e:
            logger.exception(
                f"Failed to create database engine for {settings.DATABASE_URL.render_as_string(hide_password=True)}: {e}"
            )
            raise ConnectionError(f"Could not connect to the database: {e}") from e
    return _DB_ENGINE


def _get_schema_from_introspection(engine: Engine, target_schema: str) -> str | None:
    """
    Uses SQLAlchemy inspect to get table and column definitions for a target schema.
    Formats the output similarly to DDL for the LLM prompt.
    """
    schema_parts = []
    logger.info(f"Attempting database introspection for schema: '{target_schema}'")
    try:
        inspector = sqla_inspect(engine)
        tables = inspector.get_table_names(schema=target_schema)

        if not tables:
            logger.warning(
                f"Database introspection found no tables in schema '{target_schema}'."
            )
            return None

        logger.debug(f"Found tables in schema '{target_schema}': {tables}")

        # Reflect only the tables found in the target schema
        metadata = MetaData()
        metadata.reflect(bind=engine, schema=target_schema, only=tables)

        for table_name in sorted(tables):  # Sort for consistent schema order
            table_key = f"{target_schema}.{table_name}" if target_schema else table_name
            table = metadata.tables.get(table_key)

            if table is None:
                logger.warning(
                    f"Could not get table object for {table_key} after reflection."
                )
                continue

            # Use SQLAlchemy's CreateTable construct for more accurate DDL-like representation
            from sqlalchemy.schema import CreateTable

            create_table_ddl = str(CreateTable(table).compile(engine)).strip()
            schema_parts.append(f"{create_table_ddl};")

        if not schema_parts:
            logger.warning(
                f"No table definitions could be generated for schema '{target_schema}' after reflection."
            )
            return None

        full_schema = "\n\n".join(schema_parts)
        logger.info(
            f"Successfully generated schema definition from introspection for schema '{target_schema}'."
        )
        return full_schema

    except sqlalchemy_exc.SQLAlchemyError as e:
        logger.exception(
            f"Database error during schema introspection for '{target_schema}': {e}"
        )
        return None
    except Exception as e:
        logger.exception(
            f"Unexpected error during schema introspection for '{target_schema}': {e}"
        )
        return None


def _get_schema_from_ddl_file() -> str | None:
    """Reads schema definition from the DDL file specified in settings."""
    ddl_path = settings.DB_DDL_FILE_PATH
    if not ddl_path or not ddl_path.exists():
        logger.warning(f"DDL file not configured or not found at: {ddl_path}")
        return None
    try:
        schema_content = ddl_path.read_text()
        logger.info(f"Successfully loaded schema from DDL file: {ddl_path}")
        return schema_content.strip()
    except Exception as e:
        logger.exception(f"Error reading DDL file {ddl_path}: {e}")
        return None


def get_database_schema(force_refresh: bool = False) -> str:
    """
    Retrieves the database schema, prioritizing introspection, then DDL file.

    Caches the schema unless force_refresh is True.

    Args:
        force_refresh: If True, bypass cache and reload schema.

    Returns:
        The database schema as a string, or 'ERROR:NO_SCHEMA_AVAILABLE'.
    """
    global _SCHEMA_CACHE, _SCHEMA_SOURCE
    if _SCHEMA_CACHE and not force_refresh:
        logger.debug(f"Using cached schema (source: {_SCHEMA_SOURCE})")
        return _SCHEMA_CACHE

    logger.info("Attempting to load database schema...")
    schema: str | None = None
    source: str = "Unknown"

    # 1. Try Introspection
    if settings.DATABASE_URL:
        try:
            engine = _get_db_engine()
            schema = _get_schema_from_introspection(engine, settings.DB_SCHEMA)
            if schema:
                source = "Introspection"
            else:
                logger.warning("Introspection failed to return a schema definition.")
        except ConnectionError:
            logger.error("Schema introspection skipped: Database connection failed.")
        except Exception as e:
            logger.exception(
                f"Unexpected error during schema introspection attempt: {e}"
            )

    # 2. Fallback to DDL file if introspection failed or didn't yield schema
    if not schema:
        logger.info(
            "Schema introspection failed or yielded no schema, attempting DDL file fallback."
        )
        schema = _get_schema_from_ddl_file()
        if schema:
            source = "DDL File"

    # 3. Handle failure
    if not schema:
        logger.error(
            "Failed to load database schema from both introspection and DDL file."
        )
        _SCHEMA_CACHE = "ERROR:NO_SCHEMA_AVAILABLE"
        _SCHEMA_SOURCE = "None"
    else:
        logger.info(f"Database schema loaded successfully (source: {source}).")
        _SCHEMA_CACHE = schema
        _SCHEMA_SOURCE = source

    return _SCHEMA_CACHE


def _clean_llm_output(raw_output: str) -> str:
    """
    Cleans the raw LLM output to extract only the SQL query.
    Handles markdown code blocks and potential surrounding text.
    """
    logger.debug(f"Raw LLM output before cleaning:\n{raw_output}")

    # Regex to find SQL code block ```sql ... ```
    sql_block_match = re.search(
        r"```sql\s*(.*?)\s*```", raw_output, re.DOTALL | re.IGNORECASE
    )
    if sql_block_match:
        cleaned_query = sql_block_match.group(1).strip()
        logger.debug(f"Extracted SQL from markdown block:\n{cleaned_query}")
        return cleaned_query

    # If no markdown block, try to remove common introductory/explanatory phrases
    # This is less reliable and might need refinement
    lines = raw_output.strip().splitlines()
    potential_query_lines = []
    for line in lines:
        # Skip common non-SQL lines - adjust patterns as needed
        if line.lower().startswith(
            (
                "here is the sql query",
                "sure, here's the sql",
                "the sql query is:",
                "```",
                "sql",
            )
        ):
            continue
        potential_query_lines.append(line)

    cleaned_query = "\n".join(potential_query_lines).strip()

    # Basic check if it looks like SQL (starts with SELECT, INSERT, etc.)
    if re.match(
        r"^(SELECT|INSERT|UPDATE|DELETE|WITH|CREATE|ALTER|DROP)\b",
        cleaned_query,
        re.IGNORECASE,
    ):
        logger.debug(f"Cleaned SQL query (no markdown block found):\n{cleaned_query}")
        return cleaned_query
    else:
        # If it doesn't look like SQL after cleaning, return original (maybe it was just SQL)
        logger.warning(
            "Could not confidently extract SQL. Returning potentially unclean output."
        )
        # Fallback: return the stripped raw output if cleaning failed
        return raw_output.strip()


async def generate_sql_query(
    user_query: str, force_schema_refresh: bool = False
) -> AsyncGenerator[str, None]:
    """
    Generates a SQL query from a natural language user query using an LLM,
    streaming the result.

    Args:
        user_query: The natural language query from the user.
        force_schema_refresh: Whether to force reloading the DB schema.

    Yields:
        The generated SQL query as a single string chunk after cleaning.

    Raises:
        ValueError: If the database schema cannot be loaded.
        LLMNotAvailableError: If the LLM call fails.
    """
    db_schema = get_database_schema(force_refresh=force_schema_refresh)
    if db_schema.startswith("ERROR:"):
        logger.error(
            f"Cannot generate SQL query because schema loading failed: {db_schema}"
        )
        raise ValueError(
            f"Database schema could not be loaded ({db_schema}). Cannot generate SQL query."
        )

    prompt = f"""
    You are an expert PostgreSQL query generator.
    Given the following PostgreSQL database schema (specifically for the '{settings.DB_SCHEMA}' schema) and a user question, generate a *single*, valid PostgreSQL query that accurately answers the question.

    **Instructions:**
    - Output ONLY the raw SQL query, enclosed in a markdown code block (```sql ... ```).
    - Ensure the query is syntactically correct for PostgreSQL.
    - Use table and column names exactly as defined in the schema. Qualify table names with the schema name (e.g., "{settings.DB_SCHEMA}.table_name").
    - Do NOT include any explanations, comments, or introductory text outside the markdown block.
    - Pay close attention to PostgreSQL specific functions and syntax if needed.
    - If the question is ambiguous or cannot be answered with the given schema, generate the most plausible query based on the available information.

    **Database Schema:**
    ```sql
    {db_schema}
    ```

    **User Question:**
    {user_query}

    **SQL Query:**
    ```sql
    """  # Note: We add the opening ```sql here to guide the LLM

    logger.debug(
        f"Sending prompt to LLM for user query: '{user_query}' (Schema source: {_SCHEMA_SOURCE})"
    )
    # logger.debug(f"Full prompt:\n{prompt}") # Be cautious logging full prompt with schema

    full_raw_llm_output = ""
    try:
        async for chunk in stream_llm_response(prompt):
            full_raw_llm_output += chunk

        if not full_raw_llm_output:
            logger.error(f"LLM stream returned no content for query: '{user_query}'")
            # Yield an empty string or raise error depending on desired behavior
            # yield "" # Or raise LLMNotAvailableError("LLM returned empty stream.")
            raise LLMNotAvailableError("LLM returned an empty stream.")

        # Clean the accumulated response
        sql_query = _clean_llm_output(full_raw_llm_output)

        if not sql_query:
            logger.error(
                f"LLM output was empty after cleaning for query: '{user_query}'"
            )
            raise LLMNotAvailableError("LLM returned an empty result after cleaning.")

        logger.info(f"Successfully generated and cleaned SQL for query: '{user_query}'")
        # Yield the final cleaned query as a single chunk
        yield sql_query

    except LLMNotAvailableError as e:
        logger.error(f"LLM error during SQL generation for query '{user_query}': {e}")
        # Re-raise to be handled by the endpoint
        raise
    except ValueError as e:  # Catch schema loading errors propagated
        logger.error(f"Schema error during SQL generation: {e}")
        raise  # Re-raise
    except Exception as e:
        logger.exception(
            f"Unexpected error generating SQL query for '{user_query}': {e}"
        )
        # Wrap unexpected errors in LLMNotAvailableError or a specific SQL generation error
        raise LLMNotAvailableError(
            f"Unexpected error during SQL generation: {e}"
        ) from e
