# JavasAgent 技能描述执行系统 — 技术交底书与可行性报告

> 版本: 1.0 | 日期: 2026-05-12
> 作者: 程序员 | 状态: 待评审

---

## 一、问题定义

### 1.1 现状

JavasAgent 有完整的技能框架：
- `SkillDefinition` 模型（名称、描述、参数、步骤）
- `SkillRegistry` 注册表（注册、搜索、持久化到 JSON）
- `SkillMatcher` 匹配器（文本关键词匹配）
- `SkillExecutor` 执行器（需注册 Python 函数）
- `SkillLearner` 学习器（从历史提取模式）

**但缺一个关键环节：技能描述里写的操作步骤，没有引擎能解析和执行。**

举例：用户想让 Agent "用 Word 另存为 PDF"。

**现在的做法：** 必须写 Python 代码（一个 Tool 类），注册到 ToolRegistry，才能用。

**目标做法：** 写一个 YAML 文件描述操作步骤，Agent 自动解析执行。

```yaml
# skills/word_save_pdf.yaml — 零代码扩展能力
name: "Word 另存为 PDF"
description: "在 Word 中将当前文档另存为 PDF 格式"
triggers: ["word 保存 pdf", "word 导出 pdf", "word 转 pdf"]

steps:
  - action: key_combo
    keys: "ctrl+f"          # 打开查找？不对，应该用 F12 另存为
    keys: "f12"             # 打开另存为对话框
    
  - action: wait
    duration: 1.0           # 等待对话框出现
    
  - action: click_text
    text: "文件类型"         # OCR 找到"文件类型"下拉框
    offset_x: 50            # 点击下拉框
    
  - action: click_text
    text: "PDF"             # 从下拉列表中选择 PDF
    
  - action: key_combo
    keys: "enter"           # 确认保存
```

### 1.2 目标

| 场景 | 扩展方式 | 需要写代码？ |
|------|---------|-------------|
| 通用操作（点击、打字、快捷键） | 写 YAML 技能文件 | ❌ |
| 复杂逻辑（条件判断、循环） | 写 YAML + 简单表达式 | ❌ |
| 深度集成（COM 接口、API 调用） | 写 Python Tool 类 | ✅ |

---

## 二、技术方案

### 2.1 整体架构

```
用户说 "把 Word 文档转成 PDF"
        ↓
  ┌─────────────────────┐
  │   Planner (LLM)     │  理解意图，匹配技能
  │   搜索 SkillRegistry │  找到 "word_save_pdf"
  └──────────┬──────────┘
             ↓
  ┌─────────────────────┐
  │  SkillLoader        │  加载 YAML 技能文件
  │  解析 steps 列表     │
  └──────────┬──────────┘
             ↓
  ┌──────────────────────────────────────┐
  │       StepExecutor (核心新增)         │
  │                                      │
  │  可执行的原语（Atomic Actions）：      │
  │                                      │
  │  key_combo   — 组合键 Ctrl+S         │
  │  key_type    — 输入文字 "hello"       │
  │  click       — 点击坐标 (x, y)       │
  │  click_text  — OCR 找文字 → 点击      │
  │  click_icon  — 视觉找图标 → 点击      │
  │  double_click— 双击                  │
  │  right_click — 右键                  │
  │  drag        — 拖拽 A→B             │
  │  scroll      — 滚轮上下滚动          │
  │  wait        — 等待 N 秒            │
  │  wait_text   — 等某文字出现          │
  │  screenshot  — 截屏                  │
  │  type_text   — 拟人打字（有间隔）     │
  │  move_mouse  — 拟人移动鼠标          │
  │  assert_text — 断言文字存在（验证）   │
  │  assert_screen— 断言屏幕变化         │
  │  run_skill   — 调用另一个技能（嵌套） │
  │  condition   — 条件分支              │
  │  loop        — 循环（最多 N 次）      │
  │                                      │
  │  每个原语映射到 Platform 层的一个方法  │
  └──────────────────────────────────────┘
```

### 2.2 技能文件格式设计

