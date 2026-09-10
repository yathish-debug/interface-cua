"""Record a discovery run into a typed capability artifact.

The model discovered the flow; this freezes it into a reviewable,
replayable contract. Literals you name as params are templated out,
so no raw data is persisted.
"""
from __future__ import annotations
import argparse, json, os, re
from datetime import datetime, timezone
from cua.artifact.schema import (
    Capability, Step, Locator, InputParam, OutputField, Checkpoint,
    ActionKind, RiskClass,
)

RISKY_HINTS = {"open", "submit", "confirm", "create", "delete", "transfer", "post", "save"}
MONEY = re.compile(r"\$[\d,]+\.\d{2}")


def _risk(tool: str, name: str) -> RiskClass:
    if tool == "click" and any(h in (name or "").lower() for h in RISKY_HINTS):
        return RiskClass.risky
    return RiskClass.safe


def _locator(role: str, name: str) -> Locator:
    return Locator(
        strategy="role_name", role=role, name=name,
        robustness_note=(
            f'Accessibility role "{role}" + accessible name "{name}" — the same '
            f"label a human/screen-reader sees. Survives cosmetic and DOM changes; "
            f"no CSS or test-ID dependency."
        ),
    )


def _read_acted(run_dir: str) -> list[dict]:
    path = os.path.join(run_dir, "steps.jsonl")
    acted = []
    with open(path) as f:
        for line in f:
            row = json.loads(line)
            if row.get("event") == "acted":
                acted.append(row)
    if not acted or any(r.get("locator") is None for r in acted):
        raise SystemExit(
            "This run has no durable locators (missing 'acted' lines with role+name). "
            "Re-run discovery with the enriched loop before recording."
        )
    return acted


def build(run_dir: str, cap_id: str, title: str, app_id: str, entry_url: str,
          params: dict[str, str], success_text: str) -> Capability:
    acted = _read_acted(run_dir)
    result = json.load(open(os.path.join(run_dir, "result.json")))

    # step 0: deterministic entry
    steps = [Step(index=0, action=ActionKind.navigate, url=entry_url,
                  risk=RiskClass.safe, description=f"Open {app_id}")]

    for i, row in enumerate(acted, start=1):
        tool = row["tool"]
        loc = row["locator"]
        value = row.get("value")
        # parameterize: swap any named literal for its template
        if value is not None:
            for pname, pval in params.items():
                if value == pval:
                    value = f"{{{{{pname}}}}}"
        steps.append(Step(
            index=i,
            action=ActionKind.type if tool == "type" else ActionKind.click,
            locator=_locator(loc["role"], loc["name"]),
            value=value,
            risk=_risk(tool, loc["name"]),
            description=f'{tool} "{loc["name"]}"',
        ))

    inputs = [InputParam(name=n, type="string", required=True,
                         description=f"Supplied per invocation: {n}", sensitive=True)
              for n in params]

    outputs = []
    for k, v in (result.get("outputs") or {}).items():
        pat = MONEY.pattern if isinstance(v, str) and MONEY.search(v) else None
        outputs.append(OutputField(name=k, type="string",
                                   description=f"Extracted {k}", from_text_pattern=pat))

    success = Checkpoint(kind="text_present", value=success_text,
                         description="Member detail screen reached")

    return Capability(
        capability_id=cap_id, title=title,
        description=result.get("goal", ""),
        app_id=app_id, entry_url=entry_url,
        inputs=inputs, outputs=outputs, steps=steps, success=success,
        source_run=os.path.basename(run_dir.rstrip("/")),
        created_at=datetime.now(timezone.utc).isoformat(), status="draft",
    )