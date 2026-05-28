from __future__ import annotations

import unittest
from pathlib import Path
from uuid import uuid4

from fintrace.evaluator import evaluate_batch
from fintrace.pipeline import run_batch
from fintrace.redteam import generate_redteam_batch


class FinTraceCoreTest(unittest.TestCase):
    def test_batch_graph_exports_trace_and_decisions(self) -> None:
        root = test_root("core")
        data = generate_redteam_batch(root / "data", n=33, seed=7)
        result = run_batch([data["source_dir"]], output_root=root / "runs", batch_id="test-batch", max_workers=1)

        self.assertEqual(result["batch_metrics"]["case_count"], 33)
        self.assertTrue((Path(result["work_dir"]) / "traces.jsonl").exists())
        self.assertTrue((Path(result["work_dir"]) / "batch_result.json").exists())
        decisions = result["batch_metrics"]["decision_counts"]
        self.assertIn("ESCALATE_FRAUD", decisions)
        self.assertIn("APPROVE_WITH_FLEX", decisions)
        self.assertIn("MANUAL_REVIEW", decisions)

        sample_case = result["case_results"][0]
        self.assertIn("field_provenance", sample_case)
        self.assertGreaterEqual(len(sample_case["debug_events"]), 4)
        for event in sample_case["debug_events"]:
            for key in ("node_name", "input_refs", "output_refs", "status", "latency_ms", "confidence", "errors", "next_route"):
                self.assertIn(key, event)

    def test_evaluator_scores_redteam_batch(self) -> None:
        root = test_root("eval")
        data = generate_redteam_batch(root / "data", n=55, seed=11)
        result = run_batch([data["source_dir"]], output_root=root / "runs", batch_id="eval-batch", max_workers=1)
        metrics = evaluate_batch(result, data["ground_truth_path"])

        self.assertGreaterEqual(metrics.hard_recall, 0.99)
        self.assertGreaterEqual(metrics.hard_precision, 0.9)
        self.assertGreaterEqual(metrics.field_accuracy, 0.95)
        self.assertGreaterEqual(metrics.flexible_accuracy, 0.85)


def test_root(label: str) -> Path:
    root = Path(__file__).resolve().parents[1] / "runtime" / "test_runs" / f"{label}_{uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    return root


if __name__ == "__main__":
    unittest.main()
