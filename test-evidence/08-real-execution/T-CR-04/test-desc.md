# T-CR-04 Decider 决策

## 测试目标
验证 Decider 根据置信度和风险关键词做出正确的自主/询问人类决策。

## 测试方法
- 创建 Decider 实例（默认阈值 0.6）
- 调用 `evaluate()` 传入不同 context/question/confidence
- 验证 DecisionPoint.auto_decided 是否正确

## 测试场景
1. 高置信度 + 安全操作 → auto_decided=True（自主决策）
2. 低置信度 → auto_decided=False（需要询问人类）
3. 高置信度 + 高风险关键词(删除) → auto_decided=False
4. 高置信度 + 外部发送关键词(发送邮件) → auto_decided=False

## 前置条件
- Python 3.11+
- pytest

## 预期结果
- 各场景 auto_decided 符合预期
