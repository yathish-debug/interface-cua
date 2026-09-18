"""Human-in-the-loop escalation: request/response contract, explicit session
control ownership, and the pause/resume handoff.

The automation and a human operator share ONE live session. When the engine
can't safely proceed (policy 'confirm', an unrecoverable state, a discovery
dead-end), it PAUSES in place — the browser page stays open — cedes control
to a human, and BLOCKS until the operator signals resume. Ownership is
explicit and logged at every transition, so it's always known who is driving.

The operator surface is decoupled over a file channel (request in, response
out): the channel is the mock, the handoff mechanism and control-transfer
model are real. In prod the channel is a websocket/queue and the same session
is reattached over CDP (REPORT §5).
"""
from __future__ import annotations
import os, time
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

REQUEST_NAME = "intervention_request.json"
RESPONSE_NAME = "intervention_response.json"


class Owner(str, Enum):
    automation = "automation"
    human = "human"


class Resolution(str, Enum):
    approved = "approved"     # human approves the flagged action; engine executes it
    completed = "completed"   # human performed the step(s) manually; engine skips + verifies
    aborted = "aborted"       # human declines; engine stops with a clean failure


class InterventionRequest(BaseModel):
    """Everything an operator needs to act, carried across the handoff."""
    schema_version: str = "1.0"
    capability_id: str
    capability_version: str
    goal: str
    step_index: int
    action: str
    target_name: Optional[str] = None
    reason: str                       # why we stopped
    screenshot: str                   # current-state screenshot path
    page_url: Optional[str] = None
    page_title: Optional[str] = None
    control: Owner = Owner.human      # who SHOULD be in control now
    created_at: float = Field(default_factory=time.time)


class InterventionResponse(BaseModel):
    schema_version: str = "1.0"
    resolution: Resolution
    operator: str = "operator"        # who acted (id, no PII)
    notes: str = ""                   # what the human did — recorded as evidence
    resumed_at: float = Field(default_factory=time.time)


class SessionControl:
    """Explicit, logged ownership of the one live session."""
    def __init__(self, log):
        self.owner = Owner.automation
        self._log = log

    def cede_to_human(self, reason: str):
        self.owner = Owner.human
        self._log({"event": "control_transfer", "to": "human", "reason": reason})

    def reclaim(self, resolution: str):
        self.owner = Owner.automation
        self._log({"event": "control_transfer", "to": "automation",
                   "resolution": resolution})


def escalate(evidence_dir: str, req: InterventionRequest, control: SessionControl,
             log, poll_s: float = 1.0, timeout_s: float = 900.0) -> InterventionResponse:
    """Route an intervention request and BLOCK until the operator responds.

    Runs inside the surface context, so the live page stays open and the human
    drives the SAME session. Returns the operator's response, or an 'aborted'
    response on timeout (control reclaimed either way).
    """
    req_path = os.path.join(evidence_dir, REQUEST_NAME)
    resp_path = os.path.join(evidence_dir, RESPONSE_NAME)
    if os.path.exists(resp_path):
        os.remove(resp_path)
    with open(req_path, "w") as f:
        f.write(req.model_dump_json(indent=2))
    control.cede_to_human(req.reason)
    log({"event": "escalation_raised", "step": req.step_index,
         "reason": req.reason, "request": req_path})

    waited = 0.0
    while not os.path.exists(resp_path):
        time.sleep(poll_s)
        waited += poll_s
        if waited >= timeout_s:
            log({"event": "escalation_timeout", "waited_s": waited})
            control.reclaim("timeout")
            return InterventionResponse(resolution=Resolution.aborted,
                                        notes="operator timeout — no response")
    resp = InterventionResponse.model_validate_json(open(resp_path).read())
    control.reclaim(resp.resolution.value)
    log({"event": "escalation_resolved", "resolution": resp.resolution.value,
         "operator": resp.operator, "notes_present": bool(resp.notes)})
    return resp