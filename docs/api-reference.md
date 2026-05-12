# API 参考文档

> JavasAgent 核心 API 签名与参数说明

---

## 核心层 API

### BaseAgent

位于 `src/agents/base_agent.py`，Agent 核心循环的实现。

```python
class BaseAgent(TeamIntegrationMixin):
    def __init__(self, config: AppConfig, platform: PlatformAdapter | None = None)
    async def process(self, user_input: str) -> str
    async def feedback(self, message: str) -> str | None
    async def initialize_memory(self) -> None
    async def recall(self, query: str, top_k: int = 5) -> list
    async def remember(self, content: str, category: str = "experience") -> str | None
    @property
    def status(self) -> dict
    def get_team_status(self) -> dict
```

| 方法 | 说明 |
|------|------|
| `process(user_input)` | 处理用户输入，返回结果字符串。核心入口 |
| `feedback(message)` | 处理反馈（确认/取消/补充说明），继续挂起的决策 |
| `initialize_memory()` | 初始化短期和长期记忆（异步） |
| `recall(query, top_k)` | 从长期记忆检索相关条目 |
| `remember(content, category)` | 存入长期记忆，返回 entry_id |
| `status` | 返回运行状态、调度器状态、记忆大小的字典 |
| `get_team_status()` | 返回多 Agent 团队状态 |

### Planner

位于 `src/core/planner.py`，将用户意图拆解为步骤链。

```python
class Planner:
    def __init__(self, llm: LLMClient)
    def register_tool_descriptions(self, descriptions: dict[str, str]) -> None
    async def plan(self, user_input: str, context: list[dict] | None = None) -> TaskPlan
```

| 方法 | 说明 |
|------|------|
| `register_tool_descriptions(descriptions)` | 注册可用工具描述，影响 LLM 规划 |
| `plan(user_input, context)` | 将用户输入解析为 TaskPlan |

### Executor

位于 `src/core/executor.py`，按步骤执行任务计划。

```python
class Executor:
    def register_tool(self, name: str, tool: Any) -> None
    def add_observer(self, observer: ExecutionObserver) -> None
    @property
    def is_busy(self) -> bool
    @property
    def current_plan(self) -> TaskPlan | None
    async def execute(self, plan: TaskPlan) -> ExecutionResult
```

| 方法 | 说明 |
|------|------|
| `register_tool(name, tool)` | 注册工具实例 |
| `add_observer(observer)` | 添加执行观察者 |
| `is_busy` | 当前是否有任务在执行 |
| `execute(plan)` | 执行任务计划，返回 ExecutionResult |

### Decider

位于 `src/core/decider.py`，决策点判断。

```python
class Decider:
    def __init__(self, config: AgentConfig)
    def should_ask_human(self, decision: DecisionPoint) -> bool
    def evaluate(self, context: str, question: str, confidence: float,
                 options: list[str] | None = None) -> DecisionPoint
```

| 方法 | 说明 |
|------|------|
| `should_ask_human(decision)` | 判断是否需要询问人类（置信度 < 阈值 / 高风险操作） |
| `evaluate(context, question, confidence, options)` | 创建并评估决策点 |

### Scheduler

位于 `src/core/scheduler.py`，优先级任务队列。

```python
class Scheduler:
    def __init__(self, max_concurrent: int = 1)
    async def submit(self, plan: TaskPlan) -> None
    @property
    def has_running_task(self) -> bool
    @property
    def running_tasks(self) -> list[TaskPlan]
    @property
    def queued_count(self) -> int
    @property
    def completed_count(self) -> int
```

---

## 数据模型

位于 `src/core/models.py`。

### TaskPlan

```python
@dataclass
class TaskPlan:
    id: str
    intent: str
    steps: list[Step]
    priority: Priority          # LOW=0 / NORMAL=5 / HIGH=10 / URGENT=20
    created_at: datetime
    status: PlanStatus          # PENDING / RUNNING / PAUSED / DONE / FAILED
    parent_id: str | None
```

### Step

