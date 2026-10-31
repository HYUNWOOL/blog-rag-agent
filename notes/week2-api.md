# 2주차 API 메모

설치 버전: langgraph 1.2.16, langgraph-checkpoint 4.3.0, langgraph-checkpoint-postgres 3.2.0.

확인 방법 표기: **[MCP]** docs-langchain MCP로 공식 문서 확인, **[설치본]** `.venv`의 패키지 소스로 확인, **[실험]** `experiments/week2/kill_resume.py`를 실제로 돌려 확인, **[미확인]** 확인하지 못함.

## Postgres 체크포인터

문서: https://docs.langchain.com/oss/python/langgraph/add-memory#example-using-postgres-checkpointer

### 동기·비동기 클래스 [MCP, 설치본]
- 동기 `langgraph.checkpoint.postgres.PostgresSaver`, 비동기 `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver`.
- 동기 노드 + `invoke`면 전자, async 노드 + `ainvoke`면 후자를 쓴다.
- 노드 timeout은 async 노드에서만 동작하므로, 타임아웃을 쓰면 비동기 쪽으로 가야 한다(아래 timeout 항목).
- Windows 주의 [설치본]: psycopg 비동기는 기본 `ProactorEventLoop`에서 오류를 낸다. 셀렉터 이벤트 루프를 써야 한다.

### setup()을 언제 부르나 [MCP, 설치본]
- 체크포인터를 처음 쓸 때 한 번 직접 호출한다. 자동으로 불리지 않는다.
- 하는 일: `checkpoint_migrations`, `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` 테이블 생성과 자체 마이그레이션. 이미 적용된 버전은 건너뛰므로 여러 번 불러도 된다.
- `CREATE INDEX CONCURRENTLY`를 포함해서 트랜잭션 안에서는 실패한다. 즉 Alembic 마이그레이션 안에 그대로 넣을 수 없다(결정 포인트 5번).

### 연결 관리 [설치본]
- `from_conn_string`은 `autocommit=True, prepare_threshold=0, row_factory=dict_row`로 연결을 연다. 연결을 직접 넘길 때도 이 설정을 맞춰야 한다.
- `with ... as checkpointer:` 블록을 벗어나면 연결이 닫히므로, 그래프 실행은 블록 안에서 해야 한다.
- 웹 서버처럼 동시 요청이 있으면 커넥션 풀이 필요하다. [미확인: 풀 구성 예제는 이번에 열어 보지 못함. 문서의 설치 안내는 `psycopg[binary,pool]`]

```python
from langgraph.checkpoint.postgres import PostgresSaver

with PostgresSaver.from_conn_string(url) as checkpointer:
    checkpointer.setup()  # 처음 한 번
    graph = builder.compile(checkpointer=checkpointer)
    graph.invoke(inputs, {"configurable": {"thread_id": "t1"}})
```

## thread_id, get_state, get_state_history [MCP]

문서: https://docs.langchain.com/oss/python/langgraph/checkpointers#get-state-history

- `config = {"configurable": {"thread_id": "..."}}`를 실행 메서드에 넘긴다. 체크포인터가 있으면 필수다.
- PostgresSaver에서 thread_id는 255자 안으로 둔다. 문서는 UUID를 권한다.
- `graph.get_state(config)`: 최신 `StateSnapshot`. `values`(현재 값), `next`(다음에 돌 노드), `tasks`(오류·interrupt 포함).
- `graph.get_state_history(config)`: 전체 스냅샷. **최신이 맨 앞**이다.
- `next`가 비어 있으면 끝난 실행이다.

```python
config = {"configurable": {"thread_id": "t1"}}
snapshot = graph.get_state(config)
print(snapshot.next)
for s in graph.get_state_history(config):
    print(s.metadata["step"], s.next)
```

## 실패 뒤 같은 thread_id에 None으로 다시 실행

문서: https://docs.langchain.com/oss/python/langgraph/fault-tolerance#resume-after-drain , https://docs.langchain.com/oss/python/langgraph/graph-api#re-execution-and-idempotency

- `graph.invoke(None, config)`는 새 입력 없이 마지막 체크포인트부터 이어 간다. [MCP]
- 체크포인트는 super-step 경계에 저장된다. 그래서 **저장이 끝난 노드는 다시 돌지 않고, 돌던 노드는 함수 처음부터 다시 돈다.** [MCP, 실험]
- `durability="async"`는 저장을 기다리지 않는다. 다음 노드 시작 0.05초 뒤 kill하자 `next=('__start__',)`였고, 이미 끝난 `begin_turn`까지 다시 돌았다. [실험]
- 같은 super-step에서 끝난 병렬 노드의 결과는 `checkpoint_writes`에 남아 다시 돌지 않는다(pending writes). [MCP]
- 다시 도는 노드의 부수효과는 두 번 실행될 수 있다. upsert나 멱등키로 막아야 한다. [MCP]

```python
graph.invoke({"question": "..."}, config)  # 여기서 죽었다면
graph.invoke(None, config)                 # 같은 thread_id로 재개
```

