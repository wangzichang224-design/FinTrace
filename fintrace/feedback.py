from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from .schemas import Decision, RiskLevel, RuleClass
from .storage import ensure_dir, read_json, write_json


MEMORY_VERSION = "fintrace-human-feedback-v1"
DEFAULT_TTL_DAYS = 180
AMOUNT_TOLERANCE = 1.05
DISALLOWED_MEMORY_RULES = {
    "R001_MISSING_ORIGINAL",
    "R002_DUPLICATE_INVOICE",
    "R003_SPLIT_INVOICE",
    "R005_VENDOR_BLACKLIST",
    "R006_CROSS_PERIOD",
    "R007_SIMILAR_INVOICE_NO",
    "R008_OCR_AMOUNT_CONFLICT",
    "R009_CHAT_PROMPT_INJECTION",
}


def memory_path() -> Path:
    raw = os.getenv("FINTRACE_APPROVAL_MEMORY_PATH", "runtime/feedback/approval_memory.json")
    return Path(raw)


def load_approval_memory(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path else memory_path()
    if not target.exists():
        return {"version": MEMORY_VERSION, "items": []}
    data = read_json(target)
    data.setdefault("version", MEMORY_VERSION)
    data.setdefault("items", [])
    return data


def save_approval_memory(data: dict[str, Any], path: str | Path | None = None) -> Path:
    target = Path(path) if path else memory_path()
    ensure_dir(target.parent)
    return write_json(target, data)


def approval_memory_eligible(fields: dict[str, Any], policy_hits: list[dict[str, Any]]) -> tuple[bool, str]:
    if not fields.get("employee_id"):
        return False, "缺少员工编号，不能沉淀可复用特批。"
    if not fields.get("vendor") or not fields.get("expense_type"):
        return False, "缺少供应商或费用类型，不能形成稳定相似案例。"
    for hit in policy_hits:
        if hit.get("rule_class") == RuleClass.BLOCKING_CONTROL.value:
            return False, "命中阻断控制，人工反馈不能学习为自动通过。"
        if hit.get("rule_id") in DISALLOWED_MEMORY_RULES:
            return False, f"{hit.get('rule_id')} 属于不可自动学习的风险信号。"
    return True, "eligible"


def record_manual_approval(
    case: dict[str, Any],
    approver: str,
    reason: str,
    path: str | Path | None = None,
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> dict[str, Any]:
    fields = case.get("parsed_fields", {})
    policy_hits = case.get("policy_hits", [])
    eligible, eligibility_reason = approval_memory_eligible(fields, policy_hits)
    if not eligible:
        return {"status": "rejected", "reason": eligibility_reason}

    now = datetime.now()
    signature = make_approval_signature(fields)
    amount = safe_amount(fields.get("amount"))
    item = {
        "memory_id": f"MEM-{uuid4().hex[:10]}",
        "signature": signature,
        "signature_text": signature_text(fields),
        "source_case_id": case.get("case_id") or fields.get("reimbursement_id"),
        "approved_by": approver.strip() or "finance_reviewer",
        "approval_reason": reason.strip() or "人工复核确认业务合理。",
        "approved_at": now.isoformat(timespec="seconds"),
        "expires_at": (now + timedelta(days=ttl_days)).date().isoformat(),
        "amount_limit": round(amount * AMOUNT_TOLERANCE, 2),
        "policy_refs": [hit.get("rule_id") for hit in policy_hits],
        "status": "active",
        "hit_count": 0,
        "last_matched_at": "",
    }

    data = load_approval_memory(path)
    existing = next((row for row in data["items"] if row.get("signature") == signature and row.get("status") == "active"), None)
    if existing:
        existing["amount_limit"] = max(float(existing.get("amount_limit") or 0), item["amount_limit"])
        existing["approval_reason"] = item["approval_reason"]
        existing["approved_by"] = item["approved_by"]
        existing["approved_at"] = item["approved_at"]
        existing["expires_at"] = item["expires_at"]
        existing["source_case_id"] = item["source_case_id"]
        item = existing
    else:
        data["items"].append(item)
    save_approval_memory(data, path)
    return {"status": "recorded", "memory": item}


def find_approval_memory(
    fields: dict[str, Any],
    policy_hits: list[dict[str, Any]],
    path: str | Path | None = None,
) -> dict[str, Any] | None:
    eligible, _ = approval_memory_eligible(fields, policy_hits)
    if not eligible:
        return None
    signature = make_approval_signature(fields)
    amount = safe_amount(fields.get("amount"))
    today = datetime.now().date()
    data = load_approval_memory(path)
    candidates = []
    for item in data.get("items", []):
        if item.get("status") != "active":
            continue
        if item.get("signature") != signature:
            continue
        expires_at = datetime.fromisoformat(str(item.get("expires_at"))).date()
        if expires_at < today:
            continue
        if amount > float(item.get("amount_limit") or 0):
            continue
        candidates.append(item)
    if not candidates:
        return None
    match = sorted(candidates, key=lambda row: row.get("approved_at", ""), reverse=True)[0]
    match["hit_count"] = int(match.get("hit_count") or 0) + 1
    match["last_matched_at"] = datetime.now().isoformat(timespec="seconds")
    save_approval_memory(data, path)
    return match


def learned_approval_decision(baseline: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
    decision = dict(baseline)
    decision.update(
        {
            "decision": Decision.APPROVE_WITH_FLEX.value,
            "risk_level": RiskLevel.MEDIUM.value,
            "confidence": min(max(float(baseline.get("confidence") or 0.8), 0.82), 0.88),
            "reason": "命中历史人工通过的相似案例，系统按受控例外记忆柔性通过。",
            "recommended_action": "自动通过并保留人工反馈记忆引用；付款前可抽样复核。",
            "evidence_refs": sorted(set((baseline.get("evidence_refs") or []) + ["human_feedback_memory", memory.get("memory_id", "")])),
            "reasoning_summary": "该模式曾由财务人工复核通过，且本次未命中阻断控制或不可学习风险信号，金额未超过历史特批上限。",
            "manual_review_reason": "",
            "guardrail_status": "human_feedback_memory_approved",
            "human_feedback_memory": {
                "memory_id": memory.get("memory_id"),
                "source_case_id": memory.get("source_case_id"),
                "approved_by": memory.get("approved_by"),
                "approved_at": memory.get("approved_at"),
                "amount_limit": memory.get("amount_limit"),
                "approval_reason": memory.get("approval_reason"),
            },
        }
    )
    return decision


def make_approval_signature(fields: dict[str, Any]) -> str:
    text = signature_text(fields)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def signature_text(fields: dict[str, Any]) -> str:
    parts = [
        norm(fields.get("employee_id")),
        norm(fields.get("expense_type")),
        norm(fields.get("vendor")),
        norm(fields.get("city")),
        norm(fields.get("client_id")),
        norm(fields.get("project_code")),
    ]
    return "|".join(parts)


def norm(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", "", text)


def safe_amount(value: Any) -> float:
    try:
        text = re.sub(r"[^0-9.\-]", "", str(value).replace(",", "").replace("，", ""))
        return float(text)
    except (TypeError, ValueError):
        return 0.0
