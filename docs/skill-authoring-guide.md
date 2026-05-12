# 技能编写指南

> JavasAgent YAML 技能文件编写完整参考

---

## 1. 概述

JavasAgent 的技能系统允许通过 **YAML 声明式文件** 定义可复用的操作序列。每个技能文件描述一组有序的操作步骤（如键盘快捷键、鼠标点击、文字输入），系统按步骤顺序自动执行。

技能文件放置在 `skills/` 目录下，按类别分子目录：

```
skills/
├── system/       # 系统级操作（截图、打开应用、切换窗口）
├── office/       # 办公自动化（Word、Excel、PPT）
├── browser/      # 浏览器操作（打开网页、书签、下载）
└── dev/          # 开发工具（VS Code、Git、终端）
```

---

## 2. YAML 格式说明

### 2.1 基本结构

```yaml
name: "技能名称"                    # 必填：技能的显示名称
description: "技能描述"              # 必填：一句话描述
category: "分类"                    # 可选：system / office / browser / dev
version: "1.0"                     # 可选：版本号
triggers:                          # 可选：触发关键词列表
  - "关键词1"
  - "关键词2"

parameters:                        # 可选：参数定义
  param_name:
    type: string                   # 参数类型
    description: "参数说明"
    default: ""                    # 默认值（可选）
    required: false                # 是否必填

steps:                             # 必填：步骤列表
  - action: action_name            # 必填：动作名称
    ...                            # 动作参数（因 action 而异）
    comment: "步骤说明"             # 可选：注释
```

### 2.2 字段详解

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 技能唯一名称 |
| `description` | string | ✅ | 技能描述 |
| `category` | string | ❌ | 分类名，默认 `"yaml"` |
| `version` | string | ❌ | 版本号，默认 `"1.0"` |
| `triggers` | string[] | ❌ | 触发关键词，用于意图匹配 |
| `parameters` | dict | ❌ | 参数定义，键名为参数名 |
| `steps` | list | ✅ | 步骤列表，至少包含一个步骤 |

### 2.3 参数定义

每个参数支持以下属性：

```yaml
parameters:
  filename:
    type: string          # string | integer | number | boolean | array | object
    description: "说明"
    default: ""           # 默认值
    required: false       # 是否必填
```

---

## 3. Action 参考（20 个原语）

### 3.1 键盘动作

#### `key_combo` — 组合键

按下并释放组合键。

```yaml
- action: key_combo
  keys: "ctrl+c"           # 快捷键，用 + 连接
  comment: "复制"
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `keys` | string | ✅ | 快捷键，如 `"ctrl+c"`, `"alt+f4"`, `"ctrl+shift+g"` |

#### `key_type` — 单键输入

模拟按下并释放单个按键。

```yaml
- action: key_type
  key: "enter"
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `key` | string | ✅ | 按键名，如 `"enter"`, `"escape"`, `"tab"`, `"f12"` |

### 3.2 鼠标动作

#### `click` — 点击坐标

```yaml
- action: click
  x: 100
  y: 200
  button: "left"           # left | right | middle
  clicks: 1                # 点击次数
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `x` | int | ✅ | X 坐标 |
| `y` | int | ✅ | Y 坐标 |
| `button` | string | ❌ | 按钮类型，默认 `"left"` |
| `clicks` | int | ❌ | 点击次数，默认 `1` |

#### `double_click` — 双击坐标

```yaml
- action: double_click
  x: 150
  y: 300
```

#### `right_click` — 右键点击坐标

```yaml
- action: right_click
  x: 150
  y: 300
```

#### `drag` — 拖拽

```yaml
- action: drag
  start_x: 100
  start_y: 100
  end_x: 300
  end_y: 300
  duration: 0.5            # 拖拽时长（秒）
```

#### `scroll` — 滚轮

```yaml
- action: scroll
  clicks: 3                # 滚动次数
  direction: "down"        # up | down
```

#### `move_mouse` — 移动鼠标

```yaml
- action: move_mouse
  x: 500
  y: 400
  duration: 0.3            # 移动时长（秒）
