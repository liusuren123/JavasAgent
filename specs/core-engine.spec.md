# OpenSpec: Agent 核心引擎

> spec-id: `core-engine-v1`
> status: `draft`
> phase: `phase-1`

## 概述

Agent 核心引擎是 JavasAgent 的心脏，实现 **感知→规划→执行→反思** 的主循环。

## 接口定义

### Planner

```python
class Planner:
    async def plan(self, user_intent: str, context: MemoryContext) -> TaskPlan:
        """将用户意图拆解为可执行的步骤链"""
        ...

    async def replan(self, task_id: str, reason: str) -> TaskPlan:
        """根据反思结果重新规划"""
        ...
```

### Executor

```python
class Executor:
    async def execute(self, plan: TaskPlan) -> ExecutionResult:
        """按步骤执行任务计划"""
        ...

    async def execute_step(self, step: Step) -> StepResult:
        """执行单个步骤"""
        ...

    @property
    def is_busy(self) -> bool:
        """当前是否有任务在执行"""
        ...
```

### Reflector

```python
class Reflector:
    async def reflect(self, project_state: ProjectState) -> ReflectionReport:
        """执行反思审查清单，返回审查报告"""
        ...

    async def should_continue(self, report: ReflectionReport) -> bool:
        """判断是否需要继续迭代"""
        ...
```

### Decider

```python
class Decider:
    def should_ask_human(self, decision_point: DecisionPoint) -> bool:
        """判断当前决策点是否需要询问人类"""
        ...

    async def ask_human(self, question: str, options: list[str] | None) -> str:
        """向人类提问并等待回答"""
        ...
```

### Scheduler

```python
class Scheduler:
    async def submit(self, plan: TaskPlan, priority: int = 0) -> str:
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
    priority: int
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

@dataclass
class ReflectionReport:
    timestamp: datetime
    checklist_results: dict[str, ChecklistResult]
    overall_score: float  # 0-1
    action_items: list[ActionItem]
    should_continue: bool
```

## 核心循环

```
while True:
    if scheduler.has_running_task:
        continue  # 等待当前任务完成
    
    user_input = await get_user_input()
    plan = await planner.plan(user_input, memory.context)
    
    if decider.should_ask_human(plan):
        await decider.ask_human(...)
    
    task_id = await scheduler.submit(plan)
    result = await executor.execute(plan)
    
    if reflector.should_reflect():
        report = await reflector.reflect(project_state)
        if report.should_continue:
            plan = await planner.replan(task_id, report.summary)
```

## 反思审查清单

每 10 分钟由 cron 触发，按以下清单逐项审查：

1. 功能完整性（产品视角）
2. 代码质量（工程视角）
3. 测试覆盖（质量视角）
4. 性能与资源（运行视角）
5. 安全与健壮性（防护视角）
6. 架构与演进性（长期视角）
7. 目标对齐
8. 测试结果

详细检查项见 `docs/ARCHITECTURE.md`。

## 验收标准

- [ ] 核心循环能跑通（感知→规划→执行→反思）
- [ ] Planner 能将简单意图拆解为步骤
- [ ] Executor 能执行文件操作级别的步骤
- [ ] Reflector 能输出结构化的审查报告
- [ ] Decider 能在不确定时暂停并询问
