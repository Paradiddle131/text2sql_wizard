import logging
from fastapi import APIRouter, HTTPException, Body
from fastapi.responses import StreamingResponse
from app.api.schemas import QueryRequest

from app.core.sql_generator import generate_sql_query
from app.core.llm_handler import LLMNotAvailableError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/query")
async def process_query_streamed(request_data: QueryRequest = Body(...)):
    """
    Receives a natural language query, streams generated SQL query back to the client.

    Args:
        request_data: The request body containing the natural language query.

    Returns:
        A StreamingResponse containing the generated SQL query as plain text chunks.

    Raises:
        HTTPException(400): If the query is empty.
        HTTPException(500): If the database schema cannot be loaded (via ValueError).
        HTTPException(503): If the LLM service is unavailable (via LLMNotAvailableError).
    """
    query = request_data.query
    if not query:
        logger.warning("Received empty query.")
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    logger.info(f"Received query for streaming SQL generation: '{query}'")

    try:
        sql_stream_generator = generate_sql_query(query)
        return StreamingResponse(sql_stream_generator, media_type="text/plain")

    except ValueError as e:
        logger.error(f"Schema loading error for query '{query}': {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load database schema: {e}"
        )
    except LLMNotAvailableError as e:
        logger.error(f"LLM unavailable for query '{query}': {e}")
        raise HTTPException(status_code=503, detail=f"LLM Service Unavailable: {e}")
    except Exception as e:
        logger.exception(
            f"Unexpected error processing query '{query}' before streaming: {e}"
        )
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")
