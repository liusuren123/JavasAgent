# JavasAgent 技能描述执行系统 — 开发计划

> 版本: 1.0 | 日期: 2026-05-12
> 基于技术交底书: docs/TR-skill-system.md
> 总任务数: 32 个原子任务 | 预计 10 个 Step（cron 轮次）

---

## Step 1: skills 包骨架 + 数据模型

### Task 1.1: 创建 skills 包结构
- 新建 `src/skills/__init__.py`
- 导出 SkillLoader, StepExecutor, SkillContext, SkillValidator
- 文件大小：< 0.5KB

### Task 1.2: 实现 SkillContext 执行上下文
- 新建 `src/skills/context.py`
- 实现 `SkillContext` dataclass：
  - `parameters: dict` — 用户传入参数
  - `variables: dict` — 步骤中间变量
  - `result: dict` — 最终结果
  - `screenshots: list[bytes]` — 执行截图证据
  - `current_step: int` — 当前步骤索引
  - `total_steps: int` — 总步骤数
- 实现 `get(key)` — 支持 `parameters.xxx` 和 `variables.xxx` 点号路径
- 实现 `set(key, value)` — 设置 variables
- 实现 `resolve(template)` — 解析 `"{{filename}}"` 模板变量替换
- 实现 `to_dict()` — 序列化为 dict
- 文件大小：< 4KB

### Task 1.3: 编写 SkillContext 测试
- 新建 `tests/skills/__init__.py`
- 新建 `tests/skills/test_context.py`
- 测试 `get()` 点号路径解析
- 测试 `set()` 变量存储
- 测试 `resolve()` 模板变量替换（`{{name}}` → 实际值）
- 测试 `resolve()` 嵌套路径（`{{parameters.filename}}`）
- 测试 `resolve()` 变量不存在时返回原模板
- 测试 `to_dict()` 序列化
- 文件大小：< 4KB

### Task 1.4: 修改 SkillDefinition 模型
- 修改 `src/memory/skill_models.py`
- 在 `SkillDefinition` dataclass 中新增字段：
  - `yaml_path: str = ""` — YAML 文件路径
  - `skill_version: str = "1.0"` — 技能版本
  - `triggers: list[str]` — 触发关键词列表（默认空）
  - `requirements: list[dict]` — 前置条件列表（默认空）
- 确保 `to_dict()` 和 `from_dict()` 兼容新字段
- 确保现有测试不受影响
- 文件大小变化：+20 行

---

## Step 2: 条件表达式求值器

### Task 2.1: 实现 ExpressionEvaluator
- 新建 `src/skills/expression.py`
- 实现 `ExpressionEvaluator` 类
- 实现 `evaluate(expr: str, context: SkillContext) -> bool`
- 支持的运算符：
  - 比较：`==`, `!=`, `>`, `<`, `>=`, `<=`
  - 字符串包含：`"xxx" in variable`
  - 逻辑：`and`, `or`, `not`
- 支持的值类型：
  - 字符串：`"hello"`
  - 数字：`42`, `3.14`
  - 变量引用：`parameters.filename`, `variables.count`
  - 布尔：`true`, `false`
- 实现流程：
  1. `tokenize()` — 分词（运算符、字符串、数字、变量、括号）
  2. `parse()` — 递归下降解析为 AST
  3. `eval_node()` — 求值 AST 节点
- **不使用 eval()** — 自实现解析器
- 错误处理：语法错误返回 False + 日志警告
- 文件大小：< 8KB

### Task 2.2: 编写 ExpressionEvaluator 测试
- 新建 `tests/skills/test_expression.py`
- 测试等值比较：`parameters.name == "test"`
- 测试不等比较：`parameters.count != 0`
- 测试大小比较：`variables.retries > 3`
- 测试字符串包含：`"PDF" in result.text`
- 测试逻辑运算：`a == "x" and b > 0`
- 测试 not 运算：`not parameters.dry_run`
- 测试变量不存在时返回 False
- 测试语法错误时返回 False 不崩溃
- 测试嵌套路径：`parameters.file.name == "test"`
- 文件大小：< 6KB

