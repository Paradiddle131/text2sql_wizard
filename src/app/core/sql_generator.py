import re
import logging
from sqlalchemy import create_engine, text, exc as sqlalchemy_exc

from app.core.llm_handler import LLMNotAvailableError, call_llm
from config.settings import settings

logger = logging.getLogger(__name__)

_SCHEMA_CACHE: str | None = None
_SCHEMA_SOURCE: str | None = None  # Track where the schema came from


def _get_sqlite_schema_from_introspection(engine) -> str | None:
    """Queries sqlite_master to get CREATE TABLE statements."""
    schema_parts = []
    try:
        with engine.connect() as connection:
            query = text(
                "SELECT sql FROM sqlite_master WHERE type IN ('table', 'index') AND name NOT LIKE 'sqlite_%';"
            )
            result = connection.execute(query)
            rows = result.fetchall()
            if not rows:
                logger.warning("Database introspection found no tables or indexes.")
                return None

            for row in rows:
                if row[0]:
                    schema_parts.append(row[0] + ";")

            return "\n".join(schema_parts)

    except sqlalchemy_exc.OperationalError as e:
        logger.warning(
            f"Database operational error during introspection (DB might not exist or be accessible): {e}",
            exc_info=False,
        )
        return None
    except Exception as e:
        logger.error(
            f"Unexpected error during database introspection: {e}", exc_info=True
        )
        return None


def _get_schema_from_file() -> str | None:
    """Loads schema from the fallback DDL file."""
    try:
        schema_file = settings.PROJECT_ROOT_PATH / "data/schema/create_tables.sql"
        if not schema_file.exists():
            logger.warning(f"Schema file not found at: {schema_file}")
            return None
        else:
            schema_content = schema_file.read_text()
            if not schema_content.strip():
                logger.warning(f"Schema file {schema_file} is empty.")
                return None
            return schema_content.strip()
    except Exception as e:
        logger.error(f"Error reading schema file {schema_file}: {e}", exc_info=True)
        return None


def get_database_schema() -> str:
    """
    Loads the database schema from the DDL file defined in settings.
    Caches the schema in memory after the first read.

    First attempts to get schema via database introspection for SQLite databases.
    If that fails, falls back to loading from a schema file.

    Returns:
        The database schema as a string, or a fallback string if loading fails.
    """
    global _SCHEMA_CACHE, _SCHEMA_SOURCE
    if _SCHEMA_CACHE is not None:
        return _SCHEMA_CACHE

    schema_str: str | None = None

    logger.info(f"Attempting database introspection for: {settings.DATABASE_URL}")
    if settings.DATABASE_URL.startswith("sqlite:///"):
        try:
            engine = create_engine(settings.DATABASE_URL)
            schema_str = _get_sqlite_schema_from_introspection(engine)
            if schema_str:
                logger.info("Successfully retrieved schema via database introspection.")
                _SCHEMA_SOURCE = "introspection"
            else:
                logger.warning(
                    "Introspection did not yield a schema. Checking fallback file."
                )

        except Exception as e:
            logger.error(
                f"Failed to create SQLAlchemy engine or connect for introspection: {e}",
                exc_info=True,
            )
            logger.warning("Introspection failed. Checking fallback file.")
            schema_str = None
    else:
        logger.warning(
            "Database introspection currently only implemented for SQLite. Skipping."
        )

    if schema_str is None:
        logger.info(
            "Attempting to load schema from fallback file 'data/schema/create_tables.sql'."
        )
        schema_str = _get_schema_from_file()
        if schema_str:
            logger.info("Successfully loaded schema from fallback file.")
            _SCHEMA_SOURCE = "file"

    if schema_str:
        _SCHEMA_CACHE = schema_str
    else:
        logger.error(
            "Failed to obtain database schema from introspection and fallback file."
        )
        _SCHEMA_CACHE = "ERROR:NO_SCHEMA_AVAILABLE"
        _SCHEMA_SOURCE = "none"

    logger.info(f"Schema source determined: {_SCHEMA_SOURCE}")
    return _SCHEMA_CACHE


def _clean_llm_output(raw_output: str) -> str:
    """
    Removes common LLM artifacts like markdown code blocks or explanations
    surrounding the actual SQL query.

    Args:
        raw_output: The raw string output from the language model.

    Returns:
        The cleaned string, ideally containing only the SQL query.
    """
    # Remove ```sql ... ``` markdown
    cleaned = re.sub(
        r"^\s*```sql\s*", "", raw_output, flags=re.IGNORECASE | re.MULTILINE
    )
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    cleaned = cleaned.strip().rstrip(";")
    return cleaned


async def generate_sql_query(user_query: str) -> str:
    """
    Generates an SQL query based on the user query and the database schema.

    Args:
        user_query: The natural language query from the user.

    Returns:
        The generated SQL query string.

    Raises:
        ValueError: If the database schema could not be loaded.
        LLMNotAvailableError: If the LLM call fails.
    """
    db_schema = get_database_schema()
    if db_schema.startswith("ERROR:"):
        logger.error(
            f"Cannot generate SQL query because schema loading failed: {db_schema}"
        )
        raise ValueError(
            f"Database schema could not be loaded ({db_schema}). Cannot generate SQL query."
        )

    prompt = f"""
        You are an expert SQLite SQL query generator. Given the following SQLite database schema and a user question, generate a *single*, valid SQLite SQL query that accurately answers the question.

        **Instructions:**
        - Output ONLY the raw SQL query.
        - Do NOT include any explanations, comments, introductory text.
        - Output the SQL query, preferably enclosed in a markdown code block (```sql ... ```).
        - Ensure the query is syntactically correct for SQLite.
        - Use table and column names exactly as defined in the schema. Pay close attention to case sensitivity if applicable in the schema definition (though SQLite is generally case-insensitive for identifiers).
        - If the question is ambiguous or cannot be answered with the given schema, try your best to generate the most likely query or indicate impossibility subtly if forced (but prefer generating a query).

        **Database Schema:**
        ```sql
        {db_schema}
        ```
        User Question:
        {user_query}

        SQL Query:
        """
    logger.debug(
        f"Sending prompt to LLM for user query: '{user_query}' (Schema source: {_SCHEMA_SOURCE})"
    )
    logger.debug(f"Full prompt:\n{prompt}")

    try:
        raw_llm_output = await call_llm(prompt)
        sql_query = _clean_llm_output(raw_llm_output)
        if not sql_query:
            logger.error(
                f"LLM output was empty after cleaning for query: '{user_query}'"
            )
            raise LLMNotAvailableError("LLM returned an empty result after cleaning.")

        logger.info(f"Successfully generated SQL for query: '{user_query}'")
        logger.debug(f"Generated SQL: {sql_query}")
        return sql_query
    except LLMNotAvailableError:
        # Logged in call_llm, re-raise to be handled by endpoint
        raise
    except Exception as e:
        logger.exception(f"An unexpected error occurred during SQL generation: {e}")
        raise LLMNotAvailableError(
            f"Failed to generate or process SQL query: {e}"
        ) from e
