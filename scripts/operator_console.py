"""Mock operator console — the human side of the handoff.

Real seam, mocked surface: reads the pending intervention request for a run,
shows the context, lets the operator act in the ALREADY-OPEN live browser
window (the same session automation used), records what they did, and signals
resume by writing the response.

    python scripts/operator.py --run evidence/run_XXXX
"""
from __future__ import annotations
import argparse, os, sys
from cua.escalation.intervention import (
    InterventionRequest, InterventionResponse, Resolution,
    REQUEST_NAME, RESPONSE_NAME)
from cua.safety.redaction import scrub


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="evidence run dir with a pending request")
    a = ap.parse_args()
    req_path = os.path.join(a.run, REQUEST_NAME)
    if not os.path.exists(req_path):
        sys.exit(f"no pending intervention at {req_path}")
    req = InterventionRequest.model_validate_json(open(req_path).read())

    print("\n=== INTERVENTION REQUEST ===")
    print(f"capability : {req.capability_id} v{req.capability_version}")
    print(f"goal       : {req.goal}")
    print(f"stuck at   : step {req.step_index} — {req.action}"
          f"{' → ' + req.target_name if req.target_name else ''}")
    print(f"why        : {req.reason}")
    print(f"page       : {req.page_title or ''} ({req.page_url or ''})")
    print(f"screenshot : {req.screenshot}")
    print(f"control    : {req.control.value}")
    print("\nAct in the OPEN browser window (same live session), then resolve:")
    print("  [a] approve  – let automation execute the flagged action")
    print("  [d] done     – you performed the step(s) manually; automation continues")
    print("  [x] abort    – stop the run")
    choice = input("choice [a/d/x]: ").strip().lower()
    res = {"a": Resolution.approved, "d": Resolution.completed,
           "x": Resolution.aborted}.get(choice, Resolution.aborted)
    notes = input("what did you do? (recorded as evidence): ").strip()

    resp = InterventionResponse(resolution=res, operator="op-console",
                                notes=scrub(notes))
    with open(os.path.join(a.run, RESPONSE_NAME), "w") as f:
        f.write(resp.model_dump_json(indent=2))
    print(f"\nresolved: {res.value} — control handed back to automation.")


if __name__ == "__main__":
    main()