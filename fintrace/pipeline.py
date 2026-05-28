from __future__ import annotations

import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from .case_graph import build_case_graph
from .config import get_settings
from .ingestion import assemble_cases, prepare_sources, scan_manifest
from .schemas import BatchState
from .storage import append_jsonl, ensure_dir, utcish_stamp, write_json
from .tracing import build_error_registry, trace_node


def run_batch(
    source_paths: list[str],
    output_root: str | Path | None = None,
    batch_id: str | None = None,
    llm_mode: str = "mock",
    max_workers: int = 4,
) -> dict[str, Any]:
    settings = get_settings()
    batch = batch_id or f"FTB-{utcish_stamp()}"
    root = ensure_dir(Path(output_root) if output_root else settings.output_root)
    work_dir = ensure_dir(root / batch)

    if os.getenv("LANGSMITH_API_KEY"):
        os.environ.setdefault("LANGSMITH_TRACING", "true")
        os.environ.setdefault("LANGSMITH_PROJECT", "FinTrace")

    graph = build_batch_graph()
    initial: BatchState = {
        "batch_id": batch,
        "source_paths": source_paths,
        "work_dir": str(work_dir),
        "llm_mode": llm_mode,
        "max_workers": max_workers,
        "debug_events": [],
    }
    result = graph.invoke(initial)
    return result


def build_batch_graph():
    graph = StateGraph(BatchState)
    graph.add_node("batch_ingestion", batch_ingestion_node)
    graph.add_node("case_assembly", case_assembly_node)
    graph.add_node("case_dispatch", case_dispatch_node)
    graph.add_node("batch_aggregate", batch_aggregate_node)
    graph.add_node("trace_export", trace_export_node)
    graph.add_edge(START, "batch_ingestion")
    graph.add_edge("batch_ingestion", "case_assembly")
    graph.add_edge("case_assembly", "case_dispatch")
    graph.add_edge("case_dispatch", "batch_aggregate")
    graph.add_edge("batch_aggregate", "trace_export")
    graph.add_edge("trace_export", END)
    return graph.compile()


def batch_ingestion_node(state: BatchState) -> dict[str, Any]:
    working = dict(state)
    with trace_node(working, "batch_ingestion", input_refs=working.get("source_paths", [])) as event:
        work_dir = Path(working["work_dir"])
        files = prepare_sources(working.get("source_paths", []), work_dir / "incoming")
        manifest = [item.to_dict() for item in scan_manifest(files)]
        event["output_refs"] = [m["artifact_id"] for m in manifest]
        event["details"] = {"file_count": len(manifest), "types": dict(Counter(m["artifact_type"] for m in manifest))}
        event["next_route"] = "case_assembly"
    return {"manifest": manifest, "debug_events": working.get("debug_events", [])}


def case_assembly_node(state: BatchState) -> dict[str, Any]:
    working = dict(state)
    with trace_node(working, "case_assembly", input_refs=[m["artifact_id"] for m in working.get("manifest", [])]) as event:
        cases = assemble_cases(working["batch_id"], working.get("manifest", []))
        case_index = [case.to_dict() for case in cases]
        event["output_refs"] = [c["case_id"] for c in case_index]
        event["details"] = {"case_count": len(case_index)}
        event["next_route"] = "case_dispatch"
    return {"case_index": case_index, "debug_events": working.get("debug_events", [])}


def case_dispatch_node(state: BatchState) -> dict[str, Any]:
    working = dict(state)
    with trace_node(working, "case_dispatch", input_refs=[c["case_id"] for c in working.get("case_index", [])]) as event:
        case_index = working.get("case_index", [])
        max_workers = int(working.get("max_workers") or 1)
        if max_workers > 1 and len(case_index) > 1:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                results = list(pool.map(lambda case: run_case(case, working), case_index))
        else:
            results = [run_case(case, working) for case in case_index]
        event["output_refs"] = [r["case_id"] for r in results]
        event["details"] = {"processed_cases": len(results)}
        event["next_route"] = "batch_aggregate"
    return {"case_results": results, "debug_events": working.get("debug_events", [])}


