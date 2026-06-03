# FinTrace 流程图

这份流程图用于 GitHub 展示、面试讲解和录屏截图。整改后的核心表达是：v0.1 先跑通批量导入、字段溯源、本地稳定审查和可解释导出；DeepSeek、Streamlit 和红蓝评测是 v0.2 展示与增强能力。

## 1. MVP 与增强能力分层

```mermaid
flowchart LR
    A["v0.1 MVP 输入<br/>ERP CSV/XLSX / 本地目录"] --> B["批量接入<br/>Manifest 扫描"]
    B --> C["案件归并<br/>ERP 行 + 附件文本"]
    C --> D["字段溯源<br/>字段值、来源、row/span、置信度"]
    D --> E["本地稳定模型<br/>阻断控制 + 上下文风险信号 + 冷启动门控"]
    E --> F["可解释结果导出<br/>batch_result / case_result / traces.jsonl"]

    G["v0.2 展示增强<br/>财务审核台 + 诊断与优化台"] -.-> F
    H["v0.2 LLM 增强<br/>DeepSeek 结构化审计底稿"] -.-> E
    I["v0.2 评测增强<br/>红蓝评测 / 高仿真数据"] -.-> F
```

## 2. 端到端批量审查流程

```mermaid
flowchart LR
    A["输入层<br/>多文件上传 / ZIP / 本地目录路径"] --> B["批量接入<br/>Batch Ingestion"]
    A1["ERP 导出<br/>CSV / XLSX"] --> B
    A2["异构附件<br/>OCR 文本 / PDF / 图片 / 审批聊天"] --> B

    B --> C["Manifest 扫描<br/>文件类型、哈希、大小、状态"]
    C --> D["案件归并<br/>按报销单号、员工、日期、发票号归并 case"]
    D --> E["批量调度<br/>BatchGraph 调度多个 CaseGraph"]

    E --> F["单案审查<br/>Parser / OCR"]
    F --> G["阻断控制<br/>缺原件、精确重复票、供应商黑名单"]
    F --> H["上下文风险信号<br/>超金额、拆票、跨期、相似票号、OCR 金额冲突"]
    G --> I{"是否命中阻断控制？"}
    I -->|是| J["拒绝 / 反舞弊升级<br/>不允许 LLM 覆盖"]
    I -->|否| K["企业本体上下文<br/>节假日、客户等级、员工信用、供应商风险、context_quality"]
    H --> K
    K --> L["本地稳定模型<br/>冷启动保守门控 + 柔性阈值"]
    L --> M["可选 DeepSeek<br/>只生成结构化审计底稿，需通过合规门控"]
    M --> N["最终决策<br/>自动通过 / 柔性通过 / 人工复核 / 拒绝 / 反舞弊升级"]

    J --> O["Trace Export<br/>字段、规则、本体、推理、路由、错误全部落盘"]
    N --> O
    O --> P["前端/报告<br/>财务审核台、诊断与优化台、评测与迭代"]
```

## 3. 双层 LangGraph 状态机

```mermaid
flowchart TB
    subgraph BG["BatchGraph：批量层"]
        B1["batch_ingestion<br/>扫描路径、展开 ZIP、生成文件清单"] --> B2["case_assembly<br/>把 ERP 行和附件归并为案件包"]
        B2 --> B3["case_dispatch<br/>同步调度多个 CaseGraph，单案失败不回滚批次"]
        B3 --> B4["batch_aggregate<br/>聚合决策分布、耗时、成功/失败数和错误类型"]
        B4 --> B5["trace_export<br/>导出 batch_result、traces.jsonl、case_result"]
    end

    subgraph CG["CaseGraph：单案层"]
        C1["parser<br/>结构化字段抽取 + 字段级 provenance"] --> C2["policy<br/>阻断控制 + 上下文风险信号"]
        C2 --> C3{"条件路由"}
        C3 -->|reject / fraud_escalation| C6["decision<br/>阻断控制直达结论"]
        C3 -->|need_context| C4["context<br/>企业本体 + context_quality"]
        C4 --> C5["reasoning<br/>本地稳定模型 / DeepSeek 门控"]
        C5 --> C6
    end

    B3 --> CG
    CG --> B4
```

## 4. 可溯源调试链路

```mermaid
flowchart LR
    A["原始材料<br/>ERP 行、OCR、聊天记录、PDF/图片"] --> B["字段级溯源<br/>字段值、来源文件、row/span、置信度"]
    B --> C["规则级溯源<br/>rule_id、rule_class、阈值、计算过程、命中原因"]
    C --> D["本体级溯源<br/>数据来源、冷启动项、缺失项、维护责任"]
    D --> E["推理级溯源<br/>本地基准、LLM 门控、证据引用、置信度"]
    E --> F["路由级溯源<br/>reject / flex_approve / manual_review / fraud_escalation"]
    F --> G["错误定位台<br/>OCR 错误、字段缺失、规则误杀、上下文缺失、LLM JSON、路由异常"]
```

## 5. 本地稳定模型决策流

```mermaid
flowchart TB
    A["输入<br/>parsed_fields + policy_hits + context_info"] --> B{"是否命中 blocking_control？"}
    B -->|缺原件| C["REJECT<br/>直接拒绝"]
    B -->|重复票 / 黑名单供应商| D["ESCALATE_FRAUD<br/>反舞弊升级"]
    B -->|否| E{"是否命中 contextual_risk_signal？"}
    E -->|拆票 / 跨期 / 相似票号 / OCR金额冲突| F["MANUAL_REVIEW<br/>人工复核，不直接硬拒绝"]
    E -->|仅金额超标或无风险信号| G["读取企业本体<br/>费用基准、节假日、客户、员工、供应商"]
    G --> H{"context_quality 是否允许柔性通过？"}
    H -->|否，冷启动或缺关键上下文| I["MANUAL_REVIEW<br/>不自动批准超标案件"]
    H -->|是| J["计算柔性阈值<br/>base_limit × max(节假日倍率, 客户倍率)"]
    J --> K{"金额是否在静态标准内？"}
    K -->|是| L["APPROVE<br/>自动通过"]
    K -->|否| M{"金额 <= 柔性阈值<br/>且员工信用 >= 70<br/>且供应商非高危？"}
    M -->|是| N["APPROVE_WITH_FLEX<br/>柔性通过并记录本体因子"]
    M -->|边界金额或低信用| O["MANUAL_REVIEW<br/>转人工复核"]
    M -->|明显超阈值| P["REJECT<br/>上下文不足以支持放行"]
```

## 讲解口径

- 面向产品：v0.1 先服务财务审核员的批量初筛和错误定位，v0.2 再服务作品集展示和 LLM 增强。
- 面向风控：阻断控制只处理无歧义风险；拆票、跨期、相似发票号等进入上下文风险信号，避免误杀。
- 面向工程：BatchGraph 负责批量调度，CaseGraph 负责单案状态机，每个节点都输出 `TraceEvent`。
- 面向评测：红队生成高仿真 ERP 批次和异构附件，裁判器输出 Precision、Recall、F1、字段准确率和 case 级错误归因。
