# T-MC-03: 超时失败

## 测试ID
T-MC-03

## 测试目的
验证 MotorController 在持续验证失败时正确返回 VERIFICATION_FAILED / TARGET_NOT_FOUND，且 attempts 达到 max_attempts。

## 测试方法
使用 mock 验证 MotorController 的超时/失败处理逻辑：
- Mock VisionEye 的 `find_target()` 方法返回持续失败的结果
- 验证 MotorController 在达到最大重试次数后正确返回失败状态
- 验证返回的错误类型与场景匹配（VERIFICATION_FAILED vs TARGET_NOT_FOUND）

## 测试场景及结果

| # | 场景 | 预期返回 | 实际返回 | attempts | 结果 |
|---|------|----------|----------|----------|------|
| 1 | click_target 验证始终失败（目标存在但点击后验证不通过） | VERIFICATION_FAILED | VERIFICATION_FAILED | max_attempts (3) | ✅ PASS |
| 2 | 目标始终未找到（find_target 持续返回 None） | TARGET_NOT_FOUND | TARGET_NOT_FOUND | max_attempts (3) | ✅ PASS |
| 3 | type_in_field 输入框未找到（目标定位失败） | TARGET_NOT_FOUND | TARGET_NOT_FOUND | max_attempts (3) | ✅ PASS |

## 测试结论
- **通过**: 3/3
- **状态**: ✅ PASS

## 备注
- 依赖状态：GroundingDINO/OpenCV 未安装，使用 mock 验证闭环控制逻辑
- 核心验证点：失败重试逻辑、错误状态码、最大尝试次数边界
