# OpenSpec: Agent 核心引擎

> spec-id: `core-engine-v1`
> status: `active`
> phase: `phase-1`

## 概述

Agent 核心引擎是 JavasAgent 的心脏，实现 **感知→规划→决策→执行→反馈** 的主循环。

## 接口定义

### Planner

```python
class Planner:
    async def plan(self, user_intent: str, context: str = "") -> TaskPlan:
        """将用户意图拆解为可执行的步骤链"""
        ...

    async def replan(self, original: TaskPlan, reason: str) -> TaskPlan:
        """根据执行失败原因重新规划"""
        ...
```

### Executor

```python
class Executor:
    async def execute(self, plan: TaskPlan) -> ExecutionResult:
        """按步骤执行任务计划"""
        ...

    def register_tool(self, name: str, tool: Any) -> None:
        """注册工具实例"""
        ...

    @property
    def is_busy(self) -> bool:
        """当前是否有任务在执行"""
        ...
```

### Decider

```python
class Decider:
    def should_ask_human(self, decision: DecisionPoint) -> bool:
        """判断当前决策点是否需要询问人类"""
        ...

    def evaluate(self, context: str, question: str, confidence: float, options: list[str] | None = None) -> DecisionPoint:
        """创建并评估一个决策点"""
        ...
```

### Scheduler

```python
class Scheduler:
    async def submit(self, plan: TaskPlan) -> str:
        """提交任务到队列"""
        ...

    async def cancel(self, task_id: str) -> bool:
        """取消任务"""
        ...

    @property
    def has_running_task(self) -> bool:
        """是否有正在运行的任务"""
        ...
```

## 数据结构

```python
@dataclass
class TaskPlan:
    id: str
    intent: str
    steps: list[Step]
    priority: Priority
    created_at: datetime
    status: PlanStatus  # PENDING | RUNNING | PAUSED | DONE | FAILED

@dataclass
class Step:
    id: str
    action: str
    tool: str
    params: dict
    depends_on: list[str]  # 前置步骤 ID
    retry_count: int = 0
    max_retries: int = 3
    status: StepStatus = StepStatus.PENDING
    result: str | None = None
    error: str | None = None

@dataclass
class DecisionPoint:
    context: str
    question: str
    confidence: float  # 0-1
    options: list[str]
    auto_decided: bool = False

@dataclass
class ExecutionResult:
    plan_id: str
    success: bool
    completed_steps: int
    total_steps: int
    errors: list[str]
    output: dict[str, Any]
```

## 核心循环

```
while True:
    if scheduler.has_running_task:
        continue  # 等待当前任务完成
    
    user_input = await get_user_input()
    
    # 1. 感知（屏幕分析）
    screen_context = await analyze_screen_if_needed(user_input)
    
    # 2. 规划
    plan = await planner.plan(user_input, context + screen_context)
    
    # 3. 决策
    confidence = estimate_confidence(plan)
    decision = decider.evaluate(user_input, plan.intent, confidence)
    if not decision.auto_decided:
        await ask_human(decision.question)
    
    # 4. 执行
    task_id = await scheduler.submit(plan)
    result = await executor.execute(plan)
    scheduler.mark_done(plan, result.success)
    
    # 5. 反馈
    await send_feedback(result)
```

## 验收标准

- [x] 核心循环能跑通（感知→规划→决策→执行→反馈）
- [x] Planner 能将简单意图拆解为步骤
- [x] Executor 能执行文件操作级别的步骤
- [x] Decider 能在不确定时暂停并询问
- [x] 屏幕感知模块能分析截图
- [x] 工具集（SystemControl + CodeDev）已注册并可用
