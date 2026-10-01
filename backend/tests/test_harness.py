"""Harness 测试。讲解见 docs/06-harness.md。"""
from collections import Counter

from backend.agent.harness import Harness


def conversation(rounds):
    """每轮：user → assistant(tool_calls) → tool → assistant，共 4 条。"""
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(rounds):
        msgs += [
            {"role": "user", "content": f"q{i}"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": f"t{i}"}]},
            {"role": "tool", "tool_call_id": f"t{i}", "content": "r"},
            {"role": "assistant", "content": f"a{i}"},
        ]
    return msgs


def test_short_history_untouched():
    msgs = conversation(2)
    assert Harness(max_history_messages=40).trim(msgs) == msgs


def test_trim_keeps_system_and_starts_on_user():
    msgs = conversation(5)  # 1 system + 20 条
    trimmed = Harness(max_history_messages=6).trim(msgs)

    assert trimmed[0]["role"] == "system"
    assert trimmed[1]["role"] == "user"
    # 最近 6 条是「上一轮后半 2 条 + 最后一轮 4 条」，前两条不是 user，被一起丢掉
    assert [m.get("content") for m in trimmed[1:]] == ["q4", None, "r", "a4"]


def test_trim_never_leaves_orphan_tool_message():
    msgs = conversation(5)
    for limit in range(1, 21):
        trimmed = Harness(max_history_messages=limit).trim(msgs)
        ids_called = {tc["id"] for m in trimmed for tc in m.get("tool_calls", [])}
        for m in trimmed:
            if m["role"] == "tool":
                assert m["tool_call_id"] in ids_called, f"limit={limit}"


def test_repeat_detection_counts_per_arguments():
    h, seen = Harness(max_repeat_calls=2), Counter()
    assert h.repeated_call_message("f", {"a": 1}, seen) is None
    assert h.repeated_call_message("f", {"a": 1}, seen) is None
    assert h.repeated_call_message("f", {"a": 1}, seen) is not None
    # 参数不同就是不同的调用；参数顺序不同视为相同
    assert h.repeated_call_message("f", {"a": 2}, seen) is None
    assert h.call_key("f", {"x": 1, "y": 2}) == h.call_key("f", {"y": 2, "x": 1})
