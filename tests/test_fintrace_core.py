from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fintrace.evaluator import evaluate_batch
from fintrace.ontology import build_context
from fintrace.pipeline import run_batch
from fintrace.policies import run_hard_policies
from fintrace.reasoning import apply_llm_guardrails, make_decision
from fintrace.redteam import generate_redteam_batch
from fintrace.schemas import Decision


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

    def test_blocking_controls_route_directly(self) -> None:
        fields = {
            "reimbursement_id": "T-001",
            "employee_id": "E001",
            "expense_type": "住宿",
            "amount": 800.0,
            "invoice_no": "INV-001",
            "has_original_invoice": False,
            "vendor": "上海虹桥睿选酒店",
        }
        hits, route = run_hard_policies(fields)
        self.assertEqual(route, "reject")
        self.assertEqual(hits[0]["rule_class"], "blocking_control")
        decision, trace = make_decision(fields, hits, {}, llm_mode="mock")
        self.assertEqual(decision["decision"], Decision.REJECT.value)
        self.assertEqual(decision["guardrail_status"], "blocking_control_enforced")
        self.assertIn("R001_MISSING_ORIGINAL", trace["blocking_refs"])

    def test_contextual_risk_signal_does_not_hard_reject(self) -> None:
        fields = {
            "reimbursement_id": "T-002",
            "employee_id": "E003",
            "expense_type": "餐饮",
            "amount": 1300.0,
            "invoice_no": "INV-002",
            "has_original_invoice": True,
            "vendor": "上海星河商务餐饮有限公司",
            "expense_date": "2026-05-10",
            "split_group_count": 3,
            "split_group_total": 5000.0,
        }
        hits, route = run_hard_policies(fields)
        self.assertEqual(route, "need_context")
        self.assertTrue(any(h["rule_class"] == "contextual_risk_signal" for h in hits))
        decision, _ = make_decision(fields, hits, build_context(fields), llm_mode="mock")
        self.assertEqual(decision["decision"], Decision.MANUAL_REVIEW.value)
        self.assertEqual(decision["guardrail_status"], "contextual_risk_manual_review")

    def test_cold_start_context_blocks_flexible_approval(self) -> None:
        fields = {
            "reimbursement_id": "T-003",
            "employee_id": "",
            "expense_type": "住宿",
            "amount": 3600.0,
            "invoice_no": "INV-003",
            "has_original_invoice": True,
            "vendor": "上海虹桥睿选酒店",
            "expense_date": "2026-05-02",
            "city": "三亚",
        }
        hits, _ = run_hard_policies(fields)
        context = build_context(fields)
        self.assertFalse(context["context_quality"]["allow_flexible_approval"])
        decision, _ = make_decision(fields, hits, context, llm_mode="mock")
        self.assertEqual(decision["decision"], Decision.MANUAL_REVIEW.value)
        self.assertEqual(decision["guardrail_status"], "context_cold_start_manual_review")

    def test_llm_guardrail_routes_low_confidence_to_manual_review(self) -> None:
        baseline = {
            "decision": Decision.APPROVE_WITH_FLEX.value,
            "risk_level": "MEDIUM",
            "confidence": 0.84,
            "evidence_refs": ["R004_ABSOLUTE_LIMIT"],
        }
        llm_decision = {
            "decision": Decision.APPROVE_WITH_FLEX.value,
            "risk_level": "MEDIUM",
            "confidence": 0.5,
            "evidence_refs": ["holiday_index"],
        }
        guarded, guardrail = apply_llm_guardrails(llm_decision, baseline, [], {"context_quality": {"allow_flexible_approval": True}})
        self.assertEqual(guarded["decision"], Decision.MANUAL_REVIEW.value)
        self.assertEqual(guarded["guardrail_status"], "llm_low_confidence_manual_review")
        self.assertEqual(guardrail["action"], "manual_review")

    def test_case_failure_does_not_rollback_batch(self) -> None:
        class BrokenGraph:
            def invoke(self, _state):
                raise RuntimeError("synthetic case graph failure")

        root = test_root("partial_failure")
        data = generate_redteam_batch(root / "data", n=3, seed=21)
        with patch("fintrace.pipeline.build_case_graph", return_value=BrokenGraph()):
            result = run_batch([data["source_dir"]], output_root=root / "runs", batch_id="partial-failure", max_workers=1)

        self.assertEqual(result["batch_metrics"]["case_count"], 3)
        self.assertEqual(result["batch_metrics"]["case_failed_count"], 3)
        self.assertEqual(result["batch_metrics"]["decision_counts"].get(Decision.MANUAL_REVIEW.value), 3)
        self.assertIn("case_processing_failed", result["error_registry"])


def test_root(label: str) -> Path:
    root = Path(__file__).resolve().parents[1] / "runtime" / "test_runs" / f"{label}_{uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    return root


if __name__ == "__main__":
    unittest.main()
