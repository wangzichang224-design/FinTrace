# FinTrace

FinTrace 是一个中文企业级批量费控审查 Agent。它不是“上传一张发票问 AI”的玩具，而是模拟企业 ERP 批量审单：一次输入 ERP 导出、OCR 文本、审批聊天记录、PDF/图片附件或 ZIP 包，系统自动归并案件、执行双层状态机、输出可追踪的审计链路和红蓝评测指标。

## 核心卖点

- 批量处理：一次运行 50-500 笔报销，生成 `batch_id` 和逐案 `case_id`。
- 异构输入：支持 ERP `CSV/XLSX`、扫描全能王/OCR 文本、审批聊天 `TXT/MD`、PDF/图片附件。
- 可溯源调试：字段来源、规则命中、本体工具调用、推理摘要、条件路由和错误归因全部落盘。
- 柔性费控：硬规则先拦截，节假日指数、客户等级、员工信用、供应商风险再进入柔性判断。
- 红蓝评测：红队生成高仿真批量样本，裁判器输出 Precision、Recall、F1、字段准确率和 case 级错误 drill-down。
- DeepSeek 可选：无 Key 时使用本地确定性模型；有 Key 时调用 DeepSeek 输出结构化 JSON 审计底稿，失败自动回退。

## 快速开始

```powershell
cd D:\03_AI_Projects\FinTrace
python cli.py demo-data --output-dir runtime\demo_batch --n 80 --seed 42
python cli.py run runtime\demo_batch --batch-id demo-run
streamlit run streamlit_app.py --server.port 8507
```

打开 Streamlit 后，推荐先点“生成高仿真样本并运行”，可直接得到适合录屏的批量审单结果。

## DeepSeek 模式

不要把 API Key 写入代码或 README。CLI 使用环境变量，Streamlit 使用侧边栏密码输入框。

```powershell
$env:DEEPSEEK_API_KEY="你的 Key"
$env:DEEPSEEK_BASE_URL="https://api.deepseek.com/v1"
$env:DEEPSEEK_MODEL="deepseek-chat"
python cli.py run runtime\demo_batch --llm-mode deepseek
```

如果 DeepSeek 调用失败、超时或返回非 JSON，FinTrace 会记录 `LLM调用失败` 或 `LLM JSON解析失败`，并回退到本地确定性柔性费控模型。

## 架构

FinTrace 使用双层 LangGraph 状态机：

- `BatchGraph`：批量扫描、manifest 生成、案件归并、并发调度、批次聚合、trace 导出。
- `CaseGraph`：字段抽取、硬规则、企业本体、结构化推理、最终决策。

完整流程图见：[docs/FINTRACE_FLOW.md](docs/FINTRACE_FLOW.md)。

每个节点都会写出结构化 `TraceEvent`：

```json
{
  "node_name": "hard_policy",
  "input_refs": ["amount", "invoice_no"],
  "output_refs": ["R004_ABSOLUTE_LIMIT"],
  "status": "WARN",
  "latency_ms": 1.2,
  "confidence": 0.95,
  "errors": [],
  "next_route": "need_context"
}
```

## 前端页面

- 批量处理台：路径输入、多文件/ZIP 上传、manifest、错误定位台。
- 案件列表：按决策、风险、员工、错误类型筛选。
- 审计探针：展示原始材料到最终结论的完整逻辑链。
- 字段溯源：字段值、来源 artifact、定位 span、抽取方式和置信度。
- 规则调试台：命中规则、未命中规则、阈值计算、本体工具调用。
- 批量指标：通过率、拒绝率、人工复核率、反舞弊率、平均耗时、节点失败率。
- 红蓝评测台：运行 50-500 条合成批量样本并查看指标。
- 迭代记录：展示测试-复盘-再迭代过程和本地评测报告。

## 运行评测

```powershell
python -m unittest discover -s tests -v
python cli.py eval --output-root runtime\eval_cn_mock --n 500 --seed 42
```

目标指标：

- 硬违规 Recall >= 99%
- 拒绝/升级 Precision >= 90%
- 柔性放行准确率 >= 85%
- 关键字段抽取准确率 >= 95%

## 运行产物

每次批处理都会写入 `runtime/batches/<batch_id>/`：

- `manifest.json`
- `case_index.json`
- `batch_metrics.json`
- `error_registry.json`
- `batch_result.json`
- `traces.jsonl`
- `cases/<case_id>/case_result.json`

这些文件用于定位错误：如果结果不准，可以快速判断问题来自 OCR/文本抽取、字段解析、规则阈值、本体上下文、LLM JSON、条件路由还是人工复核争议。
