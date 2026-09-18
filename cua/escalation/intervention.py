"""Human-in-the-loop escalation with audit and control-state tracking."""
from __future__ import annotations

import os
import time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from cua.audit.models import Controller, ControlState
from cua.audit.recorder import RunRecorder

REQUEST_NAME = "intervention_request.json"
RESPONSE_NAME = "intervention_response.json"


class Owner(str, Enum):
    automation = "automation"
    human = "human"


class Resolution(str, Enum):
    approved = "approved"
    completed = "completed"
    aborted = "aborted"


class InterventionRequest(BaseModel):
    schema_version: str = "1.0"
    capability_id: str
    capability_version: str
    goal: str
    step_index: int
    action: str
    target_name: Optional[str] = None
    reason: str
    screenshot: str
    page_url: Optional[str] = None
    page_title: Optional[str] = None
    control: Owner = Owner.human
    created_at: float = Field(default_factory=time.time)


class InterventionResponse(BaseModel):
    schema_version: str = "1.0"
    resolution: Resolution
    operator: str = "operator"
    notes: str = ""
    resumed_at: float = Field(default_factory=time.time)


class SessionControl:
    """Control handoff backed by the audited state machine."""

    def __init__(self, log, recorder: RunRecorder):
        self.owner = Owner.automation
        self._log = log
        self._recorder = recorder

    def cede_to_human(self, reason: str):
        self._recorder.transition(
            ControlState.PAUSED,
            Controller.AGENT,
            reason,
        )
        self._recorder.transition(
            ControlState.HUMAN,
            Controller.HUMAN,
            reason,
        )

        self.owner = Owner.human
        self._log({
            "event": "control_transfer",
            "to": "human",
            "reason": reason,
        })

    def reclaim(self, resolution: str):
        self._recorder.transition(
            ControlState.RESUMING,
            Controller.HUMAN,
            f"Human resolution: {resolution}",
        )
        self._recorder.transition(
            ControlState.AGENT,
            Controller.AGENT,
            f"Automation resumed after: {resolution}",
        )

        self.owner = Owner.automation
        self._log({
            "event": "control_transfer",
            "to": "automation",
            "resolution": resolution,
        })


def escalate(
    evidence_dir: str,
    req: InterventionRequest,
    control: SessionControl,
    log,
    recorder: RunRecorder,
    poll_s: float = 1.0,
    timeout_s: float = 900.0,
) -> InterventionResponse:
    """Pause the live session until an operator resolves the intervention."""

    req_path = os.path.join(evidence_dir, REQUEST_NAME)
    resp_path = os.path.join(evidence_dir, RESPONSE_NAME)

    if os.path.exists(resp_path):
        os.remove(resp_path)

    with open(req_path, "w") as file:
        file.write(req.model_dump_json(indent=2))

    recorder.audit(
        event_type="approval_requested",
        actor="agent",
        action=req.action,
        requires_approval=True,
        evidence_ref=req.screenshot,
        detail=req.reason,
    )

    control.cede_to_human(req.reason)

    log({
        "event": "escalation_raised",
        "step": req.step_index,
        "reason": req.reason,
        "request": req_path,
    })

    waited = 0.0

    while not os.path.exists(resp_path):
        time.sleep(poll_s)
        waited += poll_s

        if waited >= timeout_s:
            log({"event": "escalation_timeout", "waited_s": waited})

            recorder.audit(
                event_type="aborted",
                actor="agent",
                decision="aborted",
                detail="Operator timeout — no response",
            )

            control.reclaim("timeout")

            return InterventionResponse(
                resolution=Resolution.aborted,
                notes="operator timeout — no response",
            )

    response = InterventionResponse.model_validate_json(open(resp_path).read())

    if response.resolution is Resolution.approved:
        recorder.audit(
            event_type="approval_granted",
            actor=response.operator,
            action=req.action,
            decision="approved",
            evidence_ref=req.screenshot,
            detail=response.notes,
        )

    elif response.resolution is Resolution.completed:
        recorder.audit(
            event_type="manual_takeover",
            actor=response.operator,
            action=req.action,
            decision="manual",
            evidence_ref=req.screenshot,
            detail=response.notes,
        )

    else:
        recorder.audit(
            event_type="aborted",
            actor=response.operator,
            action=req.action,
            decision="aborted",
            evidence_ref=req.screenshot,
            detail=response.notes,
        )

    control.reclaim(response.resolution.value)

    log({
        "event": "escalation_resolved",
        "resolution": response.resolution.value,
        "operator": response.operator,
        "notes_present": bool(response.notes),
    })

    return response