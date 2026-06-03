from __future__ import annotations

from pathlib import Path
from typing import Any, MutableMapping

from .insights import case_failure_reason, decision_label, next_action, risk_label
from .storage import read_json


SHOWCASE_DATASET_NAME = "showcase_fintrace_v1"

SCENARIO_LABELS = {
    "time_space_conflict": "时空冲突",
    "split_invoice_evasion": "拆单规避",
    "purpose_attachment_mismatch": "事由与附件不一致",
}

SCENARIO_STORIES = {
    "time_space_conflict": "同一员工同日出现远距离城市消费，批次内未发现机票、登机牌或航班行程单。",
    "split_invoice_evasion": "同一员工、同供应商、同日期、同费用类型被拆成多张低额发票，需要合并核验。",
    "purpose_attachment_mismatch": "报销事由写客户拜访，但附件商品出现游戏机、礼品卡等非业务消费关键词。",
}

SCENARIO_REVIEW_FOCUS = {
    "time_space_conflict": "核验行程真实性和交通凭证。",
    "split_invoice_evasion": "核验是否拆单规避审批阈值。",
    "purpose_attachment_mismatch": "核验费用用途和客户接待审批。",
}

DEFAULT_SHOWCASE_PAIRS = [
    {
        "label": "同一员工同日两地消费",
        "left_case_id": "SHOW-TS-01",
        "right_case_id": "SHOW-TS-02",
        "reason": "两笔单独看金额都低，但放进批次后暴露上海到乌鲁木齐的时空冲突。",
    },
    {
        "label": "拆单规避 vs 事由不一致",
        "left_case_id": "SHOW-SPLIT-01",
        "right_case_id": "SHOW-MIS-01",
        "reason": "对比两类非金额型风险：一个靠批次关系发现，一个靠附件商品语义发现。",
    },
    {
        "label": "同一消费拆分开票",
        "left_case_id": "SHOW-SPLIT-01",
        "right_case_id": "SHOW-SPLIT-02",
        "reason": "并排查看同一晚同供应商的多张餐饮票，解释为什么需要合并复核。",
    },
]

CORE_FIELDS = [
    ("employee_name", "员工"),
    ("department", "部门"),
    ("expense_date", "日期"),
    ("expense_time", "时间"),
    ("city", "城市"),
    ("expense_type", "费用类型"),
    ("amount", "金额"),
    ("vendor", "供应商"),
    ("invoice_no", "发票号"),
    ("description", "报销事由"),
]

PROVENANCE_FIELDS = ["amount", "expense_type", "vendor", "invoice_no", "city", "expense_date", "description"]

DATASET_LABELS = {
    "showcase_fintrace_v1": "Showcase 冻结演示集",
    "fintrace-redteam-v1": "内置冻结红队集",
    "red_attack_v1": "Claude 红方攻击集",
    "dynamic_redteam": "随机红队开发自测",
    "custom_batch": "自定义批次",
}

DATASET_EXPECTED_PREFIX = {
    "showcase_fintrace_v1": "SHOW",
    "fintrace-redteam-v1": "FRZ",
    "red_attack_v1": "RA",
}

REVIEW_WIDGET_KEYS = {
    "finance_decision_filter",
    "finance_risk_filter",
    "finance_focus_filter",
    "finance_keyword",
    "finance_case_detail",
    "diagnostic_query",
    "diagnostic_case_selector",
    "comparison_pair",
    "comparison_left",
    "comparison_right",
    "field_case_selector",
    "rule_case_selector",
    "case_selector",
}

REVIEW_WIDGET_PREFIXES = (
    "finance_decision_filter_",
    "finance_risk_filter_",
    "finance_focus_filter_",
    "finance_keyword_",
    "finance_case_detail_",
    "diagnostic_query_",
    "diagnostic_case_selector_",
    "diagnostic_field_",
    "comparison_pair_",
    "comparison_left_",
    "comparison_right_",
    "feedback_approver_",
    "feedback_reason_",
    "feedback_record_",
)


def scenario_label(value: str | None) -> str:
    return SCENARIO_LABELS.get(value or "", value or "未知场景")


def dataset_label(value: str | None) -> str:
    return DATASET_LABELS.get(value or "", value or "未识别批次")


