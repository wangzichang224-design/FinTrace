# FinTrace 企业数据对接契约

FinTrace v0.1 仍然以 ERP 导出的 `CSV/XLSX` 和 mock 本体为主，但真实企业落地时不能只靠硬编码字典。本文定义 v0.2 需要对接的数据源、最小字段、刷新频率和冷启动兜底，避免“企业本体”停留在概念层。

## 1. 数据源边界

| 数据源 | 用途 | 最小字段 | 维护方 | 建议刷新 |
| --- | --- | --- | --- | --- |
| ERP/费控系统 | 报销主数据、费用类型、金额、发票号、审批状态 | reimbursement_id, employee_id, expense_type, amount, invoice_no, vendor, expense_date, approver | 财务共享中心 / IT | 每批导出或 API 实时 |
| HR 员工主数据 | 员工部门、成本中心、信用分、历史退回记录 | employee_id, department, cost_center, credit_score, reject_count_90d | HRBP / 财务共享中心 | 每日或每周 |
| CRM 客户主数据 | 客户战略等级、接待标准上浮倍数 | client_id, client_name, priority, multiplier, valid_from, valid_to | 销售运营 / CRM 管理员 | 每周或客户等级变更时 |
| 供应商主数据 | 供应商风险、黑名单、工商异常、历史争议 | vendor_name, tax_no, risk_level, blacklist_flag, dispute_count | 采购 / 内控 / 法务 | 每日或风险事件触发 |
| 费用政策表 | 费用类型、城市、职级、金额阈值 | expense_type, city, employee_grade, base_limit, effective_date | 财务制度负责人 | 半年或制度变更时 |
| 节假日/城市指数 | 柔性阈值、酒店/交通价格波动 | date, city, category, multiplier, source | 财务政策负责人 | 年度节假日 + 季度旺季 |

## 2. 接口输入建议

v0.2 可以保留文件导入，同时增加可替换 provider 接口：

```python
class ContextProvider:
    def get_employee_credit(self, employee_id: str) -> dict: ...
    def get_client_priority(self, client_id: str, client_name: str = "") -> dict: ...
    def get_vendor_risk(self, vendor_name: str, tax_no: str = "") -> dict: ...
    def get_category_benchmark(self, expense_type: str, city: str = "", employee_grade: str = "") -> dict: ...
    def get_holiday_index(self, expense_date: str, city: str = "") -> dict: ...
```

每个 provider 返回值必须包含：

- `source_type`：`erp_api`、`hr_api`、`crm_api`、`vendor_registry`、`policy_table`、`mock_*`、`missing`、`cold_start_default`
- `source`：系统名或文件名
- `owner`：业务维护责任人
- `refresh_frequency`：刷新频率
- `confidence`：数据可信度
- `reason`：业务解释

## 3. 冷启动策略

冷启动时 FinTrace 不做激进自动放行：

- 缺员工信用、供应商风险或费用基准：超标准案件转 `MANUAL_REVIEW`。
- 缺客户等级：按普通客户处理，不允许战略客户特批上浮。
- 缺节假日指数：按 1.0 倍处理，避免用虚假旺季理由放行。
- 命中阻断控制：不依赖本体，直接拒绝或反舞弊升级。

## 4. 当前 v0.1 已修复的可信度问题

- CSV 读取增加 `utf-8-sig`、`utf-8`、`gb18030`、`gbk` 兜底，兼容国内 ERP 常见编码。
- 附件匹配改为带边界的精确 token 匹配，降低发票号重叠导致的错配。
- 金额解析支持 `RMB`、`CNY`、`¥/￥`、中文逗号和千分位格式。
- 审批聊天中的“忽略制度/立即批准/绕过审核”等提示注入话术会进入上下文风险信号，默认人工复核。
- 供应商黑名单和本体供应商高危判断共用同一组高危 token，避免规则层和本体层口径不一致。
