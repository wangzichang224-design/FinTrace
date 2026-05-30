from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .policy_config import (
    approval_complete_statuses,
    approval_incomplete_statuses,
    blacklisted_vendor_tokens,
    expense_limits,
    normalize_status,
)
from .schemas import Decision, PolicyHit, RiskLevel, RuleClass


ABSOLUTE_LIMITS = expense_limits()
BLACKLISTED_VENDOR_TOKENS = blacklisted_vendor_tokens()


def run_hard_policies(fields: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Return blocking controls and contextual risk signals.

    Only blocking_control rules can directly reject or escalate. Contextual risk
    signals continue to the local decision model / LLM guardrail layer.
    """
    hits: list[PolicyHit] = []

    if fields.get("has_original_invoice") is False:
        hits.append(
            PolicyHit(
                rule_id="R001_MISSING_ORIGINAL",
                rule_version="2026.05",
                rule_class=RuleClass.BLOCKING_CONTROL.value,
                severity=RiskLevel.CRITICAL.value,
                decision_hint=Decision.REJECT.value,
                input_fields={"has_original_invoice": fields.get("has_original_invoice")},
                threshold=True,
                calculation="has_original_invoice == False",
                reason="缺少发票原件，属于可离线判定的阻断控制。",
            )
        )

    duplicate_count = int(fields.get("invoice_duplicate_count") or 1)
    if duplicate_count > 1:
        hits.append(
            PolicyHit(
                rule_id="R002_DUPLICATE_INVOICE",
                rule_version="2026.05",
                rule_class=RuleClass.BLOCKING_CONTROL.value,
                severity=RiskLevel.CRITICAL.value,
                decision_hint=Decision.ESCALATE_FRAUD.value,
                input_fields={"invoice_no": fields.get("invoice_no"), "duplicate_count": duplicate_count},
                threshold=1,
                calculation=f"invoice_duplicate_count={duplicate_count} > 1",
                reason="同一发票号或附件哈希在批次内精确重复，疑似重复报销。",
            )
        )

    split_count = int(fields.get("split_group_count") or 1)
    split_total = float(fields.get("split_group_total") or 0)
    expense_type = str(fields.get("expense_type") or "").lower()
    limit = expense_limit(expense_type)
    if split_count >= 2 and split_total > limit * 1.2:
        hits.append(
            PolicyHit(
                rule_id="R003_SPLIT_INVOICE",
                rule_version="2026.05",
                rule_class=RuleClass.CONTEXTUAL_RISK_SIGNAL.value,
                severity=RiskLevel.HIGH.value,
                decision_hint=Decision.MANUAL_REVIEW.value,
                input_fields={"split_group_count": split_count, "split_group_total": split_total},
                threshold=round(limit * 1.2, 2),
                calculation=f"split_total={split_total} > category_limit*1.2={round(limit * 1.2, 2)}",
                reason="拆票需要业务背景判断，因此作为上下文风险信号进入人工复核/推理链。",
            )
        )

    approval_status = normalize_status(fields.get("approval_status"))
    if approval_status not in approval_complete_statuses() or approval_status in approval_incomplete_statuses():
        hits.append(
            PolicyHit(
                rule_id="R010_APPROVAL_INCOMPLETE",
                rule_version="2026.05",
                rule_class=RuleClass.CONTEXTUAL_RISK_SIGNAL.value,
                severity=RiskLevel.HIGH.value,
                decision_hint=Decision.MANUAL_REVIEW.value,
                input_fields={"approval_status": fields.get("approval_status")},
                threshold="approval_status in approved/complete statuses",
                calculation=f"approval_status={fields.get('approval_status')!r} not approved",
                reason="ERP 审批状态未完成或缺失，需确认业务审批链路完整后才能进入付款。",
            )
        )

    amount = parse_policy_amount(fields.get("amount"))
    if amount is None or amount <= 0:
        hits.append(
            PolicyHit(
                rule_id="R011_ABNORMAL_AMOUNT",
                rule_version="2026.05",
                rule_class=RuleClass.CONTEXTUAL_RISK_SIGNAL.value,
                severity=RiskLevel.HIGH.value,
                decision_hint=Decision.MANUAL_REVIEW.value,
                input_fields={"amount": fields.get("amount")},
                threshold="amount > 0",
                calculation=f"amount={fields.get('amount')!r}",
                reason="金额缺失、无法解析、为 0 或为负数，需人工确认是否为空单、测试单或录入错误。",
            )
        )
        amount = 0.0
    if amount > limit:
        hits.append(
            PolicyHit(
                rule_id="R004_ABSOLUTE_LIMIT",
                rule_version="2026.05",
                rule_class=RuleClass.CONTEXTUAL_RISK_SIGNAL.value,
                severity=RiskLevel.HIGH.value,
                decision_hint=Decision.MANUAL_REVIEW.value,
                input_fields={"amount": amount, "expense_type": fields.get("expense_type")},
                threshold=limit,
                calculation=f"amount={amount} > absolute_limit={limit}",
                reason="金额超标不是硬拒绝，需要结合节假日、客户等级和员工信用做柔性判断。",
            )
        )

    vendor = str(fields.get("vendor") or "").lower()
    if any(token.lower() in vendor for token in blacklisted_vendor_tokens()):
        hits.append(
            PolicyHit(
                rule_id="R005_VENDOR_BLACKLIST",
                rule_version="2026.05",
                rule_class=RuleClass.BLOCKING_CONTROL.value,
                severity=RiskLevel.CRITICAL.value,
                decision_hint=Decision.ESCALATE_FRAUD.value,
                input_fields={"vendor": fields.get("vendor")},
                threshold="not in blacklist",
                calculation="vendor token matched blacklist",
                reason="供应商命中黑名单或高危关键词，属于阻断控制。",
            )
        )

    if is_cross_period(fields.get("expense_date")):
        hits.append(
            PolicyHit(
                rule_id="R006_CROSS_PERIOD",
                rule_version="2026.05",
                rule_class=RuleClass.CONTEXTUAL_RISK_SIGNAL.value,
                severity=RiskLevel.MEDIUM.value,
                decision_hint=Decision.MANUAL_REVIEW.value,
                input_fields={"expense_date": fields.get("expense_date")},
                threshold="90 days",
                calculation="expense_date is older than reimbursement window",
                reason="跨期长短和业务原因不同，作为上下文风险信号而不是硬拒绝。",
            )
        )

    similar_invoice_count = int(fields.get("similar_invoice_count") or 1)
    if similar_invoice_count >= 2:
        hits.append(
            PolicyHit(
                rule_id="R007_SIMILAR_INVOICE_NO",
                rule_version="2026.05",
                rule_class=RuleClass.CONTEXTUAL_RISK_SIGNAL.value,
                severity=RiskLevel.MEDIUM.value,
                decision_hint=Decision.MANUAL_REVIEW.value,
                input_fields={
                    "invoice_no": fields.get("invoice_no"),
                    "similar_invoice_count": similar_invoice_count,
                    "similar_invoice_peers": fields.get("similar_invoice_peers", []),
                },
                threshold=1,
                calculation=f"similar_invoice_count={similar_invoice_count} >= 2",
                reason="相似发票号可能是连号、改号或录入污染，需要上下文复核。",
            )
        )

    if fields.get("amount_conflict_detected"):
        hits.append(
            PolicyHit(
                rule_id="R008_OCR_AMOUNT_CONFLICT",
                rule_version="2026.05",
                rule_class=RuleClass.CONTEXTUAL_RISK_SIGNAL.value,
                severity=RiskLevel.HIGH.value,
                decision_hint=Decision.MANUAL_REVIEW.value,
                input_fields={
                    "amount": fields.get("amount"),
                    "attachment_amount": fields.get("attachment_amount"),
                },
                threshold="20% difference",
                calculation="abs(attachment_amount - erp_amount) / erp_amount > 20%",
                reason="附件 OCR 金额与 ERP 金额差异较大，需要回到字段溯源视图人工修正。",
            )
        )

    if fields.get("prompt_injection_detected"):
        hits.append(
            PolicyHit(
                rule_id="R009_CHAT_PROMPT_INJECTION",
                rule_version="2026.05",
                rule_class=RuleClass.CONTEXTUAL_RISK_SIGNAL.value,
                severity=RiskLevel.HIGH.value,
                decision_hint=Decision.MANUAL_REVIEW.value,
                input_fields={"prompt_injection_detected": True},
                threshold="no prompt override language",
                calculation="chat approval text contains prompt-injection or policy-bypass language",
                reason="审批聊天中出现越权诱导或提示注入话术，需人工确认这不是有效审批意见。",
            )
        )

    if fields.get("time_space_conflict_detected"):
        hits.append(
            PolicyHit(
                rule_id="R012_TIME_SPACE_CONFLICT",
                rule_version="2026.05",
                rule_class=RuleClass.CONTEXTUAL_RISK_SIGNAL.value,
                severity=RiskLevel.HIGH.value,
                decision_hint=Decision.MANUAL_REVIEW.value,
                input_fields={
                    "city": fields.get("city"),
                    "expense_date": fields.get("expense_date"),
                    "expense_time": fields.get("expense_time"),
                    "time_space_conflict_peers": fields.get("time_space_conflict_peers", []),
                    "time_space_conflict_detail": fields.get("time_space_conflict_detail", ""),
                },
                threshold="same employee/date, distance >= 1200km, time gap <= 6h, no flight evidence",
                calculation=str(fields.get("time_space_conflict_detail", "")),
                reason="同一员工同日出现远距离城市消费，且批次内未发现机票/航班证据，需人工核验行程真实性。",
            )
        )

    if fields.get("purpose_mismatch_detected"):
        hits.append(
            PolicyHit(
                rule_id="R013_PURPOSE_ATTACHMENT_MISMATCH",
                rule_version="2026.05",
                rule_class=RuleClass.CONTEXTUAL_RISK_SIGNAL.value,
                severity=RiskLevel.HIGH.value,
                decision_hint=Decision.MANUAL_REVIEW.value,
                input_fields={
                    "description": fields.get("description"),
                    "expense_type": fields.get("expense_type"),
                    "purpose_mismatch_terms": fields.get("purpose_mismatch_terms", []),
                },
                threshold="business purpose text should match attachment item substance",
                calculation=f"purpose_mismatch_terms={fields.get('purpose_mismatch_terms', [])}",
                reason="报销事由为客户拜访/业务沟通，但附件出现游戏机、礼品卡等非业务消费关键词，需人工核验业务实质。",
            )
        )

    route = route_from_policy_hits(hits)
    return [h.to_dict() for h in hits], route


def expense_limit(expense_type: str) -> float:
    for key, value in expense_limits().items():
        if key.lower() in expense_type:
            return value
    return 3000.0


def parse_policy_amount(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def route_from_policy_hits(hits: list[PolicyHit]) -> str:
    blocking_hints = {
        h.decision_hint
        for h in hits
        if h.matched and h.rule_class == RuleClass.BLOCKING_CONTROL.value
    }
    if Decision.ESCALATE_FRAUD.value in blocking_hints:
        return "fraud_escalation"
    if Decision.REJECT.value in blocking_hints:
        return "reject"
    return "need_context"


def is_cross_period(raw: Any) -> bool:
    if not raw:
        return False
    text = str(raw).replace("/", "-")[:10]
    try:
        dt = datetime.fromisoformat(text).date()
    except ValueError:
        return False
    anchor = date(2026, 5, 28)
    return (anchor - dt).days > 90
