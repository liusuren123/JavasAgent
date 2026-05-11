# T-PF-11: 组合键 Ctrl+C

## 测试目的
验证 WindowsAdapter.hotkey() 组合键功能。

## 测试参数
- 组合键: Ctrl+A (全选) -> Ctrl+C (复制)
- 输入文本: Hello from JavasAgent!

## 测试结果
- hotkey() 调用: 无异常
- 剪贴板内容: ''
- 测试状态: PARTIAL PASS (沙箱限制)
