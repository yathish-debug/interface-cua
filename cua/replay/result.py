"""What replay returns to a caller (an AI agent, in production).

Three outcomes, deliberately separated — conflating them is the classic
mistake. The caller branches on `outcome`, not on exceptions.
"""
from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class Outcome(str, Enum):
    success = "success"                    # goal reached; outputs returned
    business_outcome = "business_outcome"  # legit non-success (no_such_member, frozen)
    failure = "failure"                    # hard failure; debuggable


class ReplayResult(BaseModel):
    outcome: Outcome
    capability_id: str
    capability_version: str = ""
    outputs: dict[str, Any] = Field(default_factory=dict)      # on success
    business_code: str | None = None       # "no_such_member", "account_frozen", ...
    business_message: str | None = None
    failed_step_index: int | None = None   # on failure
    expected: str | None = None
    observed: str | None = None
    error: str | None = None
    steps_attempted: int = 0
    recoveries: list[str] = Field(default_factory=list)        # what replay auto-handled
    evidence_dir: str = ""