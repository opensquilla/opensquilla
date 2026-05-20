"""Pydantic slot schemas for meta-skill-creator patterns."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SequentialStep(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,30}$")
    skill: str
    task: str = Field(max_length=400)
    with_keys: dict[str, str] = Field(default_factory=dict)


class SequentialSlots(BaseModel):
    name: str
    description: str = Field(min_length=30, max_length=200)
    meta_priority: int = Field(ge=30, le=80, default=50)
    triggers: list[str] = Field(min_length=1, max_length=8)
    steps: list[SequentialStep] = Field(min_length=2, max_length=5)


class FanOutBranch(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,30}$")
    skill: str
    task: str = Field(max_length=400)
    with_keys: dict[str, str] = Field(default_factory=dict)


class FanOutTail(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,30}$")
    skill: str
    task: str = Field(max_length=400)
    with_keys: dict[str, str] = Field(default_factory=dict)


class FanOutMergeSlots(BaseModel):
    name: str
    description: str = Field(min_length=30, max_length=200)
    meta_priority: int = Field(ge=30, le=80, default=50)
    triggers: list[str] = Field(min_length=1, max_length=8)
    branches: list[FanOutBranch] = Field(min_length=2, max_length=4)
    merge: FanOutBranch
    tail: FanOutTail | None = None
