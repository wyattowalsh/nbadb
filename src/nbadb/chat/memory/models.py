from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _text_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    if isinstance(value, tuple):
        items = value
    elif isinstance(value, list | set):
        items = tuple(value)
    else:
        return ()

    normalized: list[str] = []
    for item in items:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            normalized.append(text)
    return tuple(normalized)


class MemoryPromotionMode(StrEnum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class ChatStoreRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    promotion_mode: MemoryPromotionMode | None = None


class ProfileRecord(ChatStoreRecord):
    key: str
    value: Any = None
    notes: str | None = None


class TrajectoryRecord(ChatStoreRecord):
    archetype: str
    payload: dict[str, Any] = Field(default_factory=dict)
    chosen_surfaces: tuple[str, ...] = Field(default=())
    grain: str | None = None
    sql_hash: str | None = None
    repair_notes: tuple[str, ...] = Field(default=())
    artifact_kinds: tuple[str, ...] = Field(default=())
    tags: tuple[str, ...] = Field(default=())
    replay_handle: str | None = None
    success: bool | None = None
    confidence: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        payload = data.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        data["payload"] = payload
        data["chosen_surfaces"] = _text_tuple(
            data.get("chosen_surfaces") or payload.get("chosen_surfaces")
        )
        data["repair_notes"] = _text_tuple(data.get("repair_notes") or payload.get("repair_notes"))
        data["artifact_kinds"] = _text_tuple(
            data.get("artifact_kinds") or payload.get("artifact_kinds")
        )
        data["tags"] = _text_tuple(data.get("tags") or payload.get("tags"))
        data.setdefault("grain", payload.get("grain"))
        data.setdefault("sql_hash", payload.get("sql_hash") or payload.get("source_sql_hash"))
        data.setdefault("replay_handle", payload.get("replay_handle"))
        data.setdefault("success", payload.get("success"))
        data.setdefault("confidence", payload.get("confidence"))
        data.setdefault("promotion_mode", payload.get("promotion_mode"))
        data.setdefault("session_id", payload.get("session_id"))
        if data.get("updated_at") is None and data.get("created_at") is not None:
            data["updated_at"] = data["created_at"]
        if data.get("created_at") is None and data.get("updated_at") is not None:
            data["created_at"] = data["updated_at"]
        return data


class TemplateRecord(BaseModel):
    name: str
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    promotion_mode: MemoryPromotionMode | None = None


class FindingRecord(BaseModel):
    title: str
    summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: tuple[str, ...] = Field(default=())
    entities: tuple[str, ...] = Field(default=())
    metrics: tuple[str, ...] = Field(default=())
    source_sql_hash: str | None = None
    replay_handle: str | None = None
    artifact_bundle_id: str | None = None
    artifact_bundle_name: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None
    session_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    promotion_mode: MemoryPromotionMode | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        metadata = data.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        data["metadata"] = metadata
        data["tags"] = _text_tuple(data.get("tags") or metadata.get("tags"))
        data["entities"] = _text_tuple(data.get("entities") or metadata.get("entities"))
        data["metrics"] = _text_tuple(data.get("metrics") or metadata.get("metrics"))
        data.setdefault(
            "source_sql_hash",
            metadata.get("source_sql_hash") or metadata.get("sql_hash"),
        )
        data.setdefault("replay_handle", metadata.get("replay_handle"))
        data.setdefault(
            "artifact_bundle_id",
            metadata.get("artifact_bundle_id") or metadata.get("bundle_id"),
        )
        data.setdefault("artifact_bundle_name", metadata.get("artifact_bundle_name"))
        data.setdefault("provenance", metadata.get("provenance") or {})
        data.setdefault("confidence", metadata.get("confidence"))
        data.setdefault("session_id", metadata.get("session_id"))
        data.setdefault("promotion_mode", metadata.get("promotion_mode"))
        return data
