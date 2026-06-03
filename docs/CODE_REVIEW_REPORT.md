# FinTrace 代码审核报告

> 审核视角：金蝶企业级 AI PM + Agent 开发者
> 审核日期：2026-06-03
> 审核范围：全量可读审阅，不修改任何代码

---

## 目录

1. [总体评价](#1-总体评价)
2. [架构与模块边界](#2-架构与模块边界)
3. [评测体系合理性](#3-评测体系合理性)
4. ["从作品到产品"断层分析](#4-从作品到产品断层分析)
5. [分类问题清单](#5-分类问题清单)
6. [改进路线图](#6-改进路线图)
7. [面试/演示策略建议](#7-面试演示策略建议)

---

## 1. 总体评价

### 评分维度矩阵

| 维度 | 评分 | 评语 |
|------|------|------|
| 架构设计 | ★★★★☆ | 双层状态机、条件路由、溯源设计成熟 |
| 代码质量 | ★★★☆☆ | 核心模块整洁，但存在超长函数、弱 Typing 和隐藏副作用 |
| 评测体系 | ★★★★☆ | 红蓝对抗 + 冻结回归体系完整，指标定义合理，但场景覆盖有盲区 |
| 文档质量 | ★★★★★ | 架构决策、流程图、迭代记录都很出色 |
| 前端完整度 | ★★★★☆ | Streamlit 界面专业，3 个 Tab 布局合理 |
| 企业级就绪度 | ★★☆☆☆ | 本地稳定模型策略正确，但跨平台、配置、部署、安全均有明显缺口 |
| 演示就绪度 | ★★★★☆ | Showcase 数据集 + 自动故事线 + 对比功能组合优秀 |

**一句话**：这是一个技术设计深度超出大部分个人作品的项目，但距离"直接放公司里用"还有约 40% 的企业化工程缺口。

---

## 2. 架构与模块边界

### 做对了的

1. **双层 LangGraph 状态机**（`pipeline.py` BatchGraph → `case_graph.py` CaseGraph）：批量调度与单案审查职责分离清晰。

2. **阻断控制直达路由**（`case_graph.py:25-33`）：条件路由 `route_after_policy` 让 blocking_control 跳过本体/LLM 层直送决策，这是企业费控底线逻辑的正确表达。

3. **TraceEvent 全链路埋点**（`tracing.py`）：每个节点都有 `trace_node` 上下文管理器，latency/status/errors/confidence 全部记录。这个对可观测性和调试极其重要。

4. **字段溯源设计**（`parser.py:FieldSource` + `schemas.py:FieldSource`）：字段值、来源 artifact_id、locator（row/linespan）、confidence、extraction_method 全记录。这是"可追溯"的核心数据模型。

5. **冷启动分级策略**（`reasoning.py:cold_start_decision`）：微超→柔性通过、巨超→拒绝、中间→人工复核，三档分级在冷启动场景下是正确的。批量采购/服务采购两个 business exception 也正确。

### 架构层面的问题

1. **CaseState 用 TypedDict 而非 dataclass**（`schemas.py:111-127`）：`total=False` 的 TypedDict 不做运行时校验，键不存在时静默返回 None。LangGraph 节点内大量 `working.get("key", {})` 来防御，说明类型约束不够强。这是 Python 3.11+ dataclass + `State.add_router` 能解决的问题。

2. **shared mutable state 通过 ThreadPoolExecutor 传递**（`pipeline.py:92-94`）：`list(pool.map(lambda case: run_case(case, working), case_index))` — `working` 是整个 `BatchState` dict 的浅拷贝，多个线程共享引用。目前没有发现写冲突（因为 `run_case` 新建 CaseGraph），但 debug_events 列表是共享的。需要显式深拷贝或明确只读协议。

3. **Ingestion 中 manifest/zip 遍历无上限**（`ingestion.py:52-70`）：`path.rglob("*")` 和 `zf.extractall(target)` 都没有文件数/大小上限。企业场景下一个大 ZIP 可能包含上万文件，需要加 `max_files` 和 `max_size` 约束。

4. **reasoning.py 超 500 行**（577 行）：`deterministic_decision`（88-199 行）和 `apply_llm_guardrails`（320-419 行）都在这个文件里。两个函数都超过 100 行且逻辑分支多，应拆为独立模块 `local_decision.py` 和 `guardrail.py`。

---

## 3. 评测体系合理性

### 评测设计亮点

1. **红蓝对抗隔离**（`evaluator.py:run_redteam_evaluation` vs `run_frozen_evaluation`）：动态生成（灰盒自测）和冻结数据集（严格红线）两种模式区分清楚。

2. **场景轮询设计**（`redteam.py:SCENARIOS`）：13 个场景覆盖了 clean、blocking（缺原件/重复票/黑名单）、contextual（拆票/跨期/相似票号/OCR冲突/提示注入）三大类。seed 隔离保证可复现。

3. **metric 定义合理**：hard_recall >= 99%, hard_precision >= 90%, field_accuracy >= 95%, flexible_accuracy >= 85%。这些目标既有挑战性又合理。

4. **部分失败策略**（`pipeline.py:124-172`）：单案失败不回滚批次，这是正确的企业级选择。`case_failed=True` 的容错是工业级的。

### 评测体系的关键盲区

1. **场景覆盖存在真实盲区**：
   - **多货币报销**：全部用 CNY，没有涉及 USD/JPY 汇率转换场景
   - **部分退回/红冲场景**：ERP 中常见的部分报销退回
   - **模糊日期格式**：2026/1/1 vs 2026-01-01 vs 2026年1月1日 混合场景
   - **集团多实体场景**：不同子公司费用政策不同
   - **高频正常 vs 低频攻击**：500 笔正常 + 1 笔异常，而非 50:50 的极端比例
   - **空批次/空文件/损坏文件**：异常路径未测试
   - **极端金额精度**：0.01 元 vs 9,999,999.99 元
   - **日本/韩国供应商名称**：全中文场景

2. **评测指标自身有缺陷**：
   - **`flexible_accuracy` 定义宽松**（`evaluator.py:151-154`）：只有 `flexible_allowed=True` 的 case 才计入分母，且只计算 APPROVE_WITH_FLEX 命中的。如果系统把需要用 flex 的场景误判为 APPROVE（自动通过），不会被惩罚。
   - **`manual_review_limit` 公式存在逻辑漏洞**（`evaluator.py:181`）：`max(int(total * 0.45), expected_manual_review_count + max(1, int(total * 0.05)))` — 这意味着人工复核率即使 45% 也算"可解释"，这个阈值太宽松了。
   - **没有时间性能评测**：`avg_node_latency_ms` 记录了但不作为目标指标。企业场景下批量 500 笔不能超过 5 分钟。需要有 time budget guard。

3. **冻结集缺乏"红线基准"**：`run_frozen_evaluation` 没有设计 regression comparison — 跑完新版本后自动对比硬指标是否退化。需要 "eval diff" 模式。

4. **`split_invoice` 场景的真实性问题**（`redteam.py:193-194`）：这个场景只生成了一行数据，没有生成同组的多张票。`split_group_count` 和 `split_group_total` 靠 `enrich_batch_features` 在批次级别计算。但既然只有一行，split_group 必须是 1，所以这个场景**实际上不会触发 R003**。仔细看逻辑：`split_group_count >= 2 and split_total > limit * 1.2` — 单行不会触发。这就是为什么 redteam 中没有 split_invoice 的明确测试断言在 evaluator 里检查。**这是一个实际的 bug 级别的盲区。**

5. **ocr_amount_noise 场景的重复性**：13 个场景轮询意味着如果 n=14，第 14 个 case 就是 clean 场景，和第一个 clean 场景重复。在 N=80 时 clean 场景会出现 6 次。虽然不影响功能，但在评测报告中需要 dedup 或标注。

---

## 4. "从作品到产品"断层分析

### 4.1 跨平台可复现性 (CRITICAL)

**现状**：
- `Start_FinTrace_Frontend.cmd` 用 Windows cmd
- `Start_FinTrace_Frontend_Desktop.cmd` 也用 Windows cmd
- `Makefile` 第 18 行硬编码 `python3` 和 `/bin/bash`
- `.venv` 是 Python 3.12 virtualenv（Windows 路径）
- `.playwright-cli/` 也有特定平台依赖

**缺口**：
- 没有 `pyproject.toml` 或 `setup.cfg`，只有两个 requirements.txt
- 没有 `docker-compose.yml` 或 Dockerfile
- 没有 environment.yml（conda）
- 没有 .python-version
- 没有说明在 macOS/Linux/Windows 上分别怎么跑

**Enterprise Severity：HIGH** — 跨平台不可复现意味着不能 CI/CD、不能容器化部署、团队成员加入成本高。

### 4.2 配置管理 (HIGH)

**现状**：
- `.env.local` 和 `.env` 通过 `local_env.py` 加载
- `config.py` 的 `Settings` dataclass 直接从 `os.getenv` 读取
- `.env.local` 传入 git（非 .gitignore 里）

**缺口**：
- 没有配置校验（API key 空时做什么？）
- 没有配置分层（dev/staging/prod）
- `.env.local` 里可能包含真实 API key，但没被 .gitignore 排除
- `deepseek_base_url` 和 `model` 通过环境变量覆盖，但没有 fallback 文档

**Enterprise Severity：HIGH** — 配置泄漏是安全事件。

### 4.3 安全与输入校验 (MEDIUM)

**现状**：
- ZIP 解压（`ingestion.py:65`）无路径遍历防护（Zip Slip 攻击）
- `load_local_env` 从项目根加载 .env 文件，无权限校验
- PDF/图片文本提取无超时 — 恶意 PDF 可挂死线程池

**建议**：
- ZIP 解压用 `zipfile.ZipFile.extractall` 前需检查文件名是否包含 `..`
- PDF 提取加 10 秒超时
- 文件上传大小上限

### 4.4 日志与监控 (HIGH)

**现状**：
- 只有 `tracing.py` 的调试级别追踪
- 没有结构化日志（不适用于日志聚合系统）
- `pipeline.py` 中 `case_dispatch_node` 没有 progress callback
- batch 运行中间状态不可从外部观察

**Enterprise Severity：HIGH** — 企业环境需要 SLI/SLO 监控、异常告警、审计日志。

### 4.5 错误处理与恢复 (MEDIUM)

**现状**：
- `pipeline.py:run_case` 的 try/except 捕获所有 Exception，但 message 截断到 500 字
- `tracing.py:trace_node` 在 except 后重新 raise，但依赖调用方正确处理
- 没有重试机制（外部 LLM 调用超时不重试）
- `failed_case_result` 生成完整的 MANUAL_REVIEW 回退，策略正确

**建议**：添加 retry（指数退避）、partial result 可合并机制。

---

## 5. 分类问题清单

### CRITICAL (2)

| # | 文件:行 | 问题 | 说明 |
|---|---------|------|------|
| C1 | `redteam.py:193-194` | split_invoice 场景只有一个 case，不会触发 R003 | 单行数据不可能有 split_group_count >= 2。要么生成多行，要么在评测标注中跳过对该规则的检查 |
| C2 | `ingestion.py:65-67` | ZIP 解压无 Zip Slip 防护 | 恶意 ZIP 可通过 `../` 路径覆盖项目文件。企业场景必须校验解压路径在目标目录内 |

### HIGH (8)

| # | 文件:行 | 问题 | 说明 |
|---|---------|------|------|
| H1 | 跨项目 | 无 pyproject.toml/无 Docker | 无法 CI/CD、容器化部署。这是"作品→产品"的第一堵墙 |
| H2 | `parser.py:47-152` | parse_case_fields 200+ 行 | 包含 ORC/聊天/金额冲突/提示注入/事由不匹配 5 种逻辑。应拆为 5 个子函数 |
| H3 | `streamlit_app.py` | 整个文件 1100+ 行 | 无状态组件拆分。可以用 st.Page 或更细粒度的模块化 |
| H4 | `.env.local` 未 gitignore | 真实 API key 可能泄漏 | 应添加 .env 到 .gitignore，并提供 .env.example 模板 |
| H5 | `evaluator.py:181` | manual_review_limit 公式过于宽松 | 45% 上限在真实企业是可接受的？应该至少降到 20-25% |
| H6 | `ingestion.py:52-70` | 无文件数/大小限制 | ZIP 解压和目录扫描可能 OOM 或占满磁盘 |
| H7 | `reasoning.py:12-56` | make_decision 流程缺少回退次数限制 | 目前回退很安全（回到本地模型），但理论上可以无限递归 |
| H8 | 跨项目 | 英语/中文混杂 | 函数名、变量名是英语，注释是中文，docstring 是中文。企业团队需要统一语言标准 |

### MEDIUM (12)

| # | 文件:行 | 问题 | 说明 |
|---|---------|------|------|
| M1 | `pipeline.py:92` | ThreadPoolExecutor 共享 BatchState 引用 | debug_events 列表存在潜在竞态 |
| M2 | `schemas.py:111-127` | TypedDict total=False 无运行时校验 | 应迁移到 dataclass 或 Pydantic |
| M3 | `policies.py:256-257` | expense_limit fallback 到 3000 | 未知费用类型无日志告警，silently 使用默认值 |
| M4 | `redteam.py:14-28` | 只有 13 种场景，缺少异常路径场景 | 见评测盲区列表 |
| M5 | `evaluator.py:151-154` | flexible_accuracy 分母过于乐观 | 只计算 flexible_allowed=True 的 case |
| M6 | `feedback.py:117-142` | find_approval_memory 非线程安全 | 多个 case 并发写入同一个 JSON 文件有竞态 |
| M7 | `reasoning.py:320-419` | apply_llm_guardrails 超过 100 行 | 门控逻辑应拆为独立模块 |
| M8 | `streamlit_app.py:757-768` | save_uploaded_files 无文件大小限制 | 超大文件可导致磁盘满 |
| M9 | `pipeline.py:124-172` | failed_case_result 硬编码中文 | 混合语言不利于国际化 |
| M10 | `requirements.txt` 无版本锁定 | 依赖项目可能会意外升级 | 需要 pip freeze 锁定 |
| M11 | `redteam.py:82` | write_invoice_attachment 每次硬覆盖 | 同批次内不可生成多个 variant |
| M12 | `ingestion.py:169-201` | load_table_rows 使用 eval 式列检测 | known_cols 硬编码中文列名，新增列宽支持差 |

### LOW (5)

| # | 文件:行 | 问题 | 说明 |
|---|---------|------|------|
| L1 | `config.py:24` | deepseek timeout 硬编码 20 秒 | 应从环境变量读取 |
| L2 | `parser.py:297-304` | safe_float 去除所有非数字字符 | 会吞掉负号拼接错误 |
| L3 | `storage.py:10` | utcish_stamp 实际是本地时间 | 命名误导 |
| L4 | `redteam.py:83-84` | 每个 case 生成两个附件 TXT，但 parser 只识别一个 | 两个文件会合并，但标注未考虑混合文本 |
| L5 | `Makefile:78-81` | clean 命令只清缓存不清 runtime | 历史评测数据永远不清理 |

---

## 6. 改进路线图

按"先演示效果 → 再工程加固 → 后企业化交付"三阶段排序：

### Phase 1: 演示优先 (建议 1-2 天)

| 序号 | 改进项 | 影响 | 关联问题 |
|------|--------|------|---------|
| P1-1 | 修复 split_invoice 场景，确保 case 数 >= 2 | 修复 redteam 评测的盲区 | C1 |
| P1-2 | 添加 .env.example 并 gitignore .env | 安全基线 | H4 |
| P1-3 | zip_safe_extract 防路径遍历 | 安全基线 | C2 |
| P1-4 | 添加 docker-compose.yml + Dockerfile | 一键演示 | H1 |
| P1-5 | 添加 Makefile windows target + setup.bat | 跨平台 | 环境断层 |

### Phase 2: 工程加固 (建议 3-5 天)

| 序号 | 改进项 | 影响 |
|------|--------|------|
| P2-1 | 拆 parser.py 为子模块（ocr_fields / chat_guardrail / amount_conflict / purpose_mismatch） | 可维护性 |
| P2-2 | 拆 reasoning.py 为 local_decision.py + guardrail.py + deepseek_client.py | 可测试性 |
| P2-3 | CaseState 从 TypedDict 迁移到 dataclass + validate | 类型安全 |
| P2-4 | 添加 Pydantic settings（BaseSettings → .env → env var 三层） | 配置管理 |
| P2-5 | 添加保留拼音的结构化日志（logging + json handler） | 可观测性 |
| P2-6 | 添加重试装饰器（指数退避，max_retries=3） | 健壮性 |
| P2-7 | feedback 写入改为 file lock 或 sqlite | 线程安全 |

### Phase 3: 企业化交付 (建议 1-2 周)

| 序号 | 改进项 | 影响 |
|------|--------|------|
| P3-1 | pytest + coverage + benchmark 门控 CI | 质量保证 |
| P3-2 | 评测回归对比（eval diff: 新版 vs 基线指标对比） | 评测权威性 |
| P3-3 | 扩展场景覆盖（多货币/多实体/异常路径/batch of 1/edge cases） | 评测完整性 |
| P3-4 | 添加 performance benchmark（N=100/500/1000 的批处理时间） | 性能基线 |
| P3-5 | Streamlit 添加自定义费用政策配置页（而非硬编码 JSON） | 可配置性 |
| P3-6 | LLM 调用添加 Cost Tracking | 成本管理 |
| P3-7 | 添加角色权限模型（财务审核员/财务经理/合规/管理员） | 权限控制 |

---

## 7. 面试/演示策略建议

### 当前演示的最佳路径

1. **开篇**（30 秒）："这是一个处理企业报销审核的 Agent，核心设计是本地稳定模型 + 可溯源审计链"
2. **架构图**（60 秒）：指着 FINTRACE_FLOW.md 的 mermaid 图，讲 BatchGraph→CaseGraph 双层状态机
3. **演示**（120 秒）：双击 Start_FinTrace_...cmd → 加载示例批次 → 展示"批量审核→查原因→案例对比"三个 Tab
4. **亮点**（60 秒）：冷启动分级策略（微超 flex / 巨超 reject）、阻断控制 vs 上下文风险信号的区别、溯源视图
5. **评测**（30 秒）：红蓝对抗 + 冻结回归，hard_recall >= 99%

### 面试中应该主动说出来的"我知道缺点"

```
- "扫描 ZIP 还没有防路径穿越，企业要用需要加上"
- "评测场景还缺多货币和多实体场景，这是当前最大的覆盖盲区"
- "跨平台可复现性还有问题，需要 Docker 化才能让团队一键运行"
- "600 行以上的长函数在我优先级列表里，但先保证了功能完整和评测到位"
```

这比面试官发现后追问要好得多。主动说出"我知道还有哪些地方不够企业级"，是 Senior 思维的表现。

### 需要准备的 Q&A

| 问题 | 一句话回答 | 深度回答方向 |
|------|-----------|-------------|
| "为什么用 LangGraph 而不是简单规则引擎？" | "规则引擎不能支持条件路由和链式 Trace — 我需要每个 case 的可追溯审计链" | 每个节点输出 TraceEvent |
| "断电断网怎么办？" | "本地稳定模型是默认模式，不依赖外部 LLM，断网不影响核心链路" | `make_decision` 的双层 fallback |
| "怎么确保评测可信？" | "红蓝隔离：冻结数据集不重新生成，且红队生成器和蓝队代码在独立模块中" | evaluator.py 的 metrics 定义 |
| "支持高并发吗？" | "目前是单机线程池，4 workers 内线性扩展。企业级需要 Celery + 消息队列" | 知道差距 |
| "怎么扩展新规则？" | "在 policies.py 加一条 PolicyHit → reasoning.py 在 deterministic_decision 加分支 → 确定 guardrail_status" | 扩展性设计 |

---

## 附录：文件行数统计

| 文件 | 行数 | 类别 |
|------|------|------|
| streamlit_app.py | 1100+ | 前端 |
| reasoning.py | 577 | 核心推理 |
| ingestion.py | 515 | 数据接入 |
| redteam.py | ~320 | 红队数据 |
| policies.py | 292 | 规则引擎 |
| parser.py | 305 | 字段解析 |
| fintrace/insights.py | 284 | 业务逻辑 |
| fintrace/showcase.py | 380 | 展示逻辑 |
| evaluator.py | 219 | 评测 |
| pipeline.py | 242 | 批量调度 |
| feedback.py | 199 | 人工反馈 |
| case_graph.py | 168 | 单案状态机 |
| ontology.py | 182 | 本体 |
| cli.py | 132 | CLI入口 |
| config.py | 31 | 配置 |
| schemas.py | 150 | 数据模型 |
| tracing.py | 77 | 追踪 |
| storage.py | 37 | IO |
| test_fintrace_core.py | 638 | 测试 |

---

*审核结束。FinTrace 有非常扎实的架构基础和评测体系，"20% 产品化缺口"是可以专注填补的已知地带。*