```

### 3.3 文本动作

#### `type_text` — 输入文字

```yaml
- action: type_text
  text: "Hello World"      # 要输入的文本，支持 {{变量}}
  speed: "fast"            # fast | normal | slow
  comment: "输入搜索内容"
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `text` | string | ✅ | 要输入的文本，支持 `{{变量}}` 模板 |
| `speed` | string | ❌ | 输入速度：`"fast"` / `"normal"` / `"slow"` |

#### `click_text` — 点击屏幕上的文字

通过视觉识别定位屏幕上的文字并点击。

```yaml
- action: click_text
  text: "保存"             # 要查找的文字
  offset_x: 0              # X 偏移（像素）
  offset_y: 0              # Y 偏移（像素）
  comment: "点击保存按钮"
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `text` | string | ✅ | 目标文字 |
| `offset_x` | int | ❌ | X 偏移像素 |
| `offset_y` | int | ❌ | Y 偏移像素 |

### 3.4 视觉动作

#### `click_icon` — 点击图标

通过视觉描述定位图标并点击。

```yaml
- action: click_icon
  description: "关闭按钮"
  confidence: 0.8          # 置信度阈值
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `description` | string | ✅ | 图标描述 |
| `confidence` | float | ❌ | 置信度阈值 0-1 |

#### `assert_text` — 断言文字存在

验证屏幕上是否出现指定文字（支持正则）。

```yaml
- action: assert_text
  text: "保存成功|已完成"   # 文字或正则表达式
  timeout: 5.0             # 超时时间（秒）
  comment: "验证操作完成"
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `text` | string | ✅ | 期望文字，支持 `|` 分隔多个匹配 |
| `timeout` | float | ❌ | 等待超时（秒） |

#### `assert_screen` — 断言屏幕状态

验证屏幕是否满足指定条件。

```yaml
- action: assert_screen
  description: "文件已保存"
```

#### `screenshot` — 截图

截取当前屏幕并保存到上下文。

```yaml
- action: screenshot
  region: [0, 0, 800, 600]  # 可选：截取区域 [x, y, w, h]
  comment: "记录当前状态"
```

### 3.5 控制动作

#### `wait` — 等待

```yaml
- action: wait
  duration: 0.5            # 等待时长（秒）
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `duration` | float | ✅ | 等待秒数 |

#### `wait_text` — 等待文字出现

轮询屏幕直到指定文字出现或超时。

```yaml
- action: wait_text
  text: "加载完成"
  timeout: 5.0             # 超时时间（秒）
  interval: 0.5            # 轮询间隔（秒）
  comment: "等待页面加载"
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `text` | string | ✅ | 等待出现的文字 |
| `timeout` | float | ❌ | 超时时间（秒），默认 `5.0` |
| `interval` | float | ❌ | 轮询间隔（秒），默认 `0.5` |

#### `condition` — 条件分支

根据条件表达式决定是否执行子步骤。

```yaml
- action: condition
  when: "parameters.filename != ''"
  then:
    - action: key_combo
      keys: "ctrl+a"
    - action: type_text
      text: "{{parameters.filename}}"
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `when` | string | ✅ | 条件表达式 |
| `then` | list | ✅ | 条件为真时执行的步骤列表 |

#### `loop` — 循环

重复执行子步骤，最多 100 次。

```yaml
- action: loop
  max_iterations: 5
  steps:
    - action: key_combo
      keys: "tab"
    - action: wait
      duration: 0.1
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `max_iterations` | int | ✅ | 最大循环次数，≤ 100 |
| `steps` | list | ✅ | 循环体步骤列表 |

#### `run_skill` — 调用其他技能

嵌套调用另一个技能。

```yaml
- action: run_skill
  skill_name: "浏览器打开网页"
  parameters:
    url: "https://example.com"
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `skill_name` | string | ✅ | 目标技能名称 |
| `parameters` | dict | ❌ | 传递给子技能的参数 |

> ⚠️ 注意：`run_skill` 会嵌套调用，请控制递归深度。

#### `set_var` — 设置变量

在步骤间传递中间结果。

```yaml
- action: set_var
  key: "count"
  value: 42
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `key` | string | ✅ | 变量名（支持点号路径） |
| `value` | any | ✅ | 变量值 |

---

## 4. 变量语法

### 4.1 模板变量 `{{xxx}}`

在步骤的字符串值中使用 `{{...}}` 引用上下文变量：

```yaml
- action: type_text
  text: "{{parameters.filename}}"      # 引用用户参数

