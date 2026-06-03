# FinTrace

FinTrace 是一个中文企业级批量费控审查 Agent。评审整改后，它的产品边界更清楚：

- **v0.1 MVP 主链路**：`CSV/XLSX 批量导入 -> 字段溯源 -> 本地稳定模型/规则审查 -> 可解释结果导出`
- **v0.2 展示与增强能力**：面向财务人员的 Streamlit 审核台、DeepSeek 结构化审计底稿、红蓝评测、高仿真演示数据

FinTrace 不试图一开始替代 ERP 或财务终审。它先解决批量报销初筛中最痛的两件事：风险先筛出来，错误能追回去。

---

## 快速开始

### 方式一：Docker（推荐，跨平台）

```bash
# 1. 构建并启动
docker compose up fintrace-frontend

# 2. 打开浏览器访问 http://localhost:8509
# 3. 在界面中点击「加载示例批次」
```

其他 Docker 命令：

```bash
# 运行评测
docker compose up fintrace-eval

# 运行单元测试
docker compose up fintrace-test

# CLI 模式（接收子命令）
docker compose run --rm fintrace-cli --help
docker compose run --rm fintrace-cli eval --n 80 --seed 42

# 仅构建（不启动）
docker compose build
```

### 方式二：Windows 原生

```batch
:: 首次设置
setup.bat

:: 启动 Web 界面
Start_FinTrace_Frontend.cmd
```

### 方式三：Linux / macOS 原生

```bash
# 首次设置
make setup
source .venv/bin/activate

# 启动 Streamlit
streamlit run streamlit_app.py --server.port=8509

# 或使用 Makefile
make docker  # Docker 方式
```

---

## 配置

复制 `.env.example` 为 `.env`，填入可选配置：

```bash
cp .env.example .env
```

| 环境变量 | 必需？ | 说明 |
|---------|--------|------|
| `DEEPSEEK_API_KEY` | 否 | 留空则只使用本地稳定模型（推荐初次运行） |
| `DEEPSEEK_BASE_URL` | 否 | 默认 https://api.deepseek.com/v1 |
| `DEEPSEEK_MODEL` | 否 | 默认 deepseek-chat |
| `LANGSMITH_API_KEY` | 否 | 可选，用于 LangSmith 追踪 |
| `FINTRACE_APPROVAL_MEMORY_PATH` | 否 | 人工反馈记忆存储路径 |

---

## 运行评测

```bash
# 单元测试
python -m unittest discover -s tests -v

# 动态红队评测（n=80，seed=42）
python cli.py eval --output-root runtime/eval_review_fix --n 500 --seed 42

# 冻结集回归
python cli.py eval-frozen datasets/fintrace-redteam-v1 --output-root runtime/eval_frozen
python cli.py eval-frozen datasets/showcase_fintrace_v1 --output-root runtime/showcase_eval

# 或使用 Makefile
make quickcheck          # AST + 单元测试
make regression          # 全量回归
make docker-test         # Docker 环境下的测试
make docker-eval         # Docker 环境下的评测
```

### 目标指标

| 指标 | 目标 |
|------|------|
| 硬违规 Recall | >= 99% |
| 拒绝/升级 Precision | >= 90% |
| 关键字段抽取准确率 | >= 95% |
| 柔性放行准确率 | >= 85% |
| 人工复核比例 | 可解释，不靠误杀堆高风控 |

---

## 运行产物

每次批处理都会写入 `runtime/batches/<batch_id>/`：

- `manifest.json` — 文件清单
- `case_index.json` — 案件索引
- `batch_metrics.json` — 聚合指标
- `error_registry.json` — 错误注册表
- `batch_result.json` — 完整批处理结果
- `traces.jsonl` — 全链路追踪事件
- `cases/<case_id>/case_result.json` — 单案结果

如果结论不准，可以沿着字段、规则、本体、推理、路由和错误定位台快速判断问题来自哪里。

---

## 文档入口

- [MVP 范围说明](docs/MVP_SCOPE.md)
- [流程图](docs/FINTRACE_FLOW.md)
- [企业本体冷启动方案](docs/ONTOLOGY_COLD_START.md)
- [企业数据对接契约](docs/ENTERPRISE_INTEGRATION.md)
- [企业 ERP 费控对标与智能改进](docs/ERP_EXPENSE_BENCHMARK.md)
- [红蓝对抗隔离说明](docs/RED_BLUE_ISOLATION.md)
- [Claude 红方整改报告](docs/RED_ATTACK_V1_REMEDIATION_REPORT.md)
- [路线图](docs/ROADMAP.md)
- [外展示操作手册](docs/SHOWCASE_SCRIPT.md)
- [架构决策记录](docs/ARCHITECTURE_DECISIONS.md)
- [迭代记录](docs/ITERATION_LOG.md)
- [代码审核报告](docs/CODE_REVIEW_REPORT.md)

---

## 项目结构

```
FinTrace/
├── fintrace/            # 核心 Python 包
│   ├── pipeline.py      # BatchGraph 批量调度
│   ├── case_graph.py    # CaseGraph 单案状态机
│   ├── parser.py        # 字段抽取与溯源
│   ├── policies.py      # 14 条费控规则
│   ├── reasoning.py     # 本地稳定模型 + DeepSeek 门控
│   ├── ontology.py      # 企业本体（节假日/客户/员工/供应商）
│   ├── feedback.py      # 人工反馈学习
│   ├── evaluator.py     # 评测框架
│   ├── redteam.py       # 红队数据生成
│   ├── showcase.py      # 展示逻辑
│   ├── insights.py      # 业务诊断
│   └── tracing.py       # 全链路追踪
├── streamlit_app.py     # Streamlit Web 前端
├── cli.py               # CLI 入口
├── redteam/             # 独立红队生成器（无 fintrace 依赖）
├── datasets/            # 冻结评测数据集
├── docs/                # 文档
├── runtime/             # 运行时产物（gitignore）
├── tests/               # 单元测试
├── Dockerfile           # Docker 构建
├── docker-compose.yml   # Docker Compose 编排
├── pyproject.toml       # Python 项目元数据
├── Makefile             # 自动化编排
└── setup.bat            # Windows 环境设置
```