## RetryPolicy, timeout, error_handler, Command(goto) [MCP, 설치본]

문서: https://docs.langchain.com/oss/python/langgraph/fault-tolerance

순서는 고정이다. 노드 예외(타임아웃 포함) → retry_policy가 재시도 판단 → 재시도가 끝나면 error_handler.

### RetryPolicy
- `add_node(..., retry_policy=RetryPolicy(...))`. 필드: `initial_interval, backoff_factor, max_interval, max_attempts, jitter, retry_on`.
- `retry_on`은 예외 타입이나 판단 함수. 기본값은 `default_retry_on`(`langgraph/_internal/_retry.py`)이다. `ConnectionError`와 5xx는 재시도하고 프로그래밍 오류는 제외한다. **[설치본]**

```python
from langgraph.types import RetryPolicy
builder.add_node("retrieve", retrieve, retry_policy=RetryPolicy(max_attempts=3))
```

### 노드 timeout
- `add_node(..., timeout=)`에 초, `timedelta`, `TimeoutPolicy(run_timeout=, idle_timeout=)`를 준다. `langgraph>=1.2`.
- **async 노드만 된다.** 초과하면 `NodeTimeoutError`(`node, elapsed, kind, idle_timeout, run_timeout`). 내장 `TimeoutError`의 하위 클래스가 아니다(`langgraph/errors.py`). `retry_on`을 직접 쓰면 따로 넣어야 재시도된다.
- 기본으로 재시도 대상이고, 재시도마다 타이머가 초기화되며 시간 초과된 시도의 쓰기는 지워진다.

```python
from langgraph.types import TimeoutPolicy
builder.add_node("answer", answer, timeout=TimeoutPolicy(run_timeout=60))
```

### error_handler와 NodeError, Command(goto)
- `add_node(..., error_handler=)`. 재시도가 끝난 뒤(정책이 없으면 바로) 불린다. `langgraph>=1.2`.
- 핸들러는 `(state, error: NodeError)`를 받고 `Command(update=..., goto="노드")`로 복구 경로로 보낸다. `error.error`가 원래 예외.
- `interrupt()`는 재시도와 error_handler를 모두 거치지 않는다.

```python
from langgraph.errors import NodeError
from langgraph.types import Command

def on_fail(state, error: NodeError) -> Command:
    return Command(update={"note": str(error.error)}, goto="insufficient")

builder.add_node("retrieve", retrieve, error_handler=on_fail)
```

`set_node_defaults(...)`로 그래프 전체 기본값을 줄 수 있다. 노드별 값이 우선한다.

## interrupt()와 Command(resume=...) [MCP]

문서: https://docs.langchain.com/oss/python/langgraph/interrupts#side-effects-called-before-interrupt-must-be-idempotent

- `interrupt(값)`은 그래프를 멈추고 값을 호출자에게 보여 준다. 체크포인터와 thread_id가 필요하다.
- `graph.invoke(Command(resume=답), config)`로 재개하면 그 답이 `interrupt()`의 반환값이 된다.
- **재개하면 그 노드가 함수 처음부터 다시 돈다.** `interrupt` 앞의 코드가 두 번 실행된다.
- 그래서 앞에 둘 부수효과는 멱등이어야 한다. 권장: upsert로 만들기, `interrupt` 뒤로 옮기기, 별도 노드로 분리.
- 멱등이 아닌 INSERT나 목록 추가를 앞에 두면 재개할 때마다 중복된다.

```python
def ask(state):
    answer = interrupt({"question": "어느 도시를 말하나요?"})  # 앞에 부수효과를 두지 않는다
    return {"query": answer}

graph.invoke(Command(resume="베르겐"), config)
```

## durability 모드 세 가지 [MCP, 설치본]

문서: https://docs.langchain.com/oss/python/langgraph/checkpointers#durability-modes

- 실행 메서드에 `durability=`로 준다. 타입은 `Literal["sync", "async", "exit"]`. 기본은 `"async"`.
- `"exit"`: 실행이 끝날 때만 저장. 가장 빠르지만 프로세스가 죽으면 그 실행의 중간 상태를 복구할 수 없다.
- `"async"`: 다음 단계를 돌리면서 비동기로 저장. 크래시 때 마지막 체크포인트가 빠질 작은 위험이 있다.
- `"sync"`: 다음 단계 시작 전에 저장을 끝낸다. 가장 안전하고 조금 느리다.
- 주의: JavaScript 문서의 `"sync"` 설명은 Python과 다르다(쓰기 완료를 기다리지 않고 진행). 이 메모는 Python 문서 기준이다.
- [실험] `kill_resume.py`로 `retrieve` 시작 0.3초 뒤 kill: `async`·`sync`는 `next=('retrieve',)`에서 재개해 retrieve부터 다시 돌았다. `exit`는 체크포인트가 없어 `next=()`이고, 재개가 `EmptyInputError`로 실패했다.

```python
graph.invoke(inputs, config, durability="sync")
```
