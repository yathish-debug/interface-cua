"""Employee-facing web console for replay audit trails and escalations."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from cua.escalation.intervention import (
    InterventionRequest,
    InterventionResponse,
    Resolution,
    REQUEST_NAME,
    RESPONSE_NAME,
)
from cua.safety.redaction import scrub


EVIDENCE_ROOT = Path("evidence").resolve()

app = FastAPI(title="Automation Employee Console")
templates = Jinja2Templates(directory="operator_portal/templates")

# Lets the webpage display evidence screenshots from evidence/replay_.../.
app.mount("/evidence", StaticFiles(directory="evidence"), name="evidence")


def _run_dir(run_name: str) -> Path:
    """Return a safe evidence directory; reject paths outside evidence/."""
    candidate = (EVIDENCE_ROOT / run_name).resolve()

    try:
        candidate.relative_to(EVIDENCE_ROOT)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run path.")

    if not candidate.is_dir():
        raise HTTPException(status_code=404, detail="Run not found.")

    return candidate


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []

    rows = []

    for line in path.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))

    return rows


def _load_request(run_dir: Path) -> InterventionRequest | None:
    path = run_dir / REQUEST_NAME

    if not path.exists():
        return None

    return InterventionRequest.model_validate_json(path.read_text())


def _load_response(run_dir: Path) -> InterventionResponse | None:
    path = run_dir / RESPONSE_NAME

    if not path.exists():
        return None

    return InterventionResponse.model_validate_json(path.read_text())


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    runs = []

    if EVIDENCE_ROOT.exists():
        for run_dir in sorted(EVIDENCE_ROOT.glob("replay_*"), reverse=True):
            request_path = run_dir / REQUEST_NAME
            response_path = run_dir / RESPONSE_NAME
            result_path = run_dir / "result.json"

            runs.append({
                "name": run_dir.name,
                "waiting_for_human": request_path.exists() and not response_path.exists(),
                "has_result": result_path.exists(),
            })

    return templates.TemplateResponse(
        request,
        "home.html",
        {"runs": runs},
    )


@app.get("/run/{run_name}", response_class=HTMLResponse)
def run_detail(request: Request, run_name: str):
    run_dir = _run_dir(run_name)

    intervention = _load_request(run_dir)
    response = _load_response(run_dir)

    return templates.TemplateResponse(
        request,
        "run.html",
        {
            "run_name": run_name,
            "audit_rows": _read_jsonl(run_dir / "audit.jsonl"),
            "control_rows": _read_jsonl(run_dir / "control.jsonl"),
            "intervention": intervention,
            "response": response,
        },
    )


@app.post("/run/{run_name}/resolve")
def resolve_intervention(
    run_name: str,
    resolution: str = Form(...),
    notes: str = Form(default=""),
):
    run_dir = _run_dir(run_name)

    request = _load_request(run_dir)
    existing_response = _load_response(run_dir)

    if request is None:
        raise HTTPException(status_code=400, detail="No pending intervention.")

    if existing_response is not None:
        raise HTTPException(status_code=400, detail="This intervention is already resolved.")

    try:
        chosen_resolution = Resolution(resolution)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid resolution.")

    response = InterventionResponse(
        resolution=chosen_resolution,
        operator="web-console",
        notes=scrub(notes),
    )

    (run_dir / RESPONSE_NAME).write_text(
        response.model_dump_json(indent=2)
    )

    return RedirectResponse(
        url=f"/run/{run_name}",
        status_code=303,
    )