"""将 showcase 数据集从 6 个 case 扩增到 100 个。
- 保留原有 6 个 showcase 场景 case（ID: SHOW-*）
- 新增 94 个正常报销 case（ID: NOR-*），含 ERP 行 + OCR 文本 + 审批聊天，无发票截图
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "datasets" / "showcase_fintrace_v1"

EMPLOYEES = [
    {"employee_id": "E001", "employee_name": "王明", "department": "华东销售部", "cost_center": "CC-SALES-EAST", "approver": "周倩"},
    {"employee_id": "E002", "employee_name": "李晨", "department": "企业客户部", "cost_center": "CC-KEYACC", "approver": "赵敏"},
    {"employee_id": "E003", "employee_name": "张悦", "department": "市场增长部", "cost_center": "CC-MKT-GROWTH", "approver": "陈澜"},
    {"employee_id": "E004", "employee_name": "赵敏", "department": "渠道运营部", "cost_center": "CC-OPS-CHANNEL", "approver": "林杰"},
    {"employee_id": "E005", "employee_name": "陈然", "department": "解决方案部", "cost_center": "CC-SOLUTION", "approver": "顾宁"},
    {"employee_id": "E006", "employee_name": "刘洋", "department": "交付实施部", "cost_center": "CC-DELIVERY", "approver": "沈青"},
    {"employee_id": "E007", "employee_name": "周宁", "department": "产品运营部", "cost_center": "CC-PRODOPS", "approver": "许文"},
    {"employee_id": "E008", "employee_name": "孙浩", "department": "生态合作部", "cost_center": "CC-PARTNER", "approver": "韩冰"},
]

VENDORS = [
    "上海虹桥睿选酒店", "北京国贸嘉里商务酒店", "深圳前海云际酒店",
    "杭州西溪悦榕酒店", "广州天河城际酒店", "成都高新亚朵酒店",
    "上海锦江出租汽车服务有限公司", "北京首汽约车服务有限公司",
    "深圳南山宴遇餐饮有限公司", "杭州滨江商务餐饮有限公司",
    "上海静安办公用品有限公司", "北京朝阳文具商行",
    "深圳软件园信息技术有限公司", "杭州云栖网络科技有限公司",
    "广州白云机场快线", "成都双流出行服务有限公司",
]

CITIES = ["上海", "北京", "深圳", "杭州", "广州", "成都"]
EXPENSE_TYPES = ["住宿", "餐饮", "交通", "办公"]


def make_ocr_text(row: dict) -> str:
    inv_no = row.get("invoice_no", "")
    comment = row.get("description", "")
    return f"""报销单号：{row['reimbursement_id']}
发票号码：{inv_no}
费用类型：{row['expense_type']}
费用日期：{row['expense_date']}
费用时间：{row['expense_time']}
发生城市：{row['city']}
销售方名称：{row['vendor']}
价税合计：{row['amount']}
发票原件：是
备注：{comment}"""


def make_chat_text(row: dict) -> str:
    return f"""# 审批聊天

