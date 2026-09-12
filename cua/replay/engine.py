"""Deterministic replay: run a saved capability with no LLM in the loop.

Loads the artifact, executes each step with stable role+name locators,
classifies exceptional states after every step, verifies the checkpoint,
extracts declared outputs, and returns a typed ReplayResult.

Phase 4: every step passes through the policy gate first (allowlist +
risk classification) at the same choke point discovery uses. Persisted
logs carry presence/keys only — never raw regulated data.
"""
from __future__ import annotations
import json, os, re
from datetime import datetime
from typing import Any

from playwright.sync_api import (
    sync_playwright, TimeoutError as PWTimeout, Locator as PWLocator,
)

from cua.artifact.schema import Capability, Locator, Step, ActionKind, Checkpoint
from cua.replay.result import ReplayResult, Outcome
from cua.replay.detectors import detectors_for, DetKind, Detector
from cua.safety.policy import Policy, Decision
from cua.safety.redaction import presence as _redact

STEP_TIMEOUT_MS = 5000


def _evidence_dir() -> str:
    d = os.path.join("evidence", "replay_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(d, exist_ok=True)
    return d


def _fill(value: str | None, inputs: dict[str, str]) -> str | None:
    if value is None:
        return None
    out = value
    for k, v in inputs.items():
        out = out.replace(f"{{{{{k}}}}}", str(v))
    return out


class ReplaySurface:
    """The perceive/act seam on the replay path: resolve a Locator, read text.

    Same role+name contract the artifact recorded. A legacy-web or desktop
    surface would implement this same interface differently.
    """
    def __init__(self, headed: bool = False):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=not headed)
        self._page = self._browser.new_page()

    def goto(self, url: str) -> None:
        self._page.goto(url, wait_until="domcontentloaded")

    def reload(self) -> None:
        self._page.reload(wait_until="domcontentloaded")

    def url(self) -> str:
        return self._page.url

    def resolve(self, loc: Locator) -> PWLocator:
        for strat in [loc] + loc.fallbacks:
            t = self._by(strat)
            if t is not None and t.count() > 0:
                return t.first
        raise LookupError(f"No element for role={loc.role!r} name={loc.name!r}")

    def _by(self, loc: Locator) -> PWLocator | None:
        p = self._page
        if loc.strategy == "role_name" and loc.role and loc.name:
            t = p.get_by_role(loc.role, name=loc.name, exact=True)
            return t if t.count() else p.get_by_role(loc.role, name=loc.name)
        if loc.strategy == "text" and loc.text:
            return p.get_by_text(loc.text)
        if loc.strategy == "label" and loc.name:
            return p.get_by_label(loc.name)
        if loc.strategy == "placeholder" and loc.name:
            return p.get_by_placeholder(loc.name)
        if loc.strategy == "nth_role" and loc.role:
            return p.get_by_role(loc.role).nth(loc.nth or 0)
        return None

    def page_text(self) -> str:
        return self._page.inner_text("body")

    def screenshot(self, path: str) -> None:
        self._page.screenshot(path=path)

    def close(self) -> None:
        self._browser.close()
        self._pw.stop()


def _run_step(surface: ReplaySurface, step: Step, inputs: dict[str, str]) -> None:
    if step.action == ActionKind.navigate:
        surface.goto(step.url)
        return
    if step.locator is None:
        raise LookupError(f"step {step.index} has no locator")
    target = surface.resolve(step.locator)
    target.wait_for(state="visible", timeout=STEP_TIMEOUT_MS)
    if step.action == ActionKind.type:
        target.fill("")
        target.fill(_fill(step.value, inputs) or "")
    elif step.action == ActionKind.click:
        target.click()


def _detect(page_text: str, dets: list[Detector]) -> Detector | None:
    for d in dets:
        if d.match_text in page_text:
            return d
    return None


def _checkpoint_ok(surface: ReplaySurface, cp: Checkpoint, text: str) -> bool:
    if cp.kind == "text_present":
        return (cp.value or "") in text
    if cp.kind == "url_contains":
        return (cp.value or "") in surface.url()
    if cp.kind == "role_name_present":
        try:
            return surface.resolve(Locator(role=cp.role, name=cp.name)).count() > 0
        except LookupError:
            return False
    return False


def _extract(surface: ReplaySurface, cap: Capability) -> dict:
    text = surface.page_text()
    out: dict[str, Any] = {}
    input_names = {i.name for i in cap.inputs}
    for f in cap.outputs:
        if f.name in input_names:
            continue                      # input echo -> not an extracted output
        if f.from_text_pattern:
            m = re.search(f.from_text_pattern, text)
            if m:
                out[f.name] = (m.group(1) if m.groups() else m.group(0)).strip()
            else:
                out[f.name] = None
        elif f.source:
            try:
                out[f.name] = surface.resolve(f.source).inner_text()
            except LookupError:
                out[f.name] = None
        else:
            out[f.name] = None            # declared, no extraction rule -> honest null
    return out


