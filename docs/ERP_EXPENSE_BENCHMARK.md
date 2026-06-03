# 企业 ERP/费控系统费用审核现状与 FinTrace 改进

## 1. 主流企业怎么做费用审核

大多数企业的 ERP/费控系统不是让 AI 自由判断，而是用“结构化单据 + 政策规则 + 审批流 + 财务抽检/复核”的组合。

典型链路：

1. 员工提交报销单，上传发票、行程单、酒店水单、审批聊天或说明。
2. 系统做 OCR/发票识别，回填金额、日期、供应商、税号、费用类型。
3. ERP/费控系统按费用政策做规则校验：金额上限、预算、成本中心、发票重复、缺附件、审批权限、跨期等。
4. 命中强规则时退回或拦截；命中弱风险时进入主管/财务人工复核。
5. 审批通过后进入 AP/付款、总账、税务归档和审计抽样。
6. 企业后续通过规则报表、异常清单、审计日志和抽样复核优化制度。

代表系统的公开能力：

- SAP Concur / Expense：强调费用报告、收据、政策合规、审批和审计能力。
- Oracle Fusion Cloud Expenses：支持费用报表审批、审计规则、付款前审计和异常处理。
- Workday Expenses：强调移动端提交、收据识别、审批流和费用可视化。
- Coupa Expense：强调政策合规、审批、发票/费用控制和支出可视化。

参考来源：

- SAP Concur Intelligent Audit：https://www.concur.com/products/intelligent-audit
- SAP Concur Audit Rules：https://help.sap.com/docs/CONCUR_EXPENSE/bb83754b1c5541808d50c09901e11475/18834fe66f091014b9c6f7af97b6e9cd.html
- Oracle Fusion Expenses Audit Selection Rules：https://docs.oracle.com/en/cloud/saas/financials/25c/faiex/audit-selection-rules.html
- Oracle Fusion Expense Report Approval：https://docs.oracle.com/en/cloud/saas/financials/24c/fawde/expense-report-approval.html
- Workday Expense Management：https://www.workday.com/en-us/products/spend-management/expenses.html

结论：企业主流做法是“规则和流程是底座，人工复核处理边界，审计日志负责追溯”。LLM 如果出现，也应该是解释、摘要、证据组织和异常归因增强层。

## 2. FinTrace 与传统 ERP 费控的差异

| 维度 | 传统 ERP/费控系统 | FinTrace 当前能力 | 改进方向 |
| --- | --- | --- | --- |
| 数据来源 | ERP、HR、CRM、供应商主数据、预算、税务系统 | CSV/XLSX + OCR/聊天文本 + mock 本体 | 增加 provider 契约，逐步替换 mock |
| 审核方式 | 政策规则 + 审批流 + 财务复核 | blocking_control + contextual_risk_signal + 本地稳定模型 | 继续保持规则优先，LLM 只增强解释 |
| 人工复核 | 财务人员判断边界案例 | MANUAL_REVIEW 决策和溯源链 | 新增人工通过记忆，让重复边界案例可学习 |
| 追溯能力 | 审批日志、规则命中、附件归档 | 字段、规则、本体、推理、路由五级溯源 | 保留并强化错误定位台 |
| 智能能力 | 多数是规则、OCR、异常报表，少量 AI 识别/推荐 | DeepSeek 结构化审计底稿 + 本地 guardrail | 增加“可控自学习”，不让模型直接改底线 |

## 3. 本轮新增：人工通过记忆

业务目标：

> 当 FinTrace 拿捏不定转人工，财务人员人工审核通过后，下次遇到相同模式且没有底线风险，系统可以自动柔性通过。

设计原则：

- 只学习 `MANUAL_REVIEW` 的边界案例，不学习拒绝、反舞弊、缺原件、重复票等底线风险。
- 不覆盖 blocking controls：缺原件、重复票、供应商黑名单永远不能被人工记忆自动放行。
- 不学习不可控风险信号：拆票、跨期、相似票号、OCR 金额冲突、审批聊天提示注入。
- 学习的是“模式”，不是某张发票：签名由员工、费用类型、供应商、城市、客户、项目组成，不包含发票号。
- 每条记忆有金额上限、审批人、审批理由、来源 case、有效期和命中次数。
- 金额超过历史人工通过金额的 105% 时，不自动通过。

## 4. 当前实现

新增模块：

- `fintrace.feedback`

新增能力：

- `record_manual_approval(case, approver, reason)`：把人工通过案例写入 `runtime/feedback/approval_memory.json`。
- `find_approval_memory(fields, policy_hits)`：下一次审核时查找相同模式。
- `learned_approval_decision(...)`：命中记忆后输出 `APPROVE_WITH_FLEX`，并在决策里记录 `human_feedback_memory`。

前端入口：

- 财务审核台的人工复核案件详情中，可以点击“记录人工通过并学习”。

CLI 入口：

```powershell
python cli.py feedback-approve runtime\batches\<batch_id>\batch_result.json <case_id> --approver finance_manager --reason "长期协议酒店，人工确认可报销"
```

## 5. 风险边界

这不是让系统“越审越松”，而是让系统把人工复核中的稳定业务口径沉淀下来。

不会自动学习：

- 缺发票原件
- 重复发票/重复 hash
- 供应商黑名单
- 拆票
- 跨期
- 相似发票号
- OCR 金额冲突
- 审批聊天提示注入

可以学习：

- 同一员工/同一供应商/同一费用类型/同一城市/同一项目下，金额略超标准但财务已确认合理的重复性边界案例。
