from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CASE_STEPS = {"parser", "hard_policy", "context", "reasoning", "decision"}
BASE_EXPECTED_STEPS = ["parser", "hard_policy", "decision"]
CONTEXT_EXPECTED_STEPS = ["parser", "hard_policy", "context", "reasoning", "decision"]
DIRECT_POLICY_ROUTES = {"reject", "fraud_escalation"}
TRACE_REQUIRED_FIELDS = {"node_name", "input_refs", "output_refs", "status", "latency_ms", "confidence", "errors", "next_route"}


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            text = line.strip()
            if text:
                rows.append(json.loads(text))
    return rows


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    return path


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return path


def build_external_eval_report(batch_result_path: str | Path, traces_path: str | Path | None = None) -> dict[str, Any]:
    batch_path = Path(batch_result_path)
    batch = read_json(batch_path)
    trace_path = Path(traces_path) if traces_path else batch_path.with_name("traces.jsonl")
    trace_rows = read_jsonl(trace_path)
    case_results = batch.get("case_results", [])
    events_by_case = group_events_by_case(case_results, trace_rows)
    case_reports = [build_case_report(case, events_by_case.get(case.get("case_id", ""), [])) for case in case_results]
    metrics = summarize_case_reports(case_reports, batch.get("batch_metrics", {}))
    ragas_samples = [to_ragas_agent_sample(row) for row in case_reports]
    deepeval_cases = [to_deepeval_agent_case(row) for row in case_reports]
    return {
        "report_name": "FinTrace external agent evaluation adapter",
        "adapter_version": "fintrace-external-eval-v1",
        "source": {
            "batch_result_path": str(batch_path),
            "traces_path": str(trace_path),
            "batch_id": batch.get("batch_id"),
            "case_count": len(case_results),
        },
        "built_in_metrics": batch.get("batch_metrics", {}),
        "agent_eval_metrics": metrics,
        "case_reports": case_reports,
        "ragas_agent_samples": ragas_samples,
        "deepeval_agent_cases": deepeval_cases,
        "trace_visualization": {
            "langsmith": "Set LANGSMITH_API_KEY before running FinTrace to mirror LangGraph spans in LangSmith.",
            "phoenix": "Import traces.jsonl or the emitted case_reports as local spans for Phoenix-style inspection.",
        },
    }


