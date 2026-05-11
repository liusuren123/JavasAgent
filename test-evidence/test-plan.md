# JavasAgent 全量测试计划

测试时间：2026-05-11
测试基线 commit：`608e1f0 feat(platforms): 实现 MotorController 闭环控制器 - Step 5`

---

## 一、项目功能模块清单

### 1. core（核心层）— 11 个模块
| 模块 | 文件 | 功能 |
|------|------|------|
| models | models.py | 数据模型（TaskPlan, ActionResult 等） |
| planner | planner.py | 任务规划器，动态工具注册 |
| decider | decider.py | 决策引擎 |
| executor | executor.py | 任务执行器 |
| scheduler | scheduler.py | 优先级队列调度器 |
| security_manager | security_manager.py + security_models.py + security_risk_engine.py | 安全管理，权限校验，风险评估 |
| notification | notification.py | 通知管理器 |
| desktop_notifier | desktop_notifier.py | Windows Toast 通知 |
| voice_chat | voice_chat.py | 语音对话循环 |
| agent_team | agent_team.py + collaboration_bus.py + task_distributor.py | 多 agent 协作 |
| workflow_engine | workflow_engine.py | 工作流引擎 |
| execution_observer | execution_observer.py | 执行观察者模式 |

### 2. agents（代理层）— 4 个模块
| 模块 | 文件 | 功能 |
|------|------|------|
| base_agent | base_agent.py | 基础代理（感知→规划→决策→执行循环） |
| feedback_handler | feedback_handler.py | 反馈处理（确认/取消/重新规划） |
| learning_integration | learning_integration.py | 学习集成 |
| team_integration | team_integration.py | 团队集成 |

### 3. memory（记忆层）— 7 个模块
| 模块 | 文件 | 功能 |
|------|------|------|
| short_term | short_term.py | 短期记忆（消息列表） |
| long_term | long_term.py | 长期记忆（ChromaDB 向量存储） |
| knowledge | knowledge.py | 知识库管理 |
| skill_learner | skill_learner.py | 技能学习器 |
| skill_registry | skill_registry.py | 技能注册表 |
| skill_auto_updater | skill_auto_updater.py | 技能自动优化器 |
| user_preference | user_preference.py | 用户偏好引擎 |

### 4. perception（感知层）— 7 个模块
| 模块 | 文件 | 功能 |
|------|------|------|
| screen_analyzer | screen_analyzer.py | 多模态屏幕分析 |
| ocr_engine | ocr_engine.py | OCR 文字识别 |
| window_manager | window_manager.py | 窗口管理 |
| context_engine | context_engine.py + context_detectors.py + context_models.py | 用户场景感知 |
| target_cache | target_cache.py | 目标截图缓存 |
| target_matcher | target_matcher.py | 三级目标匹配 |
| vision_eye | vision_eye.py | 视觉感知器 |

### 5. platforms（平台层）— 3 个模块
| 模块 | 文件 | 功能 |
|------|------|------|
| base | base.py | 平台抽象基类 |
| windows | windows.py | Windows 适配器（pyautogui + Win32） |
| human_hand | human_hand.py | 拟人手部模拟器 |
| motor_controller | motor_controller.py | 闭环运动控制器 |

### 6. tools（工具层）— 30+ 个模块
| 模块 | 功能 |
|------|------|
| system_control | 文件操作、进程管理 |
| code_dev | 代码开发辅助 |
| browser_control | 浏览器控制 |
| email_ops/imap/send/attachments | 邮件全套 |
| office_docx/xlsx/pptx/pdf | Office 文档操作 |
| image_ops/filters/watermark | 图像处理 |
| clipboard_ops | 剪贴板管理 |
| archive_ops | 压缩解压 |
| network_ops | 网络操作 |
| macro_recorder | 宏录制回放 |
| plugin_manager/loader/validator | 插件管理 |
| skill_executor/matcher/chain/feedback | 技能执行 |
| automation_engine | 自动化引擎 |
| voice_tts/stt | 语音合成/识别 |
| process_manager | 进程管理 |
| app_launcher | 应用启动器 |
| system_monitor | 系统监控 |
| smart_scheduler | 智能日程 |
| calendar_ops | 日历操作 |
| creative_tools | 创意工具占位 |
| photoshop_control | PS 控制 |
| premiere_control | PR 控制 |
| aftereffects_control | AE 控制 |

### 7. utils（工具层）— 5 个模块
| 模块 | 功能 |
|------|------|
| config | YAML 配置加载 |
| logger | 日志配置 |
| llm_client | 多 LLM 提供商客户端 |
| command | 命令执行器 |
| path_safety | 路径安全检查 |

---

## 二、当前测试结果摘要

**总测试数：1911**
**通过：1892（98.9%）**
**失败：19（1.1%）**

### 失败分类

#### A. ChromaDB 兼容性问题（18 个失败）
- 全部在 `tests/memory/test_long_term.py`
- 原因：`'_FakeWindll' object has no attribute 'msvcrt'`
- ChromaDB 在 Windows pytest 环境下的 sqlite3 兼容性问题
- 非功能 Bug，是测试环境问题

#### B. 工具注册断言过严（1 个失败）
- `tests/tools/test_tool_registry.py::TestAutoRegisterEnabled::test_all_enabled_registers_all`
- 原因：5 个工具因依赖缺失被 skip（network_ops, system_monitor, automation_engine, plugin_manager, app_launcher）
- 测试期望 skip=0，但实际有 5 个工具的 pip 依赖未安装

---

## 三、测试方案

### 第1层：单元测试（自动 pytest）
覆盖率目标：所有模块

### 第2层：集成测试（自动 pytest）
跨模块协作验证

### 第3层：真实执行测试（手动 + 截图证据）
需要实际桌面的操作验证

---

## 四、真实执行测试用例清单

| 用例编号 | 模块 | 测试内容 | 预期结果 |
|---------|------|---------|---------|
| REAL-001 | platforms/windows | 截屏并保存 | 生成有效 PNG |
| REAL-002 | platforms/windows | 鼠标移动到指定位置 | 鼠标到达目标位置 |
| REAL-003 | platforms/windows | 键盘输入文字 | 文字出现在记事本 |
| REAL-004 | platforms/windows | 获取活动窗口信息 | 返回正确的窗口标题和 PID |
| REAL-005 | platforms/windows | 窗口查找和激活 | 找到并激活目标窗口 |
| REAL-006 | platforms/human_hand | 拟人移动（远距离） | 贝塞尔曲线轨迹，速度递减 |
| REAL-007 | platforms/human_hand | 拟人点击 | 点击位置在 bbox 内有偏移 |
| REAL-008 | platforms/motor_controller | 闭环收敛点击 | 3-5 次迭代收敛到目标 |
| REAL-009 | perception/ocr_engine | 屏幕文字识别 | 识别桌面上的文字 |
| REAL-010 | perception/vision_eye | 目标定位 | 找到指定 UI 元素 |
| REAL-011 | tools/system_control | 文件创建和读取 | 文件正确创建和读取 |
| REAL-012 | tools/clipboard_ops | 剪贴板读写 | 正确读写剪贴板内容 |
| REAL-013 | tools/archive_ops | 文件压缩解压 | zip 文件正确创建和解压 |
| REAL-014 | tools/system_monitor | 系统资源监控 | 返回 CPU/内存/磁盘信息 |
