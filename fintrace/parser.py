from __future__ import annotations

import re
from typing import Any

from .policy_config import showcase_risk_keywords
from .schemas import FieldSource


FIELD_ALIASES = {
    "reimbursement_id": ["reimbursement_id", "claim_id", "报销单号", "单据编号", "申请单号"],
    "employee_id": ["employee_id", "员工ID", "员工编号", "工号"],
    "employee_name": ["employee_name", "员工姓名", "报销人", "申请人"],
    "department": ["department", "部门", "所属部门"],
    "cost_center": ["cost_center", "成本中心", "费用中心"],
    "project_code": ["project_code", "项目号", "项目编码"],
    "approver": ["approver", "审批人", "直属审批人"],
    "approval_status": ["approval_status", "审批状态"],
    "expense_date": ["expense_date", "费用日期", "发生日期", "消费日期"],
    "expense_time": ["expense_time", "费用时间", "发生时间", "消费时间"],
    "submitted_at": ["submitted_at", "提交日期", "报销日期"],
    "expense_type": ["expense_type", "费用类型", "报销类型"],
    "amount": ["amount", "金额", "价税合计", "报销金额"],
    "currency": ["currency", "币种"],
    "city": ["city", "城市", "发生城市"],
    "vendor": ["vendor", "供应商", "商户", "销售方名称"],
    "vendor_tax_no": ["vendor_tax_no", "销售方税号", "供应商税号"],
    "invoice_no": ["invoice_no", "发票号", "发票号码"],
    "invoice_code": ["invoice_code", "发票代码"],
    "invoice_hash": ["invoice_hash", "发票hash", "附件hash", "单据hash"],
    "invoice_type": ["invoice_type", "发票类型", "票据类型"],
    "client_id": ["client_id", "客户ID", "客户编号"],
    "client_name": ["client_name", "客户名称", "客户"],
    "has_original_invoice": ["has_original_invoice", "是否有原件", "发票原件", "原件状态"],
    "description": ["description", "摘要", "备注", "说明", "事由"],
}

TEXT_KEY_ALIASES = {
    alias.lower(): canonical
    for canonical, aliases in FIELD_ALIASES.items()
    for alias in [canonical, *aliases]
}

REQUIRED_FIELDS = ["reimbursement_id", "employee_id", "expense_type", "amount", "invoice_no"]


