import logging
import tempfile
import asyncio
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import chromadb
from chromadb.utils import embedding_functions
from fastapi import UploadFile, HTTPException
from langchain.text_splitter import RecursiveCharacterTextSplitter
from unstructured.partition.auto import partition
from unstructured.documents.elements import Element

from config.settings import settings

logger = logging.getLogger(__name__)


class RAGServiceError(Exception):
    """Custom exception for RAG service errors."""

    pass


class RAGService:
    """
    Handles document processing, embedding, storage in ChromaDB, and retrieval.
    """

    _instance = None
    _lock = asyncio.Lock()

    def __init__(self):
        """Initializes the RAG Service components."""
        logger.info("Initializing RAGService...")
        try:
            self.embedding_function = (
                embedding_functions.SentenceTransformerEmbeddingFunction(
                    model_name=settings.EMBEDDING_MODEL_NAME
                )
            )
            logger.info(f"Embedding function loaded: {settings.EMBEDDING_MODEL_NAME}")

            self.chroma_client = chromadb.PersistentClient(
                path=str(settings.VECTOR_STORE_PATH)
            )
            logger.info(
                f"ChromaDB client connected to path: {settings.VECTOR_STORE_PATH}"
            )

            self.collection = self.chroma_client.get_or_create_collection(
                name=settings.VECTOR_STORE_COLLECTION,
                embedding_function=self.embedding_function,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                f"ChromaDB collection '{settings.VECTOR_STORE_COLLECTION}' accessed/created."
            )

            self.text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=settings.CHUNK_SIZE,
                chunk_overlap=settings.CHUNK_OVERLAP,
                length_function=len,
                add_start_index=True,
            )
            logger.info(
                f"Text splitter configured: Chunk Size={settings.CHUNK_SIZE}, Overlap={settings.CHUNK_OVERLAP}"
            )

        except Exception as e:
            logger.exception("Failed to initialize RAGService components.")
            raise RAGServiceError(f"Initialization failed: {e}") from e

    @classmethod
    async def get_instance(cls):
        """Gets the singleton instance of the RAGService."""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    try:
                        loop = asyncio.get_running_loop()
                        cls._instance = await loop.run_in_executor(None, cls)
                    except Exception as e:
                        logger.error(
                            f"Error creating RAGService instance: {e}", exc_info=True
                        )
                        raise RAGServiceError(
                            "Failed to create RAGService instance"
                        ) from e
        return cls._instance

    async def _process_and_embed_file(
        self, file_path: Path, original_filename: str
    ) -> Tuple[List[str], List[Dict], List[str]]:
        """Loads, partitions, chunks, and prepares documents for embedding."""
        logger.info(f"Processing file: {original_filename} from path: {file_path}")
        try:
            elements: List[Element] = partition(
                filename=str(file_path), strategy="auto"
            )
            logger.debug(
                f"Partitioned {original_filename} into {len(elements)} elements."
            )

            full_text = "\n\n".join([str(el) for el in elements])
            if not full_text.strip():
                logger.warning(
                    f"File {original_filename} contains no extractable text."
                )
                return [], [], []

            chunks = self.text_splitter.split_text(full_text)
            logger.debug(
                f"Split text from {original_filename} into {len(chunks)} chunks."
            )

            if not chunks:
                logger.warning(
                    f"Text splitting resulted in 0 chunks for {original_filename}."
                )
                return [], [], []

            metadatas = [
                {
                    "source": original_filename,
                    "start_index": chunk.metadata["start_index"],
                }
                for chunk in self.text_splitter.create_documents(chunks)
            ]
            ids = [f"{original_filename}_{i}" for i in range(len(chunks))]

            return chunks, metadatas, ids

        except FileNotFoundError:
            logger.error(f"Temporary file not found during processing: {file_path}")
            raise RAGServiceError(
                f"Internal error: Temporary file {file_path} vanished."
            )
        except Exception as e:
            logger.exception(f"Failed to process file {original_filename}: {e}")
            raise RAGServiceError(
                f"Error partitioning/chunking file {original_filename}: {e}"
            ) from e

    async def add_document(self, file: UploadFile) -> int:
        """
        Processes an uploaded file, chunks it, embeds chunks, and adds to ChromaDB.

        Args:
            file: The uploaded file object from FastAPI.

        Returns:
            The number of chunks added to the vector store.

        Raises:
            HTTPException: If the file type is invalid or processing fails.
            RAGServiceError: For internal processing issues.
        """
        allowed_extensions = {".pdf", ".txt", ".docx"}
        file_extension = Path(file.filename).suffix.lower()

        if file_extension not in allowed_extensions:
            logger.warning(
                f"Upload rejected: Invalid file type '{file_extension}' for file '{file.filename}'"
            )
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed types: {', '.join(allowed_extensions)}",
            )

        try:
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=file_extension
            ) as tmp_file:
                content = await file.read()
                if not content:
                    logger.warning(f"Uploaded file '{file.filename}' is empty.")
                    raise HTTPException(
                        status_code=400, detail="Uploaded file cannot be empty."
                    )
                tmp_file.write(content)
                tmp_file_path = Path(tmp_file.name)
            logger.debug(
                f"Saved uploaded file '{file.filename}' to temporary path: {tmp_file_path}"
            )

            loop = asyncio.get_running_loop()
            chunks, metadatas, ids = await loop.run_in_executor(
                None, self._process_and_embed_file_sync, tmp_file_path, file.filename
            )

            if not chunks:
                logger.info(
                    f"No chunks generated for file '{file.filename}', skipping vector store addition."
                )
                return 0

            logger.info(
                f"Adding {len(chunks)} chunks from '{file.filename}' to ChromaDB collection '{self.collection.name}'..."
            )
            self.collection.add(documents=chunks, metadatas=metadatas, ids=ids)
            logger.info(
                f"Successfully added {len(chunks)} chunks from '{file.filename}' to vector store."
            )
            return len(chunks)

        except (HTTPException, RAGServiceError):
            raise
        except Exception as e:
            logger.exception(f"Unexpected error adding document '{file.filename}': {e}")
            raise RAGServiceError(
                f"Unexpected server error processing file '{file.filename}'."
            ) from e
        finally:
            if "tmp_file_path" in locals() and tmp_file_path.exists():
                try:
                    tmp_file_path.unlink()
                    logger.debug(f"Deleted temporary file: {tmp_file_path}")
                except OSError as unlink_err:
                    logger.error(
                        f"Error deleting temporary file {tmp_file_path}: {unlink_err}"
                    )
            await file.close()

    def _process_and_embed_file_sync(
        self, file_path: Path, original_filename: str
    ) -> Tuple[List[str], List[Dict], List[str]]:
        """Synchronous version of file processing for run_in_executor."""
        logger.info(
            f"Processing file (sync): {original_filename} from path: {file_path}"
        )
        try:
            elements: List[Element] = partition(
                filename=str(file_path), strategy="auto"
            )
            logger.debug(
                f"Partitioned {original_filename} into {len(elements)} elements (sync)."
            )

            full_text = "\n\n".join([str(el) for el in elements])
            if not full_text.strip():
                logger.warning(
                    f"File {original_filename} contains no extractable text (sync)."
                )
                return [], [], []

            chunks = self.text_splitter.split_text(full_text)
            logger.debug(
                f"Split text from {original_filename} into {len(chunks)} chunks (sync)."
            )

            if not chunks:
                logger.warning(
                    f"Text splitting resulted in 0 chunks for {original_filename} (sync)."
                )
                return [], [], []

            metadatas = [{"source": original_filename} for _ in chunks]
            ids = [f"{original_filename}_{i}" for i in range(len(chunks))]

            return chunks, metadatas, ids
        except FileNotFoundError:
            logger.error(
                f"Temporary file not found during processing (sync): {file_path}"
            )
            raise RAGServiceError(
                f"Internal error: Temporary file {file_path} vanished."
            )
        except Exception as e:
            logger.exception(f"Failed to process file {original_filename} (sync): {e}")
            raise RAGServiceError(
                f"Error partitioning/chunking file {original_filename}: {e}"
            ) from e

    async def retrieve_context(
        self, query: str, n_results: int = settings.RAG_RETRIEVAL_K
    ) -> Optional[str]:
        """
        Embeds a query and retrieves relevant document chunks from ChromaDB.

        Args:
            query: The user query string.
            n_results: The maximum number of chunks to retrieve.

        Returns:
            A string containing the concatenated context of retrieved chunks,
            or None if no relevant chunks are found or an error occurs.
        """
        if not query:
            return None

        logger.info(f"Retrieving context for query: '{query[:50]}...'")
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )

            if (
                not results
                or not results.get("documents")
                or not results["documents"][0]
            ):
                logger.info(
                    f"No relevant documents found in ChromaDB for query: '{query[:50]}...'"
                )
                return None

            retrieved_docs = results["documents"][0]
            metadatas = results["metadatas"][0]
            distances = results["distances"][0]

            context_parts = []
            for i, doc in enumerate(retrieved_docs):
                source = metadatas[i].get("source", "Unknown")
                distance = distances[i]
                logger.debug(
                    f"Retrieved chunk {i + 1} from '{source}' (Distance: {distance:.4f})"
                )
                context_parts.append(f"Source: {source}\nContent:\n{doc}")

            combined_context = "\n\n---\n\n".join(context_parts)
            logger.info(f"Retrieved {len(retrieved_docs)} chunks for query.")
            return combined_context

        except Exception as e:
            logger.exception(
                f"Failed to retrieve context from ChromaDB for query '{query[:50]}...': {e}"
            )
            return None


_rag_service_instance: Optional[RAGService] = None
_rag_init_lock = asyncio.Lock()


async def get_rag_service() -> RAGService:
    """Provides access to the singleton RAGService instance."""
    global _rag_service_instance
    if _rag_service_instance is None:
        async with _rag_init_lock:
            if _rag_service_instance is None:
                logger.info("Creating RAGService singleton instance.")
                _rag_service_instance = await RAGService.get_instance()
    return _rag_service_instance
