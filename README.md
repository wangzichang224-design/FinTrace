# FinTrace

FinTrace 是一个中文企业级批量费控审查 Agent。评审整改后，它的产品边界更清楚：

- **v0.1 MVP 主链路**：`CSV/XLSX 批量导入 -> 字段溯源 -> 本地稳定模型/规则审查 -> 可解释结果导出`
- **v0.2 展示与增强能力**：面向财务人员的 Streamlit 审核台、DeepSeek 结构化审计底稿、红蓝评测、高仿真演示数据

FinTrace 不试图一开始替代 ERP 或财务终审。它先解决批量报销初筛中最痛的两件事：风险先筛出来，错误能追回去。

## 文档入口

- [MVP 范围说明](docs/MVP_SCOPE.md)：回答第一个可用版本到底包含什么。
- [流程图](docs/FINTRACE_FLOW.md)：端到端流程、双层状态机、溯源链路和本地稳定模型。
- [企业本体冷启动方案](docs/ONTOLOGY_COLD_START.md)：说明 CRM/HR/供应商/节假日数据从哪里来、谁维护、缺数据怎么办。
- [企业数据对接契约](docs/ENTERPRISE_INTEGRATION.md)：定义真实 ERP、HR、CRM、供应商和费用政策数据源的最小字段、维护责任和冷启动兜底。
- [企业 ERP 费控对标与智能改进](docs/ERP_EXPENSE_BENCHMARK.md)：说明主流 ERP/费控审核方式，并记录 FinTrace 的人工通过记忆设计。
- [红蓝对抗隔离说明](docs/RED_BLUE_ISOLATION.md)：区分动态灰盒自测和冻结数据集评测，说明红队生成器与蓝队代码的隔离边界。
- [架构决策记录](docs/ARCHITECTURE_DECISIONS.md)：解释为什么使用 LangGraph、DeepSeek、本地稳定模型和 Streamlit。
- [迭代记录](docs/ITERATION_LOG.md)：记录测试、失败归因和复测过程。

## v0.1 MVP 必须有

- 批量导入 ERP `CSV/XLSX`，支持本地目录路径。
- 案件归并：一行 ERP 对应一个 case，并关联同名/同报销单附件文本。
- 字段级溯源：金额、员工、费用类型、发票号、供应商等关键字段保留来源。
- 本地稳定模型：不依赖外部 LLM，同样输入得到同样输出。
- 阻断控制与上下文风险信号分层：
  - `blocking_control`：缺原件、精确重复发票/哈希、供应商黑名单，可直达拒绝或反舞弊升级。
  - `contextual_risk_signal`：拆票、跨期、相似发票号、超金额、OCR 金额冲突，只进入推理或人工复核。
- JSON/JSONL 结果导出：每个 batch 和 case 都能离线复查。

## v0.2 展示与增强能力

- Streamlit 中文前端：默认是给财务人员用的 `财务审核台`，只展示导入批次、待处理案件、不通过原因和建议动作；复杂的字段溯源、运行链路、规则本体、LLM 门控和漏洞优化聚合放在 `诊断与优化台`。
- DeepSeek：只作为结构化审计底稿增强层，必须通过本地基准和合规门控。
- 红蓝评测：生成高仿真 ERP 批次和异构附件，输出 Precision、Recall、F1、字段准确率和错误归因。

## 快速开始

```powershell
cd D:\03_AI_Projects\FinTrace
python cli.py demo-data --output-dir runtime\demo_batch --n 80 --seed 42
python cli.py run runtime\demo_batch --batch-id demo-run
streamlit run streamlit_app.py --server.port 8508
```

`python cli.py run ...` 是 MVP 主链路。`demo-data` 和 `eval` 是演示与评测能力。

## DeepSeek 模式

不要把 API Key 写入代码或 README。CLI 使用环境变量，Streamlit 使用侧边栏密码输入框。

```powershell
$env:DEEPSEEK_API_KEY="你的 Key"
$env:DEEPSEEK_BASE_URL="https://api.deepseek.com/v1"
$env:DEEPSEEK_MODEL="deepseek-chat"
python cli.py run runtime\demo_batch --llm-mode deepseek
```

DeepSeek 输出必须经过 JSON 解析、证据引用、置信度、本地基准一致性和阻断控制校验。任何一步不通过，系统会回退到本地稳定模型或转人工复核。

## 运行评测

```powershell
python -m unittest discover -s tests -v
python cli.py eval --output-root runtime\eval_review_fix --n 500 --seed 42
python cli.py eval-frozen datasets\fintrace-redteam-v1 --output-root runtime\eval_frozen
```

目标指标：

- 硬违规 Recall >= 99%
- 拒绝/升级 Precision >= 90%
- 关键字段抽取准确率 >= 95%
- 人工复核比例可解释，不能靠误杀堆高风控

## 运行产物

每次批处理都会写入 `runtime/batches/<batch_id>/`：

- `manifest.json`
- `case_index.json`
- `batch_metrics.json`
- `error_registry.json`
- `batch_result.json`
- `traces.jsonl`
- `cases/<case_id>/case_result.json`

如果结论不准，可以沿着字段、规则、本体、推理、路由和错误定位台快速判断问题来自哪里。