def parse_case_fields(
    raw_artifacts: list[dict[str, Any]],
    batch_features: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    fields: dict[str, Any] = {}
    provenance: dict[str, list[dict[str, Any]]] = {}
    errors: list[dict[str, Any]] = []

    for artifact in raw_artifacts:
        for row in artifact.get("records", []):
            for canonical, aliases in FIELD_ALIASES.items():
                value = first_present(row, aliases)
                if value not in (None, "") and canonical not in fields:
                    fields[canonical] = normalize_field(canonical, value)
                    provenance.setdefault(canonical, []).append(
                        FieldSource(
                            field_name=canonical,
                            value=fields[canonical],
                            artifact_id=artifact["artifact_id"],
                            source_path=artifact["path"],
                            locator=f"row={artifact.get('metadata', {}).get('row_number', 1)}",
                            confidence=0.99,
                            extraction_method="erp_structured",
                        ).to_dict()
                    )

    combined_text = "\n".join(a.get("text", "") for a in raw_artifacts if a.get("text"))
    if combined_text:
        if detect_prompt_injection(combined_text):
            fields["prompt_injection_detected"] = True
            artifact = next((a for a in raw_artifacts if a.get("text")), raw_artifacts[0])
            provenance.setdefault("prompt_injection_detected", []).append(
                FieldSource(
                    field_name="prompt_injection_detected",
                    value=True,
                    artifact_id=artifact["artifact_id"],
                    source_path=artifact["path"],
                    locator=find_prompt_injection_locator(combined_text),
                    confidence=0.82,
                    extraction_method="chat_guardrail_regex",
                ).to_dict()
            )
        mismatch = detect_purpose_mismatch(combined_text, fields)
        if mismatch:
            fields["purpose_mismatch_detected"] = True
            fields["purpose_mismatch_terms"] = mismatch
            artifact = next((a for a in raw_artifacts if a.get("text")), raw_artifacts[0])
            provenance.setdefault("purpose_mismatch_detected", []).append(
                FieldSource(
                    field_name="purpose_mismatch_detected",
                    value=True,
                    artifact_id=artifact["artifact_id"],
                    source_path=artifact["path"],
                    locator=f"text_span={','.join(mismatch)}",
                    confidence=0.84,
                    extraction_method="purpose_item_consistency_regex",
                ).to_dict()
            )
        extracted = parse_text_fields(combined_text)
        if "amount" in extracted and "amount" in fields:
            text_amount = safe_float(extracted["amount"])
            erp_amount = safe_float(fields["amount"])
            if erp_amount and abs(text_amount - erp_amount) / max(erp_amount, 1) > 0.2:
                fields["amount_conflict_detected"] = True
                fields["attachment_amount"] = text_amount
                errors.append(
                    {
                        "category": "字段冲突",
                        "field": "amount",
                        "message": f"附件金额 {text_amount} 与 ERP 金额 {erp_amount} 差异超过 20%",
                    }
                )
        for key, value in extracted.items():
            if value not in (None, "") and key not in fields:
                fields[key] = normalize_field(key, value)
                artifact = next((a for a in raw_artifacts if a.get("text")), raw_artifacts[0])
                provenance.setdefault(key, []).append(
                    FieldSource(
                        field_name=key,
                        value=fields[key],
                        artifact_id=artifact["artifact_id"],
                        source_path=artifact["path"],
                        locator=find_text_locator(combined_text, str(value)),
                        confidence=0.78,
                        extraction_method=artifact.get("metadata", {}).get("extraction_method", "text_regex"),
                    ).to_dict()
                )

    fields.setdefault("currency", "CNY")
    fields["attachment_count"] = max(0, len(raw_artifacts) - 1)
    fields.update(batch_features or {})

    for field in REQUIRED_FIELDS:
        if field not in fields or fields[field] in (None, ""):
            errors.append({"category": "字段缺失", "field": field, "message": f"缺少关键字段：{field}"})

    if "amount" not in fields or fields.get("amount") in (None, ""):
        fields["amount_anomaly_detected"] = True
        errors.append({"category": "金额异常", "field": "amount", "message": "金额缺失，需人工确认。"})
    else:
        amount_value = safe_float(fields.get("amount"))
        if amount_value <= 0:
            fields["amount_anomaly_detected"] = True
            errors.append({"category": "金额异常", "field": "amount", "message": f"金额为 {amount_value}，需人工确认。"})

    return fields, provenance, errors


def first_present(row: dict[str, Any], aliases: list[str]) -> Any:
    lowered = {str(k).strip().lower(): k for k in row}
    for alias in aliases:
        if alias in row:
            return row[alias]
        hit = lowered.get(alias.lower())
        if hit is not None:
            return row[hit]
    return None


def normalize_field(key: str, value: Any) -> Any:
    if key == "amount":
        return safe_float(value)
    if key == "has_original_invoice":
        return parse_bool(value)
    if key in {
        "invoice_no",
        "invoice_code",
        "invoice_hash",
        "invoice_type",
        "employee_id",
        "employee_name",
        "reimbursement_id",
        "expense_type",
        "vendor",
        "vendor_tax_no",
        "client_id",
        "client_name",
        "department",
        "cost_center",
        "project_code",
        "approver",
        "approval_status",
        "city",
        "currency",
    }:
        return str(value).strip()
    return value


def parse_text_fields(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for line in text.splitlines():
        if ":" not in line and "：" not in line:
            continue
        key, value = re.split(r"[:：]", line, maxsplit=1)
        canonical = TEXT_KEY_ALIASES.get(key.strip().lower())
        if canonical and value.strip() and canonical not in out:
            out[canonical] = value.strip()

    fallback_patterns = {
        "reimbursement_id": r"(?:报销单号|单据编号|reimbursement_id|claim_id)\s*[:：]\s*([A-Za-z0-9_-]+)",
        "employee_id": r"(?:员工ID|员工编号|工号|employee_id)\s*[:：]\s*([A-Za-z0-9_-]+)",
        "employee_name": r"(?:员工姓名|报销人|申请人|employee_name)\s*[:：]\s*([\u4e00-\u9fffA-Za-z ]+)",
        "expense_type": r"(?:费用类型|报销类型|expense_type)\s*[:：]\s*([\u4e00-\u9fffA-Za-z_ -]+)",
        "amount": r"(?:价税合计|报销金额|金额|amount)\s*[:：￥¥\s]*([0-9,]+(?:\.[0-9]+)?)",
        "city": r"(?:城市|发生城市|city)\s*[:：]\s*([\u4e00-\u9fffA-Za-z]+)",
        "vendor": r"(?:供应商|商户|销售方名称|vendor)\s*[:：]\s*([\u4e00-\u9fffA-Za-z0-9()（） -]+)",
        "invoice_no": r"(?:发票号|发票号码|invoice_no)\s*[:：]\s*([A-Za-z0-9_-]+)",
        "client_id": r"(?:客户ID|客户编号|client_id)\s*[:：]\s*([A-Za-z0-9_-]+)",
        "client_name": r"(?:客户名称|客户|client_name)\s*[:：]\s*([\u4e00-\u9fffA-Za-z0-9()（） -]+)",
        "expense_date": r"(?:费用日期|发生日期|消费日期|expense_date)\s*[:：]\s*([0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2})",
        "expense_time": r"(?:费用时间|发生时间|消费时间|expense_time)\s*[:：]\s*([0-9]{1,2}[:：][0-9]{1,2})",
        "has_original_invoice": r"(?:是否有原件|发票原件|原件状态|has_original_invoice)\s*[:：]\s*(true|false|yes|no|是|否|有|无|原件齐全)",
    }
    for key, pattern in fallback_patterns.items():
        if key in out:
            continue
        match = re.search(pattern, text, re.I)
        if match:
            out[key] = match.group(1).strip()
    if "amount" not in out:
        amount = extract_amount_near_label(text)
        if amount:
            out["amount"] = amount
    return out


def extract_amount_near_label(text: str) -> str:
    amount_pattern = r"(?:RMB|CNY|¥|￥)?\s*([0-9]{1,3}(?:[,，][0-9]{3})+(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)"
    labels = ["amount", "total", "金额", "价税合计", "报销金额", "合计金额", "实际发生额"]
    for label in labels:
        pattern = rf"{re.escape(label)}\s*[:：]?\s*(?:人民币|RMB|CNY|¥|￥)?\s*{amount_pattern}"
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1)
    return ""


def detect_prompt_injection(text: str) -> bool:
    lowered = text.lower()
    risky_phrases = [
        "ignore all",
        "ignore previous",
        "bypass policy",
        "override policy",
        "approve immediately",
        "忽略所有",
        "忽略财务",
        "绕过制度",
        "跳过审核",
        "立即批准",
        "直接通过",
    ]
    return any(phrase in lowered for phrase in risky_phrases)


def find_prompt_injection_locator(text: str) -> str:
    for phrase in ("忽略所有", "绕过制度", "跳过审核", "立即批准", "ignore all", "bypass policy"):
        pos = text.lower().find(phrase.lower())
        if pos >= 0:
            return f"text_span={pos}:{pos + len(phrase)}"
    return "text_span=prompt_injection_phrase"


def detect_purpose_mismatch(text: str, fields: dict[str, Any]) -> list[str]:
    rules = showcase_risk_keywords()
    purpose_keywords = rules.get("business_purpose_keywords", [])
    suspicious_keywords = rules.get("non_business_item_keywords", [])
    purpose_text = " ".join(
        [
            str(fields.get("description") or ""),
            str(fields.get("expense_type") or ""),
            text,
        ]
    ).lower()
    text_lower = text.lower()
    has_business_purpose = any(keyword.lower() in purpose_text for keyword in purpose_keywords)
    suspicious_hits = [keyword for keyword in suspicious_keywords if keyword.lower() in text_lower]
    if has_business_purpose and suspicious_hits:
        return suspicious_hits
    return []


def find_text_locator(text: str, value: str) -> str:
    pos = text.find(value)
    if pos < 0:
        return "text_span=unknown"
    return f"text_span={pos}:{pos + len(value)}"


def safe_float(value: Any) -> float:
    try:
        text = str(value).replace(",", "").replace("，", "")
        text = re.sub(r"(?i)\b(rmb|cny)\b", "", text)
        text = re.sub(r"[^0-9.\-]", "", text)
        return round(float(text), 2)
    except (TypeError, ValueError):
        return 0.0


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "是", "有", "原件", "原件齐全", "yes - original"}