---

## Step 3: 技能验证器

### Task 3.1: 实现 SkillValidator
- 新建 `src/skills/validator.py`
- 实现 `ValidationResult` dataclass：`valid: bool, errors: list[str], warnings: list[str]`
- 实现 `SkillValidator` 类
- 实现 `validate(data: dict) -> ValidationResult`
- 验证规则：
  - 必填字段：`name`, `description`, `steps`
  - `steps` 必须是 list，每个 step 必须有 `action`
  - `action` 必须是合法名称（在 _VALID_ACTIONS 集合中）
  - `parameters` 中的 type 必须是合法 JSON Schema 类型
  - `loop` 类型步骤必须有 `max_iterations` 且 <= 100
  - `run_skill` 嵌套深度提示 warning
  - `condition` 必须有 `when` 字段
- 实现 `validate_file(path: Path) -> ValidationResult` — 加载 YAML + 验证
- 定义 `_VALID_ACTIONS` 常量集合（20 个 action 名）
- 文件大小：< 6KB

### Task 3.2: 编写 SkillValidator 测试
- 新建 `tests/skills/test_validator.py`
- 测试合法 YAML 通过验证
- 测试缺少 name 字段 → error
- 测试缺少 steps 字段 → error
- 测试未知 action → error
- 测试 loop 无 max_iterations → error
- 测试 loop max_iterations > 100 → error
- 测试 condition 无 when → error
- 测试合法文件但有多余 warning
- 测试 validate_file() 正确加载 YAML
- 文件大小：< 5KB

---

## Step 4: 原语实现 — 键盘 + 鼠标

### Task 4.1: 实现 keyboard actions
- 新建 `src/skills/actions/__init__.py`
- 新建 `src/skills/actions/keyboard.py`
- 实现 `exec_key_combo(step, context, platform)` — 调用 `platform.key_combo(keys)`
- 实现 `exec_key_type(step, context, platform)` — 调用 `platform.type_key(key)`
- 参数解析：`keys` 字段，支持 `"ctrl+s"`, `"alt+f4"`, `"f12"` 格式
- 错误处理：keys 为空时返回错误
- 日志：记录按键操作
- 文件大小：< 3KB

### Task 4.2: 实现 mouse actions
- 新建 `src/skills/actions/mouse.py`
- 实现 `exec_click(step, context, platform)` — 调用 `platform.click(x, y)`
- 实现 `exec_double_click(step, context, platform)` — 调用 `platform.double_click(x, y)`
- 实现 `exec_right_click(step, context, platform)` — 调用 `platform.right_click(x, y)`
- 实现 `exec_drag(step, context, platform)` — 从 `start_x, start_y` 拖到 `end_x, end_y`
- 实现 `exec_scroll(step, context, platform)` — `amount` 正数向上负数向下
- 参数支持坐标和模板变量：`x: "{{target_x}}"`, `y: "{{target_y}}"`
- 文件大小：< 4KB

### Task 4.3: 编写 keyboard + mouse actions 测试
- 新建 `tests/skills/test_actions_keyboard.py`
- 测试 key_combo 正确调用 platform
- 测试 key_type 正确调用 platform
- 测试 keys 参数缺失返回错误
- 新建 `tests/skills/test_actions_mouse.py`
- 测试 click 正确传坐标
- 测试 double_click 正确调用
- 测试 drag 从 A 到 B
- 测试 scroll 方向正负
- 所有测试使用 mock platform
- 文件大小：各 < 3KB

---

## Step 5: 原语实现 — 文字输入 + 视觉操作

### Task 5.1: 实现 text actions
- 新建 `src/skills/actions/text.py`
- 实现 `exec_type_text(step, context, platform, humanhand)` — 拟人打字
  - 参数：`text`（支持模板变量），`speed`（"fast"/"normal"/"slow"）
  - 调用 `humanhand.type_text(text, speed)`
  - text 为空时返回错误
