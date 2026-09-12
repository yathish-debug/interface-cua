"""Redaction for logs and artifacts. Regulated data never persisted raw.

Outputs RETURNED to the caller are not redacted (the caller needs them).
Anything we PERSIST carries keys/presence, never raw values, plus a scrub
for obvious secrets/PII in any free text that does get logged.
"""
from __future__ import annotations
import re

_PII = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "<ssn>"),                 # SSN
    (re.compile(r"\b\d{13,19}\b"), "<card>"),                        # card-ish digit run
    (re.compile(r"(?i)\b(password|token|secret|api[_-]?key)\b\s*[:=]\s*\S+"),
     r"\1=<redacted>"),
]


def scrub(text: str | None) -> str:
    """Scrub secrets/PII from free text before it is logged (agent observations)."""
    if not text:
        return ""
    out = text
    for pat, repl in _PII:
        out = pat.sub(repl, out)
    return out


def presence(d: dict) -> dict:
    """Log-safe view of a values dict: presence only, no raw values."""
    return {k: ("<present>" if v not in (None, "") else "<empty>") for k, v in d.items()}