# JavasAgent 技能库

本目录包含 JavasAgent 的 YAML 技能文件。每个 `.yaml` 文件定义一个可被 Agent 自动匹配和执行的技能。

## 目录结构

```
skills/
├── system/      # 系统级操作（截图、窗口切换等）
├── office/      # Office 操作（Word、Excel、PPT）
├── browser/     # 浏览器操作
└── dev/         # 开发工具操作（VS Code、Git、终端）
```

## 如何编写技能

### 最小示例

```yaml
name: "我的技能"
description: "技能描述"
steps:
  - action: wait
    duration: 1.0
```

### 完整示例（带参数和条件）

```yaml
name: "Word 另存为 PDF"
description: "在 Word 中将当前文档另存为 PDF 格式"
category: "office"
version: "1.0"
triggers:
  - "word 保存 pdf"
  - "word 转 pdf"

parameters:
  filename:
    type: string
    description: "保存的文件名"
    default: ""
    required: false

steps:
  - action: key_combo
    keys: "f12"
    comment: "打开另存为"

  - action: wait
    duration: 1.0

  - action: condition
    when: "parameters.filename != ''"
    then:
      - action: key_combo
        keys: "ctrl+a"
      - action: type_text
        text: "{{parameters.filename}}"
        speed: "fast"

  - action: key_combo
    keys: "enter"
```

## 支持的 Action（20 个）

| Action | 说明 | 关键参数 |
|--------|------|---------|
| `key_combo` | 组合键 | `keys` |
| `key_type` | 单键输入 | `keys` |
| `click` | 点击坐标 | `x`, `y` |
| `double_click` | 双击 | `x`, `y` |
| `right_click` | 右键点击 | `x`, `y` |
| `drag` | 拖拽 | `start_x`, `start_y`, `end_x`, `end_y` |
| `scroll` | 滚动 | `amount`（正=上，负=下） |
| `move_mouse` | 移动鼠标 | `x`, `y` |
| `type_text` | 拟人打字 | `text`, `speed` |
| `click_text` | OCR找字点击 | `text`, `timeout`, `offset_x`, `offset_y` |
| `click_icon` | 视觉找图标点击 | `description`, `timeout` |
| `wait` | 等待 | `duration`（秒，上限30） |
| `wait_text` | 等待文字出现 | `text`, `timeout`, `interval` |
| `screenshot` | 截屏 | `region`, `save_to` |
| `assert_text` | 断言文字存在 | `text`（支持 `\|` 分隔多匹配） |
| `assert_screen` | 断言屏幕变化 | `min_change` |
| `condition` | 条件分支 | `when`, `then`, `else` |
| `loop` | 循环 | `steps`, `max_iterations`, `break_when` |
| `run_skill` | 嵌套调用技能 | `skill_name`, `params` |
| `set_var` | 设置变量 | `name`, `value` |

## 条件表达式语法

`when` 字段支持以下运算符（**不使用 eval，安全执行**）：

- 比较：`==`, `!=`, `>`, `<`, `>=`, `<=`
- 字符串包含：`"PDF" in result.text`
- 逻辑：`and`, `or`, `not`
- 变量路径：`parameters.filename`, `variables.count`
- 括号分组：`(a > 0) and (b < 10)`

## 模板变量

字符串中的 `{{key}}` 会在执行时替换为上下文中的值：

- `{{parameters.filename}}` → 用户传入的参数
- `{{variables.count}}` → 步骤中间变量