def run_case(case: dict[str, Any], batch_state: dict[str, Any]) -> dict[str, Any]:
    graph = build_case_graph()
    initial = {
        "batch_id": batch_state["batch_id"],
        "case_id": case["case_id"],
        "raw_artifacts": case["raw_artifacts"],
        "batch_features": case.get("batch_features", {}),
        "llm_mode": batch_state.get("llm_mode", "mock"),
        "debug_events": [],
        "errors": [],
    }
    result = graph.invoke(initial)
    return result


def batch_aggregate_node(state: BatchState) -> dict[str, Any]:
    working = dict(state)
    with trace_node(working, "batch_aggregate", input_refs=[r["case_id"] for r in working.get("case_results", [])]) as event:
        results = working.get("case_results", [])
        decisions = Counter(r.get("decision", {}).get("decision", "UNKNOWN") for r in results)
        risks = Counter(r.get("decision", {}).get("risk_level", "UNKNOWN") for r in results)
        event_counts = Counter()
        latencies: list[float] = []
        for result in results:
            for ev in result.get("debug_events", []):
                event_counts[ev.get("node_name", "unknown")] += 1
                latencies.append(float(ev.get("latency_ms") or 0))
        metrics = {
            "case_count": len(results),
            "decision_counts": dict(decisions),
            "risk_counts": dict(risks),
            "avg_node_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
            "node_event_counts": dict(event_counts),
            "node_failure_count": sum(1 for r in results for ev in r.get("debug_events", []) if ev.get("status") == "ERROR"),
            "file_type_distribution": dict(Counter(m.get("artifact_type", "unknown") for m in working.get("manifest", []))),
        }
        error_registry = build_error_registry(results)
        event["output_refs"] = ["batch_metrics", "error_registry"]
        event["details"] = metrics
        event["next_route"] = "trace_export"
    return {
        "batch_metrics": metrics,
        "error_registry": error_registry,
        "debug_events": working.get("debug_events", []),
    }


def trace_export_node(state: BatchState) -> dict[str, Any]:
    working = dict(state)
    with trace_node(working, "trace_export", input_refs=["case_results", "batch_metrics"]) as event:
        work_dir = Path(working["work_dir"])
        write_json(work_dir / "manifest.json", working.get("manifest", []))
        write_json(work_dir / "case_index.json", working.get("case_index", []))
        write_json(work_dir / "batch_metrics.json", working.get("batch_metrics", {}))
        write_json(work_dir / "error_registry.json", working.get("error_registry", {}))
        write_json(work_dir / "batch_result.json", compact_batch_result(working))
        trace_rows: list[dict[str, Any]] = []
        for result in working.get("case_results", []):
            case_dir = ensure_dir(work_dir / "cases" / result["case_id"])
            write_json(case_dir / "case_result.json", result)
            for event_row in result.get("debug_events", []):
                trace_rows.append({"batch_id": working["batch_id"], "case_id": result["case_id"], **event_row})
        append_jsonl(work_dir / "traces.jsonl", trace_rows)
        event["output_refs"] = [str(work_dir / "batch_result.json"), str(work_dir / "traces.jsonl")]
        event["details"] = {"work_dir": str(work_dir), "trace_events": len(trace_rows)}
        event["next_route"] = "end"
    return {"debug_events": working.get("debug_events", [])}


def compact_batch_result(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "batch_id": state.get("batch_id"),
        "work_dir": state.get("work_dir"),
        "source_paths": state.get("source_paths", []),
        "manifest": state.get("manifest", []),
        "case_results": state.get("case_results", []),
        "batch_metrics": state.get("batch_metrics", {}),
        "error_registry": state.get("error_registry", {}),
        "debug_events": state.get("debug_events", []),
    }

