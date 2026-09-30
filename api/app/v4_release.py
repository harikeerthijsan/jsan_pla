"""Machine-enforced v4 release gate."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable

@dataclass(frozen=True)
class GateResult:
    ready: bool
    blockers: tuple[dict, ...]
    warnings: tuple[dict, ...]

def evaluate_release_gate(results: Iterable[dict]) -> GateResult:
    blockers = []
    warnings = []
    for result in results:
        outcome = str(result.get("outcome", "")).upper()
        blocking = bool(result.get("blocking"))
        if blocking and outcome == "FAIL":
            blockers.append(result)
        elif outcome in {"WARNING", "REVIEW"}:
            warnings.append(result)
    return GateResult(ready=not blockers, blockers=tuple(blockers), warnings=tuple(warnings))