```yaml
# skills/word_save_pdf.yaml
# JavasAgent 技能描述文件

# === 元信息 ===
name: "Word 另存为 PDF"
version: "1.0"
description: "在 Word 中将当前文档另存为 PDF 格式"
author: "system"
category: "office"           # 分类：office / browser / system / dev / media

# === 触发条件 ===
triggers:                     # 匹配关键词（用于 SkillMatcher）
  - "word 保存 pdf"
  - "word 导出 pdf"
  - "word 转 pdf"
  - "另存为 pdf"

# === 前置条件 ===
requirements:                 # 执行前检查
  - type: window_active       # 当前活动窗口是 Word
    pattern: "Word|文档"
  - type: file_open           # 有打开的文档（可选）

# === 参数定义 ===
parameters:
  filename:
    type: string
    description: "保存的文件名（不含扩展名）"
    default: ""               # 空则使用原文件名
    required: false

# === 执行步骤 ===
steps:
  # 步骤 1：打开另存为对话框
  - action: key_combo
    keys: "f12"
    comment: "打开另存为对话框"
    
  # 步骤 2：等待对话框出现
  - action: wait_text
    text: "另存为"
    timeout: 3.0
    comment: "等待另存为对话框"
    
  # 步骤 3：修改文件类型
  - action: click_text
    text: "文件类型"
    offset_x: 50
    comment: "点击文件类型下拉框"
    
  - action: wait
    duration: 0.3
    
  - action: click_text
    text: "PDF"
    comment: "选择 PDF 格式"
    
  # 步骤 4：（可选）修改文件名
  - action: condition
    when: "parameters.filename != ''"
    then:
      - action: key_combo
        keys: "ctrl+a"        # 全选文件名
      - action: type_text
        text: "{{filename}}"  # 使用参数
        speed: "fast"
    
  # 步骤 5：确认保存
  - action: key_combo
    keys: "enter"
    comment: "确认保存"
    
  # 步骤 6：验证
  - action: wait
    duration: 2.0
  - action: assert_text
    text: "保存成功|已完成|100%"
    comment: "验证保存完成"
```

### 2.3 核心组件设计

#### 组件 1：SkillLoader（技能加载器）

**职责：** 扫描 `skills/` 目录，加载 YAML 文件，注册到 SkillRegistry。

```python
# src/skills/skill_loader.py
class SkillLoader:
    """从 YAML 文件加载技能定义。"""
    
    def __init__(self, skills_dir: str = "./skills"):
        self._skills_dir = Path(skills_dir)
    
    async def load_all(self) -> list[SkillDefinition]:
        """扫描目录，加载所有 .yaml 技能文件。"""
    
    async def load_file(self, path: Path) -> SkillDefinition:
        """加载单个 YAML 文件，解析为 SkillDefinition。"""
    
    def validate(self, data: dict) -> list[str]:
        """验证 YAML 格式是否正确，返回错误列表。"""
```

#### 组件 2：StepExecutor（步骤执行器）— 核心新增

**职责：** 解析 YAML 中的 action，映射到 Platform 层方法执行。

```python
# src/skills/step_executor.py
class StepExecutor:
    """YAML 技能步骤执行器。"""
    
    def __init__(self, platform, perception):
        self._platform = platform      # WindowsPlatform
        self._perception = perception   # VisionEye + OCR
        self._action_map = {
            "key_combo": self._exec_key_combo,
            "key_type": self._exec_key_type,
            "click": self._exec_click,
            "click_text": self._exec_click_text,
            "click_icon": self._exec_click_icon,
            "double_click": self._exec_double_click,
            "right_click": self._exec_right_click,
            "drag": self._exec_drag,
            "scroll": self._exec_scroll,
            "wait": self._exec_wait,
            "wait_text": self._exec_wait_text,
            "screenshot": self._exec_screenshot,
            "type_text": self._exec_type_text,
            "move_mouse": self._exec_move_mouse,
            "assert_text": self._exec_assert_text,
            "assert_screen": self._exec_assert_screen,
            "run_skill": self._exec_run_skill,
            "condition": self._exec_condition,
            "loop": self._exec_loop,
        }
    
    async def execute_step(self, step: dict, context: dict) -> dict:
        """执行单个步骤，返回结果。"""
    
    async def execute_steps(self, steps: list[dict], context: dict) -> dict:
        """顺序执行步骤列表，支持错误中断。"""
```

**每个原语的实现映射：**

| YAML action | 实现方法 | 依赖 |
|-------------|---------|------|
| `key_combo` | `platform.key_combo("ctrl+s")` | pyautogui |
| `key_type` | `platform.type_key("a")` | pyautogui |
| `click` | `platform.click(x, y)` | pyautogui |
| `click_text` | `perception.find_text("保存") → platform.click(x, y)` | OCR + pyautogui |
| `click_icon` | `perception.find_object("保存按钮") → platform.click(x, y)` | GroundingDINO + pyautogui |
| `type_text` | `humanhand.type_text("hello")` | HumanHand 拟人打字 |
| `move_mouse` | `humanhand.move_to(x, y)` | HumanHand 贝塞尔曲线 |
| `wait` | `asyncio.sleep(duration)` | — |
| `wait_text` | `循环 OCR 直到文字出现` | OCR |
| `assert_text` | `OCR 检查文字是否存在` | OCR |
| `condition` | `解析 when 表达式，执行 then/else` | 简单表达式解析器 |
| `loop` | `循环执行 steps，最多 N 次` | — |
| `run_skill` | `递归调用另一个技能` | SkillExecutor |

