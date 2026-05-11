# T-PF-10: 键盘输入中文(BUG-001回归测试)

## 测试目的
验证 BUG-001 修复后，_paste_via_clipboard 使用 pyperclip 替代 ctypes，能正确处理中文/混合文本输入。

## 关联缺陷
- BUG-001: _paste_via_clipboard 中 ctypes GlobalAlloc 返回 0
- 修复方案: 使用 pyperclip 替代 ctypes 实现剪贴板操作

## 测试环境
- OS: Windows
- 目标应用: 记事本 (notepad.exe)
- 测试文本: "JavasAgent"

## 测试步骤
1. 验证 pyperclip 可用 (copy/paste 测试)
2. 直接调用 _paste_via_clipboard 验证剪贴板设置
3. 打开记事本
4. 调用 adapter.type_text() 输入混合文本
5. 截图保存证据
6. 关闭记事本（不保存）

## 预期结果
- pyperclip copy/paste 正常工作
- _paste_via_clipboard 能正确设置剪贴板内容
- 文本完整输入到记事本中
- 无 ctypes GlobalAlloc 错误

## 执行结果
_执行后填写_
