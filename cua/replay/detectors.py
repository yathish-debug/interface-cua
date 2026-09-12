"""Per-app knowledge of exceptional states: what they look like, how to react.

Deliberately separate from the recorded flow. The artifact says WHAT to do;
this says what can go wrong on THIS app and how replay classifies/reacts.
One registry serves every capability on the app and generalizes across tenants
running the same vendor product.
"""
from __future__ import annotations
from enum import Enum
from dataclasses import dataclass


class DetKind(str, Enum):
    business = "business"        # legit non-success -> stop, return business_outcome
    recoverable = "recoverable"  # auto-handle (reload/retry), then continue
    hard = "hard"                # stop, return failure


@dataclass
class Detector:
    code: str
    kind: DetKind
    match_text: str              # substring identifying the state on-screen
    message: str
    recovery: str | None = None  # "reload" | None
    max_retries: int = 0


REGISTRY: dict[str, list[Detector]] = {
    "core_servicing_console": [
        Detector("no_such_member", DetKind.business,
                 "No such member", "No member exists for the supplied ID."),
        Detector("account_frozen", DetKind.business,
                 "is frozen and cannot open",
                 "Member is frozen; the requested action is not permitted."),
        Detector("session_expired", DetKind.recoverable,
                 "Your session has expired", "Session expired mid-flow.",
                 recovery="reload", max_retries=1),
    ],
}


def detectors_for(app_id: str) -> list[Detector]:
    return REGISTRY.get(app_id, [])