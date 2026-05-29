# FinTrace 红蓝对抗隔离说明

## 当前结论

FinTrace 现在保留两种评测模式：

- `eval`：动态灰盒自测。运行时生成红队数据、跑蓝队、出报告，适合开发阶段快速回归。
- `eval-frozen`：冻结数据集评测。只读取已经生成并提交的 `datasets/fintrace-redteam-v1`，不重新生成数据，用于对外展示和跨版本对比。

## 为什么要隔离

动态生成评测有一个方法论问题：红队数据、蓝队规则、裁判标签都来自同一个代码库和同一个开发者视角，容易变成“系统是否符合作者预期”，而不是“系统是否经得起未知攻击”。

严格红蓝对抗理想上需要三个独立方：

| 角色 | 职责 | 不应该看到 |
| --- | --- | --- |
| 红队 | 设计攻击样本和边界场景 | 蓝队内部规则、裁判隐藏标签 |
| 蓝队 | 审核报销并输出决策 | 红队意图、隐藏答案 |
| 裁判 | 对比冻结标签并归因错误 | 蓝队调参过程 |

个人项目无法做到团队级隔离，但可以做代码和数据层面的最小物理隔离。

## 已实现的隔离措施

1. **代码隔离**
   - 顶层 `redteam/` 是独立包，不 import `fintrace.*`。
   - 红队生成器使用字面量决策标签，不引用蓝队 `Decision` 枚举、`policies.py` 或 `reasoning.py`。

2. **数据冻结**
   - 冻结数据集目录：`datasets/fintrace-redteam-v1`。
   - 必须包含 `ground_truth.json` 和 `dataset_manifest.json`。
   - `eval-frozen` 只读该目录，不会在评测时重新生成样本。

3. **裁判隔离**
   - `run_frozen_evaluation()` 从冻结目录读取标注，再调用蓝队 `run_batch()`。
   - 评测报告中写入 `evaluation_mode=frozen_dataset` 和隔离说明。

4. **动态模式标记**
   - 原 `eval` 没有删除，但报告会标记为 `dynamic_graybox_generation`，明确它只是开发自测，不冒充严格红蓝对抗。

## 使用方式

生成冻结数据集：

```powershell
python cli.py redteam-freeze --output-dir datasets\fintrace-redteam-v1 --n 84 --seed 20260529
```

运行冻结评测：

```powershell
python cli.py eval-frozen datasets\fintrace-redteam-v1 --output-root runtime\eval_frozen
```

动态开发自测：

```powershell
python cli.py eval --output-root runtime\eval_dev --n 500 --seed 42
```

## 面试讲法

FinTrace v0.1 早期的红蓝评测确实是灰盒自测：生成器、审核器、裁判在同一个包里，适合快速发现回归问题，但不够严格。后来我把评测分成两种模式：开发时用动态灰盒自测，展示和跨版本对比用冻结数据集。冻结集由独立 `redteam/` 包生成，不 import 蓝队规则，标签随数据集一起版本化，蓝队调规则后只能拿同一份冻结标签复测。这样虽然还达不到真实企业里独立团队红蓝对抗，但已经避免了“每次评测重新生成一份刚好适配当前规则的数据”的问题。
