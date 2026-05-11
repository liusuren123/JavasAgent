# T-PC-01: OCR 识别桌面文字

## 测试ID
T-PC-01

## 测试目的
验证 OcrEngine 的 OCR 管道逻辑，包括配置管理、数据模型、识别流程、区域定位和文字查找。

## 测试方法
使用 mock 验证 OcrEngine 管道逻辑（pytesseract/easyocr/cv2 均未安装）：
- 验证 OcrConfig / TextBlock / OcrResult / TextLocation / TextElement 数据模型
- 验证引擎不可用时的降级行为
- 使用 mock 后端验证 recognize_text / recognize_region / find_text / get_clickable_texts 的完整流程
- 验证坐标映射和模糊匹配逻辑

## 测试场景及结果

### 数据模型验证（4 项）

| # | 场景 | 预期结果 | 实际结果 | 结果 |
|---|------|----------|----------|------|
| 1 | OcrConfig 默认配置 | engine=tesseract, lang=chi_sim+eng | 正确 | ✅ PASS |
| 2 | OcrConfig 自定义配置 | 自定义值生效 | 正确 | ✅ PASS |
| 3 | TextBlock / OcrResult 数据模型 | 字段正确 | 正确 | ✅ PASS |
| 4 | TextLocation / TextElement 数据模型 | 字段正确 | 正确 | ✅ PASS |

### 不可用状态验证（4 项）

| # | 场景 | 预期结果 | 实际结果 | 结果 |
|---|------|----------|----------|------|
| 5 | 引擎不可用状态 | available=False | False | ✅ PASS |
| 6 | recognize_text 不可用 | 返回 success=False | 正确 | ✅ PASS |
| 7 | find_text 不可用 | 返回空列表 | [] | ✅ PASS |
| 8 | get_clickable_texts 不可用 | 返回空列表 | [] | ✅ PASS |

### Mock 后端流程验证（4 项）

| # | 场景 | 预期结果 | 实际结果 | 结果 |
|---|------|----------|----------|------|
| 9 | recognize_text mock 后端 | 返回完整 OcrResult | 2 blocks, full_text 正确 | ✅ PASS |
| 10 | recognize_region 坐标映射 | bbox 偏移到原图坐标 | (105, 205, 80, 25) | ✅ PASS |
| 11 | find_text 模糊匹配 | 返回匹配的 TextLocation | 找到 "设置选项" | ✅ PASS |
| 12 | get_clickable_texts 元素推断 | 推断 element_type | button/text 正确 | ✅ PASS |

### 其他验证（3 项）

| # | 场景 | 预期结果 | 实际结果 | 结果 |
|---|------|----------|----------|------|
| 13 | OcrResult 成功结果 | success=True, blocks 非空 | 正确 | ✅ PASS |
| 14 | OcrResult 失败结果 | success=False, error 非空 | 正确 | ✅ PASS |
| 15 | OCR 引擎不可用返回 | available=False | False | ✅ PASS |

## 测试结论
- **通过**: 15/15
- **状态**: ✅ PASS

## 备注
- 依赖状态：pytesseract/easyocr/OpenCV 均未安装，使用 mock 验证 OCR 管道逻辑
- 核心验证点：数据模型完整性、不可用降级策略、坐标映射、模糊匹配、元素类型推断
- 测试脚本：`_test_pc01_ocr.py`（临时文件，测试后删除）
