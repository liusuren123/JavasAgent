# T-TL-05 网络请求

## 测试目标
验证 NetworkOps 能发送 HTTP GET 请求并正确返回结果。

## 测试方法
- httpx 已安装，进行真实 HTTP 调用
- 调用 `net.execute("http_get", {"url": "https://httpbin.org/get"})`
- 调用 `net.execute("check_connectivity", {})`
- 验证返回的 success、status_code、body

## 前置条件
- Python 3.11+
- httpx 已安装（已确认 v0.28.1）
- 网络可用（httpbin.org 可访问）
- pytest + pytest-asyncio

## 预期结果
- http_get 返回 status_code=200，body 包含请求信息
- check_connectivity 返回 connected=True
