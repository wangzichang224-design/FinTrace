from __future__ import annotations

import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Any, Iterator

from .schemas import TraceEvent, TraceStatus


@contextmanager
def trace_node(
    state: dict[str, Any],
    node_name: str,
    input_refs: list[str] | None = None,
) -> Iterator[dict[str, Any]]:
    start = time.perf_counter()
    event: dict[str, Any] = {
        "node_name": node_name,
        "input_refs": input_refs or [],
        "output_refs": [],
        "status": TraceStatus.OK.value,
        "latency_ms": 0.0,
        "confidence": 1.0,
        "errors": [],
        "next_route": "",
        "details": {},
    }
    try:
        yield event
    except Exception as exc:
        event["status"] = TraceStatus.ERROR.value
        event["errors"].append({"type": exc.__class__.__name__, "message": str(exc)})
        raise
    finally:
        event["latency_ms"] = round((time.perf_counter() - start) * 1000, 2)
        state.setdefault("debug_events", []).append(TraceEvent(**event).to_dict())


def register_error(
    state: dict[str, Any],
    category: str,
    message: str,
    node_name: str = "",
    case_id: str = "",
    artifact_id: str = "",
) -> None:
    error = {
        "category": category,
        "message": message,
        "node_name": node_name,
        "case_id": case_id or state.get("case_id", ""),
        "artifact_id": artifact_id,
    }
    state.setdefault("errors", []).append(error)


def build_error_registry(case_results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    registry: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in case_results:
        case_id = result.get("case_id", "")
        for err in result.get("errors", []):
            item = dict(err)
            item.setdefault("case_id", case_id)
            registry[item.get("category", "unknown")].append(item)
        for event in result.get("debug_events", []):
            for err in event.get("errors", []):
                category = err.get("category") or err.get("type") or "node_error"
                registry[category].append(
                    {
                        "case_id": case_id,
                        "node_name": event.get("node_name", ""),
                        "message": err.get("message", str(err)),
                    }
                )
    return dict(registry)

