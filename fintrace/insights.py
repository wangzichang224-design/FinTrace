from __future__ import annotations

import re
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

    contextual_hits = [hit for hit in case.get("policy_hits", []) if hit.get("rule_class") == "contextual_risk_signal"]
    if contextual_hits:
        return _specific_hit_reason(case, _primary_hit(contextual_hits))

    manual_review_reason = decision.get("manual_review_reason")
    if manual_review_reason:
        return manual_review_reason

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
        contextual_hits = [hit for hit in case.get("policy_hits", []) if hit.get("rule_class") == "contextual_risk_signal"]
        if contextual_hits:
            return _specific_next_action(case, _primary_hit(contextual_hits))
        return "请财务复核原始附件、审批记录和字段来源，确认业务真实性后再处理。"
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
            rule_id = str(hit.get("rule_id") or "")
            rule_counter[f"{rule_id}｜{hit.get('rule_name') or RULE_DISPLAY_NAMES.get(rule_id, '规则命中')}"] += 1
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
    rule_name = first.get("rule_name") or RULE_DISPLAY_NAMES.get(first.get("rule_id"), "")
    return f"{prefix}：{first.get('rule_id')} {rule_name}。{first.get('reason', '')}".strip()


RULE_PRIORITY = [
    "R012_TIME_SPACE_CONFLICT",
    "R013_PURPOSE_ATTACHMENT_MISMATCH",
    "R003_SPLIT_INVOICE",
    "R008_OCR_AMOUNT_CONFLICT",
    "R010_APPROVAL_INCOMPLETE",
    "R011_ABNORMAL_AMOUNT",
    "R006_CROSS_PERIOD",
    "R007_SIMILAR_INVOICE_NO",
    "R009_CHAT_PROMPT_INJECTION",
    "R004_ABSOLUTE_LIMIT",
]

RULE_DISPLAY_NAMES = {
    "R001_MISSING_ORIGINAL": "缺少发票原件",
    "R002_DUPLICATE_INVOICE": "重复发票",
    "R003_SPLIT_INVOICE": "疑似拆单",
    "R004_ABSOLUTE_LIMIT": "金额超标",
    "R005_VENDOR_BLACKLIST": "供应商黑名单",
    "R006_CROSS_PERIOD": "跨期报销",
    "R007_SIMILAR_INVOICE_NO": "相似发票号",
    "R008_OCR_AMOUNT_CONFLICT": "OCR 金额冲突",
    "R009_CHAT_PROMPT_INJECTION": "审批聊天越权诱导",
    "R010_APPROVAL_INCOMPLETE": "审批状态未完成",
    "R011_ABNORMAL_AMOUNT": "金额异常",
    "R012_TIME_SPACE_CONFLICT": "时空冲突",
    "R013_PURPOSE_ATTACHMENT_MISMATCH": "事由与附件不一致",
}


def _primary_hit(hits: list[dict[str, Any]]) -> dict[str, Any]:
    priority = {rule_id: idx for idx, rule_id in enumerate(RULE_PRIORITY)}
    return sorted(hits, key=lambda hit: priority.get(str(hit.get("rule_id")), 999))[0]


