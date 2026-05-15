# JavasAgent 下一步开发计划

> 创建时间：2026-05-15
> 优先级已与产品经理对齐：验证 → UI检测 → 拟人操作 → 技能闭环

---

## Phase 1：真实环境验证（预计 3 天）

目标：在真实桌面环境跑通 3 个端到端场景，暴露问题，确认基础链路可用。

### Step 1：浏览器搜索场景 — 基础链路验证 ✅ 通过率33%
- [x] T1.1：编写端到端测试脚本 `tests/e2e/test_browser_search.py`
  - 打开浏览器 → 输入关键词 → 搜索 → 打开第一个结果 → 截图验证
- [x] T1.2：运行测试脚本，记录每个环节的成功/失败状态
- [x] T1.3：将失败原因分类（感知失败/定位失败/操作失败/决策失败）
- [x] T1.4：输出测试报告到 `test-evidence/e2e-browser-search/`

### Step 2：记事本文本编辑场景 ✅ 通过率40%
- [x] T2.1：编写端到端测试脚本 `tests/e2e/test_notepad_edit.py`
  - 打开记事本 → 输入中文文本 → 保存到指定路径 → 验证文件内容
- [x] T2.2：运行并记录结果
- [x] T2.3：输出测试报告到 `test-evidence/e2e-notepad/`

### Step 3：Excel 表格操作场景（跳过，Phase 1 结论已足够）
- [ ] T3.1~T3.3：跳过 — 两个场景失败原因一致，直接进 Phase 2

### Step 4：验证总结 + 问题清单 ✅
- [x] T4.1：汇总测试结果 — 浏览器33%+记事本40%，定位失败占75%+
- [x] T4.2：核心问题：固定坐标不可靠，需 UI 元素精确检测
- [x] T4.3：已与产品经理对齐，跳过 Step 3 直接进 Phase 2
- [x] T4.4：已同步给产品经理

---

## Phase 2：桌面 UI 元素精确检测（预计 5-7 天）

目标：实现像素级精确的 UI 元素识别，彻底告别猜坐标。

技术方案：Windows UIA + OmniParser 混合（调研报告：`research-desktop-ui-detection.md`）

### Step 5：UIA 基础封装
- [ ] T5.1：安装 `uiautomation` 库，验证基本功能
- [ ] T5.2：创建 `src/perception/ui_detector.py`，定义 `UIElement` 数据模型
  - 属性：bbox, type, text, confidence, source, clickable, actionable
- [ ] T5.3：实现 `UIADetector` 类：扫描指定窗口的所有 UI 元素
  - 获取控件树 → 提取 BoundingRectangle + ControlType + Name
  - 过滤不可见/屏幕外元素
- [ ] T5.4：实现元素查找方法
  - `find_by_name(name)` — 按名称查找
  - `find_by_type(control_type)` — 按类型查找
  - `find_by_text(text)` — 按文本内容查找
  - `find_by_automation_id(id)` — 按自动化ID查找
- [ ] T5.5：测试 `tests/perception/test_ui_detector.py`
  - 测试记事本窗口元素提取
  - 测试计算器按钮定位
  - 测试文件管理器控件树
- [ ] T5.6：git commit + push

### Step 6：UIA 操作能力
- [ ] T6.1：在 `UIADetector` 中添加操作方法
  - `click_element(element)` — 通过 UIA Invoke Pattern 点击
  - `type_text(element, text)` — 通过 UIA Value Pattern 输入
  - `select_item(element, value)` — 通过 Selection Pattern 选择
  - `get_value(element)` — 读取元素当前值
- [ ] T6.2：实现操作安全检查（目标元素是否存在、是否可操作）
- [ ] T6.3：测试 `tests/perception/test_ui_operations.py`
  - 计算器加法操作端到端测试
  - 记事本输入+保存测试
- [ ] T6.4：git commit + push

### Step 7：截图+AI 补充检测（OmniParser/Florence-2）
- [ ] T7.1：调研 OmniParser 安装和依赖（GPU/CPU 兼容性）
- [ ] T7.2：创建 `src/perception/ai_detector.py`
  - 截图 → AI 模型检测 → 输出 UIElement 列表
  - 优先用本地 Ollama qwen3-vl，云端作 fallback
- [ ] T7.3：实现 UIA + AI 结果融合逻辑
  - UIA 结果优先（坐标精确）
  - AI 结果补充 UIA 遗漏的区域
  - 去重：同一区域只保留一个结果
- [ ] T7.4：测试 `tests/perception/test_ai_detector.py`
- [ ] T7.5：git commit + push

### Step 8：混合检测器集成 + Agent 接入
- [ ] T8.1：创建 `src/perception/hybrid_detector.py`
  - `detect(window)` → UIA 先扫 → AI 补充 → OCR 增强 → 返回合并结果
  - `find(query)` → 自然语言查找（"找到输入框" → 匹配 Edit 控件）
- [ ] T8.2：将 HybridDetector 接入 BaseAgent 感知层
  - 替换现有的截图+视觉模型坐标猜测逻辑
  - Agent 操作时使用 UIA 精确坐标
