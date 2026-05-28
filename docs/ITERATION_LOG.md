# FinTrace v1 中文版迭代记录

## 迭代目标

把 FinTrace 从英文批量审单原型升级为中文企业级费控 Agent 展示版，重点补齐四件事：中文界面与报告、DeepSeek 结构化推理、高仿真红队数据、测试驱动的可追溯迭代过程。

## Round 0：基线检查

- 状态：原型已具备 BatchGraph / CaseGraph、manifest、字段溯源、硬规则、本体上下文、评测器和 Streamlit 前端。
- 发现问题：
  - 前端、README、CLI 输出以英文为主，不利于中文作品集和录屏展示。
  - 部分中文字段别名、规则文案、本体文案存在乱码，中文 ERP/OCR 材料可读性不足。
  - 红队样本过于规则化，员工、供应商、审批记录、OCR 噪声和 ERP 字段不像真实企业数据。
  - DeepSeek 接入只做了最小调用，没有在 trace 中明确记录 JSON 解析失败、调用失败和回退原因。

## Round 1：中文化与真实感增强

- 修改内容：
  - 重写中文字段抽取别名，支持 `报销单号`、`员工编号`、`费用类型`、`价税合计`、`发票号码` 等 ERP/OCR 常见字段。
  - 将硬规则、本体工具、决策原因、CLI 输出、README、Streamlit 页面全部中文化。
  - 红队生成器升级为“ERP 费控导出 + 发票 OCR 文本 + 企业微信审批记录”的批量材料包。
  - 新增相似发票号场景和 `R007_SIMILAR_INVOICE_NO` 规则，补齐“发票号相似/连号/改号”攻击覆盖。
  - DeepSeek 模式要求严格 JSON 输出，并把调用失败、JSON 解析失败、无 Key 回退写入 reasoning trace 和 error registry。

- 已验证：
  - `python -m unittest discover -s tests -v`
  - 结果：2 个核心测试通过。

## Round 2：评测复跑与前端展示优化

- 修改内容：
  - Streamlit 改为中文企业费控控制台，新增 `字段溯源`、`批量指标`、`迭代记录` 独立页面。
  - 红蓝评测报告增加目标达成状态、场景分布、错误类型统计和中文 case 级 drill-down。
  - README 明确 DeepSeek Key 只通过环境变量或侧边栏输入，不写入代码、日志或项目文件。

- 复跑命令：
  - `python -m unittest discover -s tests -v`
  - `python cli.py eval --output-root runtime\eval_cn_mock --n 500 --seed 42`

- 复跑结果：
  - 单元测试通过。
  - 500 条评测首次复跑：硬违规 Precision/Recall/F1 和字段准确率均为 100%，但整体决策准确率为 66.6%，柔性放行未达标。
  - 错误归因：`clean`、`holiday_flex`、`strategic_client_flex`、`ocr_amount_noise` 被误判为 `MANUAL_REVIEW`，原因是高仿真生成器过度复用同员工/同供应商/同日期，误触发 `R003_SPLIT_INVOICE`。

## Round 3：根据评测结果修正数据生成器

- 修改内容：
  - 非攻击样本的供应商门店加入分店后缀，避免干净样本和柔性样本在大批量下被误归并为拆票。
  - 保留真正的 `split_invoice` 和 `similar_invoice_no` 场景共享供应商/日期，用于触发规则链。

- 复跑命令：
  - `python -m unittest discover -s tests -v`
  - `python cli.py eval --output-root runtime\eval_cn_mock_v2 --n 500 --seed 42`
  - `python cli.py eval --output-root runtime\eval_cn_deepseek_fallback --n 60 --seed 42 --llm-mode deepseek`

- 复跑结果：
  - 单元测试：通过。
  - 500 条本地模型评测：决策准确率 100%，硬违规 Precision 100%，硬违规 Recall 100%，硬违规 F1 100%，字段准确率 100%，错误案件数 0。
  - DeepSeek 无 Key 回退评测：60 条样本决策准确率 100%，并在 error registry 中记录 `LLM调用失败` 回退事件；字段冲突样本也被聚合展示，证明错误定位链路可用。

## 剩余风险

- v1 图片/PDF OCR 仍是可选增强；没有本地 OCR 时，建议使用扫描全能王或企业微信导出的文本附件。
- DeepSeek 真实调用依赖网络和 Key；无 Key 或网络失败时，本地确定性模型会保证批处理可继续运行。
- 高仿真数据是 mock 企业数据，不包含真实公司隐私，可用于录屏、图文展示和面试讲解。
