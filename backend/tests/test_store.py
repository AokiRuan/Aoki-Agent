"""会话存储测试。讲解见 docs/08-fastapi-sse.md。"""
import pytest

from backend.store.base import SessionNotFound, StoredMessage
from backend.store.memory import InMemorySessionStore


async def test_create_append_and_read_back():
    store = InMemorySessionStore()
    s = await store.create_session("莉可丽丝的圣地")
    await store.append_messages(s.id, [
        StoredMessage(role="user", content="莉可丽丝的圣地"),
        StoredMessage(role="assistant", content=None, tool_calls=[{"id": "c1"}]),
        StoredMessage(role="tool", content="[...]", tool_call_id="c1", tool_name="search_anime",
                      is_error=False, data=[{"anime_id": 364450}]),
    ])
    msgs = await store.get_messages(s.id)
    assert [m.role for m in msgs] == ["user", "assistant", "tool"]
    assert msgs[2].data == [{"anime_id": 364450}]


async def test_list_sorted_by_recent_update():
    store = InMemorySessionStore()
    a = await store.create_session("a")
    b = await store.create_session("b")
    await store.append_messages(a.id, [StoredMessage(role="user", content="hi")])
    assert [s.id for s in await store.list_sessions()] == [a.id, b.id]


async def test_unknown_session():
    store = InMemorySessionStore()
    assert await store.get_session("nope") is None
    with pytest.raises(SessionNotFound):
        await store.append_messages("nope", [])
    with pytest.raises(SessionNotFound):
        await store.get_messages("nope")


async def test_returned_list_is_a_copy():
    store = InMemorySessionStore()
    s = await store.create_session("x")
    (await store.get_messages(s.id)).append(StoredMessage(role="user", content="leak"))
    assert await store.get_messages(s.id) == []


def test_to_llm_message_drops_ui_only_fields():
    m = StoredMessage(role="tool", content="txt", tool_call_id="c1", tool_name="x", is_error=False, data={"a": 1})
    # LLM 只认识 role / content / tool_call_id；其余字段发过去轻则浪费 token，重则被拒绝
    assert m.to_llm_message() == {"role": "tool", "content": "txt", "tool_call_id": "c1"}