def group_events_by_case(case_results: list[dict[str, Any]], trace_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in trace_rows:
        case_id = str(row.get("case_id") or "")
        if case_id:
            grouped.setdefault(case_id, []).append(row)
    for case in case_results:
        case_id = str(case.get("case_id") or "")
        if case_id and not grouped.get(case_id):
            grouped[case_id] = list(case.get("debug_events", []))
    return grouped


def build_case_report(case: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    node_names = [str(event.get("node_name") or "") for event in events]
    expected_steps = expected_steps_for(events)
    missing_steps = [step for step in expected_steps if step not in node_names]
    unexpected_steps = [step for step in node_names if step in CASE_STEPS and step not in expected_steps]
    order_ok = ordered_subsequence(node_names, expected_steps)
    event_completeness = score_event_completeness(events)
    decision = case.get("decision", {})
    reasoning_trace = case.get("reasoning_trace", {})
    has_decision = bool(decision.get("decision"))
    has_evidence = bool(decision.get("evidence_refs"))
    has_guardrail = bool(decision.get("guardrail_status") or reasoning_trace.get("llm_guardrail_status"))
    return {
        "case_id": case.get("case_id"),
        "case_failed": bool(case.get("case_failed")),
        "decision": decision,
        "actual_steps": [step for step in node_names if step in CASE_STEPS],
        "expected_steps": expected_steps,
        "missing_steps": missing_steps,
        "unexpected_steps": unexpected_steps,
        "tool_call_order_ok": order_ok,
        "tool_call_accuracy_ok": not missing_steps and order_ok,
        "task_completed": not case.get("case_failed") and has_decision,
        "event_schema_completeness": event_completeness,
        "decision_evidence_observable": has_evidence,
        "guardrail_observable": has_guardrail,
        "trace_explainability_score": round((event_completeness + float(has_evidence) + float(has_guardrail)) / 3, 4),
        "events": [
            {
                "node_name": event.get("node_name"),
                "input_refs": event.get("input_refs", []),
                "output_refs": event.get("output_refs", []),
                "status": event.get("status"),
                "next_route": event.get("next_route"),
                "confidence": event.get("confidence"),
                "details": event.get("details", {}),
                "errors": event.get("errors", []),
            }
            for event in events
        ],
    }


def expected_steps_for(events: list[dict[str, Any]]) -> list[str]:
    hard_policy = next((event for event in events if event.get("node_name") == "hard_policy"), {})
    if hard_policy.get("next_route") in DIRECT_POLICY_ROUTES:
        return BASE_EXPECTED_STEPS
    return CONTEXT_EXPECTED_STEPS


def ordered_subsequence(actual: list[str], expected: list[str]) -> bool:
    cursor = -1
    for step in expected:
        try:
            cursor = actual.index(step, cursor + 1)
        except ValueError:
            return False
    return True


def score_event_completeness(events: list[dict[str, Any]]) -> float:
    if not events:
        return 0.0
    scores = []
    for event in events:
        present = sum(1 for field in TRACE_REQUIRED_FIELDS if field in event)
        scores.append(present / len(TRACE_REQUIRED_FIELDS))
    return round(sum(scores) / len(scores), 4)


def summarize_case_reports(case_reports: list[dict[str, Any]], built_in_metrics: dict[str, Any]) -> dict[str, Any]:
    if not case_reports:
        return {
            "task_completion_rate": 0.0,
            "tool_call_accuracy": 0.0,
            "tool_call_f1": 0.0,
            "argument_reference_coverage": 0.0,
            "trace_explainability_score": 0.0,
            "guardrail_observability_rate": 0.0,
        }
    expected_total = 0
    actual_total = 0
    true_positive_steps = 0
    argument_events = 0
    total_events = 0
    for row in case_reports:
        expected = set(row["expected_steps"])
        actual = [step for step in row["actual_steps"] if step in CASE_STEPS]
        expected_total += len(expected)
        actual_total += len(actual)
        true_positive_steps += len(expected & set(actual))
        for event in row["events"]:
            total_events += 1
            if event.get("input_refs") and event.get("output_refs"):
                argument_events += 1
    precision = true_positive_steps / actual_total if actual_total else 0.0
    recall = true_positive_steps / expected_total if expected_total else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    metrics = {
        "task_completion_rate": rate(case_reports, "task_completed"),
        "tool_call_accuracy": rate(case_reports, "tool_call_accuracy_ok"),
        "tool_call_f1": round(f1, 4),
        "argument_reference_coverage": round(argument_events / total_events, 4) if total_events else 0.0,
        "trace_explainability_score": round(sum(row["trace_explainability_score"] for row in case_reports) / len(case_reports), 4),
        "guardrail_observability_rate": rate(case_reports, "guardrail_observable"),
    }
    for key in ("decision_accuracy", "hard_precision", "hard_recall", "field_accuracy"):
        if key in built_in_metrics:
            metrics[f"{key}_from_builtin"] = built_in_metrics[key]
    return metrics


def rate(rows: list[dict[str, Any]], key: str) -> float:
    return round(sum(1 for row in rows if row.get(key)) / len(rows), 4) if rows else 0.0


def to_ragas_agent_sample(case_report: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case_report["case_id"],
        "user_input": f"Audit reimbursement case {case_report['case_id']} with FinTrace.",
        "reference_tool_calls": [{"name": name} for name in case_report["expected_steps"]],
        "actual_tool_calls": [
            {
                "name": event.get("node_name"),
                "args": {
                    "input_refs": event.get("input_refs", []),
                    "next_route": event.get("next_route"),
                },
            }
            for event in case_report["events"]
            if event.get("node_name") in CASE_STEPS
        ],
        "response": case_report["decision"],
        "metadata": {
            "tool_call_accuracy_ok": case_report["tool_call_accuracy_ok"],
            "trace_explainability_score": case_report["trace_explainability_score"],
        },
    }


def to_deepeval_agent_case(case_report: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": f"FinTrace agent case {case_report['case_id']}",
        "input": f"Run the controlled reimbursement audit workflow for case {case_report['case_id']}.",
        "actual_output": case_report["decision"],
        "expected_tools": case_report["expected_steps"],
        "actual_tools": case_report["actual_steps"],
        "metrics_hint": ["Task Completion", "Tool Correctness", "Argument Correctness", "Plan Adherence"],
        "metadata": {
            "task_completed": case_report["task_completed"],
            "tool_call_order_ok": case_report["tool_call_order_ok"],
            "missing_steps": case_report["missing_steps"],
            "guardrail_observable": case_report["guardrail_observable"],
        },
    }


def write_external_eval_outputs(report: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    out = Path(output_dir)
    paths = {
        "report": write_json(out / "external_eval_report.json", strip_large_samples(report)),
        "ragas_samples": write_jsonl(out / "ragas_agent_samples.jsonl", report.get("ragas_agent_samples", [])),
        "deepeval_cases": write_jsonl(out / "deepeval_agent_cases.jsonl", report.get("deepeval_agent_cases", [])),
    }
    return {key: str(path) for key, path in paths.items()}


def strip_large_samples(report: dict[str, Any]) -> dict[str, Any]:
    compact = dict(report)
    compact["ragas_agent_samples_path"] = "ragas_agent_samples.jsonl"
    compact["deepeval_agent_cases_path"] = "deepeval_agent_cases.jsonl"
    compact.pop("ragas_agent_samples", None)
    compact.pop("deepeval_agent_cases", None)
    return compact


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build read-only external evaluation adapters from FinTrace batch artifacts.")
    parser.add_argument("batch_result", help="Path to batch_result.json.")
    parser.add_argument("--traces", default="", help="Optional path to traces.jsonl. Defaults to the batch_result directory.")
    parser.add_argument("--output-dir", default="", help="Output directory. Defaults to <batch_result_dir>/external_eval.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    batch_path = Path(args.batch_result)
    output_dir = Path(args.output_dir) if args.output_dir else batch_path.parent / "external_eval"
    report = build_external_eval_report(batch_path, args.traces or None)
    paths = write_external_eval_outputs(report, output_dir)
    print(f"External eval report: {paths['report']}")
    print(f"Ragas samples: {paths['ragas_samples']}")
    print(f"DeepEval cases: {paths['deepeval_cases']}")


if __name__ == "__main__":
    main()
