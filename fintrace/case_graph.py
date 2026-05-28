from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from .ontology import build_context
from .parser import parse_case_fields
from .policies import run_hard_policies
from .reasoning import make_decision
from .schemas import CaseState, TraceStatus
from .tracing import trace_node


def build_case_graph():
    graph = StateGraph(CaseState)
    graph.add_node("parser", parser_node)
    graph.add_node("hard_policy", hard_policy_node)
    graph.add_node("context", context_node)
    graph.add_node("reasoning", reasoning_node)
    graph.add_node("decision", decision_node)

    graph.add_edge(START, "parser")
    graph.add_edge("parser", "hard_policy")
    graph.add_conditional_edges(
        "hard_policy",
        route_after_policy,
        {
            "need_context": "context",
            "reject": "decision",
            "fraud_escalation": "decision",
        },
    )
    graph.add_edge("context", "reasoning")
    graph.add_edge("reasoning", "decision")
    graph.add_edge("decision", END)
    return graph.compile()


def parser_node(state: CaseState) -> dict[str, Any]:
    working = dict(state)
    with trace_node(working, "parser", input_refs=[a.get("artifact_id", "") for a in working.get("raw_artifacts", [])]) as event:
        fields, provenance, errors = parse_case_fields(
            working.get("raw_artifacts", []),
            working.get("batch_features", {}),
        )
        route = "parsed" if not errors else "parsed_with_warnings"
        event["output_refs"] = list(fields.keys())
        event["status"] = TraceStatus.WARN.value if errors else TraceStatus.OK.value
        event["confidence"] = 0.92 if not errors else 0.62
        event["errors"] = errors
        event["next_route"] = "hard_policy"
        event["details"] = {"field_count": len(fields), "route": route}
    return {
        "parsed_fields": fields,
        "field_provenance": provenance,
        "errors": working.get("errors", []) + errors,
        "debug_events": working.get("debug_events", []),
        "route": "hard_policy",
    }


def hard_policy_node(state: CaseState) -> dict[str, Any]:
    working = dict(state)
    with trace_node(working, "hard_policy", input_refs=list(working.get("parsed_fields", {}).keys())) as event:
        hits, route = run_hard_policies(working.get("parsed_fields", {}))
        event["output_refs"] = [h["rule_id"] for h in hits]
        event["status"] = TraceStatus.WARN.value if hits else TraceStatus.OK.value
        event["confidence"] = 0.95
        event["next_route"] = route
        event["details"] = {"hit_count": len(hits), "matched_rules": [h["rule_id"] for h in hits]}
    return {
        "policy_hits": hits,
        "route": route,
        "debug_events": working.get("debug_events", []),
    }


def route_after_policy(state: CaseState) -> Literal["need_context", "reject", "fraud_escalation"]:
    route = state.get("route", "need_context")
    if route in {"reject", "fraud_escalation"}:
        return route  # type: ignore[return-value]
    return "need_context"


def context_node(state: CaseState) -> dict[str, Any]:
    working = dict(state)
    with trace_node(working, "context", input_refs=["parsed_fields"]) as event:
        context = build_context(working.get("parsed_fields", {}))
        event["output_refs"] = [call["tool"] for call in context.get("tool_calls", [])]
        event["confidence"] = 0.88
        event["next_route"] = "reasoning"
        event["details"] = {"tool_count": len(context.get("tool_calls", []))}
    return {
        "context_info": context,
        "debug_events": working.get("debug_events", []),
        "route": "reasoning",
    }


def reasoning_node(state: CaseState) -> dict[str, Any]:
    working = dict(state)
    with trace_node(working, "reasoning", input_refs=["parsed_fields", "policy_hits", "context_info"]) as event:
        decision, reasoning_trace = make_decision(
            working.get("parsed_fields", {}),
            working.get("policy_hits", []),
            working.get("context_info", {}),
            llm_mode=working.get("llm_mode", "mock"),
        )
        event["output_refs"] = [decision.get("decision", "")]
        event["confidence"] = float(decision.get("confidence", 0.75))
        event["next_route"] = "decision"
        llm_meta = reasoning_trace.get("llm_meta", {})
        if llm_meta.get("status") in {"fallback", "skipped"} and llm_meta.get("error_category"):
            event["status"] = TraceStatus.WARN.value
            event["errors"].append(
                {
                    "category": llm_meta.get("error_category"),
                    "message": llm_meta.get("error_message", ""),
                }
            )
        event["details"] = {
            "risk_level": decision.get("risk_level"),
            "reason": decision.get("reason"),
            "llm_status": llm_meta.get("status", "not_used"),
        }
    return {
        "decision": decision,
        "reasoning_trace": reasoning_trace,
        "debug_events": working.get("debug_events", []),
        "route": "decision",
    }


def decision_node(state: CaseState) -> dict[str, Any]:
    working = dict(state)
    with trace_node(working, "decision", input_refs=["policy_hits", "reasoning_trace"]) as event:
        decision = working.get("decision")
        reasoning_trace = working.get("reasoning_trace")
        if not decision:
            decision, reasoning_trace = make_decision(
                working.get("parsed_fields", {}),
                working.get("policy_hits", []),
                working.get("context_info", {}),
                llm_mode=working.get("llm_mode", "mock"),
            )
        event["output_refs"] = [decision.get("decision", "")]
        event["confidence"] = float(decision.get("confidence", 0.75))
        event["next_route"] = "end"
        event["details"] = {
            "decision": decision.get("decision"),
            "risk_level": decision.get("risk_level"),
            "recommended_action": decision.get("recommended_action"),
        }
    return {
        "decision": decision,
        "reasoning_trace": reasoning_trace,
        "debug_events": working.get("debug_events", []),
        "route": "end",
    }
