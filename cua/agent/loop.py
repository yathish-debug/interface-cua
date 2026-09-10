from __future__ import annotations
import json, os, time
from datetime import datetime, timezone
from anthropic import Anthropic
from cua.surface.base import Surface
from cua.surface.types import Action
from cua.agent.prompt import SYSTEM_PROMPT, TOOLS


class AgentResult:
    def __init__(self, success, outputs, reason, steps, evidence_dir):
        self.success = success
        self.outputs = outputs
        self.reason = reason
        self.steps = steps
        self.evidence_dir = evidence_dir


def run_goal(surface: Surface, goal: str, max_steps: int = 15,
             timeout_s: int = 180, model: str | None = None) -> AgentResult:
    client = Anthropic()  # reads ANTHROPIC_API_KEY from env
    model = model or os.getenv("CUA_MODEL", "claude-sonnet-4-5")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    evidence_dir = os.path.join("evidence", f"run_{stamp}")
    os.makedirs(evidence_dir, exist_ok=True)
    steps_log = open(os.path.join(evidence_dir, "steps.jsonl"), "w")

    def log(record: dict):
        steps_log.write(json.dumps(record) + "\n")
        steps_log.flush()

    messages = [{
        "role": "user",
        "content": f"GOAL: {goal}\n\nHere is the current screen:\n\n"
                   + surface.observe().to_prompt(),
    }]

    started = time.time()
    last_signature = None
    repeat_count = 0

    for step in range(1, max_steps + 1):
        if time.time() - started > timeout_s:
            log({"step": step, "event": "stop", "reason": "timeout"})
            return AgentResult(False, {}, "Timed out", step, evidence_dir)

        # Screenshot BEFORE acting — captures the state the model reasoned about.
        shot = os.path.join(evidence_dir, f"step_{step:02d}.png")
        surface.screenshot(shot)

        resp = client.messages.create(
            model=model, max_tokens=1024, system=SYSTEM_PROMPT,
            messages=messages, tools=TOOLS, tool_choice={"type": "any"},
        )

        rationale = " ".join(b.text for b in resp.content if b.type == "text").strip()
        tool_use = next((b for b in resp.content if b.type == "tool_use"), None)
        if tool_use is None:
            log({"step": step, "event": "stop", "reason": "no tool call from model"})
            return AgentResult(False, {}, "Model returned no action", step, evidence_dir)

        name, args, tid = tool_use.name, tool_use.input, tool_use.id
        log({"step": step, "screenshot": shot, "rationale": rationale,
             "tool": name, "args": args})

        # --- terminal action ---
        if name == "finish":
            success = bool(args.get("success"))
            outputs = args.get("outputs") or {}
            reason = args.get("reason", "")
            log({"step": step, "event": "finish", "success": success,
                 "outputs": outputs, "reason": reason})
            result = {"success": success, "outputs": outputs, "reason": reason,
                      "goal": goal, "steps": step}
            with open(os.path.join(evidence_dir, "result.json"), "w") as f:
                json.dump(result, f, indent=2)
            steps_log.close()
            return AgentResult(success, outputs, reason, step, evidence_dir)

        # --- surface action ---
        try:
            action = Action(kind=name, ref=args.get("ref"), text=args.get("text"))
            surface.act(action)
            log({"step": step, "event": "acted", "tool": name,
                 "locator": getattr(surface, "last_locator", None),
                 "value": args.get("text")})
            obs = surface.observe()
            result_text = "Action done. New screen:\n\n" + obs.to_prompt()
        except Exception as exc:
            obs = surface.observe()
            result_text = f"Action FAILED: {exc}\nCurrent screen:\n\n" + obs.to_prompt()

        # Loop guard: same action + same screen 3x in a row => dead-end.
        signature = (name, json.dumps(args, sort_keys=True), obs.to_prompt())
        repeat_count = repeat_count + 1 if signature == last_signature else 0
        last_signature = signature
        if repeat_count >= 2:
            log({"step": step, "event": "stop", "reason": "stuck in a loop"})
            return AgentResult(False, {}, "Stuck — repeated same action with no change",
                               step, evidence_dir)

        # Feed the outcome back to the model (correct tool-use loop).
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": result_text}
        ]})

    log({"step": max_steps, "event": "stop", "reason": "max_steps reached"})
    steps_log.close()
    return AgentResult(False, {}, "Hit max steps without finishing", max_steps, evidence_dir)