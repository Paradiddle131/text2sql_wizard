import re
import logging
from sqlalchemy import (
    create_engine,
    inspect as sqla_inspect,
    exc as sqlalchemy_exc,
    MetaData,
)

from app.core.llm_handler import LLMNotAvailableError, call_llm
from config.settings import settings

logger = logging.getLogger(__name__)

_SCHEMA_CACHE: str | None = None
_SCHEMA_SOURCE: str | None = None  # Track where the schema came from


def _get_schema_from_introspection(engine, target_schema: str) -> str | None:
    """
    Uses SQLAlchemy inspect to get table and column definitions for a target schema.
    Formats the output similarly to DDL for the LLM prompt.
    """
    schema_parts = []
    try:
        inspector = sqla_inspect(engine)
        tables = inspector.get_table_names(schema=target_schema)

        if not tables:
            logger.warning(
                f"Database introspection found no tables in schema '{target_schema}'."
            )
            return None

        metadata = MetaData()
        metadata.reflect(bind=engine, schema=target_schema, only=tables)

        for table_name in tables:
            table = (
                metadata.tables.get(f"{target_schema}.{table_name}")
                if target_schema
                else metadata.tables.get(table_name)
            )
            if table is None:
                logger.warning(
                    f"Could not get table object for {table_name} in schema {target_schema}"
                )
                continue

            create_table_stmt = f"CREATE TABLE {target_schema}.{table_name} (\n"
            column_defs = []

            # Add column definitions
            for column in table.columns:
                col_type = str(column.type)
                col_def = f"  {column.name} {col_type}"
                if not column.nullable:
                    col_def += " NOT NULL"
                if column.primary_key:
                    col_def += " PRIMARY KEY"
                column_defs.append(col_def)

            create_table_stmt += ",\n".join(column_defs)

            # Add constraints (e.g., Foreign Keys) - Basic example
            fks = []
            for fk in table.foreign_key_constraints:
                referred_table = fk.referred_table
                referred_columns = ", ".join(el.column.name for el in fk.elements)
                constrained_columns = ", ".join(el.parent.name for el in fk.elements)
                # Construct the FK constraint string
                fks.append(
                    f"  FOREIGN KEY ({constrained_columns}) REFERENCES {referred_table.schema}.{referred_table.name} ({referred_columns})"
                )

            if fks:
                create_table_stmt += ",\n" + ",\n".join(fks)

            create_table_stmt += "\n);"
            schema_parts.append(create_table_stmt)

        if not schema_parts:
            logger.warning(
                f"Introspection reflected tables but failed to generate DDL strings for schema '{target_schema}'."
            )
            return None

        return "\n\n".join(schema_parts)

    except sqlalchemy_exc.DBAPIError as e:
        logger.warning(
            f"Database connection error during introspection: {e}", exc_info=False
        )
        return None
    except Exception as e:
        logger.error(
            f"Unexpected error during generic database introspection for schema '{target_schema}': {e}",
            exc_info=True,
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
    Retrieves the database schema, prioritizing introspection using SQLAlchemy,
    then falling back to the DDL file. Uses the schema defined in settings (DB_SCHEMA).

    Returns:
        The database schema as a string, or 'ERROR:NO_SCHEMA_AVAILABLE' if none found.
    """
    global _SCHEMA_CACHE, _SCHEMA_SOURCE
    if _SCHEMA_CACHE is not None:
        return _SCHEMA_CACHE

    schema_str: str | None = None
    target_schema = settings.DB_SCHEMA  # Use the configured schema

    # --- Priority 1: Introspection ---
    logger.info(
        f"Attempting database introspection for schema '{target_schema}' using URL: {settings.SQLALCHEMY_DATABASE_URL.replace(settings.DB_PASSWORD, '****') if settings.DB_PASSWORD else settings.SQLALCHEMY_DATABASE_URL}"
    )
    try:
        engine = create_engine(settings.SQLALCHEMY_DATABASE_URL)
        schema_str = _get_schema_from_introspection(engine, target_schema)
        if schema_str:
            logger.info(
                f"Successfully retrieved schema via database introspection for schema '{target_schema}'."
            )
            _SCHEMA_SOURCE = "introspection"
        else:
            logger.warning(
                f"Introspection did not yield a schema for '{target_schema}'. Checking fallback file."
            )
        # Dispose engine if no longer needed? Depends on usage pattern.
        # engine.dispose()

    except Exception as e:
        logger.error(
            f"Failed to create SQLAlchemy engine or connect for introspection: {e}",
            exc_info=True,
        )
        logger.warning("Introspection failed. Checking fallback file.")
        schema_str = None

    # --- Priority 2: Fallback File ---
    if schema_str is None:
        logger.info(
            "Attempting to load schema from fallback file 'data/schema/create_tables.sql'."
        )
        schema_str = _get_schema_from_file()
        if schema_str:
            logger.info("Successfully loaded schema from fallback file.")
            _SCHEMA_SOURCE = "file"

    # --- Set Cache and Return ---
    if schema_str:
        _SCHEMA_CACHE = schema_str
    else:
        logger.error(
            f"Failed to obtain database schema for '{target_schema}' from introspection and fallback file."
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
        You are an expert PostgreSQL query generator. Given a PostgreSQL database schema (primarily for the '{settings.DB_SCHEMA}' schema) and a user question, generate a *single*, valid PostgreSQL query that accurately answers the question.

        **Instructions:**
        - Output ONLY the raw SQL query.
        - Ensure the query is syntactically correct for PostgreSQL.
        - Use table and column names exactly as defined in the schema, including schema qualification (e.g., "{settings.DB_SCHEMA}.table_name") if appropriate.
        - Do NOT include any explanations, comments, introductory text.
        - Pay close attention to PostgreSQL specific functions and syntax if needed.
        - Output the SQL query, preferably enclosed in a markdown code block (```sql ... ```).
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
