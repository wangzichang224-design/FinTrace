# FinTrace 流程图

这份流程图用于 GitHub 展示、面试讲解和录屏截图。FinTrace 的核心不是单张票据问答，而是“批量案件进入系统后，每笔报销都有可追踪的证据链、规则链、本体链、推理链和错误定位链”。

## 1. 端到端批量审查流程

```mermaid
flowchart LR
    A["输入层<br/>多文件上传 / ZIP / 本地目录路径"] --> B["批量接入<br/>Batch Ingestion"]
    A1["ERP 导出<br/>CSV / XLSX"] --> B
    A2["异构附件<br/>OCR 文本 / PDF / 图片 / 审批聊天"] --> B

    B --> C["Manifest 扫描<br/>文件类型、哈希、大小、状态"]
    C --> D["案件归并<br/>按报销单号、员工、日期、发票号归并 case"]
    D --> E["批量调度<br/>BatchGraph 调度多个 CaseGraph"]

    E --> F["单案审查<br/>Parser / OCR"]
    F --> G["硬规则审查<br/>缺原件、重复票、拆票、跨期、高危供应商"]
    G --> H{"是否硬拦截？"}
    H -->|是| I["拒绝 / 反舞弊升级<br/>不再调用 LLM 覆盖底线"]
    H -->|否| J["企业本体上下文<br/>节假日指数、客户等级、员工信用、供应商风险"]
    J --> K["柔性推理<br/>本地稳定模型或 DeepSeek 结构化判断"]
    K --> L["最终决策<br/>自动通过 / 柔性通过 / 人工复核 / 拒绝 / 反舞弊升级"]

    I --> M["Trace Export<br/>字段、规则、路由、推理、错误全部落盘"]
    L --> M
    M --> N["Streamlit 控制台<br/>案件列表、审计探针、字段溯源、规则调试、批量指标"]
    M --> O["红蓝评测<br/>Precision / Recall / F1 / 字段准确率 / 错误归因"]
```

## 2. 双层 LangGraph 状态机

```mermaid
flowchart TB
    subgraph BG["BatchGraph：批量层"]
        B1["batch_ingestion<br/>扫描路径、展开 ZIP、生成文件清单"] --> B2["case_assembly<br/>把 ERP 行和附件归并为案件包"]
        B2 --> B3["case_dispatch<br/>线程池同步调度多个 CaseGraph"]
        B3 --> B4["batch_aggregate<br/>聚合决策分布、耗时、节点失败和错误类型"]
        B4 --> B5["trace_export<br/>导出 batch_result、traces.jsonl、case_result"]
    end

    subgraph CG["CaseGraph：单案层"]
        C1["parser<br/>结构化字段抽取 + 字段级 provenance"] --> C2["hard_policy<br/>硬规则命中 + 规则级 provenance"]
        C2 --> C3{"条件路由"}
        C3 -->|reject / fraud_escalation| C6["decision<br/>硬规则直达结论"]
        C3 -->|need_context| C4["context<br/>调用企业本体工具"]
        C4 --> C5["reasoning<br/>本地稳定模型 / DeepSeek JSON 审计底稿"]
        C5 --> C6
    end

    B3 --> CG
    CG --> B4
```

## 3. 可溯源调试链路

```mermaid
flowchart LR
    A["原始材料<br/>ERP 行、OCR、聊天记录、PDF/图片"] --> B["字段级溯源<br/>字段值、来源文件、row/span、置信度"]
    B --> C["规则级溯源<br/>rule_id、版本、阈值、计算过程、命中原因"]
    C --> D["本体级溯源<br/>节假日、客户等级、员工信用、供应商风险"]
    D --> E["推理级溯源<br/>结构化审计底稿、证据引用、置信度、复核原因"]
    E --> F["路由级溯源<br/>reject / flex_approve / manual_review / fraud_escalation"]
    F --> G["错误定位台<br/>OCR 错误、字段缺失、规则误杀、上下文缺失、LLM JSON、路由异常"]
```

## 4. 本地稳定模型决策流

```mermaid
flowchart TB
    A["输入<br/>parsed_fields + policy_hits + context_info"] --> B{"是否命中严重硬规则？"}
    B -->|重复发票 / 高危供应商| C["ESCALATE_FRAUD<br/>反舞弊升级"]
    B -->|缺少发票原件| D["REJECT<br/>直接拒绝"]
    B -->|否| E["读取费用基准<br/>category_benchmark.base_limit"]
    E --> F["计算柔性阈值<br/>base_limit × max(节假日倍率, 客户倍率)"]
    F --> G{"是否存在不可覆盖人工复核规则？"}
    G -->|拆票 / 跨期 / 相似发票号| H["MANUAL_REVIEW<br/>保留人工判断空间"]
    G -->|否| I{"金额是否在静态标准内？"}
    I -->|是| J["APPROVE<br/>自动通过"]
    I -->|否| K{"金额 <= 柔性阈值<br/>且员工信用 >= 70<br/>且供应商非高危？"}
    K -->|是| L["APPROVE_WITH_FLEX<br/>柔性通过并记录本体因子"]
    K -->|边界金额或低信用| M["MANUAL_REVIEW<br/>转人工复核"]
    K -->|明显超阈值| N["REJECT<br/>上下文不足以支持放行"]
```

## 讲解口径

- 面向业务：FinTrace 先守住硬性内控底线，再用企业本体做柔性判断，避免“一刀切”和“黑盒放行”。
- 面向工程：BatchGraph 负责批量调度，CaseGraph 负责单案状态机，每个节点都输出 `TraceEvent`。
- 面向评测：红队生成高仿真 ERP 批次和异构附件，裁判器输出 Precision、Recall、F1、字段准确率和 case 级错误归因。
- 面向调试：如果结论错了，可以沿着字段、规则、本体、推理、路由五条链快速定位问题点。
