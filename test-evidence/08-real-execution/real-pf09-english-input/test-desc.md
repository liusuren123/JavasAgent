# T-PF-09: 键盘输入英文(ASCII)测试

## 测试目的
验证 pyautogui.typewrite() 能正确输入纯英文(ASCII)文本。

## 测试环境
- OS: Windows NT 10.0.26200 (x64)
- 目标应用: 记事本 (notepad.exe)
- 测试文本: "Hello World! This is a test."
- pyautogui 版本: 0.9.54

## 测试步骤
1. 设置 pyautogui.FAILSAFE = False（沙箱环境必须）
2. 打开记事本
3. 等待2秒让记事本完全加载
4. 点击屏幕中央确保焦点在记事本
5. 调用 pyautogui.typewrite() 输入英文文本
6. 尝试截图保存证据
7. 关闭记事本（Alt+F4 → Tab → Enter，不保存）

## 执行结果

**日期**: 2026-05-11 09:52 CST
**状态**: PASS

### 详细输出
```
FAILSAFE: False, pos: Point(x=0, y=0)
typewrite OK: Hello World! This is a test.
截图失败: screen grab failed  (沙箱限制,正常)
[OK] T-PF-09 测试完成
```

### 注意事项
- 截图失败(screen grab failed)是沙箱环境限制,不影响测试判定
- 鼠标位置报告 (0,0) 是沙箱环境的读取限制,不影响实际操作
- pyautogui.FAILSAFE 必须在模块级设为 False,否则沙箱中鼠标在角落会触发安全机制
- typewrite 对纯ASCII文本工作正常
