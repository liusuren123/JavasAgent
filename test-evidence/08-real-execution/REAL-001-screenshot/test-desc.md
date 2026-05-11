# REAL-001: 截屏功能测试

## 测试目标
验证 `WindowsAdapter.screenshot()` 能正确截取屏幕并生成有效 PNG

## 测试步骤
1. 初始化 WindowsAdapter
2. 调用 screenshot() 获取 PNG bytes
3. 验证 bytes 非空
4. 验证 PNG magic bytes (89 50 4E 47)
5. 保存截图到文件
6. 验证文件大小 > 10KB

## 预期结果
- 返回有效的 PNG 图片数据
- 文件大小 > 10KB
- 图片可正常打开
