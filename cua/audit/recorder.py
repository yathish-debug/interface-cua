"""Append-only recorder for audit events and control-state transitions."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import uuid

from cua.audit.models import (
    AuditEntry,
    Controller,
    ControlState,
    ControlTransition,
    LEGAL_TRANSITIONS,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunRecorder:
    def __init__(self, evidence_dir: str, run_id: str):
        self.run_id = run_id
        self.dir = Path(evidence_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

        self.audit_path = self.dir / "audit.jsonl"
        self.control_path = self.dir / "control.jsonl"
        
        self.audit_path.touch(exist_ok=True)
        self.control_path.touch(exist_ok=True)

        self.state = ControlState.AGENT
        self.controller = Controller.AGENT

    def audit(
        self,
        event_type: str,
        actor: str,
        **kwargs,
    ) -> AuditEntry:
        entry = AuditEntry(
            event_id=str(uuid.uuid4()),
            run_id=self.run_id,
            ts=_now(),
            actor=actor,
            event_type=event_type,
            **kwargs,
        )

        with open(self.audit_path, "a") as file:
            file.write(entry.model_dump_json() + "\n")

        return entry

    def transition(
        self,
        to_state: ControlState,
        controller: Controller,
        reason: str,
    ) -> ControlTransition:
        if to_state not in LEGAL_TRANSITIONS[self.state]:
            raise ValueError(
                f"Illegal transition: {self.state.value} → {to_state.value}"
            )

        record = ControlTransition(
            run_id=self.run_id,
            ts=_now(),
            from_state=self.state,
            to_state=to_state,
            controller=controller,
            reason=reason,
        )

        with open(self.control_path, "a") as file:
            file.write(record.model_dump_json() + "\n")

        self.state = to_state
        self.controller = controller
        return record