```python
@dataclass
class Step:
    id: str
    action: str                 # 动作描述
    tool: str                   # 使用的工具名
    params: dict                # 工具参数
    depends_on: list[str]       # 前置步骤 ID
    retry_count: int
    max_retries: int            # 默认 3
    status: StepStatus          # PENDING / RUNNING / DONE / FAILED / SKIPPED
    result: str | None
    error: str | None
```

### ExecutionResult

```python
@dataclass
class ExecutionResult:
    plan_id: str
    status: PlanStatus
    completed_steps: int
    total_steps: int
    errors: list[str]
    duration_ms: float
```

### DecisionPoint

```python
@dataclass
class DecisionPoint:
    context: str
    question: str
    confidence: float           # 0-1
    auto_decided: bool
    options: list[str]
```

---

## 平台层 API

### PlatformAdapter（基类）

位于 `src/platforms/base.py`，所有平台适配器的抽象基类。

```python
class PlatformAdapter(ABC):
    async def screenshot(self, region: tuple[int,int,int,int] | None = None) -> bytes
    async def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> None
    async def type_text(self, text: str, interval: float = 0.02) -> None
    async def press_key(self, key: str) -> None
    async def hotkey(self, *keys: str) -> None
    async def get_active_window(self) -> dict[str, Any]
    async def find_window(self, title: str) -> list[dict[str, Any]]
    async def activate_window(self, window_id: str) -> bool
    async def scroll(self, clicks: int = 3, direction: str = "down") -> None
    async def move_to(self, x: int, y: int, duration: float = 0.3) -> None
    async def drag_to(self, start_x, start_y, end_x, end_y, duration=0.5, button="left") -> None
    async def get_screen_size(self) -> dict[str, int]
```

### MotorController

位于 `src/platforms/motor_controller.py`，感知闭环控制器。

```python
class MotorController:
    def __init__(self, vision: VisionEye, hand: HumanHand, config: MotorControllerConfig | None = None)
    async def click_target(self, description: str, verify: bool = True) -> ActionResult
    async def type_in_field(self, target_desc: str, text: str) -> ActionResult
    async def verify_action(self, expected: str) -> ActionResult
```

### HumanHand

位于 `src/platforms/human_hand.py`，拟人手部模拟器。

```python
class HumanHand:
    def __init__(self, adapter: PlatformAdapter, config: HumanHandConfig | None = None)
    async def human_move_to(self, x: int, y: int, duration: float | None = None) -> None
    async def human_click(self, x: int, y: int, button: str = "left") -> None
    async def human_type(self, text: str) -> None
    async def human_hotkey(self, *keys: str) -> None
```

---

## 语音层 API

### VoicePipeline

位于 `src/voice/pipeline.py`，完整语音管道。

```python
class VoicePipeline:
    def __init__(self, agent: Any, voice_ops: Any, config: VoicePipelineConfig | None = None)
    @property
    def state(self) -> PipelineState       # IDLE / LISTENING / PROCESSING / SPEAKING
    @property
    def is_running(self) -> bool
    def set_state_callback(self, cb: Callable[[PipelineState], None]) -> None
    async def start(self) -> None
    async def stop(self) -> None
```

### VoicePipelineConfig

```python
@dataclass
class VoicePipelineConfig:
    wake_words: list[str]              # 唤醒词列表
    wake_word_enabled: bool            # 是否启用唤醒词
    vad_threshold: float               # VAD 阈值 (0-1)
    silence_timeout: float             # 静音超时（秒）
    continuous_mode: bool              # 连续对话模式
    continuous_timeout: float          # 连续模式超时（秒）
    interruption_enabled: bool         # 允许打断
    stt_engine: str                    # STT 引擎
    tts_engine: str                    # TTS 引擎
    greeting: str                      # 唤醒后问候语
    farewell: str                      # 退出告别语
```

### AudioStream

位于 `src/voice/audio_stream.py`，麦克风音频流管理。

```python
class AudioStream:
    def start(self, callback: Callable[[bytes], None], sample_rate: int = 16000,
              chunk_size: int = 512) -> None
    def stop(self) -> None
    @staticmethod
    def save_wav(data: bytes, path: str, sample_rate: int = 16000) -> None
```

---

## 感知层 API

### VisionEye

位于 `src/perception/vision_eye.py`，视觉感知器。

