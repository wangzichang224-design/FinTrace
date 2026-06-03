# FinTrace 架构决策记录

## ADR-001：为什么使用双层 LangGraph

**Status**：Accepted

**Context**：FinTrace 同时有批量调度和单案审查两类流程。批量层关注 manifest、case assembly、并发调度和指标聚合；单案层关注字段抽取、规则、本体、推理和决策。

**Decision**：采用 `BatchGraph + CaseGraph` 双层状态机。

**Alternatives**：

- 简单 for-loop：实现快，但节点边界和 trace 不清晰，难以展示错误定位链。
- 普通 DAG 调度：能跑批量任务，但条件路由、节点状态和可视化解释弱。

**Consequences**：LangGraph 对 v0.1 不是“必须”，但它让作品集能展示产业级 Agent 的状态、路由和可观测性。MVP 仍可退化为规则引擎 + 决策树。

## ADR-002：为什么本地稳定模型是基准

**Status**：Accepted

**Context**：财务场景不能依赖 LLM 幻觉，且企业网络、Key、成本和合规限制都可能导致外部模型不可用。

**Decision**：把本地稳定模型作为默认决策基准。它由阻断控制、上下文风险信号、费用阈值、本体质量和人工复核策略组成。

**Consequences**：同样输入得到同样输出，便于红蓝评测和回归测试。DeepSeek 只能增强审计底稿，不能覆盖本地基准和阻断控制。

## ADR-003：为什么 DeepSeek 是增强层

**Status**：Accepted

**Context**：LLM 在费控里的价值不是“替财务拍板”，而是总结证据、生成审计底稿、解释边界 case。

**Decision**：DeepSeek 输出必须经过结构化 JSON 校验、证据引用校验、置信度门控、本地基准一致性校验和阻断控制校验。

**Consequences**：如果 LLM 低置信度、缺证据、与本地模型冲突或试图覆盖阻断控制，系统回退或转人工复核。

## ADR-004：为什么 Streamlit 和红蓝评测后置

**Status**：Accepted

**Context**：评审指出 MVP 需要更克制。Streamlit 和红蓝评测对首个可用版本不是必要条件，但对作品集展示、录屏和面试讲解很重要。

**Decision**：把 `run` CLI 定义为 MVP 主链路，把 Streamlit 和 `eval` 定义为 v0.2 展示/评测能力。

**Consequences**：产品叙事更清楚：先证明“批量初筛和可溯源”有价值，再展示“LLM 增强、前端控制台、红蓝评测”如何提高可信度和可讲述性。
