# 贡献指南

> 欢迎为 JavasAgent 贡献代码

---

## 开发环境搭建

```bash
# 1. Fork 并克隆
git clone https://github.com/YOUR_USERNAME/JavasAgent.git
cd JavasAgent

# 2. 创建虚拟环境
python -m venv venv
source venv/bin/activate      # Linux/macOS
.\venv\Scripts\activate       # Windows

# 3. 安装开发依赖
pip install -e ".[dev]"
```

---

## 代码规范

### 工具链

| 工具 | 用途 | 配置 |
|------|------|------|
| ruff | 代码检查 + 格式化 | `pyproject.toml` → `[tool.ruff]` |
| mypy | 类型检查 | `pyproject.toml` → `[tool.mypy]` |

### 规则

1. **文件大小**：每个文件不超过 20KB，超过则拆分
2. **类型提示**：所有公开函数必须带类型提示
3. **代码分离**：业务代码（`src/`）与测试代码（`tests/`）严格隔离
4. **行宽**：100 字符（ruff 配置）
5. **Python 版本**：目标 3.11+
6. **导入排序**：ruff 自动处理（isort 规则）

### 检查命令

```bash
# 代码检查
ruff check src/

# 自动修复
ruff check src/ --fix

# 格式化
ruff format src/

# 类型检查
mypy src/
```

---

## Git 规范

### Commit Message 格式

```
类型(范围): 简短描述

详细说明（可选）
```

类型：

| 类型 | 说明 |
|------|------|
| feat | 新功能 |
| fix | Bug 修复 |
| docs | 文档变更 |
| style | 代码风格（不影响功能） |
| refactor | 重构 |
| test | 测试相关 |
| chore | 构建/工具变更 |

示例：

```
feat(voice): 添加连续对话模式支持
fix(platforms): 修复 macOS 窗口激活失败
docs: 更新 API 参考文档
```

### 分支策略

- `main` — 主分支，稳定代码
- `feat/xxx` — 功能分支
- `fix/xxx` — 修复分支
- `docs/xxx` — 文档分支

---

## 测试规范

### 目录结构

```
tests/
├── conftest.py        # 公共 fixtures
├── core/              # 核心引擎测试
├── agents/            # Agent 测试
├── tools/             # 工具测试
├── platforms/         # 平台测试
├── memory/            # 记忆系统测试
└── voice/             # 语音模块测试
```

### 命名规范

- 测试文件：`test_<模块名>.py`
- 测试函数：`test_<功能描述>`
- 测试类：`Test<类名>`

### 标记

```python
import pytest

@pytest.mark.slow
def test_large_dataset():
    """标记为慢测试。"""
    ...

@pytest.mark.integration
def test_with_real_llm():
    """标记为集成测试（需要真实 API）。"""
    ...
```

### 运行测试

```bash
# 全部测试
pytest tests/ -q

# 跳过慢测试和集成测试
pytest tests/ -q -m "not slow and not integration"

# 指定模块
pytest tests/core/ -v

# 带覆盖率
pytest tests/ --cov=src --cov-report=html
```

### Mock vs 真实测试

- **单元测试**：mock 外部依赖（LLM、文件系统、网络）
- **集成测试**：使用真实 API，标记 `@pytest.mark.integration`
- 不在单元测试中调用真实 LLM API

---

## PR 流程

1. 从 `main` 创建功能分支
2. 编写代码和测试
3. 确保所有检查通过：
   ```bash
   ruff check src/
   mypy src/
   pytest tests/ -q
   ```
4. 提交 PR，描述变更内容
5. 等待 Review

---

## 发布流程

由维护者执行：

1. 更新 `pyproject.toml` 版本号
2. 更新 CHANGELOG
3. 打 Tag：`git tag v0.x.x`
4. 推送：`git push origin main --tags`
