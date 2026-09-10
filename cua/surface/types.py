"""Shared data shapes for perceiving and acting on a surface.

These are surface-agnostic on purpose. A web surface, a legacy web
surface, or a desktop surface all produce the same Observation shape
and accept the same Action shape. That seam is what lets the agent
loop, recorder, and replay engine stay independent of Playwright.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Element:
    ref: str            # stable-within-this-observation handle, e.g. "e3"
    role: str           # accessibility role: button, textbox, link...
    name: str           # accessible name (the label a human/screen-reader sees)
    value: str | None = None  # current value for inputs


@dataclass
class Observation:
    url: str
    title: str
    elements: list[Element] = field(default_factory=list)
    text: list[str] = field(default_factory=list)  # readable text: headings, balances, errors

    def to_prompt(self) -> str:
        """Compact, LLM-friendly rendering of the current screen."""
        lines = [f"URL: {self.url}", f"TITLE: {self.title}", "", "INTERACTIVE ELEMENTS:"]
        if self.elements:
            for e in self.elements:
                val = f' value="{e.value}"' if e.value else ""
                lines.append(f'  {e.ref} [{e.role}] "{e.name}"{val}')
        else:
            lines.append("  (none found)")
        lines.append("")
        lines.append("VISIBLE TEXT:")
        lines += [f"  {t}" for t in self.text] or ["  (none)"]
        return "\n".join(lines)


@dataclass
class Action:
    kind: str                 # "click" | "type" | "finish"
    ref: str | None = None
    text: str | None = None
    outputs: dict | None = None
    reason: str | None = None