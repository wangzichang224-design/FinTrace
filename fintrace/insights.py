from __future__ import annotations

from collections import Counter
from typing import Any


DECISION_LABELS = {
    "APPROVE": "自动通过",
    "APPROVE_WITH_FLEX": "柔性通过",
    "REJECT": "拒绝",
    "MANUAL_REVIEW": "人工复核",
    "ESCALATE_FRAUD": "反舞弊升级",
}

RISK_LABELS = {"LOW": "低", "MEDIUM": "中", "HIGH": "高", "CRITICAL": "严重"}

RULE_CLASS_LABELS = {
    "blocking_control": "阻断控制",
    "contextual_risk_signal": "上下文风险信号",
}


def decision_label(value: str | None) -> str:
    return DECISION_LABELS.get(value or "", value or "未决策")


def risk_label(value: str | None) -> str:
    return RISK_LABELS.get(value or "", value or "未知")


def case_failure_reason(case: dict[str, Any]) -> str:
    decision = case.get("decision", {})
    decision_value = decision.get("decision")
    if decision_value in {"APPROVE", "APPROVE_WITH_FLEX"}:
        return decision.get("reason") or "未命中阻断控制，系统判定可通过。"

    blocking_hits = [hit for hit in case.get("policy_hits", []) if hit.get("rule_class") == "blocking_control"]
    if blocking_hits:
        return _format_hit_reason("阻断控制命中", blocking_hits)

    manual_review_reason = decision.get("manual_review_reason")
    if manual_review_reason:
        return manual_review_reason

    contextual_hits = [hit for hit in case.get("policy_hits", []) if hit.get("rule_class") == "contextual_risk_signal"]
    if contextual_hits:
        return _format_hit_reason("风险信号触发人工复核", contextual_hits)

    errors = case.get("errors", [])
    if errors:
        first = errors[0]
        return f"{first.get('category', '处理异常')}：{first.get('message', '需要人工定位。')}"

    return decision.get("reason") or "该案件未通过自动审核，需要人工确认。"


def next_action(case: dict[str, Any]) -> str:
    decision_value = case.get("decision", {}).get("decision")
    if decision_value == "REJECT":
        return "退回员工补充或更正材料"
    if decision_value == "ESCALATE_FRAUD":
        return "提交反舞弊/内控复核"
    if decision_value == "MANUAL_REVIEW":
        return "人工复核附件、审批背景和本体上下文"
    if decision_value == "APPROVE_WITH_FLEX":
        return "保留柔性通过证据，进入付款前抽样"
    if decision_value == "APPROVE":
        return "进入后续付款流程"
    return "等待系统处理"


def debug_focus(case: dict[str, Any]) -> str:
    if case.get("errors"):
        return "字段抽取/OCR"
    if any(hit.get("rule_class") == "blocking_control" for hit in case.get("policy_hits", [])):
        return "阻断控制"
    if any(hit.get("rule_class") == "contextual_risk_signal" for hit in case.get("policy_hits", [])):
        return "风险阈值/业务上下文"
    context_quality = case.get("context_info", {}).get("context_quality", {})
    if context_quality.get("missing_items") or context_quality.get("cold_start_items"):
        return "企业本体冷启动"
    guardrail = case.get("decision", {}).get("guardrail_status") or ""
    if guardrail.startswith("llm_"):
        return "LLM 门控"
    if case.get("decision", {}).get("decision") == "MANUAL_REVIEW":
        return "人工争议"
    return "链路正常"


def review_queue_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in result.get("case_results", []):
        fields = case.get("parsed_fields", {})
        decision = case.get("decision", {})
        error_types = sorted({err.get("category", "未知错误") for err in case.get("errors", [])})
        rows.append(
            {
                "case_id": case.get("case_id"),
                "报销单号": fields.get("reimbursement_id"),
                "员工": fields.get("employee_name"),
                "部门": fields.get("department"),
                "费用类型": fields.get("expense_type"),
                "供应商": fields.get("vendor"),
                "金额": fields.get("amount"),
                "决策": decision_label(decision.get("decision")),
                "风险": risk_label(decision.get("risk_level")),
                "不通过/复核原因": case_failure_reason(case),
                "建议动作": next_action(case),
                "诊断焦点": debug_focus(case),
                "置信度": decision.get("confidence"),
                "错误类型": "、".join(error_types),
            }
        )
    return rows


