from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModelVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    version: str
    artifact_path: str | None
    row_count: int
    is_active: bool
    metrics: dict
    created_at: datetime


class RetrainRequest(BaseModel):
    force: bool = False
    min_rows: int = Field(default=500, ge=20, le=200_000)


class RetrainOut(BaseModel):
    version: str
    promoted: bool
    improved: bool
    metrics: dict
    active_version: str | None
    active_metrics: dict | None
