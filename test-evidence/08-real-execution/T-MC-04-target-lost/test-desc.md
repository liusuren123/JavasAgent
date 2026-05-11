# T-MC-04: 目标丢失

## 测试ID
T-MC-04

## 测试目的
验证 MotorController 在目标丢失时正确处理各种场景，包括目标消失、超时未出现等。

## 测试方法
使用 mock 验证 MotorController 的目标丢失处理逻辑：
- Mock VisionEye 的 `find_target()` 方法模拟目标在不同阶段消失
- 验证 MotorController 正确识别目标丢失并返回适当状态码
- 验证特殊场景：点击后目标消失（视为验证通过）

## 测试场景及结果

| # | 场景 | 预期返回 | 实际返回 | 结果 |
|---|------|----------|----------|------|
| 1 | 目标点击后消失（消失=验证通过） | SUCCESS | SUCCESS | ✅ PASS |
| 2 | 目标第 2 次迭代时消失 | TARGET_NOT_FOUND | TARGET_NOT_FOUND | ✅ PASS |
| 3 | wait_and_click 目标未出现 | TIMEOUT | TIMEOUT | ✅ PASS |
| 4 | scroll_and_find 未找到目标 | TARGET_NOT_FOUND | TARGET_NOT_FOUND | ✅ PASS |

## 测试结论
- **通过**: 4/4
- **状态**: ✅ PASS

## 备注
- 依赖状态：GroundingDINO/OpenCV 未安装，使用 mock 验证闭环控制逻辑
- 核心验证点：目标消失的语义判断、超时机制、迭代中断处理
