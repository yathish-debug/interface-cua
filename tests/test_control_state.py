import pytest

from cua.audit.models import Controller, ControlState
from cua.audit.recorder import RunRecorder


def test_legal_control_handoff(tmp_path):
    recorder = RunRecorder(
        evidence_dir=str(tmp_path / "evidence"),
        run_id="test_run",
    )

    recorder.transition(
        ControlState.PAUSED,
        Controller.AGENT,
        "Risky action requires approval",
    )
    recorder.transition(
        ControlState.HUMAN,
        Controller.HUMAN,
        "Employee takes control",
    )
    recorder.transition(
        ControlState.RESUMING,
        Controller.HUMAN,
        "Employee completed manual action",
    )
    recorder.transition(
        ControlState.AGENT,
        Controller.AGENT,
        "Automation resumes",
    )

    assert recorder.state == ControlState.AGENT
    assert recorder.controller == Controller.AGENT
    assert (tmp_path / "evidence" / "control.jsonl").exists()


def test_illegal_direct_agent_to_human_transition_fails(tmp_path):
    recorder = RunRecorder(
        evidence_dir=str(tmp_path / "evidence"),
        run_id="test_run",
    )

    with pytest.raises(ValueError, match="Illegal transition"):
        recorder.transition(
            ControlState.HUMAN,
            Controller.HUMAN,
            "Trying to skip the pause state",
        )
        
def test_audit_entry_is_written(tmp_path):
    recorder = RunRecorder(
        evidence_dir=str(tmp_path / "evidence"),
        run_id="test_run",
    )

    recorder.audit(
        event_type="run_started",
        actor="agent",
        detail="Replay started",
    )

    audit_file = tmp_path / "evidence" / "audit.jsonl"

    assert audit_file.exists()

    text = audit_file.read_text()
    assert '"event_type":"run_started"' in text
    assert '"actor":"agent"' in text
    assert "12345" not in text