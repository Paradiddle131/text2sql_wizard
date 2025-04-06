from pydantic import BaseModel, Field
from typing import Optional


class QueryRequest(BaseModel):
    """Request model for submitting a natural language query."""

    query: str = Field(..., min_length=1, description="The natural language query.")


class SQLResponse(BaseModel):
    """Response model containing the generated SQL query or an error."""

    sql_query: Optional[str] = Field(None, description="The generated SQL query.")
    error: Optional[str] = Field(
        None, description="Error message if SQL generation failed."
    )


class UploadResponse(BaseModel):
    """Response model for successful document upload."""

    filename: str = Field(..., description="Name of the uploaded file.")
    message: str = Field(..., description="Status message.")
    chunks_added: int = Field(
        ..., description="Number of text chunks added to the vector store."
    )
