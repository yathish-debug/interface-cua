"""Deterministic replay: run a saved capability with no LLM in the loop.

Phase 4: policy gate before every action.
Phase 5: same-session human escalation for irreversible actions.
Phase 5.5: append-only audit trail and audited control-state transitions.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PWTimeout,
    Locator as PWLocator,
)

from cua.artifact.schema import Capability, Locator, Step, ActionKind, Checkpoint
from cua.audit.recorder import RunRecorder
from cua.escalation.intervention import (
    InterventionRequest,
    Resolution,
    SessionControl,
    escalate,
)
from cua.replay.detectors import detectors_for, DetKind, Detector
from cua.replay.result import ReplayResult, Outcome
from cua.safety.policy import Policy, Decision
from cua.safety.redaction import presence as _redact

STEP_TIMEOUT_MS = 5000


def _evidence_dir() -> str:
    directory = os.path.join(
        "evidence",
        "replay_" + datetime.now().strftime("%Y%m%d_%H%M%S"),
    )
    os.makedirs(directory, exist_ok=True)
    return directory


def _fill(value: str | None, inputs: dict[str, str]) -> str | None:
    if value is None:
        return None

    output = value

    for key, input_value in inputs.items():
        output = output.replace(f"{{{{{key}}}}}", str(input_value))

    return output


class ReplaySurface:
    """Browser implementation for deterministic replay."""

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

    def title(self) -> str:
        return self._page.title()

    def resolve(self, loc: Locator) -> PWLocator:
        for strategy in [loc] + loc.fallbacks:
            target = self._by(strategy)

            if target is not None and target.count() > 0:
                return target.first

        raise LookupError(
            f"No element for role={loc.role!r} name={loc.name!r}"
        )

    def _by(self, loc: Locator) -> PWLocator | None:
        page = self._page

        if loc.strategy == "role_name" and loc.role and loc.name:
            target = page.get_by_role(loc.role, name=loc.name, exact=True)
            return target if target.count() else page.get_by_role(
                loc.role,
                name=loc.name,
            )

        if loc.strategy == "text" and loc.text:
            return page.get_by_text(loc.text)

        if loc.strategy == "label" and loc.name:
            return page.get_by_label(loc.name)

        if loc.strategy == "placeholder" and loc.name:
            return page.get_by_placeholder(loc.name)

        if loc.strategy == "nth_role" and loc.role:
            return page.get_by_role(loc.role).nth(loc.nth or 0)

        return None

    def page_text(self) -> str:
        return self._page.inner_text("body")

    def screenshot(self, path: str) -> None:
        self._page.screenshot(path=path)

    def close(self) -> None:
        self._browser.close()
        self._pw.stop()


def _run_step(
    surface: ReplaySurface,
    step: Step,
    inputs: dict[str, str],
) -> None:
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


def _detect(page_text: str, detectors: list[Detector]) -> Detector | None:
    for detector in detectors:
        if detector.match_text in page_text:
            return detector

    return None


def _checkpoint_ok(
    surface: ReplaySurface,
    checkpoint: Checkpoint,
    text: str,
) -> bool:
    if checkpoint.kind == "text_present":
        return (checkpoint.value or "") in text

    if checkpoint.kind == "url_contains":
        return (checkpoint.value or "") in surface.url()

    if checkpoint.kind == "role_name_present":
        try:
            return surface.resolve(
                Locator(role=checkpoint.role, name=checkpoint.name)
            ).count() > 0
        except LookupError:
            return False

    return False


def _extract(surface: ReplaySurface, capability: Capability) -> dict:
    text = surface.page_text()
    outputs: dict[str, Any] = {}

    input_names = {input_param.name for input_param in capability.inputs}

    for field in capability.outputs:
        if field.name in input_names:
            continue

        if field.from_text_pattern:
            match = re.search(field.from_text_pattern, text)

            if match:
                outputs[field.name] = (
                    match.group(1) if match.groups() else match.group(0)
                ).strip()
            else:
                outputs[field.name] = None

        elif field.source:
            try:
                outputs[field.name] = surface.resolve(field.source).inner_text()
            except LookupError:
                outputs[field.name] = None

        else:
            outputs[field.name] = None

    return outputs


def replay(
    artifact_path: str,
    inputs: dict[str, str],
    headed: bool = False,
    policy_path: str = "config/policy.json",
) -> ReplayResult:
    capability = Capability.model_validate_json(open(artifact_path).read())
    policy = Policy.load(policy_path)

    required_inputs = {
        input_param.name
        for input_param in capability.inputs
        if input_param.required
    }

    missing = required_inputs - set(inputs)

    if missing:
        raise SystemExit(f"Missing required inputs: {sorted(missing)}")

    evidence_dir = _evidence_dir()
    run_id = os.path.basename(evidence_dir)
    recorder = RunRecorder(evidence_dir, run_id)

    log_path = os.path.join(evidence_dir, "replay_log.jsonl")

    def log(record: dict) -> None:
        with open(log_path, "a") as file:
            file.write(json.dumps(record) + "\n")

    log({
        "event": "start",
        "capability": capability.capability_id,
        "version": capability.version,
        "inputs": list(inputs.keys()),
    })

    recorder.audit(
        event_type="run_started",
        actor="agent",
        detail=f"Capability started: {capability.capability_id}",
    )

    detectors = detectors_for(capability.app_id)
    surface = ReplaySurface(headed=headed)
    control = SessionControl(log, recorder)

    recoveries: list[str] = []
    attempted = 0

    def fail(
        step_index: int,
        expected: str,
        observed: str,
        error: str,
    ) -> ReplayResult:
        screenshot = os.path.join(
            evidence_dir,
            f"fail_step_{step_index}.png",
        )

        surface.screenshot(screenshot)

        log({
            "event": "hard_failure",
            "step": step_index,
            "error": error,
        })

        recorder.audit(
            event_type="hard_failure",
            actor="agent",
            evidence_ref=screenshot,
            detail=error,
        )

        return ReplayResult(
            outcome=Outcome.failure,
            capability_id=capability.capability_id,
            capability_version=capability.version,
            failed_step_index=step_index,
            expected=expected,
            observed=observed,
            error=error,
            steps_attempted=attempted,
            recoveries=recoveries,
            evidence_dir=evidence_dir,
        )

    try:
        for step in capability.steps:
            attempted += 1

            target_name = step.locator.name if step.locator else None

            policy_result = policy.evaluate(
                step.action.value,
                url=step.url,
                target_name=target_name,
                declared_risk=getattr(step, "risk", None),
            )

            log({
                "event": "policy",
                "step": step.index,
                "action": step.action.value,
                "decision": policy_result.decision.value,
                "risk": policy_result.risk.value,
                "reason": policy_result.reason,
            })

            if policy_result.decision is Decision.block:
                screenshot = os.path.join(
                    evidence_dir,
                    f"policy_block_{step.index}.png",
                )

                surface.screenshot(screenshot)

                recorder.audit(
                    event_type="hard_failure",
                    actor="agent",
                    action=step.action.value,
                    evidence_ref=screenshot,
                    detail=f"Policy blocked action: {policy_result.reason}",
                )

                return ReplayResult(
                    outcome=Outcome.failure,
                    capability_id=capability.capability_id,
                    capability_version=capability.version,
                    failed_step_index=step.index,
                    expected="action permitted by policy",
                    observed=policy_result.reason,
                    error=f"policy_block: {policy_result.reason}",
                    steps_attempted=attempted,
                    recoveries=recoveries,
                    evidence_dir=evidence_dir,
                )

            if policy_result.decision is Decision.confirm:
                screenshot = os.path.join(
                    evidence_dir,
                    f"needs_approval_{step.index}.png",
                )

                surface.screenshot(screenshot)

                request = InterventionRequest(
                    capability_id=capability.capability_id,
                    capability_version=capability.version,
                    goal=capability.description,
                    step_index=step.index,
                    action=step.action.value,
                    target_name=target_name,
                    reason=policy_result.reason,
                    screenshot=screenshot,
                    page_url=surface.url(),
                    page_title=surface.title(),
                )

                print(
                    f"\n⚠  ESCALATION at step {step.index}: "
                    f"{policy_result.reason}"
                    f"\n   operator: python scripts/operator_console.py "
                    f"--run {evidence_dir}\n"
                )

                response = escalate(
                    evidence_dir,
                    request,
                    control,
                    log,
                    recorder,
                )

                if response.resolution is Resolution.aborted:
                    abort_screenshot = os.path.join(
                        evidence_dir,
                        f"aborted_{step.index}.png",
                    )

                    surface.screenshot(abort_screenshot)

                    return ReplayResult(
                        outcome=Outcome.failure,
                        capability_id=capability.capability_id,
                        capability_version=capability.version,
                        failed_step_index=step.index,
                        needs_human=True,
                        expected="approved irreversible action",
                        observed=f"operator aborted: {response.notes}",
                        error="operator_aborted",
                        steps_attempted=attempted,
                        recoveries=recoveries,
                        evidence_dir=evidence_dir,
                    )

                if response.resolution is Resolution.completed:
                    log({
                        "event": "human_completed_step",
                        "step": step.index,
                    })

                    recorder.audit(
                        event_type="step_executed",
                        actor="human",
                        action=step.action.value,
                        detail="Human completed flagged step manually",
                    )

                    continue

                log({
                    "event": "human_approved_step",
                    "step": step.index,
                })

            try:
                _run_step(surface, step, inputs)

            except LookupError as error:
                locator = step.locator

                return fail(
                    step.index,
                    (
                        f"element {locator.role}/{locator.name}"
                        if locator
                        else "element"
                    ),
                    "element not found",
                    str(error),
                )

            except PWTimeout as error:
                return fail(
                    step.index,
                    "step to complete",
                    "timed out",
                    str(error),
                )

            log({
                "event": "step_done",
                "step": step.index,
                "action": step.action.value,
            })

            recorder.audit(
                event_type="step_executed",
                actor="agent",
                action=step.action.value,
                detail=f"Completed step {step.index}",
            )

            detected = _detect(surface.page_text(), detectors)

            if detected:
                result = _on_detect(
                    surface,
                    step,
                    detected,
                    capability,
                    evidence_dir,
                    log,
                    recorder,
                    recoveries,
                    attempted,
                )

                if result is not None:
                    return result

        text = surface.page_text()

        if not _checkpoint_ok(surface, capability.success, text):
            screenshot = os.path.join(
                evidence_dir,
                "fail_checkpoint.png",
            )

            surface.screenshot(screenshot)

            log({
                "event": "checkpoint_failed",
                "expected": capability.success.value,
            })

            recorder.audit(
                event_type="hard_failure",
                actor="agent",
                evidence_ref=screenshot,
                detail="Success checkpoint failed",
            )

            return ReplayResult(
                outcome=Outcome.failure,
                capability_id=capability.capability_id,
                capability_version=capability.version,
                expected=(
                    f"checkpoint {capability.success.value!r} satisfied"
                ),
                observed="not satisfied",
                error="checkpoint failed",
                steps_attempted=attempted,
                recoveries=recoveries,
                evidence_dir=evidence_dir,
            )

        outputs = _extract(surface, capability)

        success_screenshot = os.path.join(
            evidence_dir,
            "success.png",
        )

        surface.screenshot(success_screenshot)

        log({
            "event": "success",
            "outputs": _redact(outputs),
        })

        recorder.audit(
            event_type="run_completed",
            actor="agent",
            evidence_ref=success_screenshot,
            detail="Replay completed successfully",
        )

        return ReplayResult(
            outcome=Outcome.success,
            capability_id=capability.capability_id,
            capability_version=capability.version,
            outputs=outputs,
            steps_attempted=attempted,
            recoveries=recoveries,
            evidence_dir=evidence_dir,
        )

    finally:
        surface.close()


def _on_detect(
    surface: ReplaySurface,
    step: Step,
    detected: Detector,
    capability: Capability,
    evidence_dir: str,
    log,
    recorder: RunRecorder,
    recoveries: list[str],
    attempted: int,
) -> ReplayResult | None:
    if detected.kind == DetKind.business:
        screenshot = os.path.join(
            evidence_dir,
            f"business_{detected.code}.png",
        )

        surface.screenshot(screenshot)

        log({
            "event": "business_outcome",
            "code": detected.code,
            "step": step.index,
        })

        recorder.audit(
            event_type="business_outcome",
            actor="agent",
            action=step.action.value,
            evidence_ref=screenshot,
            detail=detected.code,
        )

        return ReplayResult(
            outcome=Outcome.business_outcome,
            capability_id=capability.capability_id,
            capability_version=capability.version,
            business_code=detected.code,
            business_message=detected.message,
            steps_attempted=attempted,
            recoveries=recoveries,
            evidence_dir=evidence_dir,
        )

    if detected.kind == DetKind.recoverable:
        for attempt in range(detected.max_retries):
            recoveries.append(f"{detected.code}:{detected.recovery}")

            log({
                "event": "recovery",
                "code": detected.code,
                "action": detected.recovery,
                "attempt": attempt + 1,
            })

            if detected.recovery == "reload":
                surface.reload()

            if _detect(surface.page_text(), [detected]) is None:
                return None

        screenshot = os.path.join(
            evidence_dir,
            f"unrecovered_{detected.code}.png",
        )

        surface.screenshot(screenshot)

        log({
            "event": "unrecovered",
            "code": detected.code,
        })

        recorder.audit(
            event_type="hard_failure",
            actor="agent",
            evidence_ref=screenshot,
            detail=f"Recoverable state persisted: {detected.code}",
        )

        return ReplayResult(
            outcome=Outcome.failure,
            capability_id=capability.capability_id,
            capability_version=capability.version,
            failed_step_index=step.index,
            expected="recoverable condition to clear",
            observed=(
                f"{detected.code} persisted after "
                f"{detected.max_retries} retry"
            ),
            error=detected.message,
            steps_attempted=attempted,
            recoveries=recoveries,
            evidence_dir=evidence_dir,
        )

    screenshot = os.path.join(
        evidence_dir,
        f"hard_{detected.code}.png",
    )

    surface.screenshot(screenshot)

    recorder.audit(
        event_type="hard_failure",
        actor="agent",
        evidence_ref=screenshot,
        detail=detected.code,
    )

    return ReplayResult(
        outcome=Outcome.failure,
        capability_id=capability.capability_id,
        capability_version=capability.version,
        failed_step_index=step.index,
        expected="no blocking condition",
        observed=detected.code,
        error=detected.message,
        steps_attempted=attempted,
        recoveries=recoveries,
        evidence_dir=evidence_dir,
    )