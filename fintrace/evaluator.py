from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .pipeline import run_batch
from .redteam import generate_redteam_batch
from .schemas import Decision
from .storage import read_json, write_json


POSITIVE_DECISIONS = {Decision.REJECT.value, Decision.ESCALATE_FRAUD.value}


@dataclass
class EvaluationMetrics:
    total_cases: int
    decision_accuracy: float
    hard_precision: float
    hard_recall: float
    hard_f1: float
    flexible_accuracy: float
    field_accuracy: float
    false_positives: int
    false_negatives: int
    case_errors: list[dict[str, Any]]
    scenario_breakdown: dict[str, dict[str, int]]
    error_type_counts: dict[str, int]
    target_status: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_redteam_evaluation(
    output_root: str | Path,
    n: int = 80,
    seed: int = 42,
    llm_mode: str = "mock",
) -> dict[str, Any]:
    root = Path(output_root)
    data_info = generate_redteam_batch(root / f"redteam_seed_{seed}_{n}", n=n, seed=seed)
    batch = run_batch([data_info["source_dir"]], output_root=root / "runs", batch_id=f"eval-{seed}-{n}", llm_mode=llm_mode)
    metrics = evaluate_batch(batch, data_info["ground_truth_path"])
    report = {
        "report_name": "FinTrace 红蓝对抗评测报告",
        "dataset_version": "fintrace-redteam-v1",
        "evaluation_mode": "dynamic_graybox_generation",
        "isolation_note": "该模式会在评测时动态生成数据，适合开发自测；严格红蓝隔离请使用 run_frozen_evaluation/eval-frozen。",
        "llm_mode": llm_mode,
        "data_info": data_info,
        "batch_id": batch["batch_id"],
        "work_dir": batch["work_dir"],
        "metrics": metrics.to_dict(),
    }
    write_json(root / f"evaluation_report_{seed}_{n}.json", report)
    return report


def run_frozen_evaluation(
    frozen_data_dir: str | Path,
    output_root: str | Path,
    llm_mode: str = "mock",
    batch_id: str | None = None,
) -> dict[str, Any]:
    dataset_dir = Path(frozen_data_dir)
    ground_truth = dataset_dir / "ground_truth.json"
    if not ground_truth.exists():
        raise FileNotFoundError(f"冻结数据集缺少 ground_truth.json：{ground_truth}")
    root = Path(output_root)
    dataset_meta = read_json(dataset_dir / "dataset_manifest.json") if (dataset_dir / "dataset_manifest.json").exists() else {}
    dataset_name = dataset_meta.get("dataset", dataset_dir.name)
    run_id = batch_id or f"frozen-{dataset_dir.name}"
    batch = run_batch([str(dataset_dir)], output_root=root / "runs", batch_id=run_id, llm_mode=llm_mode)
    metrics = evaluate_batch(batch, ground_truth)
    report = {
        "report_name": "FinTrace 冻结红蓝评测报告",
        "dataset_version": dataset_name,
        "evaluation_mode": "frozen_dataset",
        "isolation_note": "评测只读取冻结目录和冻结标注，不在运行时生成红队数据。",
        "llm_mode": llm_mode,
        "data_info": {
            "source_dir": str(dataset_dir),
            "ground_truth_path": str(ground_truth),
            "dataset_manifest": dataset_meta,
        },
        "batch_id": batch["batch_id"],
        "work_dir": batch["work_dir"],
        "metrics": metrics.to_dict(),
    }
    safe_name = str(dataset_dir.name).replace(" ", "_")
    write_json(root / f"frozen_evaluation_report_{safe_name}.json", report)
    return report


