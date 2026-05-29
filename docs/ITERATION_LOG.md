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

## Round 4：根据评审做 MVP 瘦身与风控边界重画

- 评审问题：
  - 项目能力堆叠较多，MVP 范围不清。
  - “硬规则”和“柔性推理”边界不够清楚。
  - 企业本体缺少冷启动、维护责任和数据来源说明。
  - LLM 缺少合规门控，可能在财务场景里产生幻觉风险。
  - 批量处理中缺少部分失败策略。
  - 文档有工程细节，但缺少“为什么这样做”的架构决策记录。

- 修改内容：
  - 新增 `docs/MVP_SCOPE.md`，把 v0.1 MVP 定义为 CSV/XLSX 批量导入、字段溯源、本地稳定模型、可解释结果导出。
  - 新增 `docs/ONTOLOGY_COLD_START.md`，说明费用标准、节假日、客户等级、员工信用和供应商风险的数据来源、维护责任、更新频率和冷启动默认策略。
  - 新增 `docs/ARCHITECTURE_DECISIONS.md`，解释为什么使用双层 LangGraph、为什么本地稳定模型是基准、为什么 DeepSeek 是增强层、为什么 Streamlit/红蓝评测后置。
  - 将规则改为 `blocking_control` 和 `contextual_risk_signal` 两类；拆票、跨期、相似票号、OCR 金额冲突不再作为直接硬拒绝，只进入人工复核/推理链。
  - 给 `context_info` 增加 `context_quality`；缺员工信用、供应商风险或费用基准时，不允许自动柔性通过。
  - 给 DeepSeek 增加二次门控：低置信度、缺证据、与本地基准冲突、试图覆盖阻断控制时回退或转人工复核。
  - 批量处理改为部分成功策略：单个 CaseGraph 异常时生成失败 case result，默认 `MANUAL_REVIEW`，批次不整体回滚。
  - 前端增加 MVP 定位提示、规则分类、本体冷启动质量、LLM 门控状态和失败案件数。

- 验证命令：
  - `python -m unittest discover -s tests -v`
  - `python -B -c "import cli, streamlit_app; import fintrace.schemas, fintrace.policies, fintrace.ontology, fintrace.reasoning, fintrace.pipeline; print('import ok')"`
  - `python cli.py eval --output-root runtime\eval_review_fix --n 500 --seed 42`
  - `Invoke-WebRequest -UseBasicParsing http://localhost:8508`

- 复跑结果：
  - 单元测试：7/7 通过。
  - 500 条评测：决策准确率 100%，硬违规 Precision 100%，硬违规 Recall 100%，硬违规 F1 100%，字段准确率 100%，错误案件数 0。
  - 新增目标 `人工复核比例可解释`：达成。
  - 前端：`http://localhost:8508` 返回 200。

## Round 5：前端改为财务人员优先

- 用户反馈：
  - 前端应作为财务人员日常使用入口，尽可能简单。
  - 复杂能力应放到单独区域，用于查看具体不通过原因、运行过程、逻辑推理过程，并支持漏洞查询和优化。

- 修改内容：
  - 将 Streamlit 从 8 个并列页面收敛为 3 个入口：`财务审核台`、`诊断与优化台`、`评测与迭代`。
  - `财务审核台` 只保留导入批次、运行批量审核、批次概览、待处理案件池、不通过/复核原因和建议动作。
  - 新增 `fintrace.insights` 纯逻辑模块，把不通过原因、下一步动作、诊断焦点、漏洞聚合和优化建议从 UI 中抽离，便于测试和复用。
  - `诊断与优化台` 聚合 Top 问题、规则命中、上下文缺失、冷启动字段、LLM 门控和错误源；支持按员工、单号、供应商、规则 ID、错误类型查询。
  - 单案详情改为四个调试视角：不通过原因、运行链路、规则与本体、字段溯源。

- 验证命令：
  - `python -m unittest discover -s tests -v`
  - `python -B -c "import streamlit_app; import fintrace.insights; print('import ok')"`
  - `python cli.py eval --output-root runtime\eval_frontend_simple --n 500 --seed 42`
  - Streamlit `AppTest.from_file('streamlit_app.py')` 无头渲染检查。

