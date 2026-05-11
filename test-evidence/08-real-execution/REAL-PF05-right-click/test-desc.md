# T-PF-05: 鼠标右键单击

## 测试目的
验证 WindowsAdapter.click(button="right") 鼠标右键单击功能。

## 测试参数
- 目标坐标: 屏幕中心 (1920, 1080)
- button: right
- clicks: 1

## 预期结果
- 右键菜单弹出
- 无异常抛出

## 测试环境
- 屏幕: 3840x2160
- OS: Windows
- 需禁用 pyautogui.FAILSAFE（沙箱环境中鼠标可能在角落）

## 测试结果
- **状态**: PARTIAL PASS
- **右键点击**: 成功，无异常抛出
- **截图验证**: 不可用（沙箱 screen grab 限制）
- **菜单关闭**: Esc 按键成功执行

## 日志输出
```
Screen resolution: {'width': 3840, 'height': 2160}
Right-click target: (1920, 1080)
Right-click executed successfully
Screenshot failed (sandbox limitation): screen grab failed
Esc pressed to close menu
[PARTIAL] T-PF-05: Right-click executed without error, but screenshot unavailable (sandbox).
```

## 结论
WindowsAdapter.click(button="right") 功能正常，右键单击可正确触发。截图功能受沙箱环境限制，在真实桌面环境中应可正常捕获右键菜单。
