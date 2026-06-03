from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = ROOT / "runtime" / "testsets_eval"
DIAG_DIR = ROOT / "runtime" / "diagnostics"


def load_reports() -> list[dict]:
    reports = []
    for path in sorted(EVAL_ROOT.rglob("frozen_evaluation_report_*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        report["_path"] = str(path.relative_to(ROOT))
        reports.append(report)
    return reports


def main() -> None:
    DIAG_DIR.mkdir(parents=True, exist_ok=True)
    reports = load_reports()
    lines = [
        "# FinTrace DeepSeek 测试集诊断报告",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 报告数量：{len(reports)}",
        "",
        "| 数据集 | 模式 | 决策准确率 | 字段准确率 | 错误案件 | 报告路径 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for report in reports:
        metrics = report.get("metrics", {})
        lines.append(
            "| {dataset} | {mode} | {decision:.2%} | {field:.2%} | {errors} | `{path}` |".format(
                dataset=report.get("dataset_version", ""),
                mode=report.get("llm_mode", ""),
                decision=metrics.get("decision_accuracy", 0),
                field=metrics.get("field_accuracy", 0),
                errors=len(metrics.get("case_errors", [])),
                path=report.get("_path", ""),
            )
        )

    lines.extend(
        [
            "",
            "## 结论",
            "",
            "- `deepseek_showcase_clean` 用于验证标准示例批次。",
            "- `deepseek_missing_context` 用于验证员工/客户/供应商主数据缺失时，开发诊断进入内部报告，不暴露在财务主界面。",
            "- `deepseek_invoice_visual` 用于验证可视化模拟发票附件不会破坏字段抽取和风险判断。",
            "- 如某次报告出现错误案件，先查看对应 `runs/<batch_id>/cases/<case_id>/case_result.json` 和 `error_registry.json`。",
        ]
    )
    (DIAG_DIR / "deepseek_testsets.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {DIAG_DIR / 'deepseek_testsets.md'}")


if __name__ == "__main__":
    main()
