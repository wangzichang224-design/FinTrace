from __future__ import annotations

from datetime import datetime
from typing import Any

from .policies import BLACKLISTED_VENDOR_TOKENS, expense_limit


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
    tool_calls = [
        {"tool": "get_holiday_index", "input": {"date": fields.get("expense_date"), "city": fields.get("city")}, "output": holiday},
        {"tool": "get_client_priority", "input": {"client_id": fields.get("client_id"), "client_name": fields.get("client_name")}, "output": client},
        {"tool": "get_employee_credit", "input": {"employee_id": fields.get("employee_id")}, "output": employee},
        {"tool": "get_vendor_risk", "input": {"vendor": fields.get("vendor")}, "output": vendor},
        {"tool": "get_category_benchmark", "input": {"expense_type": fields.get("expense_type")}, "output": category},
    ]
    context = {
        "holiday_index": holiday,
        "client_priority": client,
        "employee_credit": employee,
        "vendor_risk": vendor,
        "category_benchmark": category,
        "tool_calls": tool_calls,
    }
    context["context_quality"] = assess_context_quality(context)
    return context


def get_holiday_index(raw_date: Any, city: Any = None) -> dict[str, Any]:
    multiplier = 1.0
    label = "工作日"
    text = str(raw_date or "").replace("/", "-")[:10]
    source_type = "mock_calendar"
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
        source_type = "missing"
    if str(city or "") in {"三亚", "北京", "上海", "深圳"} and multiplier > 1:
        multiplier += 0.1
    return {
        "label": label,
        "multiplier": round(multiplier, 2),
        "source": "mock_holiday_price_index_v1",
        "source_type": source_type,
        "owner": "财务政策负责人",
        "refresh_frequency": "年度节假日维护，重点城市旺季指数按季度复核",
    }


def get_client_priority(client_id: Any, client_name: Any = None) -> dict[str, Any]:
    key = str(client_id or "").strip()
    if key in STRATEGIC_CLIENTS:
        return {**STRATEGIC_CLIENTS[key], "source": "mock_crm_client_tier_v1", "source_type": "mock_crm"}
    name = str(client_name or "")
    if any(token in name.lower() for token in ("strategic", "重点", "大客户", "年度框架")):
        return {
            "priority": "A",
            "multiplier": 1.2,
            "reason": "客户名称/审批记录显示战略客户属性",
            "source": "mock_crm_client_tier_v1",
            "source_type": "mock_crm_inferred",
        }
    if key or name:
        return {
            "priority": "B",
            "multiplier": 1.0,
            "reason": "CRM 未标记战略等级，按普通客户标准处理",
            "source": "mock_crm_client_tier_v1",
            "source_type": "cold_start_default",
        }
    return {
        "priority": "UNKNOWN",
        "multiplier": 1.0,
        "reason": "缺少客户编号和客户名称",
        "source": "mock_crm_client_tier_v1",
        "source_type": "missing",
    }


def get_employee_credit(employee_id: Any) -> dict[str, Any]:
    emp = str(employee_id or "").strip()
    score = EMPLOYEE_CREDIT.get(emp)
    source_type = "mock_hr_credit"
    if score is None:
        source_type = "missing" if not emp else "cold_start_default"
        score = 60
    if score >= 85:
        tier = "高信用"
    elif score >= 65:
        tier = "正常"
    else:
        tier = "受限"
    return {
        "score": score,
        "tier": tier,
        "source": "mock_employee_reimbursement_credit_v1",
        "source_type": source_type,
        "owner": "HRBP/财务共享中心",
        "refresh_frequency": "月度，根据驳回、补件、逾期和争议记录更新",
    }


def get_vendor_risk(vendor: Any) -> dict[str, Any]:
    text = str(vendor or "").lower()
    if not text:
        return {"risk": "unknown", "score": 60, "reason": "缺少供应商名称", "source": "mock_vendor_registry_v1", "source_type": "missing"}
    high_risk_tokens = {token.lower() for token in BLACKLISTED_VENDOR_TOKENS} | {"high risk", "shell company"}
    if any(token in text for token in high_risk_tokens):
        return {"risk": "high", "score": 92, "reason": "供应商注册/黑名单关键词命中", "source": "mock_vendor_registry_v1", "source_type": "mock_vendor_registry"}
    if any(token in text for token in ("咨询", "consulting", "服务", "科技服务")):
        return {"risk": "medium", "score": 55, "reason": "服务类供应商需保留业务实质证明", "source": "mock_vendor_registry_v1", "source_type": "mock_vendor_registry"}
    return {"risk": "low", "score": 20, "reason": "未发现负面信号", "source": "mock_vendor_registry_v1", "source_type": "mock_vendor_registry"}


def get_category_benchmark(expense_type: Any) -> dict[str, Any]:
    expense = str(expense_type or "").lower()
    base = expense_limit(expense)
    source_type = "mock_policy_table" if expense else "missing"
    return {
        "base_limit": base,
        "source": "mock_expense_policy_v1",
        "source_type": source_type,
        "owner": "财务制度负责人",
        "refresh_frequency": "半年或制度更新时复核",
    }


def assess_context_quality(context: dict[str, Any]) -> dict[str, Any]:
    missing_items: list[str] = []
    cold_start_items: list[str] = []
    for key in ["holiday_index", "client_priority", "employee_credit", "vendor_risk", "category_benchmark"]:
        source_type = context.get(key, {}).get("source_type", "")
        if source_type == "missing":
            missing_items.append(key)
        elif source_type == "cold_start_default":
            cold_start_items.append(key)

    critical_missing = {"employee_credit", "vendor_risk", "category_benchmark"} & set(missing_items)
    allow_flexible_approval = not critical_missing and not ("employee_credit" in cold_start_items)
    mode = "mock_ready"
    if missing_items:
        mode = "missing_context"
    elif cold_start_items:
        mode = "cold_start_default"
    return {
        "mode": mode,
        "missing_items": missing_items,
        "cold_start_items": cold_start_items,
        "allow_flexible_approval": allow_flexible_approval,
        "policy": "缺少员工信用、供应商风险或费用基准时，不允许自动柔性通过；可在静态标准内自动通过，超标案件转人工复核。",
    }
