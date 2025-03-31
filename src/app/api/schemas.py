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