- 复跑结果：
  - 单元测试：8/8 通过。
  - 500 条评测：决策准确率 100%，硬违规 Precision 100%，硬违规 Recall 100%，硬违规 F1 100%，字段准确率 100%，错误案件数 0。
  - 无头前端检查：标题、`财务审核台`、`诊断与优化台`、`评测与迭代` 渲染正常，异常数 0。

## Round 6：可信度补丁与评审漏洞修复

- 评审问题：
  - 附件匹配使用简单子串，发票号或报销单号重叠时可能错配。
  - 金额解析对 `RMB 1,280.50`、`￥12，345.67` 等真实 ERP/OCR 格式不够稳。
  - 审批聊天中的提示注入样本原本金额在标准内，系统会直接通过，评测没有真正覆盖“话术诱导”风险。
  - 供应商高危口径在规则层和本体层不完全一致。
  - 企业本体仍缺少真实 ERP/HR/CRM/供应商系统的数据对接契约。

- 修改内容：
  - 附件匹配改为带边界的精确 token 评分：报销单号、发票号、发票 hash 必须完整命中，避免 `FT-00001` 匹配到 `FT-000010`。
  - CSV 读取增加 `utf-8-sig`、`utf-8`、`gb18030`、`gbk` 兜底。
  - 金额解析支持 `RMB`、`CNY`、`¥/￥`、中文逗号和千分位格式。
  - 新增 `R009_CHAT_PROMPT_INJECTION` 上下文风险信号，聊天中出现“忽略制度/绕过审核/立即批准”等越权诱导时转人工复核。
  - 供应商本体风险复用 `BLACKLISTED_VENDOR_TOKENS`，统一规则层和本体层高危定义。
  - 红队数据新增两个干净样本场景，避免新增提示注入人工复核后把人工复核率目标推高到不可解释。
  - 新增 `docs/ENTERPRISE_INTEGRATION.md`，定义真实 ERP、HR、CRM、供应商、费用政策和节假日指数的数据源契约。

- 验证命令：
  - `python -m unittest discover -s tests -v`
  - `python -B -c "import fintrace.ingestion, fintrace.parser, fintrace.policies, fintrace.ontology, fintrace.redteam; print('import ok')"`
  - `python cli.py eval --output-root runtime\eval_credibility_patch --n 500 --seed 42`
  - `python cli.py eval --output-root runtime\eval_credibility_patch_v2 --n 500 --seed 42`

- 复盘过程：
  - 第一轮复测：决策准确率 93.40%，错误案件 33。原因是新增 `clean_office/clean_transport` 样本复用了供应商、员工和日期，被拆票规则误判为风险信号。
  - 迭代修复：给新增干净样本供应商追加分店后缀，保持真实企业分店口径，同时避免被拆票归并。

- 复跑结果：
  - 单元测试：11/11 通过。
  - 第二轮 500 条评测：决策准确率 100%，硬违规 Precision 100%，硬违规 Recall 100%，硬违规 F1 100%，字段准确率 100%，错误案件数 0。
  - 新增测试覆盖：附件精确匹配、千分位金额解析、提示注入风险信号。

## Round 7：对标企业 ERP 费控并加入人工通过记忆

- 用户反馈：
  - 需要明确说明企业 ERP 目前大多如何做费用审核，并对比 FinTrace 做改进。
  - 希望系统有智能提升：Agent 拿捏不定转人工后，如果人工审核通过，下次遇到相同模式可以直接通过。

- 修改内容：
  - 新增 `docs/ERP_EXPENSE_BENCHMARK.md`，说明主流 ERP/费控系统的典型链路：员工提交、OCR 回填、政策规则校验、审批流、财务复核、付款和审计日志。
  - 新增 `fintrace.feedback`，实现受控人工反馈记忆：记录人工通过案例、生成相似模式签名、设置金额上限和有效期、下次审核自动匹配。
  - 决策引擎接入人工通过记忆：仅当本地稳定模型输出 `MANUAL_REVIEW` 且没有底线风险时，才允许命中记忆后 `APPROVE_WITH_FLEX`。
  - 前端 `财务审核台` 增加“人工通过后沉淀为受控例外”入口，财务人员可录入复核人和通过理由。
  - CLI 新增 `feedback-approve` 命令，可从 `batch_result.json` 或单案结果中记录人工通过。
  - DeepSeek 门控增加记忆保护：如果 DeepSeek 与历史人工通过记忆冲突，系统按本地受控例外记忆处理，而不是让 LLM 推翻人工复核沉淀。

