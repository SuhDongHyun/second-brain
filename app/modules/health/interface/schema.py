from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Describe application, database, and pgvector health states.
    Literal fields keep the public health contract small and predictable."""

    status: Literal["ok", "unavailable"]
    database: Literal["ok", "unavailable"]
    pgvector: Literal["ok", "unavailable"]
