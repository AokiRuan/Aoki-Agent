"""HTTP 接口测试：注入假 LLM / 假工具，走真实的路由、SSE 编码与会话存储。
讲解见 docs/08-fastapi-sse.md。
"""
import json
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from backend.agent.harness import Harness
from backend.agent.loop import AgentLoop
from backend.agent.tracing import Tracing
from backend.app.components import Components
from backend.app.main import create_app
from backend.store.memory import InMemorySessionStore
from backend.tests.fakes import FakeLLM, FakeTools, answer, call, with_tools


def make_client(llm, tools=None):
    store = InMemorySessionStore()

    @asynccontextmanager
    async def factory():
        loop = AgentLoop(llm, tools or FakeTools(), Harness())
        yield Components(loop=loop, store=store, tracing=Tracing(None))

    return TestClient(create_app(factory))


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    """把 text/event-stream 的原始文本解析成 [(事件名, 数据)]。以 ':' 开头的是保活注释，跳过。"""
    events = []
    for block in raw.replace("\r\n", "\n").split("\n\n"):
        name, data = "message", None
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:"):].strip())
        if data is not None:
            events.append((name, data))
    return events


def chat(client, message, session_id=None):
    body = {"message": message} | ({"session_id": session_id} if session_id else {})
    with client.stream("POST", "/chat", json=body) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["cache-control"] == "no-cache"
        raw = r.read().decode("utf-8")
        assert "\\u" not in raw  # 中文原样传输，没有被转义成 \uXXXX
        return parse_sse(raw)


def names(events):
    out = []
    for n, _ in events:
        if not (n == "token" and out and out[-1] == "token"):
            out.append(n)
    return out


def test_new_session_full_event_stream():
    llm = FakeLLM(with_tools(call("c1", title="莉可丽丝"), content="我来查一下"), answer("找到了 5 处圣地"))
    with make_client(llm) as client:
        events = chat(client, "莉可丽丝的圣地在哪？")

    assert names(events) == ["session", "token", "tool_call", "tool_result", "token", "done"]
    assert "\\u" not in str(events)  # 中文原样传输，没有被转义
    session = events[0][1]
    assert session["title"] == "莉可丽丝的圣地在哪？" and session["session_id"]

    text = "".join(d["content"] for n, d in events if n == "token")
    assert text == "我来查一下找到了 5 处圣地"

    call_ev = next(d for n, d in events if n == "tool_call")
    assert call_ev == {"tool_name": "search_anime", "tool_call_id": "c1", "payload": {"title": "莉可丽丝"}}
    result_ev = next(d for n, d in events if n == "tool_result")
    assert result_ev["payload"] == {"is_error": False, "data": {"ok": "search_anime"}}

    done = events[-1][1]["payload"]
    assert "new_messages" not in done  # 内部入库用的，不发给前端
    assert done["iterations"] == 2


def test_second_turn_sends_history_and_session_restores_tool_data():
    llm = FakeLLM(
        with_tools(call("c1", title="莉可丽丝")), answer("第一轮回答"),
        answer("第二轮回答"),
    )
    with make_client(llm) as client:
        sid = chat(client, "第一轮")[0][1]["session_id"]
        second = chat(client, "第二轮", session_id=sid)

        assert second[0][1]["session_id"] == sid  # 沿用同一个会话
        sent = llm.requests[-1]["messages"]
        assert sent[0]["role"] == "system"
        assert [m["role"] for m in sent[1:]] == ["user", "assistant", "tool", "assistant", "user"]
        # 发给 LLM 的历史里不能有只给前端用的字段
        assert "data" not in sent[3] and "tool_name" not in sent[3]

        listed = client.get("/sessions").json()
        assert [s["id"] for s in listed] == [sid]

        detail = client.get(f"/sessions/{sid}").json()
        tool_msg = next(m for m in detail["messages"] if m["role"] == "tool")
        # 恢复会话时前端拿得到工具名和结构化结果，能重新在地图上打点
        assert tool_msg["tool_name"] == "search_anime"
        assert tool_msg["data"] == {"ok": "search_anime"}


def test_unknown_session_is_404_before_streaming():
    with make_client(FakeLLM()) as client:
        r = client.post("/chat", json={"message": "hi", "session_id": "nope"})
        assert r.status_code == 404
        assert client.get("/sessions/nope").status_code == 404


def test_empty_message_rejected():
    with make_client(FakeLLM()) as client:
        assert client.post("/chat", json={"message": ""}).status_code == 422


def test_llm_error_event_and_turn_not_persisted():
    with make_client(FakeLLM(RuntimeError("401 Unauthorized"))) as client:
        events = chat(client, "hi")
        assert names(events) == ["session", "error"]
        assert "401" in events[-1][1]["message"]
        sid = events[0][1]["session_id"]
        assert client.get(f"/sessions/{sid}").json()["messages"] == []
