from typing import Literal

from datetime import date
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field


class Source(BaseModel):
    page: int
    text: str
    boxes: list[list[float]]


class CareField(BaseModel):
    id: str
    group: str
    label: str
    value: str
    status: Literal["pending", "confirmed", "rejected", "clarify"] = "pending"
    source: Source | None = None


class Review(BaseModel):
    value: str = Field(max_length=2000)
    status: Literal["confirmed", "rejected", "clarify"]


class Candidate(BaseModel):
    group: str = Field(max_length=100)
    label: str = Field(max_length=100)
    value: str = Field(min_length=1, max_length=2000)
    quote: str = Field(min_length=1, max_length=2000)


class Extraction(BaseModel):
    fields: list[Candidate] = Field(max_length=150)


class MedicationEntry(BaseModel):
    request_id: UUID
    group: str = Field(min_length=1, max_length=100)
    status: Literal["taken", "skipped"]
    occurred_at: AwareDatetime | None = None
    note: str = Field(default="", max_length=500)


class VisitUpdate(BaseModel):
    status: Literal["planned", "booked", "completed"]
    planned_date: date | None = None
    note: str = Field(default="", max_length=500)