- 实现 `exec_click_text(step, context, platform, perception)` — OCR 找文字 → 点击
  - 参数：`text`, `timeout`(默认3秒), `offset_x`(默认0), `offset_y`(默认0)
  - 调用 `perception.find_text(text)` 获取坐标
  - 调用 `platform.click(x + offset_x, y + offset_y)`
  - 找不到文字时返回错误
- 文件大小：< 5KB

### Task 5.2: 实现 vision actions
- 新建 `src/skills/actions/vision.py`
- 实现 `exec_click_icon(step, context, platform, perception)` — 视觉找图标 → 点击
  - 参数：`description`（如"保存按钮"）, `timeout`(默认5秒)
  - 调用 `perception.find_object(description)` 获取 bbox
  - 点击 bbox 中心
- 实现 `exec_assert_text(step, context, perception)` — 断言文字存在
  - 参数：`text`（支持 `|` 分隔多个匹配）, `timeout`(默认3秒)
  - OCR 扫描屏幕，检查是否包含任一文字
  - 返回 `{"passed": true/false, "found": "实际找到的文字"}`
- 实现 `exec_assert_screen(step, context, platform)` — 断言屏幕变化
  - 截取当前屏幕与上一步截图对比
  - 参数：`min_change`(默认0.01，1% 变化即认为不同)
  - 使用 PIL 计算像素差异率
- 文件大小：< 6KB

### Task 5.3: 编写 text + vision actions 测试
- 新建 `tests/skills/test_actions_text.py`
- 测试 type_text 正确调用 humanhand
- 测试 type_text 模板变量替换
- 测试 click_text OCR 找到文字后点击正确坐标
- 测试 click_text 找不到文字返回错误
- 测试 offset 偏移量正确
- 新建 `tests/skills/test_actions_vision.py`
- 测试 click_icon 找到对象后点击中心
- 测试 assert_text 文字存在时 passed=true
- 测试 assert_text 文字不存在时 passed=false
- 测试 assert_screen 像素差异计算
- 所有测试使用 mock perception + mock platform
- 文件大小：各 < 4KB

---

## Step 6: 原语实现 — 控制流 + 截图

### Task 6.1: 实现 control actions
- 新建 `src/skills/actions/control.py`
- 实现 `exec_wait(step, context)` — `asyncio.sleep(duration)`
  - 参数：`duration`（秒），默认 1.0
  - 上限 30 秒，超过截断
- 实现 `exec_wait_text(step, context, perception)` — 循环 OCR 等待文字出现
  - 参数：`text`, `timeout`(默认5秒), `interval`(默认0.5秒)
  - 循环：截屏 → OCR → 检查文字 → 找到则返回 / 超时则返回错误
- 实现 `exec_condition(step, context, executor)` — 条件分支
  - 参数：`when`(表达式), `then`(步骤列表), `else`(步骤列表，可选)
  - 调用 `ExpressionEvaluator.evaluate(when, context)`
  - True → 执行 then 步骤；False → 执行 else 步骤
- 实现 `exec_loop(step, context, executor)` — 循环执行
  - 参数：`steps`(步骤列表), `max_iterations`(上限100), `break_when`(可选，条件表达式)
  - 循环执行 steps，每轮检查 break_when
  - 记录实际迭代次数
- 实现 `exec_run_skill(step, context, skill_executor)` — 嵌套调用技能
  - 参数：`skill_name`, `params`(传给子技能的参数)
  - 调用 `skill_executor.execute_skill(skill_name, params)`
  - 递归深度检查（从 context 读取，上限 5）
- 文件大小：< 8KB

### Task 6.2: 实现 screen action
- 新建 `src/skills/actions/screen.py`
- 实现 `exec_screenshot(step, context, platform)` — 截屏保存证据
  - 调用 `platform.screenshot()` 截取全屏
  - 将截图追加到 `context.screenshots`
  - 可选参数：`region`（区域截屏），`save_to`（保存路径）
  - 返回 `{"captured": true, "size": "1920x1080"}`
- 文件大小：< 3KB

