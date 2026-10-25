# 1주차 API 메모

확인 방법 표기: **[MCP]** docs-langchain·reference-langchain MCP로 확인, **[설치본]** `.venv`에 설치된 패키지 소스로 확인, **[DB]** 로컬 pgvector 컨테이너에서 확인, **[미확인]** 공식 문서를 이번에 직접 열어 보지 못함.

## pgvector

### psycopg 3에 vector 타입 등록 [설치본]
- 문서: https://github.com/pgvector/pgvector-python#psycopg-3
- `register_vector(conn)`을 연결마다 한 번 부르면 `vector` 컬럼이 Python 리스트/numpy 배열과 오간다.
- 등록 전에 `CREATE EXTENSION vector`가 되어 있어야 한다(우리는 첫 마이그레이션에서 처리).
- 설치본 시그니처: `register_vector(context: Connection, /)`, 비동기는 `register_vector_async`.
- 커넥션 풀을 쓰면 풀의 `configure` 콜백에서 등록한다. [미확인: 풀 예제는 이번에 안 열어 봄]

```python
import psycopg
from pgvector.psycopg import register_vector

with psycopg.connect(url) as conn:
    register_vector(conn)
    conn.execute("SELECT %s::vector", ([0.1, 0.2, 0.3],))
```

### HNSW 인덱스와 코사인 opclass, 짝이 맞는 거리 연산자 [DB: pgvector 0.8.7 카탈로그로 짝 확인 / 문서 링크는 미확인]
- 문서: https://github.com/pgvector/pgvector#hnsw , https://github.com/pgvector/pgvector#querying
- 인덱스는 opclass로 거리 종류를 고정한다. 쿼리의 연산자가 opclass와 짝이 맞아야 인덱스를 탄다.
- 짝: `vector_cosine_ops` ↔ `<=>`(코사인 거리), `vector_l2_ops` ↔ `<->`(L2), `vector_ip_ops` ↔ `<#>`(음수 내적), `vector_l1_ops` ↔ `<+>`(L1, HNSW만). IVFFlat은 앞의 셋만 있다.
- 코사인 거리 = 1 − 코사인 유사도. 작을수록 가깝다. `ORDER BY embedding <=> %s LIMIT k`로 쓴다.
- HNSW는 빈 테이블에도 만들 수 있고, 파라미터는 `m`, `ef_construction`(생성), `hnsw.ef_search`(검색).

```sql
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);
SELECT id, 1 - (embedding <=> %(q)s) AS similarity
FROM chunks ORDER BY embedding <=> %(q)s LIMIT %(k)s;
```

## Anthropic SDK의 tool use

문서: https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview (week0 실험 `tool_call_raw.py`로 실제 동작 확인)

### tools 정의 형식
- `{"name", "description", "input_schema"}`. `input_schema`는 JSON Schema 객체다.
- `description`이 모델이 툴을 고르는 근거라 구체적으로 쓴다.
- `strict: true`를 툴 정의 최상위에 두면 입력이 스키마에 맞게 보장된다(`additionalProperties: false` + `required` 필요).

```python
tools = [{"name": "search", "description": "블로그 청크 검색",
          "input_schema": {"type": "object", "properties": {"query": {"type": "string"}},
                           "required": ["query"]}}]
```

### stop_reason
- `tool_use`: 툴을 불러 달라는 요청. 툴을 실행하고 이어서 호출해야 한다.
- `end_turn`: 답이 끝남. `max_tokens`: 잘림. `refusal`: 거절(`stop_details` 확인).
- 루프는 `while response.stop_reason == "tool_use"`로 돌리고, 반복 상한을 함께 건다.

### tool_use와 tool_result 블록
- 응답 `content`에 `{"type": "tool_use", "id", "name", "input"}` 블록이 온다. 한 번에 여러 개일 수 있다.
- assistant 메시지로 `response.content`를 **통째로** 다시 넣는다(텍스트만 뽑으면 안 됨).
- 결과는 **user** 메시지 안의 `{"type": "tool_result", "tool_use_id": <tool_use.id>, "content": ...}`. 여러 결과는 한 메시지에 모은다.
- 실패한 툴은 버리지 말고 `is_error: true`로 돌려준다.

```python
messages.append({"role": "assistant", "content": resp.content})
messages.append({"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": b.id, "content": run(b.input)}
    for b in resp.content if b.type == "tool_use"]})
```

## LangGraph

### StateGraph [MCP]
- 문서: https://reference.langchain.com/python/langgraph/graph/state/StateGraph
- 공유 State를 읽고 일부를 돌려주는 노드들의 그래프. 노드 시그니처는 `State -> Partial<State>`.
- 빌더라서 `.compile()` 해야 `invoke`/`stream`이 생긴다.
- `add_node`, `add_edge(START, ...)`, `add_edge(..., END)`로 잇는다.

```python
from langgraph.graph import StateGraph, START, END
builder = StateGraph(State)
builder.add_node("retrieve", retrieve)
builder.add_edge(START, "retrieve"); builder.add_edge("retrieve", END)
graph = builder.compile()
```

### add_messages [MCP]
- 문서: https://reference.langchain.com/python/langgraph/graph/message/add_messages
- 메시지 리스트용 리듀서. 기본은 덧붙이기(append), 같은 `id`의 메시지가 오면 그 자리를 덮어쓴다.
- State 필드에 `Annotated[list, add_messages]`로 붙인다. 노드는 새 메시지만 돌려주면 된다.
- `messages` 하나만 필요하면 미리 만든 `MessagesState`를 상속해 필드를 추가한다.

```python
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import add_messages

class State(TypedDict):
    messages: Annotated[list, add_messages]
```

### add_conditional_edges [MCP]
- 문서: https://docs.langchain.com/oss/python/langgraph/graph-api#conditional-edges
- `add_conditional_edges(출발 노드, 라우팅 함수, 경로)`. 라우팅 함수가 State를 보고 다음 노드 이름(또는 `END`)을 돌려준다.
- 세 번째 인자는 가능한 목적지 리스트나 `{반환값: 노드}` 딕셔너리. 그림을 그릴 때 이 정보를 쓴다.
- 에이전트 루프는 "마지막 메시지에 `tool_calls`가 있으면 툴 노드, 없으면 END"가 기본형.

```python
def route(state) -> Literal["tools", END]:
    return "tools" if state["messages"][-1].tool_calls else END
builder.add_conditional_edges("llm", route, ["tools", END])
```

### recursion_limit 지정 [MCP]
- 문서: https://docs.langchain.com/oss/python/langgraph/graph-api#recursion-limit
- 한 번 실행에서 허용하는 super-step 수. 넘으면 `GraphRecursionError`.
- 1.0.6부터 기본값 1000. `configurable` 안이 아니라 config 최상위 키로 준다.
- 에러 대신 마지막 State를 받고 싶으면 `RemainingSteps` 필드로 남은 스텝을 보고 스스로 끝낸다.

```python
from langgraph.errors import GraphRecursionError
try:
    graph.invoke(inputs, {"recursion_limit": 10})
except GraphRecursionError:
    ...
```

### draw_mermaid [MCP]
- 문서: https://docs.langchain.com/oss/python/langgraph/use-graph-api#mermaid
- 컴파일된 그래프의 `get_graph().draw_mermaid()`가 Mermaid 텍스트를 돌려준다(외부 호출 없음).
- 조건부 엣지는 점선(`-.->`)으로 그려진다.
- PNG는 `draw_mermaid_png()`인데 기본은 원격 렌더링 서비스를 부른다. [미확인: 오프라인 옵션]

```python
print(graph.get_graph().draw_mermaid())
```