def detect_dataset_identity(source_paths: list[str] | tuple[str, ...] | None, result: dict[str, Any] | None = None) -> dict[str, Any]:
    paths = list(source_paths or [])
    if result:
        paths.extend(str(path) for path in result.get("source_paths", []))
    normalized = " ".join(str(path).replace("\\", "/").lower() for path in paths)

    if "showcase_fintrace_v1" in normalized:
        dataset = "showcase_fintrace_v1"
    elif "fintrace-redteam-v1" in normalized:
        dataset = "fintrace-redteam-v1"
    elif "red_attack_v1" in normalized:
        dataset = "red_attack_v1"
    elif "redteam_seed" in normalized or "/runtime/demo" in normalized or "\\runtime\\demo" in normalized:
        dataset = "dynamic_redteam"
    else:
        dataset = "custom_batch"

    return {
        "dataset": dataset,
        "label": dataset_label(dataset),
        "expected_prefix": DATASET_EXPECTED_PREFIX.get(dataset, ""),
    }


def case_prefix_summary(result: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in result.get("case_results", []):
        case_id = str(case.get("case_id") or "").strip()
        prefix = case_id.split("-", 1)[0] if "-" in case_id else case_id[:4]
        prefix = prefix or "UNKNOWN"
        counts[prefix] = counts.get(prefix, 0) + 1
    return counts


def validate_active_result_consistency(result: dict[str, Any], active_dataset: str | None) -> list[str]:
    warnings: list[str] = []
    prefixes = case_prefix_summary(result)
    expected_prefix = DATASET_EXPECTED_PREFIX.get(active_dataset or "")
    if expected_prefix:
        unexpected = {prefix: count for prefix, count in prefixes.items() if prefix != expected_prefix}
        if unexpected:
            warnings.append(
                f"{dataset_label(active_dataset)} 应只包含 {expected_prefix}- case，但当前批次发现 {unexpected}。请重新加载正确数据集。"
            )
    if len(prefixes) > 1:
        warnings.append(f"当前批次同时出现多个 case 前缀 {prefixes}，疑似混合批次或旧状态残留。")
    if active_dataset == SHOWCASE_DATASET_NAME:
        case_count = len(result.get("case_results", []))
        if case_count != 6:
            warnings.append(f"Showcase 演示集应为 6 个 case，当前为 {case_count} 个。")
    return warnings


def clear_review_widget_state(state: MutableMapping[str, Any]) -> list[str]:
    removed: list[str] = []
    for key in list(state.keys()):
        if key in REVIEW_WIDGET_KEYS or any(key.startswith(prefix) for prefix in REVIEW_WIDGET_PREFIXES):
            removed.append(key)
            del state[key]
    return removed


def build_showcase_storyline(result: dict[str, Any], ground_truth_path: str | Path | None) -> dict[str, Any]:
    labels = _load_labels(ground_truth_path)
    cases = {case.get("case_id"): case for case in result.get("case_results", [])}
    scenario_rows: list[dict[str, Any]] = []

    for scenario in _ordered_scenarios(labels):
        scenario_labels = [row for row in labels if row.get("scenario") == scenario]
        case_ids = [row.get("case_id") for row in scenario_labels if row.get("case_id") in cases]
        correct_count = sum(
            1
            for row in scenario_labels
            if cases.get(row.get("case_id"), {}).get("decision", {}).get("decision") == row.get("expected_decision")
        )
        representative = case_ids[0] if case_ids else ""
        scenario_rows.append(
            {
                "scenario": scenario,
                "场景": scenario_label(scenario),
                "案件数": len(case_ids),
                "命中正确": correct_count,
                "代表案件": representative,
                "展示故事": SCENARIO_STORIES.get(scenario, "批量材料中存在需要人工复核的上下文风险。"),
                "复核重点": SCENARIO_REVIEW_FOCUS.get(scenario, "核验原始材料、审批记录和字段来源。"),
            }
        )

    metrics = result.get("batch_metrics", {})
    return {
        "dataset": SHOWCASE_DATASET_NAME,
        "batch_id": result.get("batch_id", ""),
        "case_count": metrics.get("case_count", len(cases)),
        "scenario_count": len(scenario_rows),
        "scenarios": scenario_rows,
    }


def suggest_showcase_pairs(result: dict[str, Any], ground_truth_path: str | Path | None) -> list[dict[str, str]]:
    case_ids = {case.get("case_id") for case in result.get("case_results", [])}
    suggestions = [
        pair
        for pair in DEFAULT_SHOWCASE_PAIRS
        if pair["left_case_id"] in case_ids and pair["right_case_id"] in case_ids
    ]
    if suggestions:
        return suggestions

    labels = _load_labels(ground_truth_path)
    by_scenario: dict[str, list[str]] = {}
    for row in labels:
        case_id = row.get("case_id")
        if case_id in case_ids:
            by_scenario.setdefault(str(row.get("scenario") or "unknown"), []).append(case_id)

    for scenario, ids in by_scenario.items():
        if len(ids) >= 2:
            suggestions.append(
                {
                    "label": f"{scenario_label(scenario)}同类对比",
                    "left_case_id": ids[0],
                    "right_case_id": ids[1],
                    "reason": "同一风险场景下并排查看字段、规则和证据链差异。",
                }
            )
            break

    representatives = [ids[0] for ids in by_scenario.values() if ids]
    if len(representatives) >= 2:
        suggestions.append(
            {
                "label": "跨场景风险对比",
                "left_case_id": representatives[0],
                "right_case_id": representatives[1],
                "reason": "对比不同风险类型如何通过不同证据链触发人工复核。",
            }
        )
    return suggestions


def build_case_comparison(case_a: dict[str, Any], case_b: dict[str, Any]) -> dict[str, Any]:
    left = _case_summary(case_a)
    right = _case_summary(case_b)
    return {
        "left": left,
        "right": right,
        "field_rows": [
            {"字段": label, "左侧": left["fields"].get(field, ""), "右侧": right["fields"].get(field, "")}
            for field, label in CORE_FIELDS
        ],
        "rule_rows": _paired_rule_rows(case_a, case_b),
        "provenance_rows": [
            {
                "字段": field,
                "左侧值": left["fields"].get(field, ""),
                "左侧来源": _provenance_summary(case_a, field),
                "右侧值": right["fields"].get(field, ""),
                "右侧来源": _provenance_summary(case_b, field),
            }
            for field in PROVENANCE_FIELDS
        ],
    }


def _case_summary(case: dict[str, Any]) -> dict[str, Any]:
    decision = case.get("decision", {})
    fields = case.get("parsed_fields", {})
    return {
        "case_id": case.get("case_id", ""),
        "decision": decision_label(decision.get("decision")),
        "risk": risk_label(decision.get("risk_level")),
        "confidence": decision.get("confidence", ""),
        "reason": case_failure_reason(case),
        "next_action": next_action(case),
        "evidence_refs": decision.get("evidence_refs", []),
        "fields": fields,
        "rules": _rule_summaries(case),
    }


def _rule_summaries(case: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for hit in case.get("policy_hits", []):
        rows.append(
            {
                "rule_id": hit.get("rule_id", ""),
                "rule_name": hit.get("rule_name", ""),
                "rule_class": hit.get("rule_class", ""),
                "severity": hit.get("severity", ""),
                "calculation": hit.get("calculation", ""),
            }
        )
    return rows


def _paired_rule_rows(case_a: dict[str, Any], case_b: dict[str, Any]) -> list[dict[str, Any]]:
    left_rules = _rule_summaries(case_a)
    right_rules = _rule_summaries(case_b)
    max_len = max(len(left_rules), len(right_rules), 1)
    rows = []
    for idx in range(max_len):
        left = left_rules[idx] if idx < len(left_rules) else {}
        right = right_rules[idx] if idx < len(right_rules) else {}
        rows.append(
            {
                "左规则ID": left.get("rule_id", ""),
                "左规则类型": left.get("rule_class", ""),
                "左计算过程": left.get("calculation", ""),
                "右规则ID": right.get("rule_id", ""),
                "右规则类型": right.get("rule_class", ""),
                "右计算过程": right.get("calculation", ""),
            }
        )
    return rows


def _provenance_summary(case: dict[str, Any], field: str) -> str:
    sources = case.get("field_provenance", {}).get(field, [])
    if not sources:
        return "批次派生或未记录来源"
    chunks = []
    for source in sources[:2]:
        chunks.append(
            " / ".join(
                str(part)
                for part in [
                    source.get("artifact_id"),
                    source.get("locator"),
                    source.get("extraction_method"),
                ]
                if part
            )
        )
    if len(sources) > 2:
        chunks.append(f"+{len(sources) - 2} 个来源")
    return "；".join(chunks)


def _load_labels(ground_truth_path: str | Path | None) -> list[dict[str, Any]]:
    if not ground_truth_path:
        return []
    path = Path(ground_truth_path)
    if not path.exists():
        return []
    data = read_json(path)
    return list(data.get("labels", []))


def _ordered_scenarios(labels: list[dict[str, Any]]) -> list[str]:
    seen = []
    for preferred in SCENARIO_LABELS:
        if any(row.get("scenario") == preferred for row in labels):
            seen.append(preferred)
    for row in labels:
        scenario = str(row.get("scenario") or "unknown")
        if scenario not in seen:
            seen.append(scenario)
    return seen