#### 组件 3：ExpressionEvaluator（简单表达式求值）

**职责：** 解析 YAML 中的条件表达式（`when` 字段）。

```python
# src/skills/expression.py
class ExpressionEvaluator:
    """安全的简单表达式求值器。"""
    
    def evaluate(self, expr: str, context: dict) -> bool:
        """
        支持：
        - parameters.filename != ""
        - parameters.count > 0
        - result.status == "ok"
        - "PDF" in result.text
        """
```

**不使用 eval()** — 自己实现一个迷你解析器，只支持比较运算符和字符串操作。
安全第一。

#### 组件 4：SkillContext（执行上下文）

**职责：** 在步骤之间传递数据。

```python
# src/skills/context.py
@dataclass
class SkillContext:
    """技能执行上下文，在步骤之间传递数据。"""
    parameters: dict           # 用户传入的参数
    variables: dict            # 步骤中间变量（set_var 设置）
    result: dict               # 最终结果
    screenshots: list[bytes]   # 执行过程截图（证据）
    
    def get(self, key: str) -> Any:
        """获取变量，支持 parameters.xxx 和 variables.xxx"""
    
    def set(self, key: str, value: Any) -> None:
        """设置中间变量"""
```

#### 组件 5：SkillValidator（技能验证器）

**职责：** 验证 YAML 文件格式、动作合法性、参数完整性。

```python
# src/skills/validator.py
class SkillValidator:
    """YAML 技能文件验证器。"""
    
    def validate(self, data: dict) -> ValidationResult:
        """验证技能定义是否合法。"""
        # 检查必填字段
        # 检查 action 名称是否合法
        # 检查参数类型
        # 检查循环次数上限（防死循环）
        # 检查嵌套深度（防递归爆栈）
```

### 2.4 与现有代码的关系

**新增文件（不修改现有代码）：**
```
src/skills/
├── __init__.py
├── skill_loader.py       # YAML 加载器
├── step_executor.py      # 步骤执行器（核心）
├── expression.py         # 条件表达式求值
├── context.py            # 执行上下文
├── validator.py          # 技能验证器
└── actions/              # 原语实现（每个文件一个原语类别）
    ├── __init__.py
    ├── keyboard.py       # key_combo, key_type
    ├── mouse.py          # click, double_click, right_click, drag, scroll
    ├── text.py           # type_text, click_text
    ├── vision.py         # click_icon, assert_text, assert_screen
    ├── control.py        # wait, wait_text, condition, loop, run_skill
    └── screen.py         # screenshot
```

**修改文件（最小改动）：**
```
src/tools/skill_executor.py   # 添加 YAML 技能的执行路径
src/memory/skill_models.py    # SkillDefinition 增加 yaml_path 字段
config/default.yaml           # 添加 skills 配置节
```

### 2.5 预置技能库

系统自带一批常用技能（`skills/` 目录）：

```
skills/
├── system/
│   ├── screenshot.yaml          # 全屏截图
│   ├── screenshot_region.yaml   # 区域截图
│   ├── open_app.yaml            # 打开应用程序
│   └── switch_window.yaml       # 切换窗口
├── office/
│   ├── word_save_pdf.yaml       # Word 转 PDF
│   ├── excel_format_table.yaml  # Excel 格式化表格
│   └── ppt_export_images.yaml   # PPT 导出图片
├── browser/
│   ├── browser_open_url.yaml    # 打开网页
│   ├── browser_bookmark.yaml    # 添加书签
│   └── browser_download.yaml    # 下载文件
└── dev/
    ├── vscode_open_project.yaml # VS Code 打开项目
    ├── git_commit_push.yaml     # Git 提交推送
    └── terminal_run.yaml        # 终端执行命令
```

---

## 三、为什么这么做

### 3.1 为什么用 YAML 不用 Python？