def optimization_insights(result: dict[str, Any]) -> dict[str, Any]:
    cases = result.get("case_results", [])
    metrics = result.get("batch_metrics", {})
    decision_counts = metrics.get("decision_counts", {})
    failed_count = metrics.get("case_failed_count", 0)

    rule_counter: Counter[str] = Counter()
    class_counter: Counter[str] = Counter()
    focus_counter: Counter[str] = Counter()
    guardrail_counter: Counter[str] = Counter()
    missing_context_counter: Counter[str] = Counter()
    cold_start_counter: Counter[str] = Counter()

    for case in cases:
        focus_counter[debug_focus(case)] += 1
        for hit in case.get("policy_hits", []):
            rule_counter[f"{hit.get('rule_id')}｜{hit.get('rule_name')}"] += 1
            class_counter[RULE_CLASS_LABELS.get(hit.get("rule_class"), hit.get("rule_class", "未知规则"))] += 1
        guardrail = case.get("decision", {}).get("guardrail_status")
        if guardrail and guardrail != "local_baseline":
            guardrail_counter[guardrail] += 1
        context_quality = case.get("context_info", {}).get("context_quality", {})
        missing_context_counter.update(context_quality.get("missing_items", []))
        cold_start_counter.update(context_quality.get("cold_start_items", []))

    error_counter = Counter({category: len(rows) for category, rows in result.get("error_registry", {}).items()})
    issue_rows = []
    issue_rows.extend(_counter_rows("规则命中", rule_counter, "检查阈值、例外口径和培训材料是否一致。"))
    issue_rows.extend(_counter_rows("规则类型", class_counter, "阻断控制要少而硬，风险信号要进入人工或本体判断。"))
    issue_rows.extend(_counter_rows("诊断焦点", focus_counter, "优先处理高频焦点，能最快降低人工复核量。"))
    issue_rows.extend(_counter_rows("错误源", error_counter, "回看原始附件和字段溯源，修复解析或输入规范。"))
    issue_rows.extend(_counter_rows("上下文缺失", missing_context_counter, "补齐 CRM/HR/供应商主数据，缺失时禁止柔性自动通过。"))
    issue_rows.extend(_counter_rows("冷启动字段", cold_start_counter, "建立默认值审批口径，并标记维护责任人和更新频率。"))
    issue_rows.extend(_counter_rows("LLM 门控", guardrail_counter, "优化提示词或证据引用，但不得让 LLM 覆盖阻断控制。"))

    issue_rows.sort(key=lambda row: row["数量"], reverse=True)
    issue_case_count = sum(decision_counts.get(key, 0) for key in ("REJECT", "MANUAL_REVIEW", "ESCALATE_FRAUD")) + failed_count

    return {
        "summary": {
            "案件总数": metrics.get("case_count", len(cases)),
            "需处理案件": issue_case_count,
            "失败案件": failed_count,
            "阻断/升级": decision_counts.get("REJECT", 0) + decision_counts.get("ESCALATE_FRAUD", 0),
            "人工复核": decision_counts.get("MANUAL_REVIEW", 0),
            "通过": decision_counts.get("APPROVE", 0) + decision_counts.get("APPROVE_WITH_FLEX", 0),
        },
        "top_issues": issue_rows[:12],
        "focus_counts": dict(focus_counter),
    }


def _format_hit_reason(prefix: str, hits: list[dict[str, Any]]) -> str:
    first = hits[0]
    return f"{prefix}：{first.get('rule_id')} {first.get('rule_name')}。{first.get('reason', '')}".strip()


def _counter_rows(issue_type: str, counter: Counter[str], suggestion: str) -> list[dict[str, Any]]:
    return [
        {"类型": issue_type, "问题": key, "数量": value, "优化建议": suggestion}
        for key, value in counter.items()
        if key and value
    ]
