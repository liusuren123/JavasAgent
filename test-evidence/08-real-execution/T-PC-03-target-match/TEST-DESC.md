# T-PC-03: 目标匹配三级 fallback

## 测试目的
验证 TargetMatcher 的三级降级匹配策略（精确 -> 模糊 -> 语义）。

## 测试场景
1. 精确匹配命中（query="Submit", text="Submit"）
2. 模糊匹配降级（query="Submit", text="Submt"，编辑距离=1）
3. 语义匹配降级（query="关闭", text="关掉"，同义词命中）
4. 全部失败（query="NonExistentButton"）
5. match_all 返回多级混合结果

## 测试结果
- 场景1 精确匹配: PASS
- 场景2 模糊匹配: PASS
- 场景3 语义匹配: PASS
- 场景4 匹配失败: PASS
- 场景5 match_all: PASS
- 通过: 5/5
- 状态: PASS
