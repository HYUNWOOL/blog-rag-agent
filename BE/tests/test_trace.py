import asyncio

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from blog_rag_agent.graph.trace import read_trace, traced


class State(TypedDict):
    n: int


def graph_with(node):
    builder = StateGraph(State)
    builder.add_node("step", node)
    builder.add_edge(START, "step")
    builder.add_edge("step", END)
    return builder.compile(checkpointer=InMemorySaver())


CONFIG = {"configurable": {"thread_id": "t1"}}


def test_records_start_and_end_with_thread_id(tmp_path):
    path = tmp_path / "trace.jsonl"

    @traced(path)
    def step(state):
        return {"n": state["n"] + 1}

    assert graph_with(step).invoke({"n": 0}, CONFIG) == {"n": 1}

    events = read_trace(path)
    assert [(e["node"], e["event"]) for e in events] == [
        ("step", "start"),
        ("step", "end"),
    ]
    assert {e["thread_id"] for e in events} == {"t1"}
    assert events[0]["at"] <= events[1]["at"]
    assert events[1]["error"] is None


def test_async_node_is_traced(tmp_path):
    path = tmp_path / "trace.jsonl"

    @traced(path)
    async def step(state):
        return {"n": 1}

    assert asyncio.run(graph_with(step).ainvoke({"n": 0}, CONFIG)) == {"n": 1}
    assert [e["event"] for e in read_trace(path)] == ["start", "end"]


def test_failure_is_recorded_and_still_raised(tmp_path):
    path = tmp_path / "trace.jsonl"

    @traced(path)
    def step(state):
        raise ValueError("boom")

    with pytest.raises(ValueError):
        graph_with(step).invoke({"n": 0}, CONFIG)

    assert read_trace(path)[-1]["error"] == "ValueError"


def test_read_trace_skips_a_line_cut_off_by_a_kill(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text(
        '{"node": "a", "event": "start"}\n{"node": "b", "ev', encoding="utf-8"
    )

    assert [e["node"] for e in read_trace(path)] == ["a"]
