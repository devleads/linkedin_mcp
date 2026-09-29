"""Deterministic semantic candidate resolution."""

from dataclasses import dataclass

from linkedin_mcp.linkedin.observation import ElementCandidate, PageObservation


class AmbiguousTargetError(RuntimeError):
    pass


class SelectorDriftError(RuntimeError):
    pass


@dataclass(frozen=True)
class Resolution:
    candidate: ElementCandidate
    strategy: str
    evidence: tuple[str, ...]


def resolve_semantic_candidate(
    observation: PageObservation,
    *,
    role: str | None = None,
    accessible_name: str | None = None,
) -> Resolution:
    """Resolve exactly one visible enabled candidate by role and accessible name."""
    normalized_name = accessible_name.casefold().strip() if accessible_name else None
    matches = []
    for candidate in observation.candidates:
        if not candidate.visible or candidate.disabled:
            continue
        if role and candidate.role != role:
            continue
        if normalized_name and (candidate.name or "").casefold().strip() != normalized_name:
            continue
        matches.append(candidate)
    if not matches:
        raise SelectorDriftError("No semantic candidate matched the requested intent")
    if len(matches) > 1:
        raise AmbiguousTargetError("Multiple semantic candidates matched the requested intent")
    evidence = tuple(value for value in (f"role={role}" if role else None, f"name={accessible_name}" if accessible_name else None) if value)
    return Resolution(matches[0], "accessible_role_name", evidence)
