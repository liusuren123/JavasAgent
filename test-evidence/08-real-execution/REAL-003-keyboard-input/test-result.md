# REAL-003: 键盘输入测试

## 测试目标
验证 `WindowsAdapter.type_text()` 能正确输入中英文混合文字

## 执行结果
❌ **失败**

## 过程
1. 打开 notepad.exe ✅
2. 调用 type_text('Hello JavasAgent! 你好世界！') → 剪贴板粘贴失败
3. 错误信息：`无法分配剪贴板内存` (_paste_via_clipboard)
4. 记事本内容为空

## 原因分析
`_paste_via_clipboard` 中的 Win32 API 调用失败，`GlobalAlloc` 返回 0。
可能是权限问题或 ctypes 调用在 Python 3.13 下的兼容性问题。

## 截图证据
- screenshot_notepad.png: 记事本打开但内容为空
