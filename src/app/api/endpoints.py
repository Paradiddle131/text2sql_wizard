import logging
from fastapi import APIRouter, HTTPException, Body, Depends, UploadFile, File
from fastapi.responses import StreamingResponse

from app.api.schemas import QueryRequest, UploadResponse
from app.core.sql_generator import generate_sql_query_with_context
from app.core.llm_handler import LLMNotAvailableError
from app.services.rag_service import get_rag_service, RAGService, RAGServiceError

logger = logging.getLogger(__name__)

router = APIRouter()


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
async def process_query_streamed(
    request_data: QueryRequest = Body(...),
    rag_service: RAGService = Depends(get_rag_service),
):
    """
    Receives a natural language query, retrieves context, generates SQL, and streams it.

    Args:
        request_data: The request body containing the natural language query.
        rag_service: Dependency injected RAGService instance.

    Returns:
        A StreamingResponse containing the generated SQL query as plain text chunks.

    Raises:
        HTTPException(400): If the query is empty.
        HTTPException(500): If schema loading fails or an internal error occurs.
        HTTPException(503): If the LLM service is unavailable.
    """
    query = request_data.query
    if not query:
        logger.warning("Received empty query.")
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    logger.info(f"Received query for RAG-SQL generation: '{query}'")

    try:
        retrieved_context = await rag_service.retrieve_context(query)
        if retrieved_context:
            logger.info(
                f"Retrieved context for query '{query[:50]}...'. Length: {len(retrieved_context)}"
            )
        else:
            logger.info(
                f"No context retrieved for query '{query[:50]}...'. Proceeding with schema only."
            )

        sql_stream_generator = generate_sql_query_with_context(query, retrieved_context)

        return StreamingResponse(sql_stream_generator, media_type="text/plain")

    except ValueError as e:
        logger.error(f"Schema loading error for query '{query}': {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to load database schema: {e}"
        )
    except RAGServiceError as e:
        logger.error(
            f"RAG service error during context retrieval for query '{query}': {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"Failed to retrieve context: {e}")
    except LLMNotAvailableError as e:
        logger.error(f"LLM unavailable for query '{query}': {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=f"LLM Service Unavailable: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error processing RAG query '{query}': {e}")
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")
