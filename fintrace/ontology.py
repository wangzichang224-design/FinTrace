from __future__ import annotations

from datetime import datetime
from typing import Any

from .policies import expense_limit


STRATEGIC_CLIENTS = {
    "C001": {"priority": "S", "multiplier": 1.35, "reason": "年度框架客户/战略大客户"},
    "C009": {"priority": "A", "multiplier": 1.2, "reason": "高续约价值客户"},
}

EMPLOYEE_CREDIT = {
    "E001": 92,
    "E002": 84,
    "E003": 76,
    "E004": 48,
    "E005": 63,
    "E006": 88,
    "E007": 71,
    "E008": 57,
}


def build_context(fields: dict[str, Any]) -> dict[str, Any]:
    holiday = get_holiday_index(fields.get("expense_date"), fields.get("city"))
    client = get_client_priority(fields.get("client_id"), fields.get("client_name"))
    employee = get_employee_credit(fields.get("employee_id"))
    vendor = get_vendor_risk(fields.get("vendor"))
    category = get_category_benchmark(fields.get("expense_type"))
    return {
        "holiday_index": holiday,
        "client_priority": client,
        "employee_credit": employee,
        "vendor_risk": vendor,
        "category_benchmark": category,
        "tool_calls": [
            {"tool": "get_holiday_index", "input": {"date": fields.get("expense_date"), "city": fields.get("city")}, "output": holiday},
            {"tool": "get_client_priority", "input": {"client_id": fields.get("client_id"), "client_name": fields.get("client_name")}, "output": client},
            {"tool": "get_employee_credit", "input": {"employee_id": fields.get("employee_id")}, "output": employee},
            {"tool": "get_vendor_risk", "input": {"vendor": fields.get("vendor")}, "output": vendor},
            {"tool": "get_category_benchmark", "input": {"expense_type": fields.get("expense_type")}, "output": category},
        ],
    }


def get_holiday_index(raw_date: Any, city: Any = None) -> dict[str, Any]:
    multiplier = 1.0
    label = "工作日"
    text = str(raw_date or "").replace("/", "-")[:10]
    try:
        dt = datetime.fromisoformat(text)
        if (dt.month == 5 and 1 <= dt.day <= 5) or (dt.month == 10 and 1 <= dt.day <= 7):
            multiplier = 1.55
            label = "法定长假"
        elif dt.weekday() >= 5:
            multiplier = 1.15
            label = "周末"
    except ValueError:
        label = "日期不可识别"
    if str(city or "") in {"三亚", "北京", "上海", "深圳"} and multiplier > 1:
        multiplier += 0.1
    return {"label": label, "multiplier": round(multiplier, 2), "source": "mock_holiday_price_index_v1"}


def get_client_priority(client_id: Any, client_name: Any = None) -> dict[str, Any]:
    key = str(client_id or "").strip()
    if key in STRATEGIC_CLIENTS:
        return {**STRATEGIC_CLIENTS[key], "source": "mock_crm_client_tier_v1"}
    name = str(client_name or "")
    if any(token in name.lower() for token in ("strategic", "重点", "大客户", "年度框架")):
        return {"priority": "A", "multiplier": 1.2, "reason": "客户名称/审批记录显示战略客户属性", "source": "mock_crm_client_tier_v1"}
    return {"priority": "B", "multiplier": 1.0, "reason": "普通客户标准", "source": "mock_crm_client_tier_v1"}


def get_employee_credit(employee_id: Any) -> dict[str, Any]:
    emp = str(employee_id or "").strip()
    score = EMPLOYEE_CREDIT.get(emp)
    if score is None:
        score = 65 + (sum(ord(c) for c in emp) % 25 if emp else 0)
    if score >= 85:
        tier = "高信用"
    elif score >= 65:
        tier = "正常"
    else:
        tier = "受限"
    return {"score": score, "tier": tier, "source": "mock_employee_reimbursement_credit_v1"}


def get_vendor_risk(vendor: Any) -> dict[str, Any]:
    text = str(vendor or "").lower()
    if any(token in text for token in ("phantom", "空壳", "黑名单", "高危", "异常咨询")):
        return {"risk": "high", "score": 92, "reason": "供应商注册/黑名单关键词命中", "source": "mock_vendor_registry_v1"}
    if any(token in text for token in ("咨询", "consulting", "服务", "科技服务")):
        return {"risk": "medium", "score": 55, "reason": "服务类供应商需保留业务实质证明", "source": "mock_vendor_registry_v1"}
    return {"risk": "low", "score": 20, "reason": "未发现负面信号", "source": "mock_vendor_registry_v1"}


def get_category_benchmark(expense_type: Any) -> dict[str, Any]:
    expense = str(expense_type or "").lower()
    base = expense_limit(expense)
    return {"base_limit": base, "source": "mock_expense_policy_v1"}