- action: type_text
  text: "{{variables.saved_path}}"     # 引用中间变量
```

**支持的命名空间：**
- `parameters.xxx` — 用户传入的参数（只读）
- `variables.xxx` — 步骤中间变量（通过 `set_var` 写入）
- `result.xxx` — 最终执行结果

**点号路径：** 支持多级嵌套访问，如 `parameters.config.path`。

### 4.2 条件表达式语法

`condition` 动作的 `when` 字段使用安全表达式求值器（不使用 eval）。

**比较运算符：**

| 运算符 | 说明 | 示例 |
|--------|------|------|
| `==` | 等于 | `parameters.name == "test"` |
| `!=` | 不等于 | `parameters.filename != ""` |
| `>` | 大于 | `variables.count > 0` |
| `<` | 小于 | `variables.retry < 3` |
| `>=` | 大于等于 | `variables.size >= 100` |
| `<=` | 小于等于 | `variables.count <= 10` |

**逻辑运算符：**

| 运算符 | 说明 | 示例 |
|--------|------|------|
| `and` | 逻辑与 | `parameters.a != "" and parameters.b != ""` |
| `or` | 逻辑或 | `variables.status == "ok" or variables.status == "done"` |
| `not` | 逻辑非 | `not parameters.dry_run` |
| `in` | 字符串包含 | `"error" in variables.message` |

**字面量：**

| 类型 | 示例 |
|------|------|
| 字符串 | `"hello"`, `"保存成功"` |
| 数字 | `42`, `3.14` |
| 布尔 | `true`, `false` |

---

## 5. 完整示例：Word 另存为 PDF

```yaml
name: "Word 另存为 PDF"
description: "在 Word 中将当前文档另存为 PDF 格式"
category: "office"
version: "1.0"
triggers:
  - "word 保存 pdf"
  - "word 导出 pdf"
  - "word 转 pdf"
  - "另存为 pdf"

parameters:
  filename:
    type: string
    description: "保存的文件名（不含扩展名）"
    default: ""
    required: false

steps:
  # 步骤 1: 打开另存为对话框
  - action: key_combo
    keys: "f12"
    comment: "打开另存为对话框"

  # 步骤 2: 等待对话框出现
  - action: wait_text
    text: "另存为"
    timeout: 3.0
    comment: "等待对话框出现"

  # 步骤 3: 切换文件类型
  - action: click_text
    text: "文件类型"
    offset_x: 50
    comment: "点击文件类型下拉框"

  - action: wait
    duration: 0.3

  # 步骤 4: 选择 PDF 格式
  - action: click_text
    text: "PDF"
    comment: "选择 PDF 格式"

  # 步骤 5: 条件分支——如果用户指定了文件名，则修改
  - action: condition
    when: "parameters.filename != ''"
    then:
      - action: key_combo
        keys: "ctrl+a"
      - action: type_text
        text: "{{parameters.filename}}"
        speed: "fast"

  # 步骤 6: 确认保存
  - action: key_combo
    keys: "enter"
    comment: "确认保存"

  # 步骤 7: 等待保存完成
  - action: wait
    duration: 2.0

  # 步骤 8: 验证结果
  - action: assert_text
    text: "保存成功|已完成|100%"
    comment: "验证保存完成"
```

---

## 6. 编写最佳实践

1. **步骤注释**：每个步骤都加 `comment`，说明该步骤的目的
2. **等待策略**：操作之间适当插入 `wait` 或 `wait_text`，避免因 UI 未响应导致失败
3. **条件分支**：可选参数用 `condition` 包裹，空值时不执行
4. **验证结果**：关键操作后用 `assert_text` 或 `assert_screen` 验证
5. **变量传递**：需要跨步骤传递数据时，使用 `set_var` + `{{variables.xxx}}`
6. **文件大小**：每个 YAML 文件不超过 20KB
7. **编码格式**：统一使用 UTF-8 编码
8. **文件命名**：使用小写字母 + 下划线，如 `word_save_pdf.yaml`
9. **循环限制**：`loop` 的 `max_iterations` 不超过 100
10. **嵌套深度**：避免 `run_skill` 深层嵌套调用
