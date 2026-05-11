# T-CR-01 Planner 生成计划

## 测试目标
验证 Planner.generate_plan()（即 `plan()` 方法）在 mock LLM 返回时能正确解析为 TaskPlan 结构。

## 测试方法
- Mock LLMClient.chat_with_system，返回预定义 JSON
- 调用 `planner.plan("帮我写个脚本")` 
- 验证返回的 TaskPlan 包含正确的 intent、steps、priority

## 前置条件
- Python 3.11+
- pytest + pytest-asyncio
- 项目 src 在 PYTHONPATH

## 预期结果
- TaskPlan.intent 非空
- TaskPlan.steps 包含至少一个 Step
- Step 的 id、action、tool 字段正确
- Priority 值与 mock 数据一致
