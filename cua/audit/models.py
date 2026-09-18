"""Shared data models for audit logging and control handoff."""
from __future__ import annotations
from typing import Optional
from enum import Enum
from pydantic import BaseModel


class Controller(str, Enum):
    AGENT = "agent"
    HUMAN = "human"


class ControlState(str, Enum):
    AGENT = "AGENT"
    PAUSED = "PAUSED"
    HUMAN = "HUMAN"
    RESUMING = "RESUMING"


# Only these control-state changes are allowed.
LEGAL_TRANSITIONS = {
    ControlState.AGENT: {ControlState.PAUSED},
    ControlState.PAUSED: {ControlState.HUMAN, ControlState.AGENT},
    ControlState.HUMAN: {ControlState.RESUMING},
    ControlState.RESUMING: {ControlState.AGENT},
}


class ControlTransition(BaseModel):
    run_id: str
    ts: str
    from_state: ControlState
    to_state: ControlState
    controller: Controller
    reason: str
    
class AuditEntry(BaseModel):
    event_id: str
    run_id: str
    ts: str

    actor: str
    event_type: str

    action: Optional[str] = None
    requires_approval: bool = False
    decision: Optional[str] = None

    evidence_ref: Optional[str] = None
    detail: Optional[str] = None