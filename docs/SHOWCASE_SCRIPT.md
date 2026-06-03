# FinTrace 外展示操作手册

这份文档只给项目作者使用。前端页面面向财务人员，不再展示示例数据路径、录屏步骤、回归命令或模型配置说明。

## 快速启动

- 桌面脚本：`C:\Users\王子畅\Desktop\启动 FinTrace 前端.cmd`
- 项目路径：`D:\03_AI_Projects\FinTrace`
- 示例数据集：`D:\03_AI_Projects\FinTrace\datasets\showcase_fintrace_v1`
- 可视化模拟发票：`D:\03_AI_Projects\FinTrace\datasets\showcase_fintrace_v1\visual_invoices`
- 本地模型配置：`D:\03_AI_Projects\FinTrace\.env.local`

双击桌面脚本后等待浏览器打开。前端默认使用结构化推理模式；本机 DeepSeek 配置写在 `.env.local`，该文件不进入 Git。若 Key 缺失或网络失败，系统会自动回退到本地稳定判断。

## 录屏顺序

1. 打开前端，停留在 `批量审核`。
2. 点击 `加载示例批次`。
3. 展示 `当前批次` 指标和 `待处理案件池`。
4. 点开 `SHOW-TS-01`，讲清同日上海 09:15 与乌鲁木齐 14:10 的时空冲突，以及缺少机票/登机牌/行程单证据。
5. 指一下 `票据附件` 行，说明示例批次包含可视化模拟发票 PNG，同时保留 OCR 文本作为解析兜底。
6. 切到 `案例对比`，默认展示 `SHOW-TS-01 vs SHOW-TS-02`，并排说明字段、规则、复核原因和字段来源。
7. 如需展示其他风险，再选择 `SHOW-SPLIT-01` 或 `SHOW-MIS-01`，分别讲拆单规避、事由与附件不一致。

## 讲解话术

FinTrace 不替代 ERP 或财务终审，而是做批量报销初筛和可解释复核。系统把 ERP 导出、OCR 文本、审批聊天和附件线索归并成案件包，先用确定性规则兜住缺原件、重复票、黑名单供应商等底线风险，再把拆单、时空冲突、事由与附件不一致等上下文风险转给财务人员复核。

讲解重点放在三点：

- 财务人员先看到需要处理的单据，而不是黑箱风险分。
- 每个结论都有命中规则、原因、建议动作和字段来源。
- AI 只做辅助分析，不覆盖阻断控制，也不直接替代人工终审。

## 内部回归命令

```powershell
cd D:\03_AI_Projects\FinTrace
python -m unittest discover -s tests -v
python cli.py eval-frozen datasets\showcase_fintrace_v1 --output-root runtime\showcase_eval --llm-mode deepseek
powershell -ExecutionPolicy Bypass -File scripts\run_regression.ps1
git diff --check
```

## 开发自测数据

随机红队批次不放在外展示前端入口里。如需开发自测：

```powershell
cd D:\03_AI_Projects\FinTrace
python cli.py demo-data --output-dir runtime\demo_batch --n 80 --seed 42
python cli.py run runtime\demo_batch
```

DeepSeek 专项测试集：

```powershell
cd D:\03_AI_Projects\FinTrace
python scripts\generate_showcase_assets.py
python scripts\create_deepseek_testsets.py
python cli.py eval-frozen runtime\testsets\deepseek_showcase_clean --output-root runtime\testsets_eval\deepseek_showcase_clean --llm-mode deepseek
python cli.py eval-frozen runtime\testsets\deepseek_missing_context --output-root runtime\testsets_eval\deepseek_missing_context --llm-mode deepseek
python cli.py eval-frozen runtime\testsets\deepseek_invoice_visual --output-root runtime\testsets_eval\deepseek_invoice_visual --llm-mode deepseek
python scripts\summarize_deepseek_testsets.py
```

内部诊断报告：

- `runtime\diagnostics\latest_frontend_diagnostics.md`
- `runtime\diagnostics\deepseek_testsets.md`

## 边界提醒

- 示例数据是高仿真固定样本，不代表真实企业泛化结论。
- 模拟发票只用于产品演示和测试，不具备税务效力。
- 默认外展示界面不显示数据集路径、回归指标、随机红队或 API Key 配置。
- 当前版本不写回 ERP，不做端到端自动审批，不让模型覆盖阻断控制。
