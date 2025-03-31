import logging
from fastapi import APIRouter, HTTPException
from app.api.schemas import QueryRequest, SQLResponse
from app.core.sql_generator import generate_sql_query
from app.core.llm_handler import LLMNotAvailableError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/query", response_model=SQLResponse)
async def process_query(request_data: QueryRequest):
    """
    Receives a natural language query, generates the corresponding SQL query,
    and returns it.
    """
    logger.info(f"Received query request: '{request_data.query[:100]}...'")

    try:
        sql_result = await generate_sql_query(request_data.query)
        logger.info(f"Successfully processed query: '{request_data.query[:100]}...'")
        return SQLResponse(sql_query=sql_result)

    except ValueError as e:
        logger.error(f"Value Error during query processing: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except LLMNotAvailableError as e:
        logger.error(f"LLM Service Error: {e}")
        raise HTTPException(status_code=503, detail=f"LLM Service Unavailable: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error processing query: {request_data.query}")
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")
