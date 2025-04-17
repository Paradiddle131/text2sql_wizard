import logging
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Add src to Python path
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from utils.logging_config import setup_logging

setup_logging()

from config.settings import settings
from app.api import endpoints
from app.services.rag_service import RAGService
from app.core.sql_generator import _get_db_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    try:
        await RAGService.get_instance()
        logger.info("RAGService initialized at startup.")
        _get_db_engine()
        logger.info("Database engine initialized at startup.")
    except Exception as e:
        logger.error(f"Startup initialization failed: {e}")
        raise
    yield


app = FastAPI(
    title="Text-to-SQL Wizard",
    description="Converts natural language business queries into SQL.",
    version="0.1.0",
    lifespan=lifespan
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(endpoints.router, prefix="/api")


try:
    app.mount("/", StaticFiles(directory="src/frontend", html=True), name="static")
    logger.info("Serving static files from 'frontend' directory at '/'")
except RuntimeError as e:
    logger.error(f"Failed to mount static files directory 'frontend'. Error: {e}")
    logger.error("Ensure the 'frontend' directory exists in the project root.")


if __name__ == "__main__":
    logger.info("Application startup...")
    logger.info("Starting Uvicorn server...")
    host = getattr(settings, "APP_HOST", "0.0.0.0")
    port = getattr(settings, "APP_PORT", 8000)
    log_level = getattr(settings, "UVICORN_LOG_LEVEL".lower(), "info")

    uvicorn.run(
        app="main:app",
        host=host,
        port=port,
        reload=True,
        log_level=log_level,
        reload_dirs=["frontend", "src"],
        reload_includes=["*.py", "*.html", "*.css", "*.js"],
        reload_excludes=["*.log", "*.pyc", "*.bin"],
    )
