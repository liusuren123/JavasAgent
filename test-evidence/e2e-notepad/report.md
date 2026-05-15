# E2E Test Report: Notepad Text Edit

- **时间**: 2026-05-15 14:00:09
- **屏幕**: 3840×2160
- **测试文本**: `JavasAgent端到端测试：记事本中文输入验证
第二行：Hello World!
第三行：测试完...`
- **保存路径**: `C:\WINDOWS\TEMP\javasagent_notepad_test.txt`
- **视觉验证模型**: qwen3-vl
- **总耗时**: 57.2s

## 结果摘要

| 指标 | 值 |
|------|------|
| 总步骤 | 5 |
| 脚本判定通过 | 0 |
| 视觉验证可用 | 4 |
| 视觉验证通过 | 2 |
| 最终通过 | 2 |
| 最终失败 | 3 |
| 实际通过率 | 40% |

## 脚本判定 vs 视觉判定对比

| # | 步骤 | 脚本判定 | 视觉判定 | 最终结果 | 耗时 | 说明 |
|---|------|----------|----------|----------|------|------|
| 1 | 打开记事本 | ❌ | ✅ | ✅ | N/A |  |
| 2 | 输入中文文本 | ❌ | ❌ | ❌ | N/A | [NO] |
| 3 | 保存文件到指定路径 | ❌ | ✅ | ✅ | N/A | 保存到: C:\WINDOWS\TEMP\javasagent_notepad_test.txt |
| 4 | 验证文件内容 | ❌ | ❓ | ❌ | 0.0s | 文件不存在: C:\WINDOWS\TEMP\javasagent_notepad_test.txt |
| 5 | 关闭记事本 | ❌ | ❌ | ❌ | N/A | [NO] |

## 失败分类

| 分类 | 数量 | 说明 |
|------|------|------|
| PERCEPTION（感知失败） | 0 | 无法识别屏幕状态 |
| LOCATION（定位失败） | 0 | 无法找到目标元素位置 |
| OPERATION（操作失败） | 0 | 操作执行了但效果不对 |
| DECISION（决策失败） | 3 | 策略或时序错误 |

## 视觉分析详情

### Step 1: 打开记事本
> [YES] 记事本已打开

### Step 2: 输入中文文本
> [NO]

### Step 3: 保存文件到指定路径
> [YES] 已保存

### Step 4: 验证文件内容
> 无视觉分析结果

### Step 5: 关闭记事本
> [NO]


## 截图证据

- **打开记事本**: `step1_notepad_opened.png`
- **输入中文文本**: `step2_text_typed.png`
- **保存文件到指定路径**: `step3_after_save.png`
- **验证文件内容**: `step4_verify_state.png`
- **关闭记事本**: `step5_notepad_closed.png`

---
*本报告由 tests/e2e/test_notepad_edit.py 自动生成*