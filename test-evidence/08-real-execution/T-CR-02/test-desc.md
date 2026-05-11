# T-CR-02 Executor 执行步骤

## 测试目标
验证 Executor 能正确执行 TaskPlan 中的步骤，返回 ExecutionResult。

## 测试方法
- Mock 多个工具注册到 Executor
- 创建一个包含多步骤（含依赖）的 TaskPlan
- 调用 `executor.execute(plan)`
- 验证 ExecutionResult 的 success、completed_steps、total_steps

## 前置条件
- Python 3.11+
- pytest + pytest-asyncio

## 预期结果
- ExecutionResult.success == True
- ExecutionResult.completed_steps == len(steps)
- 各步骤 status 变为 DONE
- 依赖步骤被正确跳过（如果前置失败）
