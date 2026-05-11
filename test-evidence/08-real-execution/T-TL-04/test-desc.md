# T-TL-04 系统监控

## 测试目标
验证 SystemMonitor 能获取 CPU/内存/磁盘信息。

## 测试方法
- psutil 已安装，进行真实调用
- 调用 `monitor.execute("resource_usage", {})`
- 调用 `monitor.execute("system_info", {})`
- 调用 `monitor.execute("check_alerts", {})`
- 验证返回的 success、data 字段

## 前置条件
- Python 3.11+
- psutil 已安装（已确认可用）
- pytest + pytest-asyncio

## 预期结果
- resource_usage 返回 CPU percent (0-100)、memory percent、磁盘列表
- system_info 返回 OS 信息、开机时长
- check_alerts 返回告警检查结果