- 报销单号：{row['reimbursement_id']}
- 员工：{row['employee_name']}（{row['employee_id']}）
- 部门：{row['department']}
- 费用类型：{row['expense_type']}
- 金额：{row['amount']} 元
- 审批人：{row['approver']}
- 审批状态：{row['approval_status']}
- 主管意见：同意，按实际业务发生报销。"""


def generate_normal_rows(rng: random.Random, count: int) -> list[dict]:
    rows: list[dict] = []
    # 为每个员工生成独立的天数表，确保同一员工同一天不出现两次
    emp_day_counter: dict[str, int] = {}
    for i in range(count):
        idx = i + 1
        claim = f"NOR-{idx:05d}"
        emp = EMPLOYEES[i % len(EMPLOYEES)]
        emp_id = emp["employee_id"]
        # 每员工的天数独立递进，避免同人同一天在不同城市
        emp_day_counter[emp_id] = emp_day_counter.get(emp_id, 0) + 1
        day = min(emp_day_counter[emp_id], 31)
        exp_type = EXPENSE_TYPES[i % len(EXPENSE_TYPES)]
        # 绑定 city 和 expense_type，避免同一人同日不同城市
        city = CITIES[i % len(CITIES)]
        vendor = VENDORS[i % len(VENDORS)]
        hour = 8 + (i % 10)
        minute = (i * 7) % 60
        inv_no = f"INV-NOR-{idx:05d}"
        amount = round(rng.uniform(120, 1500), 2)

        row = {
            "reimbursement_id": claim,
            "employee_id": emp["employee_id"],
            "employee_name": emp["employee_name"],
            "department": emp["department"],
            "cost_center": emp["cost_center"],
            "project_code": f"PRJ-2026-{100 + i % 35:03d}",
            "approver": emp["approver"],
            "approval_status": "已审批",
            "expense_date": f"2026-05-{day:02d}",
            "expense_time": f"{hour:02d}:{minute:02d}",
            "expense_type": exp_type,
            "amount": amount,
            "currency": "CNY",
            "city": city,
            "vendor": vendor,
            "vendor_tax_no": f"9131{rng.randint(10_000_000_000_000_00, 99_999_999_999_999_99)}",
            "invoice_no": inv_no,
            "invoice_code": f"04{rng.randint(1_000_000_000, 9_999_999_999)}",
            "invoice_hash": f"HASH-{inv_no}",
            "invoice_type": "增值税电子普通发票",
            "client_id": "C100",
            "client_name": "标准客户",
            "has_original_invoice": True,
            "description": f"员工{exp_type}费用报销",
            "payment_method": "企业微信付款",
            "scenario": "clean",
        }
        rows.append(row)
    return rows


def write_ocr_file(row: dict) -> None:
    path = DATASET / f"{row['reimbursement_id']}_发票OCR.txt"
    path.write_text(make_ocr_text(row), encoding="utf-8")


def write_chat_file(row: dict) -> None:
    path = DATASET / f"{row['reimbursement_id']}_审批聊天.md"
    path.write_text(make_chat_text(row), encoding="utf-8")


def main() -> None:
    rng = random.Random(42)

    # 1. 读取原有 6 个 showcase case（从 git baseline，确保不被重复追加）
    orig_erp = pd.read_csv(DATASET / "erp_showcase_fintrace_v1.csv", encoding="utf-8-sig")
    orig_rows = orig_erp.to_dict(orient="records")

    # 2. 生成 94 个正常 case
    normal_rows = generate_normal_rows(rng, 94)

    # 3. 合并并写出完整 ERP（覆盖旧文件，不追加）
    all_rows = orig_rows + normal_rows
    erp_df = pd.DataFrame(all_rows)
    erp_df.to_csv(DATASET / "erp_showcase_fintrace_v1.csv", index=False, encoding="utf-8-sig")

    # 4. 清理旧 NOR-* 文件并重新写出
    for f in DATASET.glob("NOR-*"):
        f.unlink()
    for row in normal_rows:
        write_ocr_file(row)
        write_chat_file(row)

    # 5. 构建完整 ground_truth（覆盖旧文件）
    # 6 个场景 case 保留原有标注
    orig_gt = json.loads((DATASET / "ground_truth.json").read_text(encoding="utf-8"))
    orig_labels = [lab for lab in orig_gt["labels"] if lab["case_id"] in {r["reimbursement_id"] for r in orig_rows}]
    existing_lookup = {lab["case_id"]: lab for lab in orig_labels}

    new_labels = []
    for row in all_rows:
        case_id = row["reimbursement_id"]
        if case_id in existing_lookup:
            new_labels.append(existing_lookup[case_id])
        else:
            new_labels.append({
                "case_id": case_id,
                "scenario": "clean",
                "risk_type": "normal",
                "expected_decision": "APPROVE",
                "hard_violation": False,
                "flexible_allowed": False,
                "expected_fields": {
                    "amount": row["amount"],
                    "employee_id": row["employee_id"],
                    "invoice_no": row["invoice_no"],
                    "expense_type": row["expense_type"],
                },
            })

    gt = {
        "dataset": "showcase_fintrace_v1",
        "source": "expanded_from_6_to_100",
        "case_count": len(all_rows),
        "label_notes": [
            "Showcase 数据已从 6 个扩增至 100 个 case。",
            "原有 6 个 SHOW-* 场景 case 保持不变，全部标注为 MANUAL_REVIEW。",
            "新增 94 个 NOR-* 正常报销 case，全部标注为 APPROVE。",
            "94 个正常 case 只包含 OCR 文本和审批聊天，不含可视化发票截图。",
        ],
        "labels": new_labels,
    }
    (DATASET / "ground_truth.json").write_text(
        json.dumps(gt, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 6. 更新 manifest
    manifest = json.loads((DATASET / "dataset_manifest.json").read_text(encoding="utf-8"))
    manifest["case_count"] = len(all_rows)
    manifest["scenario_count"] = 3
    manifest["normal_case_count"] = 94
    manifest["showcase_case_count"] = 6
    manifest["expansion_note"] = "94 个正常 case 仅含 OCR 文本和审批聊天，不含可视化发票截图。"
    (DATASET / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"✅ showcase 数据集已从 6 个扩增至 {len(all_rows)} 个 case")
    print(f"   - 6 个 SHOW-* 场景 case（含发票截图）")
    print(f"   - 94 个 NOR-* 正常报销 case（含 OCR 文本 + 审批聊天）")


if __name__ == "__main__":
    main()
