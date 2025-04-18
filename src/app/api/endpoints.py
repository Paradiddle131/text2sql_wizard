import logging
from fastapi import APIRouter, HTTPException, Body, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from app.api.schemas import QueryRequest, UploadResponse
from app.core.sql_generator import generate_sql_query_with_context, _get_db_engine
from app.core.llm_handler import LLMNotAvailableError
from app.services.rag_service import get_rag_service, RAGService, RAGServiceError

import json

logger = logging.getLogger(__name__)

router = APIRouter()


def extract_sql_query(raw_sql: str) -> str:
    """Extracts and cleans the SQL query from markdown/code block formatting."""
    if not raw_sql:
        return ""
    sql = raw_sql.strip()
    sql = sql.replace("```sql", "").replace("```", "").replace("\n", " ")
    return sql.strip()


@router.post("/upload_doc", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...), rag_service: RAGService = Depends(get_rag_service)
):
    """
    Uploads a document (PDF, TXT, DOCX), processes it, and adds it to the RAG vector store.

    Args:
        file: The document file to upload.
        rag_service: Dependency injected RAGService instance.

    Returns:
        A response indicating success and the number of chunks added.

    Raises:
        HTTPException(400): If the file type is invalid or processing fails expectedly.
        HTTPException(500): If an unexpected server error occurs during processing.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    logger.info(f"Received file upload request: {file.filename} ({file.content_type})")

    try:
        chunks_added = await rag_service.add_document(file)
        logger.info(
            f"Successfully processed and added {chunks_added} chunks for file: {file.filename}"
        )
        return UploadResponse(
            filename=file.filename,
            message="File processed and added to knowledge base.",
            chunks_added=chunks_added,
        )
    except HTTPException as http_exc:
        raise http_exc
    except RAGServiceError as rag_err:
        logger.error(
            f"RAG service error processing '{file.filename}': {rag_err}", exc_info=True
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to process document: {rag_err}"
        )
    except Exception as e:
        logger.exception(f"Unexpected error uploading file '{file.filename}': {e}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected server error occurred during file upload.",
        )


@router.post("/query")
async def process_query(
    request_data: QueryRequest = Body(...),
    rag_service: RAGService = Depends(get_rag_service),
):
    """
    Receives a natural language query, retrieves context, generates SQL, and streams both SQL and result as plain text chunks.
    """
    query = request_data.query
    if not query:
        logger.warning("Received empty query.")
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    logger.info(f"Received query for RAG-SQL generation: '{query}'")

    async def sql_and_result_stream():
        try:
            retrieved_context = await rag_service.retrieve_context(query)

            sql_chunks = []
            async for chunk in generate_sql_query_with_context(query, retrieved_context):
                sql_chunks.append(chunk)
                yield chunk
            sql_query = "".join(sql_chunks).strip()

            if not sql_query:
                logger.error("No SQL query was generated.")
                yield "\n--ERROR--\nNo SQL query was generated."
                return

            yield "\n--SQL-END--\n"

            executable_sql = extract_sql_query(sql_query)
            try:
                engine = _get_db_engine()
                with engine.connect() as connection:
                    result_proxy = connection.execute(text(executable_sql))
                    try:
                        result = result_proxy.fetchall()
                        if result and isinstance(result, list) and hasattr(result[0], "__iter__"):
                            columns = result_proxy.keys() if hasattr(result_proxy, "keys") else None
                            if columns:
                                table_header = "| " + " | ".join(columns) + " |\n"
                                table_sep = "|" + "|".join([" --- " for _ in columns]) + "|\n"
                                table_rows = "".join([
                                    "| " + " | ".join(str(cell) for cell in row) + " |\n" for row in result
                                ])
                                markdown_table = table_header + table_sep + table_rows
                                yield f"--RESULT--\n{markdown_table}\n"
                                return
                    except Exception:
                        result = None
            except Exception as exec_err:
                logger.error(f"SQL execution failed: {exec_err}")
                yield f"--ERROR--\nSQL execution failed: {exec_err}\n"
                return

            yield f"--RESULT--\n{result}\n"
        except LLMNotAvailableError as e:
            logger.error(f"LLM error during SQL generation: {e}", exc_info=True)
            yield f"--ERROR--\nLLM error: {e}\n"
        except Exception as e:
            logger.exception(f"Unexpected error generating SQL or executing query: {e}")
            yield f"--ERROR--\nUnexpected error: {e}\n"

    return StreamingResponse(sql_and_result_stream(), media_type="text/plain")