def _specific_hit_reason(case: dict[str, Any], hit: dict[str, Any]) -> str:
    fields = case.get("parsed_fields", {})
    rule_id = hit.get("rule_id")
    if rule_id == "R012_TIME_SPACE_CONFLICT":
        detail = fields.get("time_space_conflict_detail") or hit.get("calculation") or "同日远距离城市消费"
        return f"同一员工同日出现远距离消费：{detail}。批次内未发现机票、登机牌或航班行程单，因此需人工核验行程真实性。"
    if rule_id == "R003_SPLIT_INVOICE":
        count = fields.get("split_group_count") or hit.get("input_fields", {}).get("split_group_count")
        total = fields.get("split_group_total") or hit.get("input_fields", {}).get("split_group_total")
        vendor = fields.get("vendor") or "同一供应商"
        date = fields.get("expense_date") or "同一日期"
        category = fields.get("expense_type") or "同一费用类型"
        return f"同员工、同供应商（{vendor}）、同日期（{date}）、同费用类型（{category}）出现 {count} 张票，合计 {total} 元，疑似拆单规避审批。"
    if rule_id == "R013_PURPOSE_ATTACHMENT_MISMATCH":
        terms = "、".join(map(str, fields.get("purpose_mismatch_terms") or hit.get("input_fields", {}).get("purpose_mismatch_terms", [])))
        description = fields.get("description") or "客户拜访/业务沟通"
        return f"报销事由写的是“{description}”，但附件商品包含 {terms or '非业务消费'}，与客户拜访用途不一致，需核验业务实质。"
    if rule_id == "R010_APPROVAL_INCOMPLETE":
        return f"ERP 审批状态为“{fields.get('approval_status') or '空'}”，还未形成完整审批链，不能直接进入付款。"
    if rule_id == "R011_ABNORMAL_AMOUNT":
        return f"报销金额为 {fields.get('amount')}，属于空金额、零金额或负数金额异常，需要人工确认是否为录入错误或测试单。"
    if rule_id == "R008_OCR_AMOUNT_CONFLICT":
        return f"ERP 金额为 {fields.get('amount')}，附件/OCR 金额为 {fields.get('attachment_amount')}，差异超过 20%，需要回到原始票据修正字段。"
    if rule_id == "R006_CROSS_PERIOD":
        return f"费用日期为 {fields.get('expense_date')}，已超过报销窗口，需要确认是否有延迟提交说明或特批。"
    if rule_id == "R007_SIMILAR_INVOICE_NO":
        return f"该发票号与批次内其他发票号高度相似，关联案件：{fields.get('similar_invoice_peers', [])}，需要核验是否改号、连号或录入污染。"
    if rule_id == "R009_CHAT_PROMPT_INJECTION":
        return "审批聊天中出现“忽略制度/绕过审核/立即批准”等越权话术，该话术不能作为有效审批依据。"
    if rule_id == "R004_ABSOLUTE_LIMIT":
        amount = fields.get("amount")
        threshold = hit.get("threshold")
        return f"金额 {amount} 元超过当前费用标准 {threshold} 元，需要结合客户等级、节假日、员工信用或专项审批判断。"
    return _format_hit_reason("风险信号触发人工复核", [hit])


def _specific_next_action(case: dict[str, Any], hit: dict[str, Any]) -> str:
    rule_id = hit.get("rule_id")
    fields = case.get("parsed_fields", {})
    if rule_id == "R012_TIME_SPACE_CONFLICT":
        route = _time_space_route(fields.get("time_space_conflict_detail", ""))
        return f"要求员工补充{route}机票、登机牌、行程单或改签说明；无法提供则退回相关单据或转内控复核。"
    actions = {
        "R003_SPLIT_INVOICE": "合并查看同日同供应商发票，核验是否拆单；要求补充完整消费清单和高管/专项审批，无法说明拆分原因则退回或升级复核。",
        "R013_PURPOSE_ATTACHMENT_MISMATCH": "要求员工说明礼品卡/游戏机与客户拜访的业务关系，并补充客户接待审批；无法证明业务用途则退回。",
        "R010_APPROVAL_INCOMPLETE": "退回员工或部门负责人补齐审批流，待 ERP 状态变为已审批后再复核。",
        "R011_ABNORMAL_AMOUNT": "核对 ERP 原始行和发票金额，修正空金额、零金额或负数金额后重新提交。",
        "R008_OCR_AMOUNT_CONFLICT": "打开字段溯源，对照原始发票修正 OCR 或 ERP 金额，再重新运行该批次。",
        "R006_CROSS_PERIOD": "要求补充延迟报销说明、部门审批或财务特批依据。",
        "R007_SIMILAR_INVOICE_NO": "对照相似发票号的原始票据，确认是否重复、改号或录入错误。",
        "R009_CHAT_PROMPT_INJECTION": "忽略聊天中的越权指令，只采纳正式审批记录；必要时提醒提交人不得诱导系统绕过制度。",
        "R004_ABSOLUTE_LIMIT": "检查是否存在客户等级、节假日涨价、专项预算或历史人工特批；没有依据则退回或转上级审批。",
    }
    return actions.get(str(rule_id), "请财务复核原始附件、审批记录和字段来源，确认业务真实性后再处理。")


def _time_space_route(detail: str) -> str:
    match = re.search(r"([\u4e00-\u9fffA-Za-z]+)\s+\d{1,2}:\d{2}\s+vs\s+([\u4e00-\u9fffA-Za-z]+)\s+\d{1,2}:\d{2}", str(detail))
    if match:
        return f"{match.group(1)}至{match.group(2)}"
    return "两地之间的"


def _counter_rows(issue_type: str, counter: Counter[str], suggestion: str) -> list[dict[str, Any]]:
    return [
        {"类型": issue_type, "问题": key, "数量": value, "优化建议": suggestion}
        for key, value in counter.items()
        if key and value
    ]