def evaluate_batch(batch_result: dict[str, Any], ground_truth_path: str | Path) -> EvaluationMetrics:
    gt = read_json(Path(ground_truth_path))
    labels = {row["case_id"]: row for row in gt.get("labels", [])}
    results = {row["case_id"]: row for row in batch_result.get("case_results", [])}
    total = len(labels)

    correct_decisions = 0
    hard_tp = hard_fp = hard_fn = 0
    flex_total = flex_correct = 0
    field_total = field_correct = 0
    manual_review_count = 0
    expected_manual_review_count = 0
    case_errors: list[dict[str, Any]] = []
    scenario_breakdown: dict[str, Counter[str]] = defaultdict(Counter)

    for case_id, label in labels.items():
        result = results.get(case_id)
        if not result:
            case_errors.append({"case_id": case_id, "error_type": "缺少案件结果", "expected": label["expected_decision"], "actual": None})
            hard_fn += 1 if label.get("hard_violation") else 0
            continue
        actual = result.get("decision", {}).get("decision")
        expected = label["expected_decision"]
        if expected == Decision.MANUAL_REVIEW.value:
            expected_manual_review_count += 1
        if actual == Decision.MANUAL_REVIEW.value:
            manual_review_count += 1
        scenario = str(label.get("scenario", "unknown"))
        scenario_breakdown[scenario]["total"] += 1
        if actual == expected:
            correct_decisions += 1
            scenario_breakdown[scenario]["correct"] += 1
        else:
            case_errors.append(
                {
                    "case_id": case_id,
                    "scenario": scenario,
                    "error_type": "决策不一致",
                    "expected": expected,
                    "actual": actual,
                    "debug_hint": locate_debug_hint(result),
                }
            )

        expected_positive = expected in POSITIVE_DECISIONS
        actual_positive = actual in POSITIVE_DECISIONS
        if actual_positive and expected_positive:
            hard_tp += 1
        elif actual_positive and not expected_positive:
            hard_fp += 1
        elif expected_positive and not actual_positive:
            hard_fn += 1

        if label.get("flexible_allowed"):
            flex_total += 1
            if actual == Decision.APPROVE_WITH_FLEX.value:
                flex_correct += 1

        parsed = result.get("parsed_fields", {})
        for field, expected_value in label.get("expected_fields", {}).items():
            field_total += 1
            if values_equal(parsed.get(field), expected_value):
                field_correct += 1
            else:
                case_errors.append(
                    {
                        "case_id": case_id,
                        "scenario": scenario,
                        "error_type": "字段抽取不一致",
                        "field": field,
                        "expected": expected_value,
                        "actual": parsed.get(field),
                        "debug_hint": "打开字段溯源视图，检查该字段来自 ERP 行还是附件 OCR 文本。",
                    }
                )

    precision = hard_tp / (hard_tp + hard_fp) if hard_tp + hard_fp else 1.0
    recall = hard_tp / (hard_tp + hard_fn) if hard_tp + hard_fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    decision_accuracy = round(correct_decisions / total, 4) if total else 0
    flexible_accuracy = round(flex_correct / flex_total, 4) if flex_total else 1.0
    field_accuracy = round(field_correct / field_total, 4) if field_total else 0
    error_type_counts = dict(Counter(err.get("error_type", "未知错误") for err in case_errors))
    manual_review_limit = max(int(total * 0.45), expected_manual_review_count + max(1, int(total * 0.05)))
    return EvaluationMetrics(
        total_cases=total,
        decision_accuracy=decision_accuracy,
        hard_precision=round(precision, 4),
        hard_recall=round(recall, 4),
        hard_f1=round(f1, 4),
        flexible_accuracy=flexible_accuracy,
        field_accuracy=field_accuracy,
        false_positives=hard_fp,
        false_negatives=hard_fn,
        case_errors=case_errors,
        scenario_breakdown={key: dict(value) for key, value in scenario_breakdown.items()},
        error_type_counts=error_type_counts,
        target_status={
            "硬违规 Recall >= 99%": recall >= 0.99,
            "拒绝/升级 Precision >= 90%": precision >= 0.9,
            "柔性放行准确率 >= 85%": flexible_accuracy >= 0.85,
            "关键字段抽取准确率 >= 95%": field_accuracy >= 0.95,
            "人工复核比例可解释": manual_review_count <= manual_review_limit,
        },
    )


def values_equal(actual: Any, expected: Any) -> bool:
    try:
        return abs(float(actual) - float(expected)) < 0.01
    except (TypeError, ValueError):
        return str(actual).strip() == str(expected).strip()


def locate_debug_hint(result: dict[str, Any]) -> str:
    events = result.get("debug_events", [])
    if not events:
        return "No trace events recorded."
    last = events[-1]
    decision = result.get("decision", {})
    return f"检查节点={last.get('node_name')}，路由={last.get('next_route')}，结论原因={decision.get('reason', '')}"
