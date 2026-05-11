# T-CR-03 Scheduler 优先级队列

## 测试目标
验证 Scheduler 按优先级排序，高优先级任务先出队。

## 测试方法
- 创建不同优先级的 TaskPlan（LOW=0, NORMAL=5, HIGH=10, URGENT=20）
- 按随机顺序 submit 到 Scheduler
- 循环 get_next() 取出所有任务
- 验证取出顺序按优先级降序（URGEST 最先）

## 前置条件
- Python 3.11+
- pytest + pytest-asyncio

## 预期结果
- get_next() 返回的任务按优先级从高到低排列
- queue_size 从 N 递减到 0
