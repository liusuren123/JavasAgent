"""短期记忆测试。"""

import pytest

from src.memory.short_term import ShortTermMemory


class TestShortTermMemory:
    """ShortTermMemory 测试。"""

    def test_add_and_get(self) -> None:
        mem = ShortTermMemory(max_messages=10)
        mem.add("user", "hello")
        mem.add("assistant", "hi there")

        msgs = mem.get_messages()
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[1].role == "assistant"

    def test_max_messages_limit(self) -> None:
        mem = ShortTermMemory(max_messages=3)
        for i in range(5):
            mem.add("user", f"msg {i}")

        assert mem.size == 3
        msgs = mem.get_messages()
        assert msgs[0].content == "msg 2"

    def test_get_last_n(self) -> None:
        mem = ShortTermMemory(max_messages=10)
        for i in range(5):
            mem.add("user", f"msg {i}")

        msgs = mem.get_messages(last_n=2)
        assert len(msgs) == 2
        assert msgs[0].content == "msg 3"

    def test_context_for_llm(self) -> None:
        mem = ShortTermMemory(max_messages=10)
        mem.add("system", "你是助手")
        mem.add("user", "你好")

        llm_msgs = mem.get_context_for_llm()
        assert len(llm_msgs) == 2
        assert llm_msgs[0]["role"] == "system"

    def test_context_for_llm_truncation(self) -> None:
        mem = ShortTermMemory(max_messages=100)
        for i in range(10):
            mem.add("user", "x" * 1000)

        llm_msgs = mem.get_context_for_llm(max_chars=3000)
        total = sum(len(m["content"]) for m in llm_msgs)
        assert total <= 3000 + 1000  # 允许多一条

    def test_context_variables(self) -> None:
        mem = ShortTermMemory()
        mem.set("project", "JavasAgent")
        assert mem.get("project") == "JavasAgent"
        assert mem.get("missing", "default") == "default"

    def test_clear(self) -> None:
        mem = ShortTermMemory()
        mem.add("user", "test")
        mem.set("key", "value")
        mem.clear()
        assert mem.size == 0
        assert mem.get("key") is None