```python
class VisionEye:
    def __init__(self, llm: LLMClient, config: PerceptionConfig)
    async def capture_and_analyze(self) -> VisionFrame
    async def find_target(self, description: str) -> list[TargetInfo]
    async def locate_on_screen(self, description: str) -> tuple[int, int] | None
```

---

## 配置参考

完整配置见 `config/default.yaml`，主要配置节：

| 配置节 | 字段 | 说明 |
|--------|------|------|
| `agent` | `name`, `ask_human_threshold`, `max_task_duration`, `max_step_retries` | Agent 基础配置 |
| `llm` | `default_provider`, `providers.*`, `temperature`, `max_tokens` | LLM 接入配置 |
| `memory` | `short_term_max_messages`, `long_term_db_path`, `embedding_model` | 记忆系统配置 |
| `platform` | `action_delay`, `screenshot_path`, `log_level`, `log_path` | 平台层配置 |
| `tools.*` | `enabled` | 各工具启用/禁用 |
| `voice` | `wake_word`, `vad`, `stt`, `tts`, `pipeline` | 语音模块配置 |
| `email` | `smtp_host`, `imap_host`, `address`, `password` | 邮件配置 |

---

## 技能系统 API

技能系统位于 `src/skills/`，负责加载、验证和执行 YAML 定义的声明式技能。

### SkillLoader

位于 `src/skills/skill_loader.py`，扫描目录并加载 YAML 技能文件。

```python
class SkillLoader:
    def __init__(self, skills_dirs: list[str] | None = None) -> None
    def load_all(self) -> list[SkillDefinition]
    def load_file(self, path: Path) -> SkillDefinition | None
    def reload(self) -> list[SkillDefinition]
    def get_skill_path(self, skill_name: str) -> Path | None
```

| 方法 | 说明 |
|------|------|
| `__init__(skills_dirs)` | 初始化加载器，`skills_dirs` 默认 `["./skills", "./data/skills"]` |
| `load_all()` | 扫描所有目录的 `*.yaml` 文件，验证后返回 `SkillDefinition` 列表 |
| `load_file(path)` | 加载单个 YAML 文件，验证失败返回 `None` |
| `reload()` | 清空缓存后重新加载所有技能 |
| `get_skill_path(skill_name)` | 根据技能名称查找对应文件路径 |

**加载流程：** 读取 YAML → `SkillValidator.validate()` → 转换为 `SkillDefinition` → 缓存。

### StepExecutor

位于 `src/skills/step_executor.py`，顺序执行步骤链的核心调度器。

```python
class StepExecutor:
    def __init__(
        self,
        platform: Any = None,
        perception: Any = None,
        humanhand: Any = None,
        skill_executor: Any = None,
    ) -> None
    async def execute_step(self, step: dict[str, Any], context: SkillContext) -> dict[str, Any]
    async def execute_steps(self, steps: list[dict[str, Any]], context: SkillContext) -> dict[str, Any]
    def _resolve_params(self, step: dict[str, Any], context: SkillContext) -> dict[str, Any]
```

| 方法 | 说明 |
|------|------|
| `__init__(platform, perception, humanhand, skill_executor)` | 初始化执行器，注入平台和感知依赖 |
| `execute_step(step, context)` | 执行单个步骤：查 ACTION_REGISTRY → 模板替换 → 调用 action 函数 |
| `execute_steps(steps, context)` | 顺序执行步骤列表，某步失败时中断 |
| `_resolve_params(step, context)` | 对步骤中所有字符串值做 `{{xxx}}` 模板变量替换 |

**执行结果格式：**

```python
# 成功
{"success": True, "completed_steps": 5, "total_steps": 5}

# 失败
{"success": False, "completed_steps": 2, "total_steps": 5,
 "failed_step": 2, "failed_action": "click_text", "error": "未找到目标文字"}
```

### SkillContext

位于 `src/skills/context.py`，步骤间传递参数和变量的上下文对象。

