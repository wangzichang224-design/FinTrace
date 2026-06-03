# FinTrace 开源评测工具接入方案

## 结论

FinTrace 的主评测口径仍然是内置的 `eval` 和 `eval-frozen`。Ragas、DeepEval、Phoenix、LangSmith 不替代现有指标，而是作为增强层：

- `eval-frozen` 负责业务结果指标：决策准确率、硬违规 Precision/Recall/F1、字段准确率。
- 外部评测适配器负责 Agent 过程指标：步骤顺序、工具调用完整性、参数引用覆盖、trace 可解释性。
- Phoenix/LangSmith 负责可视化定位：从某个错误 case 反查 parser、policy、context、reasoning、decision 哪一步掉链子。

## Baseline 命令

先跑内置 baseline，再生成外部评测样本：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -B -c "import cli; import fintrace.evaluator; import fintrace.pipeline; print('import ok')"
python -B -m unittest discover -s tests -v
python cli.py eval-frozen datasets\fintrace-redteam-v1 --output-root runtime\eval_frozen
python cli.py eval-frozen datasets\showcase_fintrace_v1 --output-root runtime\showcase_eval
```

## 外部评测适配器

适配器只读取 `batch_result.json` 和 `traces.jsonl`，不 import `fintrace.pipeline`，也不改主链路。

```powershell
python scripts\external_eval_adapter.py `
  runtime\eval_frozen\runs\frozen-fintrace-redteam-v1\batch_result.json `
  --output-dir runtime\external_eval\fintrace_redteam
```

输出：

- `external_eval_report.json`：汇总指标和每个 case 的过程检查。
- `ragas_agent_samples.jsonl`：Ragas 风格的 agent tool-call 样本。
- `deepeval_agent_cases.jsonl`：DeepEval 风格的 agent case 样本。

可选依赖单独放在 `requirements-eval.txt`，避免污染核心运行环境：

```powershell
pip install -r requirements-eval.txt
```

## 指标映射

| FinTrace 适配指标 | 对应工具理念 | 说明 |
| --- | --- | --- |
| `task_completion_rate` | DeepEval Task Completion | case 是否完成并输出受控决策。 |
| `tool_call_accuracy` | Ragas ToolCallAccuracy / DeepEval Tool Correctness | 是否按 `parser -> hard_policy -> context -> reasoning -> decision` 或阻断直达路径执行。 |
| `tool_call_f1` | Ragas ToolCallF1 | 实际步骤与期望步骤的过程级 F1。 |
| `argument_reference_coverage` | DeepEval Argument Correctness | trace 事件是否有 `input_refs` 和 `output_refs`，便于追溯参数来源。 |
| `trace_explainability_score` | AgentTrace / Phoenix / LangSmith | trace 字段完整性、证据引用、guardrail 状态是否可观察。 |
| `guardrail_observability_rate` | LLM guardrail observability | DeepSeek/本地基线/人类反馈记忆是否留下门控状态。 |

## 使用边界

- 不用 LM Eval Harness 作为主方案。它更适合评底座模型，不适合直接评 FinTrace 这种业务 Agent 流程。
- 不把 Ragas/DeepEval 分数包装成财务准确率。财务准确率只看冻结数据集和人工标注。
- 不在适配器里重新跑推理。适配器只能读取既有产物，否则会破坏红蓝隔离和可复现性。

## 面试讲法

FinTrace 的评测不是“手工点几个 demo case”，而是分成两层：

1. 业务正确性：冻结红队集和 showcase 集回归，衡量 Precision、Recall、F1 和字段准确率。
2. Agent 过程正确性：外部适配器把 `traces.jsonl` 转成 Ragas/DeepEval/Phoenix/LangSmith 可消费的样本，检查工具顺序、参数引用和门控可观察性。

这能说明我理解企业级 AI 产品不能只看最终答案，还要能解释每一步为什么这么走、错了能定位到哪一层。