### Task 6.3: 编写 control + screen actions 测试
- 新建 `tests/skills/test_actions_control.py`
- 测试 wait 正确等待
- 测试 wait 超过 30 秒被截断
- 测试 wait_text 文字出现时立即返回
- 测试 wait_text 超时返回错误
- 测试 condition when=true 执行 then
- 测试 condition when=false 执行 else
- 测试 loop 执行指定次数
- 测试 loop break_when 提前退出
- 测试 loop max_iterations 超限
- 测试 run_skill 调用子技能
- 测试 run_skill 递归深度超限返回错误
- 新建 `tests/skills/test_actions_screen.py`
- 测试 screenshot 截图存入 context
- 测试 screenshot 返回正确大小
- 文件大小：各 < 5KB

### Task 6.4: 实现 actions 包注册
- 修改 `src/skills/actions/__init__.py`
- 导出所有 action 函数
- 定义 `ACTION_REGISTRY: dict[str, Callable]` — action 名 → 执行函数的映射
- 包含全部 20 个 action 的注册
- 文件大小：< 3KB

---

## Step 7: StepExecutor 步骤执行器

### Task 7.1: 实现 StepExecutor 核心
- 新建 `src/skills/step_executor.py`
- 实现 `StepExecutor.__init__(platform, perception, humanhand, skill_executor=None)`
- 实现 `execute_step(step: dict, context: SkillContext) -> dict`
  - 从 step 中取 `action` 字段
  - 从 ACTION_REGISTRY 查找对应函数
  - 调用函数，传入 step, context, 以及需要的子系统
  - 返回执行结果 dict
- 实现 `execute_steps(steps: list[dict], context: SkillContext) -> dict`
  - 顺序执行每个 step
  - 某步返回 `{"success": false}` 时中断，记录失败步骤
  - 每步更新 `context.current_step`
  - 返回最终结果 dict：`{"success", "completed_steps", "total_steps", "failed_step", "error"}`
- 实现 `_resolve_params(step: dict, context: SkillContext) -> dict`
  - 对 step 中所有字符串值做 `context.resolve()` 模板替换
  - 返回替换后的 step dict
- 日志：每步执行前后记录
- 文件大小：< 6KB

### Task 7.2: 编写 StepExecutor 测试
- 新建 `tests/skills/test_step_executor.py`
- 测试 execute_step 正确路由到 action 函数
- 测试 execute_step 未知 action 返回错误
- 测试 execute_steps 顺序执行多步
- 测试 execute_steps 中间步骤失败时中断
- 测试 _resolve_params 模板变量替换
- 测试 context.current_step 递增
- 测试空步骤列表返回成功
- 使用 mock action 函数
- 文件大小：< 5KB

---

## Step 8: SkillLoader YAML 加载器

### Task 8.1: 实现 SkillLoader
- 新建 `src/skills/skill_loader.py`
- 实现 `SkillLoader.__init__(skills_dirs: list[str] = None)` — 默认 `["./skills", "./data/skills"]`
- 实现 `load_all() -> list[SkillDefinition]` — 扫描所有目录的 .yaml 文件
- 实现 `load_file(path: Path) -> SkillDefinition` — 加载单个 YAML
  - 读取 YAML
  - 调用 `SkillValidator.validate()` 验证
  - 转换为 SkillDefinition：name, description, category, triggers, requirements, parameters, steps
  - 设置 `yaml_path`, `skill_version`, `source="yaml"`
  - 验证失败时日志警告并跳过
- 实现 `reload() -> list[SkillDefinition]` — 清空后重新加载（热更新）
- 实现 `get_skill_path(skill_name: str) -> Path | None` — 根据名称找到文件路径
- 文件大小：< 6KB

### Task 8.2: 编写 SkillLoader 测试
- 新建 `tests/skills/test_skill_loader.py`
- 创建临时目录 + 测试 YAML 文件
- 测试 load_all() 扫描加载
- 测试 load_file() 正确解析 YAML
- 测试 load_file() 验证失败时跳过
- 测试 load_file() 必填字段缺失时跳过
- 测试 reload() 清空后重新加载
- 测试多目录扫描
- 测试子目录递归扫描
- 文件大小：< 5KB

