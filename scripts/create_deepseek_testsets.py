from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "datasets" / "showcase_fintrace_v1"
TARGET_ROOT = ROOT / "runtime" / "testsets"


def copy_dataset(target: Path) -> None:
    if target.exists():
        try:
            shutil.rmtree(target, onexc=remove_readonly)
        except PermissionError:
            shutil.copytree(SOURCE, target, dirs_exist_ok=True)
            return
    shutil.copytree(SOURCE, target)


def remove_readonly(function, path, excinfo) -> None:
    try:
        os.chmod(path, 0o700)
        function(path)
    except Exception:
        raise excinfo


def make_missing_context(target: Path) -> None:
    csv_path = target / "erp_showcase_fintrace_v1.csv"
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    employee_map = {
        "SHOW-TS": "E_MISSING_TS",
        "SHOW-SPLIT": "E_MISSING_SPLIT",
        "SHOW-MIS": "E_MISSING_MIS",
    }
    client_map = {
        "SHOW-TS": "C_MISSING_TS",
        "SHOW-SPLIT": "C_MISSING_SPLIT",
        "SHOW-MIS": "C_MISSING_MIS",
    }
    for prefix, employee_id in employee_map.items():
        mask = df["reimbursement_id"].str.startswith(prefix)
        df.loc[mask, "employee_id"] = employee_id
        df.loc[mask, "client_id"] = client_map[prefix]
    df["vendor_tax_no"] = [f"UNKNOWN_VENDOR_TAX_{idx + 1:03d}" for idx in range(len(df))]
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    ground_truth_path = target / "ground_truth.json"
    ground_truth = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    ground_truth["dataset"] = "deepseek_missing_context"
    for label in ground_truth.get("labels", []):
        case_id = label.get("case_id", "")
        for prefix, employee_id in employee_map.items():
            if case_id.startswith(prefix):
                label.setdefault("expected_fields", {})["employee_id"] = employee_id
    ground_truth_path.write_text(json.dumps(ground_truth, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = target / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["dataset"] = "deepseek_missing_context"
    manifest["purpose"] = "故意缺少员工/客户/供应商上下文，用于验证开发诊断进入内部日志而非财务主界面。"
    manifest["expected_internal_diagnostics"] = ["employee_credit", "client_priority", "vendor_risk"]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def make_invoice_visual(target: Path) -> None:
    manifest_path = target / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["dataset"] = "deepseek_invoice_visual"
    manifest["purpose"] = "带可视化模拟发票 PNG 的 Showcase 样本，用于验证附件展示和字段溯源。"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    TARGET_ROOT.mkdir(parents=True, exist_ok=True)

    clean = TARGET_ROOT / "deepseek_showcase_clean"
    missing = TARGET_ROOT / "deepseek_missing_context"
    visual = TARGET_ROOT / "deepseek_invoice_visual"

    copy_dataset(clean)
    copy_dataset(missing)
    copy_dataset(visual)
    make_missing_context(missing)
    make_invoice_visual(visual)

    readme = TARGET_ROOT / "README.md"
    readme.write_text(
        "\n".join(
            [
                "# FinTrace DeepSeek 本地测试集",
                "",
                "- `deepseek_showcase_clean`：Showcase 正常样本，用于 DeepSeek 跑通。",
                "- `deepseek_missing_context`：故意缺员工/客户/供应商上下文，诊断应进入内部报告。",
                "- `deepseek_invoice_visual`：带可视化模拟发票 PNG，用于验证附件展示。",
            ]
        ),
        encoding="utf-8",
    )
    print(f"created testsets under {TARGET_ROOT}")


if __name__ == "__main__":
    main()
