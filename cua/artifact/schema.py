"""Typed, versioned contract for a reusable capability.

A human reviewer and a calling agent both read this: what it does,
what it needs (inputs), what it returns (outputs), the exact steps,
and the checkpoint that proves success. Decoupled from the raw model
transcript on purpose — the transcript is evidence, this is the API.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


ARTIFACT_SCHEMA_VERSION = "1.0"


class RiskClass(str, Enum):
    """Labels used while recording a capability."""

    safe = "safe"
    risky = "risky"


class ActionKind(str, Enum):
    navigate = "navigate"
    click = "click"
    type = "type"
    extract = "extract"


class Locator(BaseModel):
    """How replay re-finds a control. Try primary, then fallbacks in order."""

    strategy: Literal[
        "role_name", "text", "label", "placeholder", "nth_role"
    ] = "role_name"
    role: str | None = None
    name: str | None = None
    text: str | None = None
    nth: int | None = None
    robustness_note: str = ""
    fallbacks: list["Locator"] = Field(default_factory=list)


class Checkpoint(BaseModel):
    """A condition asserted to prove we reached the intended state."""

    kind: Literal[
        "url_contains", "text_present", "role_name_present"
    ] = "text_present"
    value: str | None = None
    role: str | None = None
    name: str | None = None
    description: str = ""


class InputParam(BaseModel):
    name: str
    type: Literal["string", "number", "boolean"] = "string"
    required: bool = True
    description: str = ""
    sensitive: bool = False


class OutputField(BaseModel):
    name: str
    type: Literal["string", "number", "boolean"] = "string"
    description: str = ""
    source: Locator | None = None
    from_text_pattern: str | None = None


class Step(BaseModel):
    index: int
    action: ActionKind
    locator: Locator | None = None
    value: str | None = None
    url: str | None = None
    description: str = ""
    risk: Optional[str] = None  # e.g. "irreversible" → needs human approval


class Capability(BaseModel):
    schema_version: str = ARTIFACT_SCHEMA_VERSION
    capability_id: str
    version: str = "1.0.0"
    title: str
    description: str = ""
    app_id: str
    entry_url: str
    inputs: list[InputParam] = Field(default_factory=list)
    outputs: list[OutputField] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    success: Checkpoint
    source_run: str = ""
    created_at: str = ""
    status: Literal["draft", "approved"] = "draft"


Locator.model_rebuild()