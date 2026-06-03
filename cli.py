from __future__ import annotations

import argparse
from pathlib import Path

from fintrace.evaluator import run_frozen_evaluation, run_redteam_evaluation
from fintrace.feedback import record_manual_approval
from fintrace.local_env import load_local_env
from fintrace.pipeline import run_batch
from fintrace.redteam import generate_redteam_batch
from fintrace.storage import read_json


load_local_env(Path(__file__).resolve().parent)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FinTrace 中文企业级批量费控审查 Agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    demo = sub.add_parser("demo-data", help="生成高仿真 ERP 导出和异构附件包")
    demo.add_argument("--output-dir", default="runtime/demo_batch")
    demo.add_argument("--n", type=int, default=80)
    demo.add_argument("--seed", type=int, default=42)

    run = sub.add_parser("run", help="对一个或多个文件/目录/ZIP 运行批量审查")
    run.add_argument("paths", nargs="+", help="文件、目录或 ZIP 包路径")
    run.add_argument("--output-root", default="runtime/batches")
    run.add_argument("--batch-id", default="")
    run.add_argument("--llm-mode", choices=["mock", "deepseek"], default="mock")
    run.add_argument("--max-workers", type=int, default=4)

    ev = sub.add_parser("eval", help="生成红队数据、运行批量图并输出评测指标")
    ev.add_argument("--output-root", default="runtime/eval")
    ev.add_argument("--n", type=int, default=80)
    ev.add_argument("--seed", type=int, default=42)
    ev.add_argument("--llm-mode", choices=["mock", "deepseek"], default="mock")

    freeze = sub.add_parser("redteam-freeze", help="生成物理隔离的冻结红队数据集")
    freeze.add_argument("--output-dir", default="datasets/fintrace-redteam-v1")
    freeze.add_argument("--n", type=int, default=84)
    freeze.add_argument("--seed", type=int, default=20260529)

    ev_frozen = sub.add_parser("eval-frozen", help="读取冻结红队数据集运行评测，不重新生成数据")
    ev_frozen.add_argument("frozen_data_dir", help="包含 ground_truth.json 的冻结数据集目录")
    ev_frozen.add_argument("--output-root", default="runtime/eval_frozen")
    ev_frozen.add_argument("--llm-mode", choices=["mock", "deepseek"], default="mock")
    ev_frozen.add_argument("--batch-id", default="")

    feedback = sub.add_parser("feedback-approve", help="记录一笔人工复核通过案例，沉淀为受控例外记忆")
    feedback.add_argument("batch_result", help="batch_result.json 或单案 case_result.json 路径")
    feedback.add_argument("case_id", help="要学习的 case_id；如果传入单案文件可填该单案 case_id")
    feedback.add_argument("--approver", default="finance_reviewer")
    feedback.add_argument("--reason", default="人工复核确认业务合理。")
    feedback.add_argument("--memory-path", default="")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.cmd == "demo-data":
        info = generate_redteam_batch(Path(args.output_dir), n=args.n, seed=args.seed)
        print(f"演示批次已生成：{info['source_dir']}")
        print(f"ERP 导出：{info['erp_path']}")
        print(f"标注答案：{info['ground_truth_path']}")
    elif args.cmd == "run":
        result = run_batch(
            args.paths,
            output_root=Path(args.output_root),
            batch_id=args.batch_id or None,
            llm_mode=args.llm_mode,
            max_workers=args.max_workers,
        )
        print(f"批次：{result['batch_id']}")
        print(f"产物目录：{result['work_dir']}")
        print(f"案件数：{result['batch_metrics'].get('case_count')}")
        print(f"决策分布：{result['batch_metrics'].get('decision_counts')}")
    elif args.cmd == "eval":
        report = run_redteam_evaluation(Path(args.output_root), n=args.n, seed=args.seed, llm_mode=args.llm_mode)
        metrics = report["metrics"]
        print(f"评测批次：{report['batch_id']}")
        print(f"产物目录：{report['work_dir']}")
        print(f"决策准确率：{metrics['decision_accuracy']:.2%}")
        print(f"硬违规 Precision：{metrics['hard_precision']:.2%}")
        print(f"硬违规 Recall：{metrics['hard_recall']:.2%}")
        print(f"硬违规 F1：{metrics['hard_f1']:.2%}")
        print(f"字段准确率：{metrics['field_accuracy']:.2%}")
        print(f"错误案件数：{len(metrics['case_errors'])}")
        print(f"目标达成：{metrics.get('target_status')}")
    elif args.cmd == "redteam-freeze":
        from redteam.generator import generate_frozen_dataset

        info = generate_frozen_dataset(Path(args.output_dir), n=args.n, seed=args.seed)
        print(f"冻结红队数据集已生成：{info['source_dir']}")
        print(f"ERP 导出：{info['erp_path']}")
        print(f"冻结标注：{info['ground_truth_path']}")
    elif args.cmd == "eval-frozen":
        report = run_frozen_evaluation(
            args.frozen_data_dir,
            output_root=Path(args.output_root),
            llm_mode=args.llm_mode,
            batch_id=args.batch_id or None,
        )
        metrics = report["metrics"]
        print(f"冻结评测批次：{report['batch_id']}")
        print(f"数据集：{report['dataset_version']}")
        print(f"产物目录：{report['work_dir']}")
        print(f"决策准确率：{metrics['decision_accuracy']:.2%}")
        print(f"硬违规 Precision：{metrics['hard_precision']:.2%}")
        print(f"硬违规 Recall：{metrics['hard_recall']:.2%}")
        print(f"字段准确率：{metrics['field_accuracy']:.2%}")
        print(f"错误案件数：{len(metrics['case_errors'])}")
        print(f"目标达成：{metrics.get('target_status')}")
    elif args.cmd == "feedback-approve":
        payload = read_json(Path(args.batch_result))
        if "case_results" in payload:
            case = next((row for row in payload.get("case_results", []) if row.get("case_id") == args.case_id), None)
        else:
            case = payload if payload.get("case_id") == args.case_id else None
        if not case:
            raise SystemExit(f"未找到 case_id：{args.case_id}")
        result = record_manual_approval(case, approver=args.approver, reason=args.reason, path=args.memory_path or None)
        print(f"反馈状态：{result['status']}")
        print(f"原因：{result.get('reason', result.get('memory', {}).get('approval_reason', ''))}")
        if result.get("memory"):
            print(f"记忆ID：{result['memory']['memory_id']}")
            print(f"金额上限：{result['memory']['amount_limit']}")


if __name__ == "__main__":
    main()