### Task 8.3: 创建 skills 目录和初始示例
- 新建 `skills/` 目录
- 新建 `skills/README.md` — 说明如何编写技能文件
- 新建 `skills/system/screenshot.yaml` — 全屏截图
  - action: screenshot + save_to 参数
- 新建 `skills/system/open_app.yaml` — 打开应用程序
  - action: key_combo(win), type_text(应用名), key_combo(enter)
- 文件大小：各 < 1KB

---

## Step 9: 集成 — 串联现有技能框架

### Task 9.1: 修改 SkillExecutor 添加 YAML 执行路径
- 修改 `src/tools/skill_executor.py`
- 在 `_execute_skill()` 方法中新增 YAML 技能执行路径：
  - 检查 skill.yaml_path 是否非空（YAML 技能）
  - 如果是 YAML 技能：加载 steps → 创建 SkillContext → 调用 StepExecutor.execute_steps()
  - 如果是注册函数技能：走原有 executor_fn 路径
- 在 `__init__()` 中接受 `step_executor` 参数
- 在 `_handle_auto_execute()` 匹配时同时搜索 YAML 技能
- 文件大小变化：+40 行

### Task 9.2: 修改 SkillMatcher 支持 triggers 匹配
- 修改 `src/tools/skill_matcher.py`
- 在 `match()` 方法中增加 triggers 字段匹配维度：
  - 遍历 candidates 的 triggers 列表
  - 任务描述包含任一 trigger → 额外加权分
  - 与现有 name/description/tags 匹配分数合并
- 文件大小变化：+30 行

### Task 9.3: 更新配置文件
- 修改 `config/default.yaml`
- 新增 `skills` 配置节：
  ```yaml
  skills:
    dirs:
      - "./skills"
      - "./data/skills"
    hot_reload: true          # 监听文件变化自动重新加载
    max_loop_iterations: 100
    max_skill_depth: 5
    validate_on_load: true    # 加载时验证
  ```

### Task 9.4: 编写集成测试
- 新建 `tests/skills/test_integration.py`
- 测试完整流程：YAML → SkillLoader → SkillRegistry → SkillMatcher → StepExecutor
- 测试 YAML 技能和 Python 函数技能共存
- 测试 YAML 技能中嵌套调用另一个 YAML 技能
- 测试 YAML 技能条件分支
- 测试 YAML 技能循环 + break
- 测试错误传播：某步失败时整体返回失败
- 使用 mock platform + mock perception
- 文件大小：< 6KB

---

## Step 10: 预置技能库 + 收尾

### Task 10.1: 创建 system 预置技能（3 个）
- `skills/system/screenshot.yaml` — 已在 Step 8 创建，补充完善
- `skills/system/screenshot_region.yaml` — 区域截图
  - 参数：x, y, width, height
  - steps: screenshot(region=...)
- `skills/system/switch_window.yaml` — 切换窗口
  - steps: key_combo(alt+tab), wait(0.3), 如果不是目标窗口再 tab

### Task 10.2: 创建 office 预置技能（3 个）
- `skills/office/word_save_pdf.yaml` — Word 另存为 PDF
  - 按 TR-skill-system.md 中的示例完整实现
- `skills/office/excel_format_table.yaml` — Excel 格式化当前表格
  - steps: key_combo(ctrl+a), key_combo(ctrl+shift+l), ...
- `skills/office/ppt_export_images.yaml` — PPT 导出为图片
  - steps: key_combo(alt+f), click_text("另存为"), ...

### Task 10.3: 创建 browser 预置技能（3 个）
- `skills/browser/browser_open_url.yaml` — 打开网页
  - 参数：url
  - steps: key_combo(ctrl+l), type_text(url), key_combo(enter)
- `skills/browser/browser_bookmark.yaml` — 添加书签
  - steps: key_combo(ctrl+d), wait(0.5), key_combo(enter)
- `skills/browser/browser_download.yaml` — 下载当前页面文件
  - steps: key_combo(ctrl+s), wait_text("保存"), key_combo(enter)