| | YAML 技能文件 | Python Tool 类 |
|---|---|---|
| 学习门槛 | 低（写配置） | 高（写代码） |
| 安全性 | 高（有限原语） | 低（任意代码） |
| 可视化 | 好（步骤清晰） | 差（逻辑在代码里） |
| 可分享 | 好（复制文件） | 中（需 pip install） |
| 表达能力 | 中（有限原语） | 高（任意 Python） |

**结论：** 80% 的操作可以用 YAML 描述。剩下 20%（COM 接口、API 调用）用 Python Tool。

### 3.2 为什么不用 LLM 直接规划操作？

可以让 Agent 每次都靠 LLM 规划"下一步点哪里"。但：
- **不可靠** — LLM 不知道当前屏幕长什么样，容易瞎指挥
- **慢** — 每一步都要调 LLM，延迟高
- **贵** — 一个操作 10 步 = 10 次 LLM 调用

YAML 技能是**确定性执行**：写好步骤，每一步精确执行，不需要 LLM 介入。只在"匹配哪个技能"和"参数是什么"时用 LLM。

### 3.3 为什么需要条件表达式？

同一个技能在不同情况下步骤不同。比如"另存为 PDF"：
- 如果用户指定了文件名 → 需要输入文件名
- 如果没指定 → 跳过

没有条件表达式，就必须拆成两个技能文件。有了 `condition`，一个文件搞定。

---

## 四、可行性评估

### 4.1 技术可行性

| 组件 | 可行性 | 风险 | 说明 |
|------|--------|------|------|
| YAML 加载 | ✅ 高 | 无 | PyYAML 已有 |
| 步骤执行器 | ✅ 高 | 低 | 映射到已有 Platform 方法 |
| click_text (OCR) | ⚠️ 中 | OCR 精度 | 需要一个好的 OCR 引擎 |
| click_icon (视觉) | ⚠️ 中 | 模型依赖 | 需要 GroundingDINO |
| 条件表达式 | ✅ 高 | 低 | 简单解析器，不用 eval |
| 嵌套技能调用 | ⚠️ 中 | 递归深度 | 限制最大深度 5 |

### 4.2 依赖

无新增依赖。全部基于已有模块：
- `pyyaml` — YAML 解析（已有）
- Platform 层 — pyautogui（已有）
- OCR — PaddleOCR / Windows OCR（已有框架）
- 视觉 — GroundingDINO（已有框架）

---

## 五、安全考量

### 5.1 表达式求值安全

**坚决不用 eval()。** 自己实现迷你解析器，只支持：
- 比较运算：`==`, `!=`, `>`, `<`, `>=`, `<=`
- 字符串包含：`"xxx" in variable`
- 变量访问：`parameters.xxx`, `variables.xxx`, `result.xxx`
- 逻辑运算：`and`, `or`, `not`

不支持：函数调用、import、exec、任意代码。

### 5.2 循环安全

YAML 中 `loop` 最大迭代次数硬编码上限 100。
超过自动停止。

### 5.3 嵌套调用安全

`run_skill` 最大递归深度 5。
超过抛异常。

### 5.4 技能来源安全

- 系统预置技能（`skills/` 目录）— 可信
- 用户自定义技能（`data/skills/` 目录）— 用户自行负责
- 从网络下载的技能 — 需要用户确认（未来功能）

---

## 六、开发规模

| 组件 | 代码量 | 预计时间 |
|------|--------|---------|
| skill_loader.py | ~200 行 | 20 min |
| step_executor.py | ~400 行 | 40 min |
| expression.py | ~150 行 | 25 min |
| context.py | ~80 行 | 10 min |
| validator.py | ~150 行 | 20 min |
| actions/keyboard.py | ~60 行 | 10 min |
| actions/mouse.py | ~80 行 | 10 min |
| actions/text.py | ~80 行 | 10 min |
| actions/vision.py | ~100 行 | 15 min |
| actions/control.py | ~120 行 | 15 min |
| actions/screen.py | ~40 行 | 5 min |
| skill_executor.py 修改 | ~50 行 | 10 min |
| 测试 | ~600 行 | 60 min |
| 预置技能文件 12 个 | ~600 行 YAML | 30 min |
| **合计** | **~2710 行** | **~5 小时** |

---

## 七、与后台服务的关系

技能执行系统是 Agent 内核的一部分，与后台服务独立：
- 后台服务启动 → 加载 Agent → 加载技能注册表 → 自动加载 YAML 技能
- 热键呼出 → 用户说 "帮我转 PDF" → 匹配技能 → 执行 YAML 步骤
- 语音唤醒 → "把文档转成 PDF" → 同上

两者可以并行开发，互不依赖。