def replay(artifact_path: str, inputs: dict[str, str], headed: bool = False,
           policy_path: str = "config/policy.json") -> ReplayResult:
    cap = Capability.model_validate_json(open(artifact_path).read())
    policy = Policy.load(policy_path)

    required = {i.name for i in cap.inputs if i.required}
    missing = required - set(inputs)
    if missing:
        raise SystemExit(f"Missing required inputs: {sorted(missing)}")

    ev = _evidence_dir()
    log_path = os.path.join(ev, "replay_log.jsonl")

    def log(obj: dict) -> None:
        with open(log_path, "a") as fp:
            fp.write(json.dumps(obj) + "\n")

    log({"event": "start", "capability": cap.capability_id,
         "version": cap.version, "inputs": list(inputs.keys())})  # keys only

    dets = detectors_for(cap.app_id)
    surface = ReplaySurface(headed=headed)
    recoveries: list[str] = []
    attempted = 0

    def fail(step_idx, expected, observed, err) -> ReplayResult:
        surface.screenshot(os.path.join(ev, f"fail_step_{step_idx}.png"))
        log({"event": "hard_failure", "step": step_idx, "error": err})
        return ReplayResult(
            outcome=Outcome.failure, capability_id=cap.capability_id,
            capability_version=cap.version, failed_step_index=step_idx,
            expected=expected, observed=observed, error=err,
            steps_attempted=attempted, recoveries=recoveries, evidence_dir=ev)

    try:
        for step in cap.steps:
            attempted += 1

            # --- policy gate: same choke point discovery uses ---
            tname = step.locator.name if step.locator else None
            pr = policy.evaluate(step.action.value, url=step.url,
                                 target_name=tname,
                                 declared_risk=getattr(step, "risk", None))
            log({"event": "policy", "step": step.index, "action": step.action.value,
                 "decision": pr.decision.value, "risk": pr.risk.value, "reason": pr.reason})
            if pr.decision is Decision.block:
                surface.screenshot(os.path.join(ev, f"policy_block_{step.index}.png"))
                return ReplayResult(
                    outcome=Outcome.failure, capability_id=cap.capability_id,
                    capability_version=cap.version, failed_step_index=step.index,
                    expected="action permitted by policy", observed=pr.reason,
                    error=f"policy_block: {pr.reason}", steps_attempted=attempted,
                    recoveries=recoveries, evidence_dir=ev)
            if pr.decision is Decision.confirm:
                surface.screenshot(os.path.join(ev, f"needs_approval_{step.index}.png"))
                return ReplayResult(
                    outcome=Outcome.failure, capability_id=cap.capability_id,
                    capability_version=cap.version, failed_step_index=step.index,
                    needs_human=True, expected="approved irreversible action",
                    observed=pr.reason, error=f"needs_approval: {pr.reason}",
                    steps_attempted=attempted, recoveries=recoveries, evidence_dir=ev)

            # --- act ---
            try:
                _run_step(surface, step, inputs)
            except LookupError as e:
                loc = step.locator
                return fail(step.index,
                            f"element {loc.role}/{loc.name}" if loc else "element",
                            "element not found", str(e))
            except PWTimeout as e:
                return fail(step.index, "step to complete", "timed out", str(e))

            log({"event": "step_done", "step": step.index, "action": step.action.value})

            hit = _detect(surface.page_text(), dets)
            if hit:
                res = _on_detect(surface, step, hit, cap, ev, log, recoveries, attempted)
                if res is not None:
                    return res            # business/hard -> stop; recoverable -> continue

        text = surface.page_text()
        if not _checkpoint_ok(surface, cap.success, text):
            surface.screenshot(os.path.join(ev, "fail_checkpoint.png"))
            log({"event": "checkpoint_failed", "expected": cap.success.value})
            return ReplayResult(
                outcome=Outcome.failure, capability_id=cap.capability_id,
                capability_version=cap.version,
                expected=f"checkpoint {cap.success.value!r} satisfied",
                observed="not satisfied", error="checkpoint failed",
                steps_attempted=attempted, recoveries=recoveries, evidence_dir=ev)

        outputs = _extract(surface, cap)
        surface.screenshot(os.path.join(ev, "success.png"))
        log({"event": "success", "outputs": _redact(outputs)})
        return ReplayResult(
            outcome=Outcome.success, capability_id=cap.capability_id,
            capability_version=cap.version, outputs=outputs,
            steps_attempted=attempted, recoveries=recoveries, evidence_dir=ev)
    finally:
        surface.close()


def _on_detect(surface, step, hit, cap, ev, log, recoveries, attempted) -> ReplayResult | None:
    if hit.kind == DetKind.business:
        surface.screenshot(os.path.join(ev, f"business_{hit.code}.png"))
        log({"event": "business_outcome", "code": hit.code, "step": step.index})
        return ReplayResult(
            outcome=Outcome.business_outcome, capability_id=cap.capability_id,
            capability_version=cap.version, business_code=hit.code,
            business_message=hit.message, steps_attempted=attempted,
            recoveries=recoveries, evidence_dir=ev)

    if hit.kind == DetKind.recoverable:
        for attempt in range(hit.max_retries):
            recoveries.append(f"{hit.code}:{hit.recovery}")
            log({"event": "recovery", "code": hit.code,
                 "action": hit.recovery, "attempt": attempt + 1})
            if hit.recovery == "reload":
                surface.reload()
            if _detect(surface.page_text(), [hit]) is None:
                return None               # recovered -> continue the flow
        surface.screenshot(os.path.join(ev, f"unrecovered_{hit.code}.png"))
        log({"event": "unrecovered", "code": hit.code})
        return ReplayResult(
            outcome=Outcome.failure, capability_id=cap.capability_id,
            capability_version=cap.version, failed_step_index=step.index,
            expected="recoverable condition to clear",
            observed=f"{hit.code} persisted after {hit.max_retries} retry",
            error=hit.message, steps_attempted=attempted,
            recoveries=recoveries, evidence_dir=ev)

    surface.screenshot(os.path.join(ev, f"hard_{hit.code}.png"))
    return ReplayResult(
        outcome=Outcome.failure, capability_id=cap.capability_id,
        capability_version=cap.version, failed_step_index=step.index,
        expected="no blocking condition", observed=hit.code,
        error=hit.message, steps_attempted=attempted,
        recoveries=recoveries, evidence_dir=ev)