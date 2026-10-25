"""LangGraph 에이전트: agent ↔ tools 루프. 다음에 할 일은 LLM이 정하고, 라우팅은 should_continue가 한다.

실행: uv run python -m blog_rag_agent.graph.research "질문"
     uv run python -m blog_rag_agent.graph.research --mermaid
깨뜨리기 스위치: RESEARCH_NO_REDUCER=1 이면 messages에서 add_messages 리듀서를 뺀다.
"""

import os
import sys
from typing import Annotated, Literal

import psycopg
from langchain.messages import HumanMessage, SystemMessage
from langchain.tools import tool
from langchain_anthropic import ChatAnthropic
from langgraph.graph import END, START, StateGraph, add_messages
from pgvector.psycopg import register_vector
from typing_extensions import TypedDict

from blog_rag_agent.agent_tools import (
    GET_POST_DESC,
    MAX_TOKENS,
    MODEL,
    SEARCH_POSTS_DESC,
    SYSTEM_PROMPT,
    run_get_post,
    run_search_posts,
)
from blog_rag_agent.config import load_settings

RECURSION_LIMIT = (
    10  # super-step 상한. 넘으면 GraphRecursionError로 멈춘다(1주차 결정).
)


def make_state(no_reducer: bool) -> type:
    # 리듀서가 있으면 노드가 돌려준 메시지가 기존 목록 뒤에 붙고, 없으면 목록을 통째로 덮어쓴다.
    messages_type = list if no_reducer else Annotated[list, add_messages]
    return TypedDict("State", {"messages": messages_type, "llm_calls": int})


def build_graph(
    conn, embedder, model: ChatAnthropic, *, no_reducer: bool | None = None
):
    if no_reducer is None:
        no_reducer = os.environ.get("RESEARCH_NO_REDUCER") == "1"
    State = make_state(no_reducer)

    @tool("search_posts", description=SEARCH_POSTS_DESC)
    def search_posts(query: str) -> str:
        return run_search_posts(conn, embedder, query)

    @tool("get_post", description=GET_POST_DESC)
    def get_post(post_id: int) -> str:
        return run_get_post(conn, post_id)

    tools_by_name = {t.name: t for t in (search_posts, get_post)}
    model_with_tools = model.bind_tools(list(tools_by_name.values()))

    def agent(state):
        # 시스템 프롬프트는 State에 넣지 않고 매번 앞에 붙인다. State에는 대화만 쌓인다.
        response = model_with_tools.invoke(
            [SystemMessage(SYSTEM_PROMPT), *state["messages"]]
        )
        return {"messages": [response], "llm_calls": state["llm_calls"] + 1}

    def tools(state):
        # tool_call을 통째로 넘기면 tool_call_id가 채워진 ToolMessage가 나온다.
        calls = state["messages"][-1].tool_calls
        return {"messages": [tools_by_name[tc["name"]].invoke(tc) for tc in calls]}

    def should_continue(state) -> Literal["tools", "__end__"]:
        return "tools" if state["messages"][-1].tool_calls else END

    builder = StateGraph(State)
    builder.add_node("agent", agent)
    builder.add_node("tools", tools)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", should_continue, ["tools", END])
    builder.add_edge("tools", "agent")
    return builder.compile()


def make_model(api_key: str) -> ChatAnthropic:
    return ChatAnthropic(
        model=MODEL, api_key=api_key, max_tokens=MAX_TOKENS, effort="low"
    )


def initial_state(question: str) -> dict:
    return {"messages": [HumanMessage(question)], "llm_calls": 0}


def run_graph(question: str, graph) -> dict:
    state = graph.invoke(initial_state(question), {"recursion_limit": RECURSION_LIMIT})
    usages = [
        m.usage_metadata
        for m in state["messages"]
        if getattr(m, "usage_metadata", None)
    ]
    return {
        "answer": state["messages"][-1].text,
        "llm_calls": state["llm_calls"],
        "input_tokens": sum(u["input_tokens"] for u in usages),
        "output_tokens": sum(u["output_tokens"] for u in usages),
        "state": state,
    }


def main() -> None:
    from blog_rag_agent.embedding import LocalEmbedder

    settings = load_settings()
    if "--mermaid" in sys.argv:
        # 그림만 그릴 때는 DB·임베더가 필요 없다(툴이 실행되지 않는다).
        print(
            build_graph(None, None, make_model(settings.anthropic_api_key))
            .get_graph()
            .draw_mermaid()
        )
        return
    question = sys.argv[1] if len(sys.argv) > 1 else "스위스에서 배를 탄 이유가 뭐야?"
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        register_vector(conn)
        graph = build_graph(
            conn,
            LocalEmbedder(settings.embedding_model),
            make_model(settings.anthropic_api_key),
        )
        # stream_mode="values": 노드 하나가 끝날 때마다 그 시점의 State 전체를 받는다.
        for i, state in enumerate(
            graph.stream(
                initial_state(question),
                {"recursion_limit": RECURSION_LIMIT},
                stream_mode="values",
            )
        ):
            last = state["messages"][-1]
            print(
                f"[state {i}] messages={len(state['messages'])} llm_calls={state['llm_calls']} "
                f"types={[type(m).__name__ for m in state['messages']]} "
                f"tool_calls={[(c['name'], c['args']) for c in getattr(last, 'tool_calls', [])]}"
            )
    print(f"\n답:\n{last.text}")


if __name__ == "__main__":
    main()
