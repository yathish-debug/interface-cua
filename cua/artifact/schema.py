"""Typed, versioned contract for a reusable capability.

A human reviewer and a calling agent both read this: what it does,
what it needs (inputs), what it returns (outputs), the exact steps,
and the checkpoint that proves success. Decoupled from the raw model
transcript on purpose — the transcript is evidence, this is the API.
"""
from __future__ import annotations
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field

ARTIFACT_SCHEMA_VERSION = "1.0"


class RiskClass(str, Enum):
    safe = "safe"      # reversible / read-only: navigate, type, read
    risky = "risky"    # irreversible / state-changing: submit, confirm, delete


class ActionKind(str, Enum):
    navigate = "navigate"
    click = "click"
    type = "type"
    extract = "extract"


class Locator(BaseModel):
    """How replay re-finds a control. Try primary, then fallbacks in order."""
    strategy: Literal["role_name", "text", "label", "placeholder", "nth_role"] = "role_name"
    role: str | None = None
    name: str | None = None          # accessible name — the human-visible label
    text: str | None = None
    nth: int | None = None           # disambiguate when a name repeats
    robustness_note: str = ""        # WHY this is stable — for reviewers
    fallbacks: list["Locator"] = Field(default_factory=list)


class Checkpoint(BaseModel):
    """A condition asserted to prove we reached the intended state."""
    kind: Literal["url_contains", "text_present", "role_name_present"] = "text_present"
    value: str | None = None         # substring / expected text
    role: str | None = None
    name: str | None = None
    description: str = ""


class InputParam(BaseModel):
    name: str
    type: Literal["string", "number", "boolean"] = "string"
    required: bool = True
    description: str = ""
    sensitive: bool = False          # if true: never logged/echoed on replay


class OutputField(BaseModel):
    name: str
    type: Literal["string", "number", "boolean"] = "string"
    description: str = ""
    source: Locator | None = None            # read from this control, or...
    from_text_pattern: str | None = None     # ...regex over visible text


class Step(BaseModel):
    index: int
    action: ActionKind
    locator: Locator | None = None   # None for navigate
    value: str | None = None         # templated "{{member_id}}" or literal
    url: str | None = None           # for navigate
    risk: RiskClass = RiskClass.safe
    description: str = ""


class Capability(BaseModel):
    schema_version: str = ARTIFACT_SCHEMA_VERSION
    capability_id: str               # stable slug: "lookup_member_savings"
    version: str = "1.0.0"           # this capability's own semver
    title: str
    description: str = ""
    app_id: str                      # logical app, generic across tenants
    entry_url: str                   # tenant-specific value lives here
    inputs: list[InputParam] = Field(default_factory=list)
    outputs: list[OutputField] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    success: Checkpoint              # final condition replay verifies
    source_run: str = ""             # evidence run it was recorded from
    created_at: str = ""
    status: Literal["draft", "approved"] = "draft"


Locator.model_rebuild()   # resolve the self-referential fallbacks