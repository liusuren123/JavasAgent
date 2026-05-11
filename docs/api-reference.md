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
