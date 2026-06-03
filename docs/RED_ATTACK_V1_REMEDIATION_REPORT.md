# FinTrace red_attack_v1 整改报告

日期：2026-05-30  
数据集：`datasets/red_attack_v1`  
来源：Claude 红方上传数据沉淀后的冻结回归集  
定位：独立红方样本暴露问题 -> 错误归因 -> 规则/门控定向修复 -> 冻结集复测

## 一、本轮红方结论

红方报告中的核心判断成立：FinTrace 的阻断控制层较稳，但本地稳定模型在冷启动、审批完整性和异常金额上存在缺口。原型在“能不能拦住底线风险”上表现不错，但在“拿捏不定时怎么分层处理”上需要更像真实财务审核。

本轮不把问题归因给 prompt，而是落到四类工程修复：

- 基础风险规则补齐：审批状态、金额异常。
- 冷启动策略重画：微超、巨超、战略客户、批量采购、服务采购分别处理。
- 规则配置化：费用限额、黑名单、审批状态、冷启动阈值和关键词从 JSON 配置读取。
- 回归标准化：Claude 红方数据集冻结为 `red_attack_v1`，后续不再运行时重生成。

## 二、已修复问题

### P0-1 无审批状态检测

新增 `R010_APPROVAL_INCOMPLETE`。审批状态为空、未审批、审批中、待审批、驳回、pending、rejected 等不再自动通过，而是作为高风险上下文信号转人工复核。

### P0-2 零金额/异常金额无保护

新增 `R011_ABNORMAL_AMOUNT`。金额缺失、无法解析、`<= 0` 会进入人工复核。Parser 同步记录“金额异常”错误，方便在诊断台定位是字段抽取问题还是业务录入问题。

### P0-3 冷启动一刀切

冷启动不再只看 `amount > base`：

- 微超 `<= 5%` 且无非金额风险：`APPROVE_WITH_FLEX`。
- 巨超 `> 50%` 且缺少明确本体支撑：`REJECT`。
- S/A 客户招待在客户倍数内：可柔性通过。
- 办公批量采购在配置倍数内、审批完整、供应商非高危：可自动通过。
- 服务采购/咨询类大额支出：不直接拒绝，转人工核验合同、报告和验收材料。

### P1-1 规则外部配置化

新增 `fintrace/default_policy_rules.json` 和 `fintrace/policy_config.py`。企业可通过 `FINTRACE_POLICY_OVERRIDES_PATH` 或 `runtime/policy_overrides.json` 覆盖默认规则，不需要改代码。

可配置项包括：

- 费用限额
- 供应商黑名单 token
- 审批完成/未完成状态
- 冷启动微超/巨超阈值
- 批量采购关键词和倍数上限
- 服务采购关键词和人工复核倍数

### P1-2 回归流水线

新增 `scripts/run_regression.ps1`，一次运行：

- 单元测试
- 内置冻结红队集 `fintrace-redteam-v1`
- Claude 红方冻结集 `red_attack_v1`
- 指标摘要输出

## 三、评测口径变化

`red_attack_v1` 的人工复核比例较高，因为它本身是红方攻击集，不是自然业务流量。评测器不再用固定 `45%` 卡死所有数据集，而是结合数据集标注中“预期人工复核”的数量判断人工复核比例是否可解释。

这避免把攻击集误判为“人工复核比例失控”，同时仍保留对自然流量评测的风险约束。

## 四、复测结果

本轮回归命令：

```powershell
python -m unittest discover -s tests -v
python cli.py eval-frozen datasets\fintrace-redteam-v1 --output-root runtime\regression_check\fintrace_redteam
python cli.py eval-frozen datasets\red_attack_v1 --output-root runtime\regression_check\red_attack_v1
powershell -ExecutionPolicy Bypass -File scripts\run_regression.ps1
```

复测结果：

- 单元测试：18/18 通过。
- 内置冻结红队集 `fintrace-redteam-v1`：84 案，决策准确率 100%，硬违规 Precision/Recall 100%，字段抽取准确率 100%，错误案件数 0。
- Claude 红方冻结集 `red_attack_v1`：28 案，决策准确率 100%，硬违规 Precision/Recall 100%，字段抽取准确率 100%，错误案件数 0。
- 所有目标项均达成：硬违规 Recall、拒绝/升级 Precision、柔性放行准确率、关键字段抽取准确率、人工复核比例可解释。

## 五、剩余边界

本轮整改仍属于作品集/PoC 级工程增强，不等于真实企业上线：

- `red_attack_v1` 是 Claude 红方样本，不是财务专家独立标注集。
- 企业本体仍以 mock/导入数据为主，未对接真实 HR、CRM、供应商管理和预算系统。
- 图片/PDF OCR 还需要更强的生产级识别、置信度校验和人工纠错工作台。
- 规则变更已有配置入口，但还没有审批流、灰度发布、版本回滚和影响评估机制。
- 运行结果以文件落盘为主，尚未升级到多用户数据库、权限和不可篡改审计日志。

## 六、面试表述建议

可以这样讲：

> 我没有把红方报告当成“模型不够聪明”，而是拆成可验证的风控缺口。第一轮红方数据暴露出审批状态、异常金额和冷启动策略三个问题，我把它们分别落到规则层、字段层和本地稳定模型层修复，再把红方数据冻结成回归集。这个过程证明 FinTrace 的价值不是让 LLM 直接拍板，而是让财务审核的错误能被定位、复现和定向修复。
