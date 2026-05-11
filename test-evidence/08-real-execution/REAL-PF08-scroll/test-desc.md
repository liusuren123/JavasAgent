# T-PF-08: 鼠标滚轮滚动测试

## 测试目的
验证 WindowsAdapter.scroll() 方法能正确执行鼠标滚轮向上和向下滚动。

## 测试参数
- 向下滚动: clicks=3, direction="down"
- 向上滚动: clicks=3, direction="up"

## 预期结果
1. 滚轮向下滚动 3 次成功执行，无异常
2. 滚轮向上滚动 3 次成功执行，无异常

## 实际结果
- 向下滚动: 成功完成
- 向上滚动: 成功完成
- 截图: screenshot_after_scroll.png (已保存)
- **[PASS]** 测试通过

## 证据文件
- `screenshot_after_scroll.png` — 滚动后屏幕截图
