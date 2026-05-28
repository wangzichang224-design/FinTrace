from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .schemas import Decision, PolicyHit, RiskLevel


ABSOLUTE_LIMITS = {
    "hotel": 3000.0,
    "住宿": 3000.0,
    "meal": 2000.0,
    "餐饮": 2000.0,
    "transport": 8000.0,
    "交通": 8000.0,
    "client_entertainment": 5000.0,
    "客户招待": 5000.0,
    "office": 1500.0,
    "办公": 1500.0,
}

BLACKLISTED_VENDOR_TOKENS = {"黑名单", "phantom", "空壳", "高危供应商", "异常咨询"}


def run_hard_policies(fields: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    hits: list[PolicyHit] = []

    if fields.get("has_original_invoice") is False:
        hits.append(
            PolicyHit(
                rule_id="R001_MISSING_ORIGINAL",
                rule_version="2026.05",
                severity=RiskLevel.CRITICAL.value,
                decision_hint=Decision.REJECT.value,
                input_fields={"has_original_invoice": fields.get("has_original_invoice")},
                threshold=True,
                calculation="has_original_invoice == False",
                reason="缺少发票原件，触发财务硬性拦截规则。",
            )
        )

    duplicate_count = int(fields.get("invoice_duplicate_count") or 1)
    if duplicate_count > 1:
        hits.append(
            PolicyHit(
                rule_id="R002_DUPLICATE_INVOICE",
                rule_version="2026.05",
                severity=RiskLevel.CRITICAL.value,
                decision_hint=Decision.ESCALATE_FRAUD.value,
                input_fields={"invoice_no": fields.get("invoice_no"), "duplicate_count": duplicate_count},
                threshold=1,
                calculation=f"invoice_duplicate_count={duplicate_count} > 1",
                reason="同一发票号或附件哈希在批次内重复出现，疑似重复报销。",
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
                severity=RiskLevel.HIGH.value,
                decision_hint=Decision.MANUAL_REVIEW.value,
                input_fields={"split_group_count": split_count, "split_group_total": split_total},
                threshold=round(limit * 1.2, 2),
                calculation=f"split_total={split_total} > category_limit*1.2={round(limit * 1.2, 2)}",
                reason="同员工、同供应商、同日期多笔报销累计超阈值，疑似拆分发票规避审批。",
            )
        )

    amount = float(fields.get("amount") or 0)
    if amount > limit:
        hits.append(
            PolicyHit(
                rule_id="R004_ABSOLUTE_LIMIT",
                rule_version="2026.05",
                severity=RiskLevel.HIGH.value,
                decision_hint=Decision.MANUAL_REVIEW.value,
                input_fields={"amount": amount, "expense_type": fields.get("expense_type")},
                threshold=limit,
                calculation=f"amount={amount} > absolute_limit={limit}",
                reason="金额超过静态费用标准，需结合节假日、客户等级和员工信用做柔性判断。",
            )
        )

    vendor = str(fields.get("vendor") or "").lower()
    if any(token.lower() in vendor for token in BLACKLISTED_VENDOR_TOKENS):
        hits.append(
            PolicyHit(
                rule_id="R005_VENDOR_BLACKLIST",
                rule_version="2026.05",
                severity=RiskLevel.CRITICAL.value,
                decision_hint=Decision.ESCALATE_FRAUD.value,
                input_fields={"vendor": fields.get("vendor")},
                threshold="not in blacklist",
                calculation="vendor token matched blacklist",
                reason="供应商命中黑名单或高危关键词，需升级反舞弊复核。",
            )
        )

    if is_cross_period(fields.get("expense_date")):
        hits.append(
            PolicyHit(
                rule_id="R006_CROSS_PERIOD",
                rule_version="2026.05",
                severity=RiskLevel.MEDIUM.value,
                decision_hint=Decision.MANUAL_REVIEW.value,
                input_fields={"expense_date": fields.get("expense_date")},
                threshold="90 days",
                calculation="expense_date is older than reimbursement window",
                reason="费用发生日期超过 90 天报销窗口，需人工确认跨期原因。",
            )
        )

    similar_invoice_count = int(fields.get("similar_invoice_count") or 1)
    if similar_invoice_count >= 2:
        hits.append(
            PolicyHit(
                rule_id="R007_SIMILAR_INVOICE_NO",
                rule_version="2026.05",
                severity=RiskLevel.MEDIUM.value,
                decision_hint=Decision.MANUAL_REVIEW.value,
                input_fields={
                    "invoice_no": fields.get("invoice_no"),
                    "similar_invoice_count": similar_invoice_count,
                    "similar_invoice_peers": fields.get("similar_invoice_peers", []),
                },
                threshold=1,
                calculation=f"similar_invoice_count={similar_invoice_count} >= 2",
                reason="同员工/同供应商/同日出现高度相似发票号，需排查连号、改号或录入污染。",
            )
        )

    route = route_from_policy_hits(hits)
    return [h.to_dict() for h in hits], route


def expense_limit(expense_type: str) -> float:
    for key, value in ABSOLUTE_LIMITS.items():
        if key.lower() in expense_type:
            return value
    return 3000.0


def route_from_policy_hits(hits: list[PolicyHit]) -> str:
    hints = {h.decision_hint for h in hits if h.matched}
    if Decision.ESCALATE_FRAUD.value in hints:
        return "fraud_escalation"
    if Decision.REJECT.value in hints:
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
