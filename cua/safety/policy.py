"""One policy, enforced at the perceive/act choke point on BOTH paths.

Discovery (agent loop) and replay call evaluate() before every action.
Deny-by-default on hosts; irreversible actions are flagged for a human
(Decision.confirm) rather than executed autonomously. This is the seam
where Phase 5 escalation attaches.
"""
from __future__ import annotations
import json
from enum import Enum
from urllib.parse import urlparse
from dataclasses import dataclass
from pydantic import BaseModel, Field


class Decision(str, Enum):
    allow = "allow"
    block = "block"       # not permitted at all -> refuse, log, do not act
    confirm = "confirm"   # irreversible -> needs human approval (routes to escalation)


class Risk(str, Enum):
    safe = "safe"
    irreversible = "irreversible"


@dataclass
class PolicyResult:
    decision: Decision
    risk: Risk
    reason: str


class Policy(BaseModel):
    version: str = "1.0"
    allowed_hosts: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    irreversible_routes: list[str] = Field(default_factory=list)
    irreversible_names: list[str] = Field(default_factory=list)
    allow_irreversible: bool = False   # global gate; flipped only with approval

    @classmethod
    def load(cls, path: str = "config/policy.json") -> "Policy":
        raw = json.load(open(path))
        irr = raw.pop("irreversible", {}) or {}
        return cls(
            **raw,
            irreversible_routes=irr.get("route_patterns", []),
            irreversible_names=irr.get("name_patterns", []),
        )

    def _host_ok(self, url: str | None) -> bool:
        if not url:                       # non-nav action; page host already vetted
            return True
        host = urlparse(url).netloc or url
        return any(host == h for h in self.allowed_hosts)

    def _is_irreversible(self, url: str | None, target_name: str | None,
                         declared_risk: str | None) -> bool:
        if declared_risk:                 # artifact-declared wins
            return declared_risk == "irreversible"
        hay_url = (url or "").lower()
        hay_name = (target_name or "").lower()
        if any(p in hay_url for p in self.irreversible_routes):
            return True
        if any(p in hay_name for p in self.irreversible_names):
            return True
        return False

    def evaluate(self, action: str, url: str | None = None,
                 target_name: str | None = None,
                 declared_risk: str | None = None) -> PolicyResult:
        # 1) action-kind allowlist
        if self.allowed_actions and action not in self.allowed_actions:
            return PolicyResult(Decision.block, Risk.safe,
                                f"action '{action}' not in allowlist")
        # 2) host allowlist (deny-by-default)
        if not self._host_ok(url):
            host = urlparse(url).netloc or url
            return PolicyResult(Decision.block, Risk.safe,
                                f"host '{host}' not in allowlist")
        # 3) risk classification
        if self._is_irreversible(url, target_name, declared_risk):
            if self.allow_irreversible:
                return PolicyResult(Decision.allow, Risk.irreversible,
                                    "irreversible action explicitly approved")
            return PolicyResult(Decision.confirm, Risk.irreversible,
                                "irreversible action requires human approval")
        return PolicyResult(Decision.allow, Risk.safe, "safe action within allowlist")