### Task 10.4: 创建 dev 预置技能（3 个）
- `skills/dev/vscode_open_project.yaml` — VS Code 打开项目
  - 参数：project_path
  - steps: key_combo(ctrl+k ctrl+o), type_text(project_path), key_combo(enter)
- `skills/dev/git_commit_push.yaml` — Git 提交推送
  - 参数：message
  - steps: key_combo(ctrl+shift+g), type_text(message), ...
- `skills/dev/terminal_run.yaml` — 终端执行命令
  - 参数：command
  - steps: key_combo(ctrl+`), type_text(command), key_combo(enter)

### Task 10.5: 更新文档
- 更新 `docs/architecture.md` — 添加技能系统架构图
- 新建 `docs/skill-authoring-guide.md` — 技能编写指南
  - YAML 格式说明
  - 20 个 action 的参数和用法
  - 变量和条件表达式语法
  - 完整示例
- 更新 `docs/api-reference.md` — 添加 SkillLoader / StepExecutor API

### Task 10.6: 全量测试 + commit + push
- 执行 `python -m pytest tests/ -q` — 确认 0 失败
- 执行 `python -m pytest tests/skills/ -q` — 确认新增测试全绿
- `git add -A && git commit -m "feat(skills): YAML 技能描述执行系统完整实现" && git push origin main`

---

## 文件清单总览

### 新建文件（22 个）

```
src/skills/__init__.py                          # skills 包
src/skills/context.py                           # 执行上下文
src/skills/expression.py                        # 条件表达式求值
src/skills/validator.py                         # 技能验证器
src/skills/step_executor.py                     # 步骤执行器
src/skills/skill_loader.py                      # YAML 加载器
src/skills/actions/__init__.py                  # actions 注册表
src/skills/actions/keyboard.py                  # 键盘原语
src/skills/actions/mouse.py                     # 鼠标原语
src/skills/actions/text.py                      # 文字原语
src/skills/actions/vision.py                    # 视觉原语
src/skills/actions/control.py                   # 控制流原语
src/skills/actions/screen.py                    # 截屏原语
tests/skills/__init__.py                        # 测试包
tests/skills/test_context.py                    # 上下文测试
tests/skills/test_expression.py                 # 表达式测试
tests/skills/test_validator.py                  # 验证器测试
tests/skills/test_step_executor.py              # 执行器测试
tests/skills/test_skill_loader.py               # 加载器测试
tests/skills/test_actions_keyboard.py           # 键盘测试
tests/skills/test_actions_mouse.py              # 鼠标测试
tests/skills/test_actions_text.py               # 文字测试
tests/skills/test_actions_vision.py             # 视觉测试
tests/skills/test_actions_control.py            # 控制流测试
tests/skills/test_actions_screen.py             # 截屏测试
tests/skills/test_integration.py               # 集成测试
skills/README.md                                # 技能编写说明
skills/system/screenshot.yaml                   # 全屏截图
skills/system/screenshot_region.yaml            # 区域截图
skills/system/switch_window.yaml                # 切换窗口
skills/office/word_save_pdf.yaml                # Word转PDF
skills/office/excel_format_table.yaml           # Excel格式化
skills/office/ppt_export_images.yaml            # PPT导图片
skills/browser/browser_open_url.yaml            # 打开网页
skills/browser/browser_bookmark.yaml            # 添加书签
skills/browser/browser_download.yaml            # 下载文件
skills/dev/vscode_open_project.yaml             # VS Code打开
skills/dev/git_commit_push.yaml                 # Git提交
skills/dev/terminal_run.yaml                    # 终端命令
docs/skill-authoring-guide.md                   # 技能编写指南
```

### 修改文件（5 个）

```
src/memory/skill_models.py                      # 新增 yaml_path, triggers 字段
src/tools/skill_executor.py                     # 新增 YAML 执行路径
src/tools/skill_matcher.py                      # 新增 triggers 匹配
config/default.yaml                             # 新增 skills 配置节
docs/architecture.md                            # 更新架构图
docs/api-reference.md                           # 更新 API 文档
```