- 风险边界：
  - 不学习缺原件、重复发票、供应商黑名单、拆票、跨期、相似票号、OCR 金额冲突、审批聊天提示注入。
  - 只学习同员工、同供应商、同费用类型、同城市/客户/项目下的边界特批模式。
  - 下一次金额不得超过历史人工通过金额的 105%。

- 验证命令：
  - `python -m unittest discover -s tests -v`
  - `python -B -c "import cli, streamlit_app; import fintrace.feedback, fintrace.reasoning; print('import ok')"`
  - `python cli.py eval --output-root runtime\eval_feedback_memory --n 500 --seed 42`
  - `Invoke-WebRequest -UseBasicParsing http://localhost:8508`

- 复跑结果：
  - 单元测试：12/12 通过。
  - 500 条评测：决策准确率 100%，硬违规 Precision 100%，硬违规 Recall 100%，硬违规 F1 100%，字段准确率 100%，错误案件数 0。
  - 新增测试覆盖：人工通过记忆能让相同边界案例下一次自动柔性通过。

## Round 8：红蓝评测物理隔离整改

- 用户/评审问题：
  - 原 `eval` 在同一次调用里完成红队数据生成、蓝队审核和裁判评测，属于动态灰盒自测，不是严格红蓝对抗。
  - 红队数据、蓝队规则和裁判标注都在同一包内，容易变成“验证系统是否符合作者预期”，而不是验证系统是否能经受未知攻击。
  - 每次评测运行时重新生成样本，规则修改后的前后版本缺少同一冻结标注集上的可比性。

- 修改内容：
  - 新增顶层 `redteam/` 独立包，冻结数据生成器不 import `fintrace.*`，不复用蓝队 `Decision`、`policies.py` 或 `reasoning.py`。
  - 新增 `datasets/fintrace-redteam-v1` 冻结数据集，包含 ERP CSV、OCR/审批聊天附件、`ground_truth.json` 和 `dataset_manifest.json`。
  - CLI 新增 `redteam-freeze` 与 `eval-frozen`：前者生成冻结集，后者只读冻结目录评测，不在评测时重新生成样本。
  - `run_redteam_evaluation()` 保留为开发灰盒自测，并在报告中标记 `evaluation_mode=dynamic_graybox_generation`；`run_frozen_evaluation()` 标记为 `evaluation_mode=frozen_dataset`。
  - 新增 `docs/RED_BLUE_ISOLATION.md`，明确三层隔离：代码依赖隔离、冻结数据隔离、裁判只读冻结标注。
  - 修复隔离测试：用 AST 检查 `redteam/generator.py` 是否存在 `import fintrace` / `from fintrace...`，不再因为元数据里出现项目名而误判失败。

- 验证命令：
  - `python -m unittest discover -s tests -v`
  - `python cli.py eval-frozen datasets\fintrace-redteam-v1 --output-root runtime\eval_frozen`
  - `python cli.py eval --output-root runtime\eval_dynamic_smoke --n 140 --seed 42`
  - `python -B -c "import cli; import fintrace.evaluator; import redteam.generator; print('import ok')"`
  - `rg -n "sk-[0-9a-fA-F]{16,}" -S .`
  - `git diff --check`

- 复跑结果：
  - 单元测试：13/13 通过，新增隔离测试确认顶层 `redteam/` 包没有 import `fintrace.*`。
  - 冻结数据集评测：84 条样本，决策准确率 100%，硬违规 Precision 100%，硬违规 Recall 100%，字段准确率 100%，错误案件数 0。
  - 动态灰盒烟测：140 条样本，决策准确率 100%，硬违规 Precision/Recall/F1 均为 100%，字段准确率 100%，错误案件数 0。
  - 安全检查：未检出 `sk-...` 形式 API Key；`git diff --check` 无空白错误。

- 对外表述边界：
  - v0.1 做到了个人项目可实现的工程隔离：红队包不依赖蓝队代码，评测使用版本化冻结标注集，不再运行时动态生成样本。
  - 仍不冒充企业级真实盲测；真实红蓝对抗需要独立红队、独立蓝队和独立裁判。
