from fakes import FakeEmbedder
from langchain.messages import AIMessage, ToolCall
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from test_load import BODY, write_post

from blog_rag_agent.embedding import EMBEDDING_DIM
from blog_rag_agent.graph.research import RECURSION_LIMIT, build_graph, initial_state
from blog_rag_agent.ingest.load import load_dir


class FakeToolCallingModel(GenericFakeChatModel):
    # GenericFakeChatModel은 bind_tools가 없다. 정해 둔 응답을 순서대로 돌려주기만 하면 된다.
    def bind_tools(self, tools, **kwargs):
        return self


def scripted_model():
    return FakeToolCallingModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="search_posts", args={"query": "첫째 날"}, id="c1"
                        )
                    ],
                ),
                AIMessage(content="첫째 날 이야기입니다."),
            ]
        )
    )


def run(db, tmp_path, *, no_reducer):
    write_post(tmp_path, "bergen", BODY)
    embedder = FakeEmbedder(dim=EMBEDDING_DIM)
    load_dir(db, tmp_path, embedder)
    graph = build_graph(db, embedder, scripted_model(), no_reducer=no_reducer)
    return graph.invoke(initial_state("질문"), {"recursion_limit": RECURSION_LIMIT})


def test_agent_tools_loop_appends_messages(db, tmp_path):
    state = run(db, tmp_path, no_reducer=False)

    types = [type(m).__name__ for m in state["messages"]]
    assert types == ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage"]
    assert state["messages"][2].tool_call_id == "c1"  # 툴 결과가 호출 id와 짝이 맞다
    # 실제 DB 검색 결과가 들어 있다
    assert "bergen 여행" in state["messages"][2].content
    assert state["llm_calls"] == 2


def test_without_reducer_history_is_overwritten(db, tmp_path):
    state = run(db, tmp_path, no_reducer=True)

    # 노드가 돌려준 메시지가 목록을 통째로 덮어써서 마지막 메시지 하나만 남는다.
    assert [type(m).__name__ for m in state["messages"]] == ["AIMessage"]
    assert state["llm_calls"] == 2