- [ ] T8.3：更新 `src/tools/browser_control.py` 等工具使用新检测器
- [ ] T8.4：测试 `tests/perception/test_hybrid_detector.py`
- [ ] T8.5：用 Phase 1 的浏览器搜索场景重新验证
- [ ] T8.6：git commit + push

---

## Phase 3：拟人操作人化（预计 3-5 天，收窄范围）

目标：鼠标和键盘操作更像人类，降低被检测风险。

### Step 9：鼠标轨迹人化
- [ ] T9.1：升级 `src/platforms/windows.py` 的鼠标移动
  - 贝塞尔曲线增加随机控制点偏移
  - 移动速度非线性（启动慢 → 中间快 → 接近目标减速）
  - 轨迹增加微抖动（±1-2px 随机偏移）
- [ ] T9.2：点击行为人化
  - 按下和抬起重写为独立操作
  - 按压时长随机化（50-150ms）
  - 点击后微小移动（±3px）
- [ ] T9.3：测试 `tests/platforms/test_human_mouse.py`
- [ ] T9.4：git commit + push

### Step 10：键盘输入人化
- [ ] T10.1：升级键盘输入方法
  - 按键间隔随机化（30-120ms，正态分布）
  - 偶尔触发退格+重输（模拟打字纠错，概率 2%）
  - 中英文切换增加延迟
- [ ] T10.2：剪贴板输入也增加延迟（粘贴前等待 200-500ms）
- [ ] T10.3：测试 `tests/platforms/test_human_keyboard.py`
- [ ] T10.4：git commit + push

### Step 11：基于 UI 检测的操作（不再用坐标）
- [ ] T11.1：创建 `src/platforms/smart_operator.py`
  - `click_element(name_or_text)` — 通过 UIA/OCR 定位后点击
  - `type_in_field(label, text)` — 找到输入框后输入
  - `press_button(label)` — 找到按钮后点击
  - 不再暴露原始坐标给调用者
- [ ] T11.2：测试 `tests/platforms/test_smart_operator.py`
- [ ] T11.3：用 Phase 1 场景重新验证拟人效果
- [ ] T11.4：git commit + push

---

## Phase 4：技能系统闭环（预计 5-7 天）

目标：Agent 能从执行过程中自动学习技能，新场景自动匹配已有技能。

### Step 12：技能自动录制
- [ ] T12.1：创建 `src/skills/recorder.py`
  - 监听 Agent 的每次操作（截图、点击、输入、等待）
  - 按时间顺序记录为步骤列表
  - 自动识别关键帧（操作前后的截图对比）
- [ ] T12.2：录制结果自动转换为 YAML 技能描述
  - 泛化坐标为语义描述（"点击'保存'按钮"而非"点击(300,200)"）
  - 自动提取 OCR 文本作为步骤描述
- [ ] T12.3：测试 `tests/skills/test_recorder.py`
- [ ] T12.4：git commit + push

### Step 13：技能检索与匹配
- [ ] T13.1：升级 `src/skills/skill_matcher.py`
  - 用户指令 → 向量化 → 匹配最相关的技能描述
  - 支持模糊匹配（"做个表格" → 匹配"Excel 创建表格"技能）
  - 返回匹配度 Top 3 + 置信度
- [ ] T13.2：技能执行前确认机制
  - 匹配度 > 0.8 → 自动执行
  - 0.5-0.8 → 展示匹配结果，询问用户确认
  - < 0.5 → 告知无匹配技能，走普通规划流程
- [ ] T13.3：测试 `tests/skills/test_skill_matching.py`
- [ ] T13.4：git commit + push

### Step 14：技能库积累 + 端到端验证
- [ ] T14.1：预置 5-10 个常用技能 YAML
  - 浏览器搜索、记事本编辑、Excel 操作、文件管理、截图保存等
- [ ] T14.2：用真实场景验证技能闭环
  - 用户说"帮我搜一下天气" → 自动匹配浏览器搜索技能 → 执行
- [ ] T14.3：技能执行结果评分（成功/失败/部分成功）
- [ ] T14.4：全量回归测试
- [ ] T14.5：git commit + push

---

## 原子任务总计

| Phase | Steps | Tasks | 预计天数 |
|-------|-------|-------|----------|
| Phase 1 真实环境验证 | 4 | 13 | 3 天 |
| Phase 2 UI 元素检测 | 4 | 22 | 5-7 天 |
| Phase 3 拟人操作 | 3 | 11 | 3-5 天 |
| Phase 4 技能闭环 | 3 | 13 | 5-7 天 |
| **总计** | **14** | **59** | **16-22 天** |

## Cron 执行策略

- 每个 cron 周期（4 分钟）检查是否有正在运行的子任务
- 没有子任务时启动新的子任务，子任务内完成一个完整 Step 的所有 Tasks
- 每个 Task 完成后立即 git commit
- 全部 Tasks 完成后 git push
- 测试必须通过才能 commit（reflector 相关代码不加入项目）
