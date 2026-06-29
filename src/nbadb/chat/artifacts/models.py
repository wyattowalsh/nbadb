from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ArtifactKind(StrEnum):
    TEMPLATE = "template"
    FINDING = "finding"
    EXPORT = "export"
    NOTEBOOK = "notebook"
    SCRIPT = "script"


class ArtifactPointer(BaseModel):
    kind: ArtifactKind
    name: str
    path: str | None = None


class ResultEnvelope(BaseModel):
    title: str
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    pointers: tuple[ArtifactPointer, ...] = ()
