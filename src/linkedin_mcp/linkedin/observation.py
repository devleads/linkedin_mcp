"""Sanitized browser observations used by deterministic page adapters."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ElementCandidate:
    reference: str
    role: str | None = None
    name: str | None = None
    visible: bool = True
    disabled: bool = False
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PageObservation:
    url: str
    title: str = ""
    ready_state: str = ""
    visible_text: str = ""
    headings: tuple[str, ...] = ()
    landmarks: tuple[str, ...] = ()
    candidates: tuple[ElementCandidate, ...] = ()
    page_revision: int = 0

    def safe_model_payload(self) -> dict[str, Any]:
        """Return only bounded structural data; browser secrets are never included."""
        return {
            "url": self.url,
            "title": self.title[:300],
            "ready_state": self.ready_state,
            "headings": [value[:300] for value in self.headings[:20]],
            "landmarks": list(self.landmarks[:20]),
            "candidates": [
                {
                    "reference": item.reference,
                    "role": item.role,
                    "name": (item.name or "")[:300],
                    "visible": item.visible,
                    "disabled": item.disabled,
                }
                for item in self.candidates[:100]
            ],
            "page_revision": self.page_revision,
        }