```python
@dataclass
class SkillContext:
    parameters: dict[str, Any]        # 用户传入参数（只读）
    variables: dict[str, Any]         # 步骤中间变量（可读写）
    result: dict[str, Any]            # 最终执行结果
    screenshots: list[bytes]          # 执行过程截图列表
    current_step: int                 # 当前步骤索引（从 0 开始）
    total_steps: int                  # 总步骤数

    def get(self, key: str, default: Any = None) -> Any
    def set(self, key: str, value: Any) -> None
    def resolve(self, template: Any) -> Any
    def to_dict(self) -> dict[str, Any]
```

| 方法 | 说明 |
|------|------|
| `get(key, default)` | 获取变量值，支持点号路径（`parameters.xxx`, `variables.xxx`） |
| `set(key, value)` | 设置中间变量（支持点号路径设置嵌套值） |
| `resolve(template)` | 替换字符串中的 `{{key}}` 占位符为上下文实际值 |
| `to_dict()` | 序列化为字典（screenshots 转为长度列表） |

**变量查找优先级：** 纯键名 → `variables` → `parameters`。

**模板变量示例：**

```python
ctx = SkillContext(parameters={"filename": "report"})
ctx.resolve("{{parameters.filename}}.pdf")  # → "report.pdf"
```

### SkillValidator

位于 `src/skills/validator.py`，验证 YAML 技能定义的格式和合法性。

```python
class SkillValidator:
    def validate(self, data: dict[str, Any]) -> ValidationResult
    def validate_file(self, path: Path) -> ValidationResult
```

| 方法 | 说明 |
|------|------|
| `validate(data)` | 验证技能字典：必填字段、steps 格式、action 合法性 |
| `validate_file(path)` | 加载 YAML 文件并验证 |

**ValidationResult：**

```python
@dataclass
class ValidationResult:
    valid: bool                    # 是否通过验证
    errors: list[str]              # 错误列表（阻止加载）
    warnings: list[str]            # 警告列表（可加载但不建议）
```

**验证规则：**
- `name`、`description`、`steps` 为必填字段
- `steps` 必须是列表
- 每个 step 必须有合法的 `action`（20 个合法 action 之一）
- `loop` 必须有 `max_iterations` 且 ≤ 100
- `condition` 必须有 `when` 字段
- 参数 `type` 必须是合法 JSON Schema 类型

### ExpressionEvaluator

位于 `src/skills/expression.py`，安全条件表达式求值器。

```python
class ExpressionEvaluator:
    def evaluate(self, expr: str, context: Any) -> bool
```

| 方法 | 说明 |
|------|------|
| `evaluate(expr, context)` | 求值条件表达式，返回布尔结果。语法错误返回 `False` |

**特性：**
- 不使用 `eval()`，自实现 tokenizer + 递归下降解析器
- 支持比较运算：`==`, `!=`, `>`, `<`, `>=`, `<=`
- 支持逻辑运算：`and`, `or`, `not`
- 支持字符串包含：`in`
- 支持字面量：字符串、数字、布尔
- 支持变量路径：`parameters.xxx`, `variables.xxx`

### Actions 注册表

位于 `src/skills/actions/__init__.py`，20 个原语 action 的统一注册表。

```python
def get_action_registry() -> dict[str, Callable]
```

| Action | 模块 | 说明 |
|--------|------|------|
| `key_combo` | `keyboard.py` | 组合键 |
| `key_type` | `keyboard.py` | 单键输入 |
| `click` | `mouse.py` | 点击坐标 |
| `double_click` | `mouse.py` | 双击坐标 |
| `right_click` | `mouse.py` | 右键点击 |
| `drag` | `mouse.py` | 拖拽 |
| `scroll` | `mouse.py` | 滚轮 |
| `move_mouse` | `mouse.py` | 移动鼠标 |
| `type_text` | `text.py` | 输入文字 |
| `click_text` | `text.py` | 点击文字 |
| `click_icon` | `vision.py` | 点击图标 |
| `assert_text` | `vision.py` | 断言文字 |
| `assert_screen` | `vision.py` | 断言屏幕 |
| `screenshot` | `screen.py` | 截图 |
| `wait` | `control.py` | 等待 |
| `wait_text` | `control.py` | 等待文字 |
| `condition` | `control.py` | 条件分支 |
| `loop` | `control.py` | 循环 |
| `run_skill` | `control.py` | 调用技能 |
| `set_var` | `control.py` | 设置变量 |
